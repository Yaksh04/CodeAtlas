"""Eval dataset format (JSONL).

Line 1 is a metadata record pinning the repository and commit the gold line numbers refer to::

    {"_meta": {"repo": "https://github.com/pallets/flask", "commit": "<40-char sha>"}}

Every following line is one question::

    {"id": "q001", "question": "...", "category": "definition",
     "gold_spans": [{"file_path": "src/flask/app.py", "start_line": 10, "end_line": 20}],
     "answerable": true}

Gold labels are (file, line range) spans, NOT chunk IDs, so any chunker can be scored against
the same labels. Changing a dataset or a metric definition requires a reviewed PR.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from codeatlas.core.models import QuestionCategory, Repository
from codeatlas.ingest.git import GitReader
from codeatlas.ingest.text import normalize_newlines, split_lines


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GoldSpan(_Frozen):
    file_path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def _check(self) -> GoldSpan:
        if self.end_line < self.start_line:
            raise ValueError("end_line < start_line")
        return self


class EvalQuestion(_Frozen):
    id: str
    question: str
    category: QuestionCategory
    gold_spans: list[GoldSpan] = Field(default_factory=list)
    answerable: bool = True
    notes: str | None = None

    @model_validator(mode="after")
    def _check(self) -> EvalQuestion:
        if self.answerable and not self.gold_spans:
            raise ValueError(f"{self.id}: answerable question needs at least one gold span")
        return self


class DatasetMeta(_Frozen):
    repo: str
    commit: str


class Dataset(_Frozen):
    meta: DatasetMeta
    questions: list[EvalQuestion]
    sha256: str  # of the file bytes; recorded with every result


def load_dataset(path: Path) -> Dataset:
    raw = path.read_bytes()
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if not records or "_meta" not in records[0]:
        raise ValueError(f"{path}: first line must be a {{'_meta': ...}} record")
    questions = [EvalQuestion.model_validate(r) for r in records[1:]]
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate question ids")
    return Dataset(
        meta=DatasetMeta.model_validate(records[0]["_meta"]),
        questions=questions,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def validate_against_repo(dataset: Dataset, repo: Repository) -> list[str]:
    """Problems with gold spans at the repo's indexed commit (empty list = valid)."""
    problems: list[str] = []
    if dataset.meta.commit != repo.indexed_commit:
        problems.append(
            f"dataset is for commit {dataset.meta.commit[:12]} but repo is at "
            f"{repo.indexed_commit[:12]}"
        )
        return problems
    line_counts: dict[str, int | None] = {}
    with GitReader(Path(repo.local_path)) as reader:
        for q in dataset.questions:
            for span in q.gold_spans:
                if span.file_path not in line_counts:
                    data = reader.read(f"{repo.indexed_commit}:{span.file_path}")
                    line_counts[span.file_path] = (
                        None
                        if data is None
                        else len(split_lines(normalize_newlines(data.decode("utf-8", "replace"))))
                    )
                n = line_counts[span.file_path]
                if n is None:
                    problems.append(f"{q.id}: {span.file_path} does not exist at the commit")
                elif span.end_line > n:
                    problems.append(
                        f"{q.id}: {span.file_path} has {n} lines, span ends at {span.end_line}"
                    )
    return problems
