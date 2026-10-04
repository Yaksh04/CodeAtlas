"""Where CodeAtlas keeps clones and indexes.

Default is ``~/.codeatlas`` (override with ``CODEATLAS_HOME``). Deliberately *not* inside the
project checkout: on this team's machines the checkout lives in OneDrive, and syncing SQLite
files and cloned repos there causes locks and needless traffic.
"""

from __future__ import annotations

import os
from pathlib import Path


def data_home() -> Path:
    env = os.environ.get("CODEATLAS_HOME")
    return Path(env) if env else Path.home() / ".codeatlas"


def clones_dir(home: Path | None = None) -> Path:
    return (home or data_home()) / "repos"


def index_dir(repo_id: str, commit: str, chunker: str, home: Path | None = None) -> Path:
    """One index per (repository, commit, chunking strategy)."""
    return (home or data_home()) / "indexes" / repo_id / commit[:12] / chunker
