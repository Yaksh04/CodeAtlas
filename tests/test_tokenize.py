from __future__ import annotations

import pytest

from codeatlas.core.ids import chunk_id, content_hash, module_path
from codeatlas.retrieve.tokenize import split_identifier, tokenize


@pytest.mark.parametrize(
    ("word", "parts"),
    [
        ("getUserById", ["get", "user", "by", "id"]),
        ("get_user_by_id", ["get", "user", "by", "id"]),
        ("HTTPAuthMiddleware", ["http", "auth", "middleware"]),
        ("parseHTMLString", ["parse", "html", "string"]),
        ("__init__", ["init"]),
        ("_private_helper", ["private", "helper"]),
        ("MAX_RETRIES", ["max", "retries"]),
        ("sha256Hash", ["sha256", "hash"]),
        ("HTTP2Server", ["http2", "server"]),
        ("route", ["route"]),
        ("XMLHttpRequest", ["xml", "http", "request"]),
    ],
)
def test_split_identifier(word: str, parts: list[str]) -> None:
    assert split_identifier(word) == parts


def test_tokenize_keeps_whole_identifier_and_parts() -> None:
    assert tokenize("getUserById") == ["getuserbyid", "get", "user", "by", "id"]
    assert tokenize("get_user_by_id") == ["get_user_by_id", "get", "user", "by", "id"]
    assert tokenize("__init__") == ["__init__", "init"]
    assert tokenize("route") == ["route"]


def test_camel_and_snake_forms_share_part_tokens() -> None:
    camel, snake = set(tokenize("getUserById")), set(tokenize("get_user_by_id"))
    assert {"get", "user", "by", "id"} <= camel & snake


def test_tokenize_ignores_punctuation_numbers_and_one_letter_names() -> None:
    assert tokenize("x = 42 + a") == []
    assert tokenize("foo.bar(baz)") == ["foo", "bar", "baz"]


def test_query_stopwords_only_dropped_on_request() -> None:
    q = "Where is the user login handled?"
    assert tokenize(q, drop_stopwords=True) == ["user", "login", "handled"]
    assert "where" in tokenize(q)


def test_module_path() -> None:
    assert module_path("src/flask/app.py") == "flask.app"
    assert module_path("src/flask/json/__init__.py") == "flask.json"
    assert module_path("tests/test_basic.py") == "tests.test_basic"
    assert module_path("setup.py") == "setup"


def test_ids_and_hash() -> None:
    assert chunk_id("r", "a.py", "a.f", 1) == "r:a.py:a.f#1"
    assert chunk_id("r", "a.py", "a.f", 0, part=2) == "r:a.py:a.f#0.p2"
    assert content_hash("x") == content_hash("x") != content_hash("y")
