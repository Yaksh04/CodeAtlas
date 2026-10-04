"""Text normalization shared by every chunker, so line numbers mean the same thing everywhere."""

from __future__ import annotations


def normalize_newlines(text: str) -> str:
    """CRLF -> LF. Line *counts* are unchanged, so citations stay valid for CRLF checkouts."""
    return text.replace("\r\n", "\n")


def split_lines(text: str) -> list[str]:
    """Split on ``\\n`` only (``str.splitlines`` also splits on form feeds and unicode
    separators, which would disagree with Tree-sitter's row numbers)."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def slice_lines(lines: list[str], start_line: int, end_line: int) -> str:
    """Text of the 1-indexed inclusive range, without a trailing newline."""
    return "\n".join(lines[start_line - 1 : end_line])
