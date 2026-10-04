# CodeAtlas

Structure-aware, agentic codebase intelligence: AST-level retrieval, a code graph, verified
`file:line` citations, and an evaluation harness that measures which retrieval strategy works
for which kind of question.

Design: [docs/SPEC.md](docs/SPEC.md) · Plan and decisions: [docs/PLAN.md](docs/PLAN.md) ·
Contributor/agent notes: [CLAUDE.md](CLAUDE.md)

## Status: Sprint 1 (parse → chunk → lexical search → measure)

```
pip install -e ".[dev]"

# index a repo at a pinned commit (clones into ~/.codeatlas, or $CODEATLAS_HOME)
codeatlas index https://github.com/pallets/flask --rev 22d924701a6ae2e4cd01e9a15bbaf3946094af65

codeatlas chunks https://github.com/pallets/flask src/flask/sansio/scaffold.py
codeatlas search https://github.com/pallets/flask "Scaffold.route"

# score a retriever config against a labelled dataset -> results/<name>/<timestamp>/
codeatlas eval --config configs/bm25_ast.yaml
codeatlas eval --config configs/bm25_fixed.yaml     # fixed-window baseline
```

## Layout
```
src/codeatlas/   core · ingest · index · retrieve · eval   (llm, verify, agent, api, tours: later)
tests/           pytest; fixtures/ holds a tiny sample repo
configs/         one YAML per retriever configuration (ablation row)
datasets/        eval questions with (file, line-range) gold spans, pinned to a commit
scripts/         dataset builders
docs/            SPEC.md, PLAN.md
web/             Next.js frontend (Sprint 7)
```
