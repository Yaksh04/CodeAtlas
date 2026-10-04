"""Run one retriever configuration against one dataset and write a reproducible record.

``codeatlas eval --config configs/bm25_ast.yaml`` -> ``results/<name>/<timestamp>/``:

* ``config.json``       resolved config + everything needed to reproduce (commit, dataset hash,
                        chunker parameters, index stats, package versions)
* ``metrics.json``      overall and per-category metrics, latency summary
* ``per_question.jsonl`` top results and hit rank for every question (for error analysis)
* ``report.md``         human-readable tables and the list of misses
"""

from __future__ import annotations

import json
import platform
import statistics
import time
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from codeatlas.core.models import Chunk, Query
from codeatlas.eval.dataset import EvalQuestion, load_dataset, validate_against_repo
from codeatlas.eval.metrics import (
    RetrievedSpan,
    file_recall_at_k,
    first_hit_rank,
    mean,
    recall_at_k,
    reciprocal_rank,
)
from codeatlas.index.pipeline import build_index, index_exists, index_path, open_store
from codeatlas.ingest.chunker import get_chunker
from codeatlas.ingest.repo import resolve_repository
from codeatlas.retrieve.factory import build_retriever


class RetrieverConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["bm25"]
    params: dict[str, Any] = Field(default_factory=dict)


class EvalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    repo: str  # URL or local path
    rev: str  # pinned commit (full SHA recommended)
    chunker: Literal["ast", "fixed"]
    retriever: RetrieverConfig
    dataset: str  # path, relative to the config file
    ks: list[int] = Field(default_factory=lambda: [1, 5, 10])

    @staticmethod
    def load(path: Path) -> tuple[EvalConfig, Path]:
        """Returns the config and the directory relative paths resolve against."""
        cfg = EvalConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        return cfg, path.resolve().parent


