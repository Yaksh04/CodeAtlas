"""Git access, scanning, store and full indexing, against a real throwaway git repo."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.core.models import Repository
from codeatlas.index.pipeline import build_index, index_exists, open_store
from codeatlas.ingest.chunker import AstChunker, FixedWindowChunker
from codeatlas.ingest.git import GitError, GitReader, list_tree
from codeatlas.ingest.repo import is_url, repo_id_from_source, resolve_repository
from codeatlas.ingest.scan import is_test_path, iter_source_files
from codeatlas.ingest.text import slice_lines, split_lines

from .conftest import git


def test_repo_id_and_url_detection() -> None:
    assert repo_id_from_source("https://github.com/pallets/flask") == "pallets__flask"
    assert repo_id_from_source("https://github.com/pallets/flask.git") == "pallets__flask"
    assert repo_id_from_source("git@github.com:pallets/flask.git") == "pallets__flask"
    assert is_url("https://x/y") and not is_url("C:/some/dir")


def test_resolve_repository_pins_full_sha(sample_repo_path: Path, home: Path) -> None:
    repo = resolve_repository(str(sample_repo_path), home=home)
    assert len(repo.indexed_commit) == 40
    assert repo.indexed_commit == git(sample_repo_path, "rev-parse", "HEAD")
    assert repo.id == "sample_repo" and repo.url is None


def test_resolve_rejects_non_git_dir(tmp_path: Path) -> None:
    with pytest.raises(GitError):
        resolve_repository(str(tmp_path))


def test_git_reader_reads_blobs_and_reports_missing(sample_repo: Repository) -> None:
    root = Path(sample_repo.local_path)
    with GitReader(root) as reader:
        by_rev = reader.read(f"{sample_repo.indexed_commit}:pkg/auth.py")
        assert by_rev is not None and b"validate_token" in by_rev
        entry = next(
            e for e in list_tree(root, sample_repo.indexed_commit) if e.path == "pkg/auth.py"
        )
        assert reader.read(entry.blob_sha) == by_rev
        assert reader.read(f"{sample_repo.indexed_commit}:nope.py") is None
        assert reader.read(entry.blob_sha) == by_rev  # protocol still in sync after a miss


def test_reader_serves_committed_content_not_working_tree(sample_repo: Repository) -> None:
    root = Path(sample_repo.local_path)
    (root / "pkg" / "auth.py").write_text("# uncommitted edit\n")
    files = {s.path: t for s, t in iter_source_files(sample_repo)}
    assert "validate_token" in files["pkg/auth.py"]


def test_scan_filters_and_flags_tests(sample_repo_path: Path, home: Path) -> None:
    (sample_repo_path / "README.md").write_text("docs")
    (sample_repo_path / "vendor").mkdir()
    (sample_repo_path / "vendor" / "lib.py").write_text("def v(): pass\n")
    (sample_repo_path / "tests").mkdir()
    (sample_repo_path / "tests" / "test_a.py").write_text("def test_a():\n    pass\n")
    (sample_repo_path / "blob.py").write_bytes(b"x = 1\0\0")
    git(sample_repo_path, "add", "-A")
    git(sample_repo_path, "commit", "-q", "-m", "more")
    repo = resolve_repository(str(sample_repo_path), home=home)
    found = {s.path: s for s, _ in iter_source_files(repo)}
    assert set(found) == {"pkg/auth.py", "pkg/shapes.py", "pkg/storage.py", "tests/test_a.py"}
    assert found["tests/test_a.py"].is_test and not found["pkg/auth.py"].is_test


def test_scan_normalizes_crlf_without_changing_line_numbers(
    sample_repo_path: Path, home: Path
) -> None:
    (sample_repo_path / "pkg" / "win.py").write_bytes(b"def f():\r\n    return 1\r\n")
    git(sample_repo_path, "add", "-A")
    git(sample_repo_path, "commit", "-q", "-m", "crlf")
    repo = resolve_repository(str(sample_repo_path), home=home)
    source, text = next((s, t) for s, t in iter_source_files(repo) if s.path == "pkg/win.py")
    assert "\r" not in text and source.n_lines == 2


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_basic.py", True),
        ("src/pkg/test_utils.py", True),
        ("src/pkg/utils_test.py", True),
        ("conftest.py", True),
        ("src/pkg/testing.py", False),
        ("src/pkg/latest.py", False),
    ],
)
def test_is_test_path(path: str, expected: bool) -> None:
    assert is_test_path(path) is expected


def test_build_index_end_to_end(sample_repo: Repository, home: Path) -> None:
    chunker = AstChunker()
    assert not index_exists(sample_repo, chunker, home)
    stats = build_index(sample_repo, chunker, home)
    assert index_exists(sample_repo, chunker, home)
    assert stats.files == 3 and stats.files_with_syntax_errors == 0
    assert stats.chunks == sum(stats.chunks_by_kind.values())

    with open_store(sample_repo, chunker, home) as store:
        assert store.count_chunks() == stats.chunks and store.count_files() == 3
        assert store.load_repository() == sample_repo
        chunk = store.get_chunk("sample_repo:pkg/auth.py:pkg.auth.validate_token#0")
        assert chunk is not None and chunk.signature == "def validate_token(token: str) -> bool"


def test_every_indexed_chunk_matches_committed_source(sample_repo: Repository, home: Path) -> None:
    """The Sprint 1 acceptance invariant, on the fixture repo (Flask version is in eval tests)."""
    build_index(sample_repo, AstChunker(), home)
    sources = {s.path: split_lines(t) for s, t in iter_source_files(sample_repo)}
    with open_store(sample_repo, AstChunker(), home) as store:
        for c in store.iter_chunks():
            lines = sources[c.file_path]
            assert 1 <= c.start_line <= c.end_line <= len(lines)
            if c.part_count == 1:
                assert c.content == slice_lines(lines, c.start_line, c.end_line), c.id


def test_reindex_is_idempotent_and_chunkers_use_separate_indexes(
    sample_repo: Repository, home: Path
) -> None:
    a = build_index(sample_repo, AstChunker(), home)
    b = build_index(sample_repo, AstChunker(), home)
    assert (a.files, a.chunks, a.chunks_by_kind) == (b.files, b.chunks, b.chunks_by_kind)
    build_index(sample_repo, FixedWindowChunker(), home)
    with open_store(sample_repo, AstChunker(), home) as ast_store:
        assert ast_store.count_chunks() == a.chunks  # untouched by the fixed-window build
