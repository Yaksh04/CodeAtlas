"""Shared fixtures: a real throwaway git repository built from tests/fixtures/sample_repo."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from codeatlas.core.models import Repository
from codeatlas.ingest.repo import resolve_repository

FIXTURES = Path(__file__).parent / "fixtures"


def git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    out = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=True, env=env
    ).stdout
    return out.decode().strip()


@pytest.fixture
def sample_repo_path(tmp_path: Path) -> Path:
    dest = tmp_path / "sample_repo"
    shutil.copytree(FIXTURES / "sample_repo", dest)
    git(dest, "init", "-q")
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "initial")
    return dest


@pytest.fixture
def sample_repo(sample_repo_path: Path, tmp_path: Path) -> Repository:
    return resolve_repository(str(sample_repo_path), home=tmp_path / "home")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"
