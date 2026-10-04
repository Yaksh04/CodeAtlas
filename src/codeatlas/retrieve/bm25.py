"""BM25 retriever over chunks, with an exact-identifier bonus.

Two things make plain BM25 work for code:

1. Document text = name tokens (repeated ``name_boost`` times) + file-path tokens + content
   tokens, all through the identifier-aware tokenizer.
2. Exact names. If the query mentions an identifier that *is* a symbol (``Scaffold.route``,
   ``validate_token``), chunks defining it get an additive bonus, discounted when the name is
   ambiguous (``__init__`` defined in thirty classes should not flood the top ranks).

Both knobs are constructor arguments so the eval can sweep them.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

from codeatlas.core.models import Chunk, Provenance, Query, RetrievalResult
from codeatlas.index.lexical import BM25Index
from codeatlas.retrieve.tokenize import STOPWORDS, tokenize

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


def document_tokens(chunk: Chunk, name_boost: int) -> list[str]:
    return (
        tokenize(chunk.qualified_name) * name_boost
        + tokenize(chunk.file_path)
        + tokenize(chunk.content)
    )


class BM25Retriever:
    name = "bm25"

    def __init__(
        self,
        chunks: Iterable[Chunk],
        *,
        name_boost: int = 3,
        exact_qualified_bonus: float = 20.0,
        exact_symbol_bonus: float = 10.0,
        include_tests: bool = True,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.exact_qualified_bonus = exact_qualified_bonus
        self.exact_symbol_bonus = exact_symbol_bonus
        kept = [c for c in chunks if include_tests or not c.is_test]
        self._index = BM25Index(k1=k1, b=b)
        self._index.build({c.id: document_tokens(c, name_boost) for c in kept})

        # Exact-name lookup tables cover part 0 of named symbols only.
        self._by_symbol: dict[str, list[str]] = defaultdict(list)
        self._by_qualified: dict[str, list[str]] = defaultdict(list)
        for c in kept:
            if c.symbol_name is None or c.part_index != 0:
                continue
            self._by_symbol[c.symbol_name].append(c.id)
            dotted = c.qualified_name.split(".")
            for i in range(len(dotted) - 1):  # every suffix with >= 2 components
                self._by_qualified[".".join(dotted[i:])].append(c.id)

    def _name_bonuses(self, text: str) -> dict[str, float]:
        bonuses: dict[str, float] = defaultdict(float)
        for ident in set(_IDENT.findall(text)):
            if ident.lower() in STOPWORDS:
                continue
            if "." in ident:
                table, bonus = self._by_qualified, self.exact_qualified_bonus
            else:
                table, bonus = self._by_symbol, self.exact_symbol_bonus
            ids = table.get(ident, [])
            for chunk_id in ids:
                bonuses[chunk_id] += bonus / len(ids)
        return bonuses

    def retrieve(self, query: Query, k: int) -> list[RetrievalResult]:
        text_scores = self._index.scores(tokenize(query.text, drop_stopwords=True))
        bonuses = self._name_bonuses(query.text)
        combined = {
            cid: text_scores.get(cid, 0.0) + bonuses.get(cid, 0.0)
            for cid in text_scores.keys() | bonuses.keys()
        }
        ranked = sorted(combined.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        results = []
        for rank, (chunk_id, score) in enumerate(ranked, start=1):
            provenance = [Provenance(stage="bm25", score=text_scores.get(chunk_id, 0.0))]
            if chunk_id in bonuses:
                provenance.append(Provenance(stage="exact_name", score=bonuses[chunk_id]))
            results.append(
                RetrievalResult(
                    chunk_id=chunk_id, score=score, rank=rank, stage="bm25", provenance=provenance
                )
            )
        return results
