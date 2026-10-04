"""Command line entry point: ``codeatlas index | chunks | search | eval``."""

from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Sequence
from pathlib import Path

from codeatlas.core.models import Query
from codeatlas.eval.runner import EvalConfig, run_eval
from codeatlas.index.pipeline import build_index, index_exists, index_path, open_store
from codeatlas.ingest.chunker import get_chunker
from codeatlas.ingest.repo import resolve_repository
from codeatlas.retrieve.bm25 import BM25Retriever


def _add_source_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("source", help="GitHub URL or path to a local git repository")
    p.add_argument("--rev", default=None, help="commit/tag/branch to index (default: HEAD)")
    p.add_argument("--chunker", choices=["ast", "fixed"], default="ast")
    p.add_argument("--home", type=Path, default=None, help="data dir (default: ~/.codeatlas)")


def cmd_index(args: argparse.Namespace) -> int:
    repo = resolve_repository(args.source, args.rev, args.home)
    chunker = get_chunker(args.chunker)
    stats = build_index(repo, chunker, args.home)
    print(f"repo      {repo.id} @ {repo.indexed_commit[:12]}")
    print(f"index     {index_path(repo, chunker, args.home)}")
    print(f"files     {stats.files}  (with syntax errors: {stats.files_with_syntax_errors})")
    print(f"chunks    {stats.chunks}  {stats.chunks_by_kind}")
    print(f"time      {stats.seconds}s")
    return 0


def _ensure_index(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    repo = resolve_repository(args.source, args.rev, args.home)
    chunker = get_chunker(args.chunker)
    if not index_exists(repo, chunker, args.home):
        build_index(repo, chunker, args.home)
    return repo, chunker


def cmd_chunks(args: argparse.Namespace) -> int:
    repo, chunker = _ensure_index(args)
    with open_store(repo, chunker, args.home) as store:
        chunks = store.chunks_in_file(args.file)
    if not chunks:
        print(f"no chunks for {args.file}")
        return 1
    for c in chunks:
        part = f" part {c.part_index + 1}/{c.part_count}" if c.part_count > 1 else ""
        print(f"{c.start_line:>5}-{c.end_line:<5} {c.kind.value:<12} {c.qualified_name}{part}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    repo, chunker = _ensure_index(args)
    with open_store(repo, chunker, args.home) as store:
        chunks = {c.id: c for c in store.iter_chunks()}
    retriever = BM25Retriever(chunks.values())
    for r in retriever.retrieve(Query(text=args.query, repo_id=repo.id), args.k):
        c = chunks[r.chunk_id]
        print(
            f"{r.rank:>2}  {r.score:7.2f}  {c.file_path}:{c.start_line}-{c.end_line}  "
            f"{c.kind.value} {c.qualified_name}"
        )
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    cfg, base_dir = EvalConfig.load(args.config)
    out = run_eval(cfg, base_dir, home=args.home, results_root=args.results_dir)
    print((out / "report.md").read_text(encoding="utf-8"))
    print(f"results written to {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codeatlas")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("index", help="parse and index a repository at one commit")
    _add_source_args(p)
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("chunks", help="list the chunks of one file")
    _add_source_args(p)
    p.add_argument("file", help="repo-relative path, e.g. src/flask/app.py")
    p.set_defaults(func=cmd_chunks)

    p = sub.add_parser("search", help="BM25 search over an indexed repository")
    _add_source_args(p)
    p.add_argument("query")
    p.add_argument("-k", type=int, default=10)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("eval", help="run a retriever config against a dataset")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--home", type=Path, default=None)
    p.add_argument("--results-dir", type=Path, default=None)
    p.set_defaults(func=cmd_eval)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
