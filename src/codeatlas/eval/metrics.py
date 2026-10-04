"""Retrieval metrics. Small, pure, and hand-verifiable — these decide the results.

A retrieved chunk is a ``(file_path, start_line, end_line)`` triple. It *hits* a gold span when
it is in the same file and the line ranges overlap. Matching on line overlap (not chunk IDs)
is what lets fixed-window and AST chunks be scored against identical gold labels.

* ``recall_at_k``      fraction of gold spans hit by at least one of the top-k chunks
* ``file_recall_at_k`` fraction of gold *files* appearing among the top-k chunks
* ``reciprocal_rank``  1 / rank of the first chunk hitting any gold span (0 if none)

Dataset-level MRR / Recall@k are plain means over answerable questions.
"""

from __future__ import annotations

from collections.abc import Sequence

from codeatlas.eval.dataset import GoldSpan

RetrievedSpan = tuple[str, int, int]  # (file_path, start_line, end_line), in rank order


def hits(chunk: RetrievedSpan, gold: GoldSpan) -> bool:
    path, start, end = chunk
    return path == gold.file_path and start <= gold.end_line and gold.start_line <= end


def recall_at_k(ranked: Sequence[RetrievedSpan], gold: Sequence[GoldSpan], k: int) -> float:
    if not gold:
        raise ValueError("recall is undefined without gold spans")
    top = ranked[:k]
    return sum(any(hits(c, g) for c in top) for g in gold) / len(gold)


def file_recall_at_k(ranked: Sequence[RetrievedSpan], gold: Sequence[GoldSpan], k: int) -> float:
    if not gold:
        raise ValueError("recall is undefined without gold spans")
    gold_files = {g.file_path for g in gold}
    top_files = {path for path, _, _ in ranked[:k]}
    return len(gold_files & top_files) / len(gold_files)


def first_hit_rank(ranked: Sequence[RetrievedSpan], gold: Sequence[GoldSpan]) -> int | None:
    for rank, chunk in enumerate(ranked, start=1):
        if any(hits(chunk, g) for g in gold):
            return rank
    return None


def reciprocal_rank(ranked: Sequence[RetrievedSpan], gold: Sequence[GoldSpan]) -> float:
    rank = first_hit_rank(ranked, gold)
    return 0.0 if rank is None else 1.0 / rank


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
