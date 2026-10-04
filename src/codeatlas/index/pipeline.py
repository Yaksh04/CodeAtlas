"""Full (non-incremental) indexing: repository -> files -> chunks -> SQLite + manifest."""

from __future__ import annotations

import json
import shutil
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from codeatlas.core.models import Repository
from codeatlas.core.paths import index_dir
from codeatlas.index.store import ChunkStore
from codeatlas.ingest.chunker import Chunker
from codeatlas.ingest.python_extractor import extract_python
from codeatlas.ingest.scan import iter_source_files

DB_NAME = "index.sqlite"
MANIFEST_NAME = "manifest.json"


@dataclass
class IndexStats:
    files: int
    chunks: int
    files_with_syntax_errors: int
    chunks_by_kind: dict[str, int]
    seconds: float


def index_path(repo: Repository, chunker: Chunker, home: Path | None = None) -> Path:
    return index_dir(repo.id, repo.indexed_commit, chunker.name, home)


def index_exists(repo: Repository, chunker: Chunker, home: Path | None = None) -> bool:
    return (index_path(repo, chunker, home) / MANIFEST_NAME).exists()


def build_index(repo: Repository, chunker: Chunker, home: Path | None = None) -> IndexStats:
    """Build (replacing any previous build) the index for ``repo`` at its pinned commit."""
    started = time.perf_counter()
    target = index_path(repo, chunker, home)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    kinds: Counter[str] = Counter()
    syntax_errors = 0
    n_files = n_chunks = 0
    with ChunkStore(target / DB_NAME) as store:
        store.save_repository(repo)
        for source, text in iter_source_files(repo):
            chunks = chunker.chunk_file(source, text)
            # Syntax-error tracking re-parses only for the stats line; cheap next to embedding.
            if source.language == "python" and extract_python(text, source.path).has_syntax_errors:
                syntax_errors += 1
            store.upsert_files([source])
            store.upsert_chunks(chunks)
            kinds.update(c.kind.value for c in chunks)
            n_files += 1
            n_chunks += len(chunks)

    stats = IndexStats(
        files=n_files,
        chunks=n_chunks,
        files_with_syntax_errors=syntax_errors,
        chunks_by_kind=dict(sorted(kinds.items())),
        seconds=round(time.perf_counter() - started, 3),
    )
    manifest = {
        "repository": repo.model_dump(),
        "chunker": chunker.name,
        "chunker_params": {k: v for k, v in vars(chunker).items() if not k.startswith("_")},
        "stats": asdict(stats),
    }
    (target / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return stats


def open_store(repo: Repository, chunker: Chunker, home: Path | None = None) -> ChunkStore:
    return ChunkStore(index_path(repo, chunker, home) / DB_NAME)
