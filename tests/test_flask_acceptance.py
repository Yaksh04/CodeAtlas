"""Sprint 1 acceptance criteria on the real pinned Flask checkout.

Skipped unless CODEATLAS_FLASK_REPO points at a clone containing the pinned commit.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codeatlas.core.models import Query
from codeatlas.eval.dataset import load_dataset, validate_against_repo
from codeatlas.index.pipeline import build_index, open_store
from codeatlas.ingest.chunker import AstChunker
from codeatlas.ingest.repo import resolve_repository
from codeatlas.ingest.scan import iter_source_files
from codeatlas.ingest.text import slice_lines, split_lines
from codeatlas.retrieve.bm25 import BM25Retriever

FLASK_SHA = "22d924701a6ae2e4cd01e9a15bbaf3946094af65"
DATASET = Path(__file__).parent.parent / "datasets" / "flask_seed.jsonl"

pytestmark = pytest.mark.flask


@pytest.fixture(scope="module")
def flask_index(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    clone = os.environ.get("CODEATLAS_FLASK_REPO")
    if not clone or not (Path(clone) / ".git").exists():
        pytest.skip("set CODEATLAS_FLASK_REPO to a Flask clone containing the pinned commit")
    home = tmp_path_factory.mktemp("home")
    repo = resolve_repository(clone, FLASK_SHA, home)
    stats = build_index(repo, AstChunker(), home)
    return repo, stats, home


def test_every_chunk_matches_committed_source_and_nothing_crashes(flask_index) -> None:  # type: ignore[no-untyped-def]
    repo, stats, home = flask_index
    assert stats.files > 50 and stats.chunks > 500
    assert stats.files_with_syntax_errors == 0

    sources = {s.path: split_lines(t) for s, t in iter_source_files(repo)}
    seen: set[str] = set()
    with open_store(repo, AstChunker(), home) as store:
        for c in store.iter_chunks():
            assert c.id not in seen
            seen.add(c.id)
            lines = sources[c.file_path]
            assert 1 <= c.start_line <= c.end_line <= len(lines), c.id
            if c.part_count == 1:
                assert c.content == slice_lines(lines, c.start_line, c.end_line), c.id
    assert len(seen) == stats.chunks


def test_seed_dataset_is_valid_for_the_pinned_commit(flask_index) -> None:  # type: ignore[no-untyped-def]
    repo, _, _ = flask_index
    assert validate_against_repo(load_dataset(DATASET), repo) == []


def test_exact_symbol_queries_return_a_definition_at_rank_1(flask_index) -> None:  # type: ignore[no-untyped-def]
    """Spec F1: 'a query for an exact function name returns it at rank 1'.

    Checked by name, not by gold span: a symbol defined several times (``@overload`` stubs)
    may legitimately return any of its definitions first.
    """
    repo, _, home = flask_index
    with open_store(repo, AstChunker(), home) as store:
        chunks = {c.id: c for c in store.iter_chunks()}
    retriever = BM25Retriever(chunks.values())
    wanted = {
        "find_best_app": "flask.cli.find_best_app",
        "stream_with_context": "flask.helpers.stream_with_context",
        "get_debug_flag": "flask.helpers.get_debug_flag",
        "load_dotenv": "flask.cli.load_dotenv",
        "SecureCookieSessionInterface": "flask.sessions.SecureCookieSessionInterface",
        "Scaffold.route": "flask.sansio.scaffold.Scaffold.route",
    }
    for query, qualified in wanted.items():
        top = retriever.retrieve(Query(text=query, repo_id=repo.id), 1)[0]
        assert chunks[top.chunk_id].qualified_name == qualified, query
