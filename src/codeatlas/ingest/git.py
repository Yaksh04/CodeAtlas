"""Thin wrapper over the git CLI.

Source text is always read from git's object database at a specific commit, never from the
working tree. That makes "the file exists at the indexed commit" meaningful for citation
verification, and avoids CRLF/autocrlf surprises on Windows checkouts.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType


class GitError(RuntimeError):
    pass


def run_git(repo: Path, *args: str) -> bytes:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.decode('utf-8', 'replace')}")
    return proc.stdout


def resolve_commit(repo: Path, rev: str) -> str:
    """Full 40-char SHA for any rev (branch, tag, short SHA, HEAD)."""
    out = run_git(repo, "rev-parse", "--verify", f"{rev}^{{commit}}")
    return out.decode().strip()


@dataclass(frozen=True)
class TreeEntry:
    path: str
    blob_sha: str
    size: int


def list_tree(repo: Path, commit: str) -> list[TreeEntry]:
    """All regular files (blobs) at ``commit``. Submodules and symlinks are skipped."""
    raw = run_git(repo, "ls-tree", "-r", "-l", "-z", commit)
    entries: list[TreeEntry] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        meta, _, path = record.decode("utf-8", "replace").partition("\t")
        mode, obj_type, sha, size = meta.split()
        if obj_type != "blob" or mode == "120000":
            continue
        entries.append(TreeEntry(path=path, blob_sha=sha, size=int(size)))
    return entries


class GitReader:
    """Persistent ``git cat-file --batch`` process: one spawn for thousands of reads.

    ``read`` accepts anything git can name: a blob SHA or ``<commit>:<path>``.
    """

    def __init__(self, repo: Path) -> None:
        self._repo = repo
        self._proc: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> GitReader:
        self._proc = subprocess.Popen(
            ["git", "-C", str(self._repo), "cat-file", "--batch"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._proc is not None:
            assert self._proc.stdin is not None
            self._proc.stdin.close()
            self._proc.wait()
            if self._proc.stdout is not None:
                self._proc.stdout.close()
            self._proc = None

    def read(self, spec: str) -> bytes | None:
        """Object contents, or ``None`` if git does not know the object."""
        proc = self._proc
        if proc is None or proc.stdin is None or proc.stdout is None:
            raise GitError("GitReader must be used as a context manager")
        proc.stdin.write(spec.encode("utf-8") + b"\n")
        proc.stdin.flush()
        header = proc.stdout.readline().decode("utf-8", "replace").split()
        if len(header) == 2 and header[1] == "missing":
            return None
        if len(header) != 3:
            raise GitError(f"unexpected cat-file header for {spec!r}: {header}")
        size = int(header[2])
        data: bytes = proc.stdout.read(size)
        proc.stdout.read(1)  # trailing LF after the contents
        return data
