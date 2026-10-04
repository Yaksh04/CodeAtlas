"""Chunkers turn one file into ``Chunk``s. Two strategies, one interface, so the eval can
compare them (ablation rows 1 vs 2).

* ``AstChunker``: one chunk per function / method / class header / module-level run.
* ``FixedWindowChunker``: the naive baseline (overlapping line windows).

Content rules (tested):
* A normal chunk's ``content`` is exactly the source lines ``start_line..end_line`` (trailing
  blank lines trimmed).
* An oversized function is split at statement boundaries. Part 0 is a plain slice; parts >= 1
  are the repeated ``def`` header lines followed by their slice. Part spans are contiguous and
  together cover the whole function.
"""

from __future__ import annotations

from typing import Protocol

from codeatlas.core.ids import chunk_id, content_hash, module_path
from codeatlas.core.models import Chunk, ChunkKind, SourceFile
from codeatlas.ingest.python_extractor import extract_python
from codeatlas.ingest.symbols import Symbol
from codeatlas.ingest.text import slice_lines, split_lines


class Chunker(Protocol):
    name: str

    def chunk_file(self, source: SourceFile, text: str) -> list[Chunk]: ...


def _trim_end(lines: list[str], start: int, end: int) -> int:
    """Move ``end`` up past trailing blank lines (never above ``start``)."""
    while end > start and not lines[end - 1].strip():
        end -= 1
    return end


class AstChunker:
    name = "ast"

    def __init__(self, max_chunk_chars: int = 6000) -> None:
        self.max_chunk_chars = max_chunk_chars

    def chunk_file(self, source: SourceFile, text: str) -> list[Chunk]:
        if source.language != "python":
            raise ValueError(f"AstChunker does not support language {source.language!r}")
        lines = split_lines(text)
        extracted = extract_python(text, source.path)
        chunks: list[Chunk] = []
        for sym in extracted.symbols:
            chunks.extend(self._symbol_chunks(source, lines, sym))
        for block in extracted.module_blocks:
            end = _trim_end(lines, block.start_line, block.end_line)
            chunks.append(
                self._make(
                    source,
                    kind=ChunkKind.MODULE_BLOCK,
                    qualified_name=f"{extracted.module}.<module>",
                    ordinal=block.ordinal,
                    symbol_name=None,
                    start=block.start_line,
                    end=end,
                    content=slice_lines(lines, block.start_line, end),
                )
            )
        chunks.sort(key=lambda c: (c.start_line, c.end_line, c.id))
        return chunks

    # ---------------------------------------------------------------- helpers

    def _symbol_chunks(self, source: SourceFile, lines: list[str], sym: Symbol) -> list[Chunk]:
        end = _trim_end(lines, sym.start_line, sym.header_end_line)
        if sym.kind is ChunkKind.CLASS or end - sym.start_line < 1:
            spans = [(sym.start_line, end)]
        else:
            spans = self._split_spans(lines, sym, end)

        chunks: list[Chunk] = []
        header = self._header_text(lines, sym)
        for part, (start, stop) in enumerate(spans):
            body = slice_lines(lines, start, stop)
            content = body if part == 0 else f"{header}\n{body}"
            chunks.append(
                self._make(
                    source,
                    kind=sym.kind,
                    qualified_name=sym.qualified_name,
                    ordinal=sym.ordinal,
                    symbol_name=sym.name,
                    start=start,
                    end=stop,
                    content=content,
                    sym=sym,
                    part=(part, len(spans)),
                )
            )
        return chunks

    def _split_spans(self, lines: list[str], sym: Symbol, end: int) -> list[tuple[int, int]]:
        """Greedy packing of body statements into parts of at most ``max_chunk_chars``.

        Boundaries fall between statements. A single statement larger than the limit stays
        whole. Spans are contiguous, so no line of the function is lost.
        """
        if len(slice_lines(lines, sym.start_line, end)) <= self.max_chunk_chars:
            return [(sym.start_line, end)]
        spans: list[tuple[int, int]] = []
        part_start, part_end = sym.start_line, None
        for _, stmt_end in sym.body_stmt_spans:
            if (
                part_end is not None
                and len(slice_lines(lines, part_start, stmt_end)) > self.max_chunk_chars
            ):
                spans.append((part_start, part_end))
                part_start = part_end + 1
            part_end = stmt_end
        spans.append((part_start, end))
        return spans

    @staticmethod
    def _header_text(lines: list[str], sym: Symbol) -> str:
        first_stmt = sym.body_stmt_spans[0][0] if sym.body_stmt_spans else sym.def_line + 1
        header = slice_lines(lines, sym.def_line, max(sym.def_line, first_stmt - 1))
        return header if header.strip() else f"{sym.signature}:"

    @staticmethod
    def _make(
        source: SourceFile,
        *,
        kind: ChunkKind,
        qualified_name: str,
        ordinal: int,
        symbol_name: str | None,
        start: int,
        end: int,
        content: str,
        sym: Symbol | None = None,
        part: tuple[int, int] = (0, 1),
    ) -> Chunk:
        part_index, part_count = part
        return Chunk(
            id=chunk_id(
                source.repository_id,
                source.path,
                qualified_name,
                ordinal,
                part=part_index if part_count > 1 else None,
            ),
            repository_id=source.repository_id,
            file_path=source.path,
            language=source.language,
            kind=kind,
            symbol_name=symbol_name,
            qualified_name=qualified_name,
            signature=sym.signature if sym else None,
            docstring=sym.docstring if sym else None,
            parent_qualified_name=sym.parent_qualified_name if sym else None,
            start_line=start,
            end_line=end,
            content=content,
            content_hash=content_hash(content),
            part_index=part_index,
            part_count=part_count,
            indexed_commit=source.commit,
            is_test=source.is_test,
        )


class FixedWindowChunker:
    """Baseline: overlapping windows of ``window_lines`` lines, ignoring code structure."""

    name = "fixed"

    def __init__(self, window_lines: int = 40, overlap_lines: int = 10) -> None:
        if not 0 <= overlap_lines < window_lines:
            raise ValueError("need 0 <= overlap_lines < window_lines")
        self.window_lines = window_lines
        self.overlap_lines = overlap_lines

    def chunk_file(self, source: SourceFile, text: str) -> list[Chunk]:
        lines = split_lines(text)
        module = module_path(source.path)
        step = self.window_lines - self.overlap_lines
        chunks: list[Chunk] = []
        start = 1
        while start <= len(lines):
            end = min(start + self.window_lines - 1, len(lines))
            content = slice_lines(lines, start, end)
            if content.strip():
                chunks.append(
                    Chunk(
                        id=chunk_id(source.repository_id, source.path, module, len(chunks)),
                        repository_id=source.repository_id,
                        file_path=source.path,
                        language=source.language,
                        kind=ChunkKind.FIXED_WINDOW,
                        qualified_name=module,
                        start_line=start,
                        end_line=end,
                        content=content,
                        content_hash=content_hash(content),
                        indexed_commit=source.commit,
                        is_test=source.is_test,
                    )
                )
            if end == len(lines):
                break
            start += step
        return chunks


def get_chunker(name: str) -> Chunker:
    if name == "ast":
        return AstChunker()
    if name == "fixed":
        return FixedWindowChunker()
    raise ValueError(f"unknown chunker {name!r} (expected 'ast' or 'fixed')")
