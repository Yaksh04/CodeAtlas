"""Metrics checked against values worked out by hand."""

from __future__ import annotations

import pytest

from codeatlas.eval.dataset import GoldSpan
from codeatlas.eval.metrics import (
    file_recall_at_k,
    first_hit_rank,
    hits,
    mean,
    recall_at_k,
    reciprocal_rank,
)


def g(path: str, a: int, b: int) -> GoldSpan:
    return GoldSpan(file_path=path, start_line=a, end_line=b)


def test_overlap_semantics() -> None:
    gold = g("a.py", 10, 20)
    assert hits(("a.py", 1, 10), gold)  # touching at one line counts
    assert hits(("a.py", 20, 30), gold)
    assert hits(("a.py", 12, 14), gold)  # chunk inside gold
    assert hits(("a.py", 1, 100), gold)  # chunk contains gold
    assert not hits(("a.py", 1, 9), gold)
    assert not hits(("a.py", 21, 30), gold)
    assert not hits(("b.py", 10, 20), gold)  # wrong file


def test_reciprocal_rank_and_first_hit() -> None:
    gold = [g("a.py", 10, 20)]
    ranked = [("b.py", 1, 5), ("a.py", 1, 5), ("a.py", 15, 18), ("a.py", 12, 13)]
    assert first_hit_rank(ranked, gold) == 3
    assert reciprocal_rank(ranked, gold) == pytest.approx(1 / 3)
    assert reciprocal_rank([("z.py", 1, 2)], gold) == 0.0
    assert first_hit_rank([], gold) is None


def test_recall_is_fraction_of_gold_spans_hit() -> None:
    gold = [g("a.py", 10, 20), g("b.py", 1, 5), g("c.py", 1, 5)]
    ranked = [("a.py", 12, 14), ("x.py", 1, 2), ("b.py", 3, 4), ("c.py", 100, 200)]
    assert recall_at_k(ranked, gold, 1) == pytest.approx(1 / 3)
    assert recall_at_k(ranked, gold, 2) == pytest.approx(1 / 3)
    assert recall_at_k(ranked, gold, 3) == pytest.approx(2 / 3)
    assert recall_at_k(ranked, gold, 4) == pytest.approx(2 / 3)  # c.py chunk misses the lines


def test_file_recall_ignores_line_ranges() -> None:
    gold = [g("a.py", 10, 20), g("a.py", 50, 60), g("b.py", 1, 5)]
    ranked = [("a.py", 1, 2), ("b.py", 900, 901)]
    assert file_recall_at_k(ranked, gold, 1) == pytest.approx(1 / 2)
    assert file_recall_at_k(ranked, gold, 2) == 1.0
    assert recall_at_k(ranked, gold, 2) == 0.0  # same chunks miss every line range


def test_recall_requires_gold() -> None:
    with pytest.raises(ValueError):
        recall_at_k([("a.py", 1, 2)], [], 5)


def test_mean() -> None:
    assert mean([1.0, 0.0, 0.5]) == pytest.approx(0.5)
    assert mean([]) == 0.0
