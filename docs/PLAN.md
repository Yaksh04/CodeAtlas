# CodeAtlas — engineering plan

[SPEC.md](SPEC.md) is authoritative; this file records how we sequence it and what we decided.

## Sprints (~1.5 weeks each)
| # | Name | Ends with | Ablation rows |
|---|---|---|---|
| 1 | Parse, chunk, search lexically, measure | AST + fixed chunkers, BM25, eval harness, Flask seed set | BM25 on ast / fixed |
| 2 | Dense, baseline, hybrid | Embedder interface, FAISS, RRF, LLM cache skeleton, ~50 questions | 1 fixed+dense, 2 AST+dense, 3 +BM25 hybrid, no-retrieval control |
| 3 | Graph + verified answers (**MVP gate**) | graph construction (defines/imports/inherits/calls + confidence), citation verifier, `codeatlas ask` | citation validity, abstention |
| 4 | Structure-aware retrieval | graph expansion (depth/edge-type configurable), `tests` edges, reranker, HyDE | 4 graph, 5 rerank, 6 HyDE |
| 5 | Agent + router | six tools, 8-call budget, trace, rule-based router, thin API | 7 agent, G routed |
| 6 | Commit-aware indexing | incremental updater, commits table, `git_log`, consistency test, SWE-bench Lite localization | re-index time |
| 7 | API + UI | FastAPI/SSE, Monaco citations, React Flow graph from real provenance | — |
| 8 | Tours + final eval | entry points, clusters, reading order, write-up | full ablation table |

Gates: **A** after Sprint 3 (end-to-end slice works, citation validity reported); **B** after
Sprint 4 (every retrieval claim has a number). Agent and tours start only after their gate. If time
runs short, cut tours before cutting eval.

## Why the MVP is drawn where it is
- Hybrid (BM25 + dense + RRF) is in: cheap, the spec's "exact name at rank 1" needs it, and it is a ladder rung.
- Citation verification is in: the MVP ends in an LLM answer; unverified citations would make it untrustworthy, and the mechanical checks are deterministic.
- Graph *construction* is in (freezes the contracts, highest risk); graph *expansion* is not, so its effect is measured against a hybrid baseline as its own row.
- Reranker, HyDE, agent, router, incremental indexing, UI, tours: measured or built after the gate.

## Decisions taken (defaults; change via PR)
1. Target repo: **pallets/flask @ 3.1.3** (`22d924701a6a…`). FastAPI later as a harder case; add one obscure repo to control for training-data contamination. **Open.**
2. Package layout `src/codeatlas/{core,ingest,index,retrieve,eval,…}` (spec's top-level dirs would install as generic names like `index`, `api`).
3. Chunk id = `repo:path:qualified_name#ordinal[.pPART]`; no line numbers or commit, so edits keep identity and only `content_hash` moves.
4. Gold labels = `(file, start, end)` spans; a chunk hits when it overlaps (same file, ranges intersect).
5. Text source = git object DB at a pinned SHA. Data dir outside OneDrive.
6. SQLite is the durable store; search structures are rebuilt from it. One index per (repo, commit, chunker).
7. Pydantic v2 for contracts.
8. Class chunk = class header only (up to the first method); methods are their own chunks. Functions nested in functions belong to their parent. Definitions inside `if`/`try`/`with` at module or class scope are found.
9. BM25 is hand-written (~40 lines, Lucene-style IDF) instead of `rank_bm25`: it is the baseline, so it should be readable and testable.
10. Test files are indexed with `is_test`; `include_tests` is a retriever option (default true until the eval says otherwise).
11. Question taxonomy fixed in `core.models.QuestionCategory`.
12. tree-sitter pinned to 0.25.2 (0.26.0 memory-corruption bug; see CLAUDE.md).

## Open items / known limits
- `Recall@k` counts a chunk as a hit on **any** line overlap. That favors large chunks (a 40-line window
  touching a 3-line gold span counts). Decide in Sprint 2 whether to add a stricter variant
  (e.g. chunk must contain the gold span's first line, or ≥ X% overlap) — needs a reviewed PR.
- The Flask seed set (33 questions, 2 unanswerable) was drafted by Claude and must be reviewed by a
  teammate before results are quoted. Line numbers are resolved mechanically (`scripts/build_flask_seed.py`).
- The gold format has no "any of these spans" grouping. q002 (`stream_with_context`) has two `@overload`
  stubs plus the implementation; all three are valid definitions but only the implementation is labelled, so
  BM25 (correctly) ranks the stubs 1-2 and scores a miss at rank 1. Add an any-of group in a reviewed PR.
- A module block drops the non-definition lines of a compound statement that contains a definition
  (e.g. `import x` inside `try:` next to a fallback `def`). Rare; revisit if the eval shows it matters.
- Class-level statements that appear *after* the first method are not part of any chunk.
