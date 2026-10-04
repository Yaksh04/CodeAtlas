"""The retriever interface every strategy implements (BM25 now; dense, hybrid, graph, agent
later). Eval configs select implementations, so ablations swap them without touching callers."""

from __future__ import annotations

from typing import Protocol

from codeatlas.core.models import Query, RetrievalResult


class Retriever(Protocol):
    name: str

    def retrieve(self, query: Query, k: int) -> list[RetrievalResult]:
        """Top ``k`` results, best first, with 1-indexed ``rank``."""
        ...
