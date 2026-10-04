from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from codeatlas.core.models import Repository
from codeatlas.eval.dataset import load_dataset, validate_against_repo
from codeatlas.eval.runner import EvalConfig, run_eval

QUESTIONS = [
    {
        "id": "q1",
        "question": "Where is validate_token defined?",
        "category": "definition",
        "gold_spans": [{"file_path": "pkg/auth.py", "start_line": 4, "end_line": 6}],
    },
    {
        "id": "q2",
        "question": "look up a user by primary key",
        "category": "single_hop",
        "gold_spans": [{"file_path": "pkg/auth.py", "start_line": 9, "end_line": 11}],
    },
    {
        "id": "q3",
        "question": "insert a record into the database",
        "category": "single_hop",
        "gold_spans": [{"file_path": "pkg/storage.py", "start_line": 11, "end_line": 14}],
    },
    {
        "id": "q4",
        "question": "how does the kubernetes operator scale pods",
        "category": "architecture",
        "gold_spans": [],
        "answerable": False,
    },
]


def write_dataset(path: Path, commit: str, questions: list[dict] = QUESTIONS) -> None:
    lines = [{"_meta": {"repo": "sample", "commit": commit}}, *questions]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")


def write_config(tmp: Path, repo: Repository, chunker: str = "ast") -> Path:
    cfg = {
        "name": f"bm25_{chunker}",
        "repo": repo.local_path,
        "rev": repo.indexed_commit,
        "chunker": chunker,
        "retriever": {"type": "bm25"},
        "dataset": "data.jsonl",
    }
    path = tmp / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg))
    write_dataset(tmp / "data.jsonl", repo.indexed_commit)
    return path


def test_dataset_loading_and_validation(tmp_path: Path, sample_repo: Repository) -> None:
    write_dataset(tmp_path / "d.jsonl", sample_repo.indexed_commit)
    ds = load_dataset(tmp_path / "d.jsonl")
    assert [q.id for q in ds.questions] == ["q1", "q2", "q3", "q4"]
    assert len(ds.sha256) == 64
    assert validate_against_repo(ds, sample_repo) == []


def test_dataset_rejects_bad_records(tmp_path: Path) -> None:
    bad_span = dict(QUESTIONS[0], gold_spans=[{"file_path": "a", "start_line": 9, "end_line": 2}])
    no_gold = dict(QUESTIONS[0], gold_spans=[])
    dup = [QUESTIONS[0], QUESTIONS[0]]
    for i, qs in enumerate([[bad_span], [no_gold], dup]):
        write_dataset(tmp_path / f"{i}.jsonl", "a" * 40, qs)
        with pytest.raises((ValidationError, ValueError)):
            load_dataset(tmp_path / f"{i}.jsonl")
    (tmp_path / "nometa.jsonl").write_text(json.dumps(QUESTIONS[0]) + "\n")
    with pytest.raises(ValueError, match="_meta"):
        load_dataset(tmp_path / "nometa.jsonl")


def test_validation_catches_out_of_range_missing_file_and_wrong_commit(
    tmp_path: Path, sample_repo: Repository
) -> None:
    qs = [
        dict(
            QUESTIONS[0],
            id="far",
            gold_spans=[{"file_path": "pkg/auth.py", "start_line": 1, "end_line": 999}],
        ),
        dict(
            QUESTIONS[0],
            id="gone",
            gold_spans=[{"file_path": "pkg/nope.py", "start_line": 1, "end_line": 2}],
        ),
    ]
    write_dataset(tmp_path / "d.jsonl", sample_repo.indexed_commit, qs)
    problems = validate_against_repo(load_dataset(tmp_path / "d.jsonl"), sample_repo)
    assert any("far" in p and "lines" in p for p in problems)
    assert any("gone" in p and "does not exist" in p for p in problems)

    write_dataset(tmp_path / "e.jsonl", "f" * 40)
    assert (
        "dataset is for commit"
        in validate_against_repo(load_dataset(tmp_path / "e.jsonl"), sample_repo)[0]
    )


def test_config_rejects_unknown_fields(tmp_path: Path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text(
        "name: x\nrepo: r\nrev: v\nchunker: ast\nretriever: {type: bm25}\ndataset: d\nsurprise: 1\n"
    )
    with pytest.raises(ValidationError):
        EvalConfig.load(p)


def test_run_eval_scores_and_writes_artifacts(
    tmp_path: Path, sample_repo: Repository, home: Path
) -> None:
    cfg, base = EvalConfig.load(write_config(tmp_path, sample_repo))
    out = run_eval(cfg, base, home=home, results_root=tmp_path / "results")

    metrics = json.loads((out / "metrics.json").read_text())
    assert metrics["overall"]["n"] == 3  # the unanswerable question is excluded
    assert metrics["overall"]["mrr"] == 1.0  # all three are easy lexical hits on the fixture
    assert metrics["overall"]["recall@1"] == 1.0
    assert set(metrics["by_category"]) == {"definition", "single_hop"}

    snapshot = json.loads((out / "config.json").read_text())
    assert snapshot["commit"] == sample_repo.indexed_commit
    assert len(snapshot["dataset_sha256"]) == 64
    assert snapshot["config"]["retriever"] == {"type": "bm25", "params": {}}
    assert snapshot["chunker_params"] == {"max_chunk_chars": 6000}
    assert "python" in snapshot["versions"]

    rows = [json.loads(x) for x in (out / "per_question.jsonl").read_text().splitlines()]
    assert rows[0]["top"][0]["qualified_name"] == "pkg.auth.validate_token"
    assert "# bm25_ast" in (out / "report.md").read_text()


def test_run_eval_is_deterministic(tmp_path: Path, sample_repo: Repository, home: Path) -> None:
    cfg, base = EvalConfig.load(write_config(tmp_path, sample_repo))
    a = run_eval(cfg, base, home=home, results_root=tmp_path / "r1")
    b = run_eval(cfg, base, home=home, results_root=tmp_path / "r2")
    for name in ("per_question.jsonl", "config.json"):
        assert (a / name).read_text() == (b / name).read_text(), name
    ma, mb = (json.loads((d / "metrics.json").read_text()) for d in (a, b))
    assert ma["overall"] == mb["overall"] and ma["by_category"] == mb["by_category"]


def test_run_eval_refuses_dataset_for_other_commit(
    tmp_path: Path, sample_repo: Repository, home: Path
) -> None:
    cfg_path = write_config(tmp_path, sample_repo)
    write_dataset(tmp_path / "data.jsonl", "0" * 40)
    cfg, base = EvalConfig.load(cfg_path)
    with pytest.raises(ValueError, match="does not match repository"):
        run_eval(cfg, base, home=home, results_root=tmp_path / "results")


def test_fixed_chunker_config_runs(tmp_path: Path, sample_repo: Repository, home: Path) -> None:
    cfg, base = EvalConfig.load(write_config(tmp_path, sample_repo, "fixed"))
    out = run_eval(cfg, base, home=home, results_root=tmp_path / "results")
    metrics = json.loads((out / "metrics.json").read_text())
    assert metrics["overall"]["recall@10"] == 1.0