def _versions() -> dict[str, str]:
    out = {"python": platform.python_version()}
    for pkg in ("codeatlas", "tree-sitter", "tree-sitter-python", "pydantic"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = "unknown"
    return out


def score_question(
    q: EvalQuestion, ranked: list[RetrievedSpan], ks: list[int]
) -> dict[str, float | int | None]:
    scores: dict[str, float | int | None] = {"mrr": reciprocal_rank(ranked, q.gold_spans)}
    scores["first_hit_rank"] = first_hit_rank(ranked, q.gold_spans)
    for k in ks:
        scores[f"recall@{k}"] = recall_at_k(ranked, q.gold_spans, k)
        scores[f"file_recall@{k}"] = file_recall_at_k(ranked, q.gold_spans, k)
    return scores


def aggregate(rows: list[dict[str, Any]], ks: list[int]) -> dict[str, float]:
    names = ["mrr"] + [f"{m}@{k}" for k in ks for m in ("recall", "file_recall")]
    out = {name: round(mean([r["scores"][name] for r in rows]), 4) for name in names}
    out["n"] = len(rows)
    return out


def run_eval(
    cfg: EvalConfig, base_dir: Path, *, home: Path | None = None, results_root: Path | None = None
) -> Path:
    """Execute the config. Returns the results directory."""
    dataset = load_dataset(base_dir / cfg.dataset)
    repo = resolve_repository(cfg.repo, cfg.rev, home)
    problems = validate_against_repo(dataset, repo)
    if problems:
        raise ValueError("dataset does not match repository:\n  " + "\n  ".join(problems))

    chunker = get_chunker(cfg.chunker)
    if not index_exists(repo, chunker, home):
        build_index(repo, chunker, home)
    manifest = json.loads((index_path(repo, chunker, home) / "manifest.json").read_text())

    with open_store(repo, chunker, home) as store:
        chunks: dict[str, Chunk] = {c.id: c for c in store.iter_chunks()}
    retriever = build_retriever(cfg.retriever.type, cfg.retriever.params, chunks.values())

    max_k = max(cfg.ks)
    rows: list[dict[str, Any]] = []
    latencies_ms: list[float] = []
    for q in dataset.questions:
        if not q.answerable:
            continue  # abstention metrics arrive with answer generation (Sprint 3)
        started = time.perf_counter()
        results = retriever.retrieve(Query(text=q.question, repo_id=repo.id), max(max_k, 10))
        latencies_ms.append((time.perf_counter() - started) * 1000)
        ranked = [
            (
                chunks[r.chunk_id].file_path,
                chunks[r.chunk_id].start_line,
                chunks[r.chunk_id].end_line,
            )
            for r in results
        ]
        rows.append(
            {
                "id": q.id,
                "category": q.category.value,
                "question": q.question,
                "scores": score_question(q, ranked, cfg.ks),
                "gold": [g.model_dump() for g in q.gold_spans],
                "top": [
                    {
                        "rank": r.rank,
                        "chunk_id": r.chunk_id,
                        "qualified_name": chunks[r.chunk_id].qualified_name,
                        "span": f"{ranked[i][0]}:{ranked[i][1]}-{ranked[i][2]}",
                        "score": round(r.score, 4),
                    }
                    for i, r in enumerate(results[:5])
                ],
            }
        )

    by_category = {
        cat: aggregate([r for r in rows if r["category"] == cat], cfg.ks)
        for cat in sorted({r["category"] for r in rows})
    }
    metrics = {
        "overall": aggregate(rows, cfg.ks),
        "by_category": by_category,
        "latency_ms": {
            "median": round(statistics.median(latencies_ms), 3) if latencies_ms else 0.0,
            "max": round(max(latencies_ms), 3) if latencies_ms else 0.0,
        },
    }

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = (results_root or Path("results")) / cfg.name / stamp
    out_dir.mkdir(parents=True)
    snapshot = {
        "config": cfg.model_dump(),
        "commit": repo.indexed_commit,
        "dataset_sha256": dataset.sha256,
        "chunker_params": manifest["chunker_params"],
        "index_stats": manifest["stats"],
        "versions": _versions(),
    }
    (out_dir / "config.json").write_text(json.dumps(snapshot, indent=2, sort_keys=True))
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True))
    (out_dir / "per_question.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8"
    )
    (out_dir / "report.md").write_text(render_report(cfg, metrics, rows), encoding="utf-8")
    return out_dir


def _table(header: list[str], body: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)


def render_report(cfg: EvalConfig, metrics: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    cols = [k for k in metrics["overall"] if k != "n"]
    table_rows = [
        ["ALL", str(metrics["overall"]["n"]), *(f"{metrics['overall'][c]:.3f}" for c in cols)]
    ]
    for cat, m in metrics["by_category"].items():
        table_rows.append([cat, str(m["n"]), *(f"{m[c]:.3f}" for c in cols)])
    misses = [
        r
        for r in rows
        if r["scores"]["first_hit_rank"] is None or r["scores"]["first_hit_rank"] > max(cfg.ks)
    ]
    out = [
        f"# {cfg.name}",
        f"repo `{cfg.repo}` @ `{cfg.rev[:12]}` | chunker `{cfg.chunker}` | "
        f"retriever `{cfg.retriever.type}` {cfg.retriever.params or ''}",
        "",
        _table(["category", "n", *cols], table_rows),
        "",
        f"median latency: {metrics['latency_ms']['median']} ms",
        "",
        f"## Misses (no hit in top {max(cfg.ks)}): {len(misses)}",
    ]
    for r in misses:
        gold = ", ".join(f"{g['file_path']}:{g['start_line']}-{g['end_line']}" for g in r["gold"])
        top = ", ".join(t["span"] for t in r["top"][:3])
        out.append(
            f"- **{r['id']}** ({r['category']}) {r['question']}\n  gold: {gold}\n  top3: {top}"
        )
    return "\n".join(out) + "\n"
