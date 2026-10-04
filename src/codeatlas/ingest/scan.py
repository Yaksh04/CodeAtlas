"""Filesystem scan: which files at a commit are worth parsing, and their text."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

from codeatlas.core.models import Repository, SourceFile
from codeatlas.ingest.git import GitReader, list_tree
from codeatlas.ingest.text import normalize_newlines, split_lines

LANGUAGE_BY_EXTENSION = {".py": "python"}
MAX_FILE_BYTES = 1_000_000
SKIP_DIRS = frozenset({"node_modules", "vendor", "site-packages", ".venv", "venv", "__pycache__"})
_TEST_FILE = re.compile(r"(^test_.*\.py$)|(.*_test\.py$)|(^conftest\.py$)")


def is_test_path(path: str) -> bool:
    p = PurePosixPath(path)
    return bool(_TEST_FILE.match(p.name)) or any(part in ("tests", "test") for part in p.parts[:-1])


def language_for(path: str) -> str | None:
    return LANGUAGE_BY_EXTENSION.get(PurePosixPath(path).suffix)


def iter_source_files(repo: Repository) -> Iterator[tuple[SourceFile, str]]:
    """Yield ``(SourceFile, text)`` for every supported, non-vendored, non-binary file."""
    root = Path(repo.local_path)
    with GitReader(root) as reader:
        for entry in list_tree(root, repo.indexed_commit):
            language = language_for(entry.path)
            if language is None or entry.size > MAX_FILE_BYTES:
                continue
            if SKIP_DIRS.intersection(PurePosixPath(entry.path).parts[:-1]):
                continue
            data = reader.read(entry.blob_sha)
            if data is None or b"\0" in data:
                continue
            text = normalize_newlines(data.decode("utf-8", errors="replace"))
            yield (
                SourceFile(
                    repository_id=repo.id,
                    path=entry.path,
                    language=language,
                    blob_sha=entry.blob_sha,
                    commit=repo.indexed_commit,
                    n_lines=len(split_lines(text)),
                    is_test=is_test_path(entry.path),
                ),
                text,
            )
