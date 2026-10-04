from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.core.models import ChunkKind
from codeatlas.ingest.python_extractor import extract_python
from codeatlas.ingest.symbols import ExtractedFile, Symbol

SHAPES = (Path(__file__).parent / "fixtures/sample_repo/pkg/shapes.py").read_text()


@pytest.fixture(scope="module")
def shapes() -> ExtractedFile:
    return extract_python(SHAPES, "pkg/shapes.py")


def by_name(ex: ExtractedFile, qualified: str, ordinal: int = 0) -> Symbol:
    matches = [s for s in ex.symbols if s.qualified_name == qualified and s.ordinal == ordinal]
    assert len(matches) == 1, f"{qualified}#{ordinal}: {[s.qualified_name for s in ex.symbols]}"
    return matches[0]


def test_module_path_and_symbol_inventory(shapes: ExtractedFile) -> None:
    assert shapes.module == "pkg.shapes"
    assert not shapes.has_syntax_errors
    assert sorted((s.qualified_name, s.ordinal) for s in shapes.symbols) == [
        ("pkg.shapes.Shape", 0),
        ("pkg.shapes.Shape.Meta", 0),
        ("pkg.shapes.Shape.__init__", 0),
        ("pkg.shapes.Shape.describe", 0),
        ("pkg.shapes.Shape.label", 0),
        ("pkg.shapes.Shape.label", 1),
        ("pkg.shapes.area_of_circle", 0),
        ("pkg.shapes.area_of_circle", 1),
        ("pkg.shapes.fetch_area", 0),
    ]


def test_plain_function(shapes: ExtractedFile) -> None:
    s = by_name(shapes, "pkg.shapes.area_of_circle")
    assert (s.start_line, s.end_line) == (8, 10)
    assert s.kind is ChunkKind.FUNCTION
    assert s.signature == "def area_of_circle(radius: float) -> float"
    assert s.docstring == "Return the area of a circle."
    assert s.parent_qualified_name is None


def test_decorated_async_multiline_signature(shapes: ExtractedFile) -> None:
    s = by_name(shapes, "pkg.shapes.fetch_area")
    assert (s.start_line, s.def_line, s.end_line) == (13, 15, 20)  # span includes decorators
    assert s.signature == "async def fetch_area(shape_id: int, scale: float = 1.0) -> float"


def test_nested_function_is_not_a_symbol(shapes: ExtractedFile) -> None:
    assert not any("inner_helper" in s.qualified_name for s in shapes.symbols)


def test_class_header_stops_before_first_method(shapes: ExtractedFile) -> None:
    s = by_name(shapes, "pkg.shapes.Shape")
    assert s.kind is ChunkKind.CLASS
    assert (s.start_line, s.end_line, s.header_end_line) == (23, 43, 27)
    assert s.signature == "class Shape(Base)"
    assert s.docstring == "A generic shape."


def test_methods_and_parent(shapes: ExtractedFile) -> None:
    init = by_name(shapes, "pkg.shapes.Shape.__init__")
    assert init.kind is ChunkKind.METHOD
    assert init.parent_qualified_name == "pkg.shapes.Shape"
    assert (init.start_line, init.end_line) == (28, 29)


def test_property_setter_gets_distinct_ordinals(shapes: ExtractedFile) -> None:
    getter = by_name(shapes, "pkg.shapes.Shape.label", 0)
    setter = by_name(shapes, "pkg.shapes.Shape.label", 1)
    assert (getter.start_line, getter.end_line) == (31, 33)
    assert (setter.start_line, setter.end_line) == (35, 37)


def test_nested_class_without_methods(shapes: ExtractedFile) -> None:
    meta = by_name(shapes, "pkg.shapes.Shape.Meta")
    assert (meta.start_line, meta.end_line, meta.header_end_line) == (39, 40, 40)
    assert meta.parent_qualified_name == "pkg.shapes.Shape"


def test_definition_inside_try_except_is_found_with_new_ordinal(shapes: ExtractedFile) -> None:
    fallback = by_name(shapes, "pkg.shapes.area_of_circle", 1)
    assert (fallback.start_line, fallback.end_line) == (49, 50)
    assert fallback.kind is ChunkKind.FUNCTION  # try/except is not a class scope


def test_module_blocks_skip_defs_and_def_containing_compounds(shapes: ExtractedFile) -> None:
    assert [(b.start_line, b.end_line, b.ordinal) for b in shapes.module_blocks] == [
        (1, 5, 0),
        (53, 53, 1),
    ]


def test_empty_file() -> None:
    ex = extract_python("", "pkg/empty.py")
    assert ex.symbols == [] and ex.module_blocks == []


def test_syntax_error_does_not_crash_and_is_flagged() -> None:
    ex = extract_python("def ok():\n    return 1\n\ndef broken(:\n    pass\n", "pkg/bad.py")
    assert ex.has_syntax_errors
    assert any(s.name == "ok" for s in ex.symbols)


def test_init_file_module_path() -> None:
    ex = extract_python("def f():\n    pass\n", "src/flask/json/__init__.py")
    assert ex.symbols[0].qualified_name == "flask.json.f"


def test_trailing_comment_is_not_part_of_module_block() -> None:
    text = "X = 1\n# describes f\n\ndef f():\n    pass\n"
    ex = extract_python(text, "m.py")
    assert [(b.start_line, b.end_line) for b in ex.module_blocks] == [(1, 1)]
