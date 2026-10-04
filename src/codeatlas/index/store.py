"""SQLite metadata store: repository, files, chunks.

SQLite is the durable source of truth. Search structures (BM25 now, FAISS and the graph later)
are derived from it and can always be rebuilt.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path
from types import TracebackType

from codeatlas.core.models import Chunk, Repository, SourceFile

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY, repository_id TEXT NOT NULL, language TEXT NOT NULL,
    blob_sha TEXT NOT NULL, commit_sha TEXT NOT NULL, n_lines INTEGER NOT NULL,
    is_test INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY, repository_id TEXT NOT NULL, file_path TEXT NOT NULL,
    language TEXT NOT NULL, kind TEXT NOT NULL, symbol_name TEXT,
    qualified_name TEXT NOT NULL, signature TEXT, docstring TEXT,
    parent_qualified_name TEXT, start_line INTEGER NOT NULL, end_line INTEGER NOT NULL,
    content TEXT NOT NULL, content_hash TEXT NOT NULL, part_index INTEGER NOT NULL,
    part_count INTEGER NOT NULL, indexed_commit TEXT NOT NULL, last_modified_commit TEXT,
    is_test INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_file ON chunks(file_path);
CREATE INDEX IF NOT EXISTS chunks_symbol ON chunks(symbol_name);
"""

_CHUNK_COLUMNS = tuple(Chunk.model_fields)


class ChunkStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._db.execute(
            "INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
        )
        self._db.commit()

    def __enter__(self) -> ChunkStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._db.commit()
        self._db.close()

    # ------------------------------------------------------------- repository

    def save_repository(self, repo: Repository) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO meta VALUES ('repository', ?)", (repo.model_dump_json(),)
        )
        self._db.commit()

    def load_repository(self) -> Repository | None:
        row = self._db.execute("SELECT value FROM meta WHERE key = 'repository'").fetchone()
        return Repository.model_validate_json(row["value"]) if row else None

    # ------------------------------------------------------------------ files

    def upsert_files(self, files: Iterable[SourceFile]) -> None:
        self._db.executemany(
            "INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    f.path,
                    f.repository_id,
                    f.language,
                    f.blob_sha,
                    f.commit,
                    f.n_lines,
                    int(f.is_test),
                )
                for f in files
            ],
        )
        self._db.commit()

    def count_files(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM files").fetchone()[0])

    # ----------------------------------------------------------------- chunks

    def upsert_chunks(self, chunks: Iterable[Chunk]) -> None:
        placeholders = ", ".join("?" * len(_CHUNK_COLUMNS))
        self._db.executemany(
            f"INSERT OR REPLACE INTO chunks ({', '.join(_CHUNK_COLUMNS)}) VALUES ({placeholders})",
            [tuple(getattr(c, col) for col in _CHUNK_COLUMNS) for c in chunks],
        )
        self._db.commit()

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        row = self._db.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
        return Chunk(**dict(row)) if row else None

    def iter_chunks(self) -> Iterator[Chunk]:
        for row in self._db.execute("SELECT * FROM chunks ORDER BY file_path, start_line, id"):
            yield Chunk(**dict(row))

    def chunks_in_file(self, file_path: str) -> list[Chunk]:
        rows = self._db.execute(
            "SELECT * FROM chunks WHERE file_path = ? ORDER BY start_line, id", (file_path,)
        )
        return [Chunk(**dict(r)) for r in rows]

    def count_chunks(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
