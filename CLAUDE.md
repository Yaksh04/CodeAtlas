# CodeAtlas — instructions for Claude Code

Source of truth: [docs/SPEC.md](docs/SPEC.md). Sprint plan and recorded decisions: [docs/PLAN.md](docs/PLAN.md).

## What this is
A structure-aware, agentic "chat with a codebase" system, and equally a **research harness**: the
goal is to measure which retrieval strategy (lexical, dense, hybrid, AST, graph expansion,
reranking, agent) works for which kind of code question. Do not architect the eval so that the
proposed system wins automatically; negative results are results.

## Current status (updated 2026-10-04)
**Sprint 1 complete** (parse -> chunk -> lexical search -> measure). Next: **Sprint 2** (dense
retrieval, fixed-chunk baseline, RRF hybrid; ablation rows 1-3). Full roadmap in [docs/PLAN.md](docs/PLAN.md).

Done in Sprint 1:
- Tree-sitter Python extractor -> `Symbol` -> AST chunker (+ fixed-window baseline chunker); split of
  oversized functions; stable chunk ids + content hashes.
- Git object-DB reader, scanner, SQLite `ChunkStore`, full indexing pipeline, manifest per index.
- Identifier-aware tokenizer, hand-written BM25, exact-name bonus, `Retriever` interface.
- Eval harness: dataset format (JSONL, pinned commit), metrics (Recall@k, file recall, MRR),
  runner writing config snapshot + per-question results + report.
- Flask 3.1.3 seed dataset (33 questions, 2 unanswerable), built by `scripts/build_flask_seed.py`.
- 84 tests (4 need `CODEATLAS_FLASK_REPO`), ruff + mypy clean, CI workflow written (not yet run on GitHub).

Baseline results, BM25 on Flask 3.1.3, 31 answerable questions:
| chunker | MRR | R@1 | R@5 | R@10 |
|---|---|---|---|---|
| ast | 0.657 | 0.516 | 0.753 | 0.812 |
| fixed | 0.458 | 0.242 | 0.731 | 0.892 |

BM25 is strong on symbol lookup/definition, weak on conceptual and multi-hop questions. Fixed windows
win at R@10 (unverified guess: the any-overlap hit rule favors large chunks).

Open items: seed questions need teammate review; decide a stricter overlap metric and an "any-of"
gold group (q002 overloads) via reviewed PR; second obscure repo for contamination control; the two
placeholder diagrams in the spec are missing; CI untested.

## Layout (`src/codeatlas/`)
| package | role | status |
|---|---|---|
| `core` | shared contracts (`models.py`), ids/hashes, data-dir paths | Sprint 1 |
| `ingest` | git access, scan, Tree-sitter extractor, chunkers | Sprint 1 |
| `index` | SQLite store, BM25, indexing pipeline | Sprint 1 |
| `retrieve` | tokenizer, retrievers, factory | BM25 done; dense/hybrid Sprint 2 |
| `eval` | dataset format, metrics, runner | Sprint 1 |
| `llm`, `verify` | LLM interface + cache; citation verifier | Sprint 2–3 |
| `agent`, `api`, `tours`, `web/` | later sprints | placeholders |

## Commands (Windows; venv lives outside OneDrive)
```
C:\Users\yaksh\codeatlas-env\venv\Scripts\activate
pip install -e ".[dev]"
pytest                                   # add CODEATLAS_FLASK_REPO=<flask clone> for the Flask/ast check
ruff format src tests scripts && ruff check src tests scripts
mypy
codeatlas index <url-or-path> --rev <sha> [--chunker ast|fixed]
codeatlas chunks <url-or-path> <file>    # inspect chunks of one file
codeatlas search <url-or-path> "query"
codeatlas eval --config configs/bm25_ast.yaml
```
Data (clones, indexes) goes to `$CODEATLAS_HOME` (default `~/.codeatlas`). Never put it inside the
OneDrive checkout.

## Rules
- Every new module ships with tests. Keep the agent loop, citation verifier and eval metrics small
  and read line by line — they decide the results.
- Downstream code never touches Tree-sitter objects; extractors emit `ingest.symbols.Symbol`.
- Source text comes from the git object DB at a pinned commit (`ingest.git`), never the working tree.
- Gold labels are `(file, line range)` spans matched by overlap, not chunk ids, so any chunker can
  be scored against the same dataset. Changing a dataset or metric definition needs a reviewed PR.
- Interfaces (`Retriever`, later `Embedder`, `LLM`, `Reranker`) exist so ablations swap
  implementations; don't add abstractions beyond that.
- Everyone must be able to explain every module in a viva. Prefer explicit code over cleverness.

## Gotchas found the hard way
- **tree-sitter is pinned to 0.25.2.** 0.26.0 returned corrupted `Node` objects (garbage
  positions, then an access violation) when nodes from `named_children` were read more than once.
  Re-test `tests/test_extractor_vs_ast.py` on the Flask checkout before bumping.
- Keep the `Tree` referenced while its nodes are in use (`extract_python` does).
- `tests/fixtures/` is excluded from ruff on purpose: its exact text and line numbers are asserted.
- Line numbers are 1-indexed inclusive; CRLF is normalized to LF at read time (counts unchanged).
