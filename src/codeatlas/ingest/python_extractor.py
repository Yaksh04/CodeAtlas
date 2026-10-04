"""Tree-sitter Python extractor: source text -> normalized ``Symbol``s.

Scope rules (deliberately simple and documented, because retrieval quality depends on them):

* Top-level functions, classes, and methods of (possibly nested) classes become symbols.
* Functions nested inside functions do NOT become symbols; their text belongs to the parent.
* ``if`` / ``try`` / ``with`` / ``for`` / ``while`` / ``match`` blocks at module or class level
  are searched for definitions (``if TYPE_CHECKING:``, ``try: ... except ImportError:``
  fallbacks, version-conditional defs). Such a compound statement that contains a definition is
  not itself emitted as a module block.
* Module-level statements outside any def/class are grouped into contiguous ``ModuleBlock``s.
"""

from __future__ import annotations

import ast
import inspect
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from codeatlas.core.ids import module_path
from codeatlas.core.models import ChunkKind
from codeatlas.ingest.symbols import ExtractedFile, ModuleBlock, Symbol

_PARSER = Parser(Language(tree_sitter_python.language()))
_COMPOUND = frozenset(
    {
        "if_statement",
        "try_statement",
        "with_statement",
        "for_statement",
        "while_statement",
        "match_statement",
        "case_clause",
    }
)


def _def_node(node: Node) -> Node | None:
    """The function/class definition behind ``node``, unwrapping decorators."""
    if node.type == "decorated_definition":
        node = node.child_by_field_name("definition") or node
    return node if node.type in ("function_definition", "class_definition") else None


def _nested_blocks(node: Node) -> Iterator[Node]:
    """Statement blocks belonging to a compound statement (including elif/else/except/...)."""
    for child in node.named_children:
        if child.type == "block":
            yield child
        elif child.type.endswith("_clause") or child.type == "case_clause":
            yield from _nested_blocks(child)


def _contains_def(node: Node) -> bool:
    for block in _nested_blocks(node):
        for child in block.named_children:
            if _def_node(child) is not None:
                return True
            if child.type in _COMPOUND and _contains_def(child):
                return True
    return False


def _first_line(node: Node) -> int:
    return node.start_point.row + 1


def _last_line(node: Node) -> int:
    """1-indexed last line. A node ending at column 0 really ends on the previous line."""
    end = node.end_point
    return end.row if end.column == 0 and end.row + 1 > _first_line(node) else end.row + 1


def _docstring(body: Node) -> str | None:
    first = next((c for c in body.named_children if c.type != "comment"), None)
    if first is None or first.type != "expression_statement" or not first.named_children:
        return None
    literal = first.named_children[0]
    if literal.type != "string" or literal.text is None:
        return None
    raw = literal.text.decode("utf-8", "replace")
    try:
        value = ast.literal_eval(raw)
        if not isinstance(value, str):
            value = raw
    except (ValueError, SyntaxError):
        value = raw
    return inspect.cleandoc(value) or None


@dataclass
class _Walker:
    src: bytes
    module: str
    counts: Counter[str] = field(default_factory=Counter)
    symbols: list[Symbol] = field(default_factory=list)

    def signature(self, node: Node, body: Node) -> str:
        text = self.src[node.start_byte : body.start_byte].decode("utf-8", "replace")
        return " ".join(text.split()).rstrip(":").rstrip()

    def next_ordinal(self, qualified_name: str) -> int:
        ordinal = self.counts[qualified_name]
        self.counts[qualified_name] += 1
        return ordinal

    def walk_scope(self, container: Node, scope: str, in_class: bool) -> None:
        """Emit symbols found directly in ``container`` (module or class body), recursing
        through compound statements but never into function bodies."""
        parent = scope if in_class else None
        for child in container.named_children:
            definition = _def_node(child)
            if definition is not None:
                if definition.type == "function_definition":
                    self.function(child, definition, scope, parent, in_class)
                else:
                    self.klass(child, definition, scope, parent)
            elif child.type in _COMPOUND:
                for block in _nested_blocks(child):
                    self.walk_scope(block, scope, in_class)

    def function(
        self, outer: Node, node: Node, scope: str, parent: str | None, in_class: bool
    ) -> None:
        name_node = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        if name_node is None or name_node.text is None or body is None:
            return
        name = name_node.text.decode("utf-8", "replace")
        qualified = f"{scope}.{name}"
        self.symbols.append(
            Symbol(
                name=name,
                qualified_name=qualified,
                kind=ChunkKind.METHOD if in_class else ChunkKind.FUNCTION,
                signature=self.signature(node, body),
                docstring=_docstring(body),
                parent_qualified_name=parent,
                start_line=_first_line(outer),
                end_line=_last_line(outer),
                header_end_line=_last_line(outer),
                def_line=_first_line(node),
                body_stmt_spans=tuple((_first_line(s), _last_line(s)) for s in body.named_children),
                ordinal=self.next_ordinal(qualified),
            )
        )

    def klass(self, outer: Node, node: Node, scope: str, parent: str | None) -> None:
        name_node = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        if name_node is None or name_node.text is None or body is None:
            return
        name = name_node.text.decode("utf-8", "replace")
        qualified = f"{scope}.{name}"
        start, end = _first_line(outer), _last_line(outer)
        first_nested = next(
            (
                c
                for c in body.named_children
                if _def_node(c) is not None or (c.type in _COMPOUND and _contains_def(c))
            ),
            None,
        )
        header_end = max(start, _first_line(first_nested) - 1) if first_nested else end
        self.symbols.append(
            Symbol(
                name=name,
                qualified_name=qualified,
                kind=ChunkKind.CLASS,
                signature=self.signature(node, body),
                docstring=_docstring(body),
                parent_qualified_name=parent,
                start_line=start,
                end_line=end,
                header_end_line=header_end,
                def_line=_first_line(node),
                ordinal=self.next_ordinal(qualified),
            )
        )
        self.walk_scope(body, qualified, in_class=True)


def _module_blocks(root: Node) -> list[ModuleBlock]:
    blocks: list[ModuleBlock] = []
    run: list[Node] = []

    def flush() -> None:
        while run and run[-1].type == "comment":  # a trailing comment belongs to what follows
            run.pop()
        if run:
            blocks.append(ModuleBlock(_first_line(run[0]), _last_line(run[-1]), len(blocks)))
        run.clear()

    for child in root.named_children:
        is_boundary = _def_node(child) is not None or (
            child.type in _COMPOUND and _contains_def(child)
        )
        if is_boundary:
            flush()
        else:
            run.append(child)
    flush()
    return blocks


def extract_python(text: str, file_path: str) -> ExtractedFile:
    """Parse ``text`` (already newline-normalized) and return its symbols and module blocks."""
    src = text.encode("utf-8")
    # Keep `tree` alive for the whole function: nodes do not own it, and touching a node after
    # the tree is garbage-collected is a hard crash (access violation), not an exception.
    tree = _PARSER.parse(src)
    root = tree.root_node
    module = module_path(file_path)
    walker = _Walker(src=src, module=module)
    walker.walk_scope(root, module, in_class=False)
    return ExtractedFile(
        module=module,
        symbols=walker.symbols,
        module_blocks=_module_blocks(root),
        has_syntax_errors=root.has_error,
    )
