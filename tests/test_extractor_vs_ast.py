"""Independent check of the Tree-sitter extractor against Python's own ``ast`` module.

``ast`` is a different parser written by different people, so agreement on every symbol's name
and line span across a real codebase is strong evidence the extractor is right. The ``ast``
walker below follows the same scope rules documented in ``python_extractor``.
"""

from __future__ import annotations

import ast
import os
from collections import Counter
from pathlib import Path

import pytest

from codeatlas.core.ids import module_path
from codeatlas.ingest.git import GitReader, list_tree
from codeatlas.ingest.python_extractor import extract_python
from codeatlas.ingest.text import normalize_newlines

FIXTURES = Path(__file__).parent / "fixtures/sample_repo"
FLASK_SHA = "22d924701a6ae2e4cd01e9a15bbaf3946094af65"

Span = tuple[str, int, int, int]  # qualified_name, ordinal, start_line, end_line


def ast_symbols(text: str, file_path: str) -> list[Span]:
    counts: Counter[str] = Counter()
    out: list[Span] = []

    def walk(body: list[ast.stmt], scope: str) -> None:
        for node in body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                qualified = f"{scope}.{node.name}"
                start = min([d.lineno for d in node.decorator_list] + [node.lineno])
                assert node.end_lineno is not None
                out.append((qualified, counts[qualified], start, node.end_lineno))
                counts[qualified] += 1
                if isinstance(node, ast.ClassDef):
                    walk(node.body, qualified)
            else:
                # compound statements at module/class level: search their blocks for defs
                for field in ("body", "orelse", "finalbody"):
                    walk(getattr(node, field, []) or [], scope)
                for handler in getattr(node, "handlers", []) or []:
                    walk(handler.body, scope)
                for case in getattr(node, "cases", []) or []:
                    walk(case.body, scope)

    walk(ast.parse(text).body, module_path(file_path))
    return out


def ts_symbols(text: str, file_path: str) -> list[Span]:
    return [
        (s.qualified_name, s.ordinal, s.start_line, s.end_line)
        for s in extract_python(text, file_path).symbols
    ]


def test_matches_ast_on_fixtures() -> None:
    for path in sorted(FIXTURES.rglob("*.py")):
        rel = path.relative_to(FIXTURES).as_posix()
        text = path.read_text()
        assert sorted(ts_symbols(text, rel)) == sorted(ast_symbols(text, rel)), rel


@pytest.mark.flask
def test_matches_ast_on_every_file_of_pinned_flask() -> None:
    flask = os.environ.get("CODEATLAS_FLASK_REPO")
    if not flask or not (Path(flask) / ".git").exists():
        pytest.skip("set CODEATLAS_FLASK_REPO to a Flask clone containing the pinned commit")
    root = Path(flask)
    n_files = n_symbols = 0
    with GitReader(root) as reader:
        for entry in list_tree(root, FLASK_SHA):
            if not entry.path.endswith(".py"):
                continue
            data = reader.read(entry.blob_sha)
            assert data is not None
            text = normalize_newlines(data.decode("utf-8"))
            try:
                expected = ast_symbols(text, entry.path)
            except SyntaxError:
                continue
            assert sorted(ts_symbols(text, entry.path)) == sorted(expected), entry.path
            n_files += 1
            n_symbols += len(expected)
    assert n_files > 50 and n_symbols > 500
