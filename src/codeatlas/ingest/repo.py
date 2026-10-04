"""Turn a user-supplied source (GitHub URL or local path) into a pinned ``Repository``."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from codeatlas.core.models import Repository
from codeatlas.core.paths import clones_dir
from codeatlas.ingest.git import GitError, resolve_commit, run_git

_URL = re.compile(r"^(https?://|git@|ssh://|git://)")


def is_url(source: str) -> bool:
    return bool(_URL.match(source))


def repo_id_from_source(source: str) -> str:
    """``https://github.com/pallets/flask(.git)`` -> ``pallets__flask``; local path -> dir name."""
    if is_url(source):
        tail = re.split(r"[:/]", source.removesuffix(".git").rstrip("/"))[-2:]
        raw = "__".join(tail)
    else:
        raw = Path(source).resolve().name
    return re.sub(r"[^A-Za-z0-9_.-]", "_", raw)


def resolve_repository(source: str, rev: str | None = None, home: Path | None = None) -> Repository:
    """Clone a URL source (or open a local path) and pin ``rev`` to a full SHA.

    An existing clone is only fetched when ``rev`` is not already present, so runs against a
    pinned commit are reproducible and work offline.
    """
    if is_url(source):
        repo_id = repo_id_from_source(source)
        local = clones_dir(home) / repo_id
        if not local.exists():
            local.parent.mkdir(parents=True, exist_ok=True)
            proc = subprocess.run(
                ["git", "clone", "--quiet", source, str(local)], capture_output=True, check=False
            )
            if proc.returncode != 0:
                raise GitError(f"clone failed: {proc.stderr.decode('utf-8', 'replace')}")
        url: str | None = source
    else:
        local = Path(source).resolve()
        if not (local / ".git").exists():
            raise GitError(f"{local} is not a git repository")
        repo_id = repo_id_from_source(source)
        url = None

    try:
        commit = resolve_commit(local, rev or "HEAD")
    except GitError:
        if url is None:
            raise
        run_git(local, "fetch", "--tags", "--quiet", "origin")
        commit = resolve_commit(local, rev or "HEAD")
    try:
        branch = run_git(local, "symbolic-ref", "--short", "HEAD").decode().strip()
    except GitError:  # detached HEAD
        branch = None
    return Repository(
        id=repo_id, url=url, local_path=str(local), default_branch=branch, indexed_commit=commit
    )
