"""Build a retriever from a config entry. New strategies register here (Sprint 2: dense, hybrid)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from codeatlas.core.models import Chunk
from codeatlas.retrieve.base import Retriever
from codeatlas.retrieve.bm25 import BM25Retriever


def build_retriever(kind: str, params: dict[str, Any], chunks: Iterable[Chunk]) -> Retriever:
    if kind == "bm25":
        return BM25Retriever(chunks, **params)
    raise ValueError(f"unknown retriever type {kind!r}")
