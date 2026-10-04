"""Shared data contracts.

Every other package (ingest, index, retrieve, eval, later agent/verify) depends on these
types and on nothing Tree-sitter-specific. Sprint 1 only defines what Sprint 1 needs; the
graph, answer and tool-result types arrive with the sprints that produce them.

Conventions:
* Line numbers are 1-indexed and inclusive on both ends.
* ``Chunk.id`` is a *stable identity* (see ``core.ids``); ``Chunk.content_hash`` changes when
  the text changes. Incremental indexing diffs on the pair.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ChunkKind(StrEnum):
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"  # class header: signature, docstring, class-level statements before 1st method
    MODULE_BLOCK = "module_block"  # a run of module-level statements outside any def/class
    FIXED_WINDOW = "fixed_window"  # baseline chunker only


class QuestionCategory(StrEnum):
    """Fixed taxonomy for eval questions. Changing it later means relabeling datasets."""

    SYMBOL_LOOKUP = "symbol_lookup"
    DEFINITION = "definition"
    REFERENCE = "reference"
    SINGLE_HOP = "single_hop"
    MULTI_HOP = "multi_hop"
    ARCHITECTURE = "architecture"
    CHANGE_IMPACT = "change_impact"
    HISTORY = "history"
    DEBUGGING = "debugging"
    CROSS_FILE = "cross_file"


class Repository(_Frozen):
    id: str
    url: str | None = None
    local_path: str
    default_branch: str | None = None
    indexed_commit: str  # full 40-char SHA


class SourceFile(_Frozen):
    repository_id: str
    path: str  # repo-relative, forward slashes
    language: str
    blob_sha: str
    commit: str
    n_lines: int
    is_test: bool = False


class Chunk(_Frozen):
    id: str
    repository_id: str
    file_path: str
    language: str
    kind: ChunkKind
    symbol_name: str | None = None  # short name, e.g. "route"
    qualified_name: str  # module-qualified, e.g. "flask.sansio.scaffold.Scaffold.route"
    signature: str | None = None
    docstring: str | None = None
    parent_qualified_name: str | None = None
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    content: str
    content_hash: str
    # Oversized symbols are split; every part shares the symbol's qualified_name.
    part_index: int = 0
    part_count: int = 1
    indexed_commit: str
    last_modified_commit: str | None = None  # filled by Sprint 6
    is_test: bool = False

    @model_validator(mode="after")
    def _check_span(self) -> Chunk:
        if self.end_line < self.start_line:
            raise ValueError(f"end_line {self.end_line} < start_line {self.start_line}")
        return self


class Citation(_Frozen):
    repository_id: str
    commit: str
    file_path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def _check_span(self) -> Citation:
        if self.end_line < self.start_line:
            raise ValueError(f"end_line {self.end_line} < start_line {self.start_line}")
        return self


class Query(_Frozen):
    text: str
    repo_id: str
    category: QuestionCategory | None = None  # eval only; retrievers must not read it
    filters: dict[str, str] = Field(default_factory=dict)


class Provenance(_Frozen):
    """One step in how a result reached the candidate set (basis for retrieval observability)."""

    stage: str  # "bm25" | "dense" | "rrf" | "graph" | "rerank" | "agent"
    score: float
    via_edge: str | None = None  # e.g. "calls" for graph-expanded results
    from_chunk_id: str | None = None


class RetrievalResult(_Frozen):
    chunk_id: str
    score: float
    rank: int = Field(ge=1)
    stage: str  # stage that produced the final score
    provenance: list[Provenance] = Field(default_factory=list)
