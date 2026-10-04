from __future__ import annotations

from pathlib import Path

from codeatlas.core.models import Chunk, ChunkKind, SourceFile
from codeatlas.ingest.chunker import AstChunker, FixedWindowChunker
from codeatlas.ingest.text import slice_lines, split_lines

SHAPES = (Path(__file__).parent / "fixtures/sample_repo/pkg/shapes.py").read_text()


def source(path: str = "pkg/shapes.py", is_test: bool = False) -> SourceFile:
    return SourceFile(
        repository_id="r",
        path=path,
        language="python",
        blob_sha="b" * 40,
        commit="c" * 40,
        n_lines=0,
        is_test=is_test,
    )


def test_normal_chunks_are_exact_source_slices() -> None:
    lines = split_lines(SHAPES)
    chunks = AstChunker().chunk_file(source(), SHAPES)
    assert chunks
    for c in chunks:
        assert c.part_count == 1
        assert c.content == slice_lines(lines, c.start_line, c.end_line), c.id
        assert c.content == c.content.rstrip("\n")


def test_class_chunk_is_header_only() -> None:
    chunks = {c.id: c for c in AstChunker().chunk_file(source(), SHAPES)}
    cls = chunks["r:pkg/shapes.py:pkg.shapes.Shape#0"]
    assert (cls.start_line, cls.end_line) == (23, 26)  # trailing blank line trimmed
    assert "def describe" not in cls.content
    assert cls.kind is ChunkKind.CLASS


def test_ids_are_unique_and_stable_across_body_edits() -> None:
    chunks = AstChunker().chunk_file(source(), SHAPES)
    assert len({c.id for c in chunks}) == len(chunks)

    edited = SHAPES.replace(
        "return self.name\n\n    @label", "return self.name.upper()\n\n    @label"
    )
    assert edited != SHAPES
    after = {c.id: c for c in AstChunker().chunk_file(source(), edited)}
    before = {c.id: c for c in chunks}
    assert before.keys() == after.keys()  # identity unchanged...
    changed = {i for i in before if before[i].content_hash != after[i].content_hash}
    assert changed == {"r:pkg/shapes.py:pkg.shapes.Shape.label#0"}  # ...only the edited hash moves


def test_duplicate_qualified_names_get_distinct_ids() -> None:
    ids = {c.id for c in AstChunker().chunk_file(source(), SHAPES)}
    assert "r:pkg/shapes.py:pkg.shapes.area_of_circle#0" in ids
    assert "r:pkg/shapes.py:pkg.shapes.area_of_circle#1" in ids


def test_chunk_metadata_is_propagated() -> None:
    chunks = AstChunker().chunk_file(
        source("tests/test_x.py", is_test=True), "def test_a():\n    pass\n"
    )
    (c,) = chunks
    assert c.is_test and c.indexed_commit == "c" * 40 and c.symbol_name == "test_a"


def _big_function() -> str:
    body = "\n".join(f"    value_{i} = compute({i})  # padding line" for i in range(60))
    return f'def big(a, b):\n    """Doc."""\n{body}\n    return a\n'


def test_oversized_function_is_split_contiguously_with_repeated_header() -> None:
    text = _big_function()
    lines = split_lines(text)
    chunks = AstChunker(max_chunk_chars=600).chunk_file(source("m.py"), text)
    parts = [c for c in chunks if c.qualified_name == "m.big"]
    assert len(parts) > 2
    assert [p.part_index for p in parts] == list(range(len(parts)))
    assert all(p.part_count == len(parts) for p in parts)
    assert len({p.id for p in parts}) == len(parts)

    # spans are contiguous and cover the whole function
    assert parts[0].start_line == 1 and parts[-1].end_line == len(lines)
    for prev, nxt in zip(parts, parts[1:], strict=False):
        assert nxt.start_line == prev.end_line + 1
    # part 0 is a pure slice; later parts are header + slice
    assert parts[0].content == slice_lines(lines, parts[0].start_line, parts[0].end_line)
    for p in parts[1:]:
        assert p.content.startswith("def big(a, b):\n")
        assert p.content.endswith(slice_lines(lines, p.start_line, p.end_line))
    # no source line is lost
    covered = "\n".join(slice_lines(lines, p.start_line, p.end_line) for p in parts)
    assert covered == "\n".join(lines)


def test_small_function_is_not_split() -> None:
    chunks = AstChunker(max_chunk_chars=600).chunk_file(source("m.py"), "def f():\n    return 1\n")
    assert len(chunks) == 1 and chunks[0].part_count == 1


def test_fixed_window_covers_file_with_overlap() -> None:
    text = "\n".join(f"line {i}" for i in range(1, 101)) + "\n"
    chunks = FixedWindowChunker(window_lines=40, overlap_lines=10).chunk_file(source("m.py"), text)
    spans = [(c.start_line, c.end_line) for c in chunks]
    assert spans == [(1, 40), (31, 70), (61, 100)]
    assert all(c.kind is ChunkKind.FIXED_WINDOW for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)


def test_fixed_window_skips_blank_windows_and_handles_short_files() -> None:
    assert FixedWindowChunker().chunk_file(source("m.py"), "") == []
    (only,) = FixedWindowChunker().chunk_file(source("m.py"), "x = 1\n")
    assert (only.start_line, only.end_line) == (1, 1)


def test_chunk_model_rejects_inverted_span() -> None:
    import pytest
    from pydantic import ValidationError

    good = AstChunker().chunk_file(source("m.py"), "def f():\n    pass\n")[0]
    with pytest.raises(ValidationError):
        Chunk(**{**good.model_dump(), "start_line": 5, "end_line": 2})
