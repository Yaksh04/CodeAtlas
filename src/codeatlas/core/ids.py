"""Stable identifiers and hashes.

Chunk identity deliberately excludes line numbers and commit SHAs, so editing a function's
body keeps its ID and changes only its ``content_hash``. That pair is what incremental
indexing (Sprint 6) diffs on.
"""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_id(
    repo_id: str,
    file_path: str,
    qualified_name: str,
    ordinal: int = 0,
    part: int | None = None,
) -> str:
    """``ordinal`` disambiguates duplicate qualified names in one file (``@overload``,
    property setters, ``if/else`` alternative definitions). ``part`` is set only for the
    pieces of an oversized symbol that was split."""
    base = f"{repo_id}:{file_path}:{qualified_name}#{ordinal}"
    return base if part is None else f"{base}.p{part}"


def module_path(file_path: str) -> str:
    """``src/flask/app.py`` -> ``flask.app``; ``pkg/__init__.py`` -> ``pkg``.

    A leading ``src/`` is dropped (src-layout). Otherwise the path is used verbatim, which
    keeps names unique and predictable without needing to read packaging metadata.
    """
    parts = list(PurePosixPath(file_path).with_suffix("").parts)
    if parts and parts[0] == "src" and len(parts) > 1:
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)
