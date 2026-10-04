"""Language-neutral output of an extractor. No Tree-sitter types may appear here."""

from __future__ import annotations

from dataclasses import dataclass, field

from codeatlas.core.models import ChunkKind


@dataclass(frozen=True)
class Symbol:
    """A function, method or class found in one file.

    ``start_line``/``end_line`` cover the whole definition including decorators. For classes,
    ``header_end_line`` is the last line before the first nested def (the part that becomes the
    class chunk); for functions it equals ``end_line``.
    """

    name: str
    qualified_name: str
    kind: ChunkKind  # FUNCTION | METHOD | CLASS
    signature: str
    docstring: str | None
    parent_qualified_name: str | None
    start_line: int
    end_line: int
    header_end_line: int
    def_line: int  # the `def`/`class` line (differs from start_line when decorated)
    body_stmt_spans: tuple[tuple[int, int], ...] = ()  # functions only; used for splitting
    ordinal: int = 0  # disambiguates duplicate qualified names within the file


@dataclass(frozen=True)
class ModuleBlock:
    """A run of module-level statements that are not part of any def/class."""

    start_line: int
    end_line: int
    ordinal: int


@dataclass(frozen=True)
class ExtractedFile:
    module: str  # dotted module path derived from the file path
    symbols: list[Symbol] = field(default_factory=list)
    module_blocks: list[ModuleBlock] = field(default_factory=list)
    has_syntax_errors: bool = False
