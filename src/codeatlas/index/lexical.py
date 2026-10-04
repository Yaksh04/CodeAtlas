"""BM25 over pre-tokenized documents.

Written by hand (about 40 lines) rather than pulled from a library: it is the baseline every
other retriever is compared against, so its behavior should be readable and testable.

Formula (Lucene-style, IDF is never negative):

    idf(t)      = ln(1 + (N - df + 0.5) / (df + 0.5))
    score(d, q) = sum over unique query terms t of
                  idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(d) / avg_len))
"""

from __future__ import annotations

import math
from collections import Counter


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._postings: dict[str, list[tuple[str, int]]] = {}  # term -> [(doc_id, tf)]
        self._lengths: dict[str, int] = {}
        self._avg_len = 0.0

    def build(self, docs: dict[str, list[str]]) -> None:
        self._postings = {}
        self._lengths = {doc_id: len(tokens) for doc_id, tokens in docs.items()}
        total = sum(self._lengths.values())
        self._avg_len = total / len(docs) if docs else 0.0
        for doc_id, tokens in docs.items():
            for term, tf in Counter(tokens).items():
                self._postings.setdefault(term, []).append((doc_id, tf))

    def __len__(self) -> int:
        return len(self._lengths)

    def scores(self, query_tokens: list[str]) -> dict[str, float]:
        """BM25 score of every document sharing at least one term with the query."""
        n_docs = len(self._lengths)
        out: dict[str, float] = {}
        for term in set(query_tokens):
            postings = self._postings.get(term)
            if not postings:
                continue
            df = len(postings)
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            for doc_id, tf in postings:
                norm = self.k1 * (1 - self.b + self.b * self._lengths[doc_id] / self._avg_len)
                out[doc_id] = out.get(doc_id, 0.0) + idf * tf * (self.k1 + 1) / (tf + norm)
        return out

    def search(self, query_tokens: list[str], k: int) -> list[tuple[str, float]]:
        ranked = sorted(self.scores(query_tokens).items(), key=lambda kv: (-kv[1], kv[0]))
        return ranked[:k]
