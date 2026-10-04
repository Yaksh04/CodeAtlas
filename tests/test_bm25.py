from __future__ import annotations

import math

import pytest

from codeatlas.core.models import Chunk, ChunkKind, Query
from codeatlas.index.lexical import BM25Index
from codeatlas.retrieve.bm25 import BM25Retriever


def test_bm25_hand_computed_score() -> None:
    # 2 docs, term "cat" in doc a only (tf=2), doc lengths 3 and 2 -> avg 2.5
    index = BM25Index(k1=1.5, b=0.75)
    index.build({"a": ["cat", "cat", "dog"], "b": ["dog", "bird"]})
    idf = math.log(1 + (2 - 1 + 0.5) / (1 + 0.5))
    expected = idf * 2 * 2.5 / (2 + 1.5 * (1 - 0.75 + 0.75 * 3 / 2.5))
    assert index.scores(["cat"]) == {"a": pytest.approx(expected)}


def test_bm25_prefers_rare_terms_and_is_deterministic() -> None:
    index = BM25Index()
    index.build({"a": ["common", "rare"], "b": ["common"], "c": ["common"], "d": ["other"]})
    assert index.search(["common", "rare"], 3)[0][0] == "a"
    # b and c tie exactly (same length); both are shorter than a, so length-normalization
    # ranks them above a, and ties break by id.
    assert [d for d, _ in index.search(["common"], 3)] == ["b", "c", "a"]
    assert index.search(["missing"], 5) == []


def make(name: str, kind: ChunkKind, content: str, path: str = "pkg/m.py", **kw: object) -> Chunk:
    short = name.rsplit(".", 1)[-1]
    return Chunk(
        id=f"r:{path}:{name}#0",
        repository_id="r",
        file_path=path,
        language="python",
        kind=kind,
        symbol_name=short,
        qualified_name=name,
        start_line=1,
        end_line=2,
        content=content,
        content_hash="h",
        indexed_commit="c" * 40,
        **kw,  # type: ignore[arg-type]
    )


def q(text: str) -> Query:
    return Query(text=text, repo_id="r")


@pytest.fixture
def chunks() -> list[Chunk]:
    return [
        make("pkg.auth.validate_token", ChunkKind.FUNCTION, "def validate_token(t): check jwt"),
        make("pkg.auth.HTTPAuthMiddleware", ChunkKind.CLASS, "class HTTPAuthMiddleware: reject"),
        make(
            "pkg.views.login",
            ChunkKind.FUNCTION,
            "def login(request): token = validate_token(request.token); "
            + "validate_token validate_token validate_token",
            path="pkg/views.py",
        ),
        make("pkg.db.save", ChunkKind.FUNCTION, "def save(conn): conn.commit()", path="pkg/db.py"),
        make("pkg.a.Store.__init__", ChunkKind.METHOD, "def __init__(self): pass", path="pkg/a.py"),
        make("pkg.b.Cache.__init__", ChunkKind.METHOD, "def __init__(self): pass", path="pkg/b.py"),
    ]


def test_exact_symbol_lookup_beats_frequent_mentions(chunks: list[Chunk]) -> None:
    top = BM25Retriever(chunks).retrieve(q("Where is validate_token defined?"), 3)
    assert top[0].chunk_id.endswith("pkg.auth.validate_token#0")
    # `login` mentions the name four times and still ranks below the definition
    assert top[1].chunk_id.endswith("pkg.views.login#0")
    assert [r.rank for r in top] == [1, 2]  # only chunks sharing a term are returned


def test_camel_case_class_found_by_parts_and_whole(chunks: list[Chunk]) -> None:
    r = BM25Retriever(chunks)
    assert r.retrieve(q("auth middleware"), 1)[0].chunk_id.endswith("HTTPAuthMiddleware#0")
    assert r.retrieve(q("HTTPAuthMiddleware"), 1)[0].chunk_id.endswith("HTTPAuthMiddleware#0")


def test_qualified_suffix_lookup(chunks: list[Chunk]) -> None:
    top = BM25Retriever(chunks).retrieve(q("Cache.__init__"), 1)
    assert top[0].chunk_id.endswith("pkg.b.Cache.__init__#0")


def test_ambiguous_name_bonus_is_discounted(chunks: list[Chunk]) -> None:
    r = BM25Retriever(chunks, exact_symbol_bonus=10.0)
    res = {x.chunk_id: x for x in r.retrieve(q("__init__"), 5)}
    bonuses = [p.score for x in res.values() for p in x.provenance if p.stage == "exact_name"]
    assert bonuses == [5.0, 5.0]  # 10 split across two definitions


def test_provenance_and_stopword_only_query(chunks: list[Chunk]) -> None:
    r = BM25Retriever(chunks)
    top = r.retrieve(q("validate_token"), 1)[0]
    assert [p.stage for p in top.provenance] == ["bm25", "exact_name"]
    assert r.retrieve(q("where is the"), 5) == []


def test_include_tests_flag() -> None:
    src = make("pkg.f", ChunkKind.FUNCTION, "def f(): frobnicate")
    test = make("tests.test_f", ChunkKind.FUNCTION, "def test_f(): frobnicate", is_test=True)
    assert len(BM25Retriever([src, test], include_tests=True).retrieve(q("frobnicate"), 5)) == 2
    kept = BM25Retriever([src, test], include_tests=False).retrieve(q("frobnicate"), 5)
    assert [r.chunk_id for r in kept] == [src.id]
