# CodeAtlas — Chat with Your Codebase: Design Spec

Sep 30, 2026

## Overview

CodeAtlas is a structure-aware, agentic assistant for chatting with a codebase. It answers questions with verified file:line citations, re-indexes incrementally on every commit, generates onboarding tours, and is measured on a public benchmark.

The baseline spec (chunk files, embed, top-k retrieve, ask an LLM) fails on the questions people actually ask. "Where is auth handled?" spans a middleware, a decorator, a config file and their callers, so no single chunk holds the answer. CodeAtlas closes that gap with six upgrades:

| #   | Feature                            | Baseline does                         | CodeAtlas does                                                                    |
| --- | ---------------------------------- | ------------------------------------- | --------------------------------------------------------------------------------- |
| 1   | Code graph + hybrid retrieval      | Fixed-size chunks, dense search only  | AST chunks, call/import graph, BM25 + dense + graph expansion, reranker           |
| 2   | Agentic retrieval                  | One retrieval pass                    | LLM explores with tools (search, definition, references, read lines, git log)     |
| 3   | Incremental, commit-aware indexing | Re-index everything on each commit    | Re-embed only changed AST nodes; answer questions about history                   |
| 4   | Verified citations                 | Citations are whatever the LLM writes | Every claim cites file:line, checked against the index; abstains when unsupported |
| 5   | Evaluation harness                 | None                                  | SWE-bench Lite file localization + repo QA set + ablations                        |
| 6   | Onboarding tours                   | None                                  | Auto-generated architecture map and guided walkthroughs of main flows             |

First target repo: a medium-sized Python project such as FastAPI or Flask. Scale to a larger repo only after the eval numbers are stable.

## System architecture

Two paths share one index. Every push runs an incremental indexing job that writes to four stores; every question runs through a router, the agent, and a citation verifier that reads the same stores.

&#91;embedded content: system architecture · indexing path and query path\]

The tour generator reads the code graph offline and caches tours per commit; the UI serves them alongside chat.

## Feature specs

Each feature below lists what it does, how to build it, and the acceptance criteria that mark it done.

### F1. Code graph + hybrid retrieval

Parse every file with Tree-sitter and store two things: AST-level chunks and a code graph.

- **Chunks:** one per function, method or class. Each carries its signature, docstring, parent class, file path, start/end lines, language and a content hash. Oversized functions split at statement boundaries with the signature repeated.
- **Graph nodes:** files, modules, classes, functions, tests. **Edges:** `imports`, `calls`, `defines`, `inherits`, `tests` (test function touches target). Store in NetworkX first; move to SQLite tables or Neo4j only if needed.
- **Retrieval:** run BM25 (identifier-aware tokenizer that splits `camelCase` and `snake_case`) and dense search in parallel, merge with reciprocal rank fusion, expand the top hits one hop along `calls` and `defines` edges, then rerank with a cross-encoder.
- **Query rewriting:** generate a short hypothetical code snippet for the question (HyDE for code) and embed that alongside the raw question.

Done when: hybrid + graph beats dense-only on the eval set (F5), and a query for an exact function name returns it at rank 1.

### F2. Agentic retrieval

The LLM answers by exploring, not by reading one fixed context. It gets these tools:

| Tool                           | Returns                                  |
| ------------------------------ | ---------------------------------------- |
| `search(query, filters)`       | Top chunks from the F1 hybrid retriever  |
| `go_to_definition(symbol)`     | Definition location + code               |
| `find_references(symbol)`      | Call sites from the graph                |
| `read_lines(file, start, end)` | Exact source lines at the indexed commit |
| `list_dir(path)`               | Directory contents                       |
| `git_log(path, n)`             | Recent commits touching a path           |

- Cap at 8 tool calls per question; stop early when the model says it has enough.
- A router sends simple lookups ("where is X defined?") straight to F1 to save cost and latency.
- Stream the exploration trace to the UI as a collapsible panel.

Done when: agentic mode beats single-shot on multi-hop questions in the eval set, with median latency under a target the team sets after the first measurement.

### F3. Incremental, commit-aware indexing

A GitHub Actions workflow runs on every push to the default branch.

1. Diff the commit to get changed, added, deleted and renamed files.
2. Re-parse only those files; compare chunk content hashes with the index.
3. Re-embed only changed chunks; delete removed ones; update graph edges touching changed files.
4. Tag every chunk with the commit SHA it was indexed at, plus last-modified commit and author from `git blame`.
5. Store per-commit metadata (message, author, date, files touched) in a commits table so the agent can answer "when did the rate limiter change and why?"

Done when: a one-file commit re-indexes in seconds rather than minutes, and a full re-index produces the same index as incremental updates (a consistency test in CI).

### F4. Verified citations

- The answer prompt requires a citation `[path:start-end]` after every factual claim about the code.
- A post-processor parses citations and checks each one: the file exists at the indexed commit, the line range is valid, and the cited lines contain the symbol or text the claim names (exact match or fuzzy match above a threshold).
- Failed citations are dropped or repaired by a quick lookup; if a claim loses all its support, the answer marks it as unverified or the system abstains.
- The UI shows each citation as a clickable snippet with a few surrounding lines.

Done when: citation validity (share of citations that pass the check) is reported in the eval and stays above a target the team sets.

### F5. Evaluation harness

See the Evaluation plan section for metrics and datasets. The harness is a CLI (`codeatlas eval --config ...`) that runs any retriever configuration against any dataset and writes a results table, so every ablation is one command.

### F6. Onboarding tours

A new contributor asks "explain this repo to me" and gets a guided tour built from the code graph.

- **Architecture map:** cluster the module-level graph (community detection such as Louvain), have the LLM name each cluster, and render it as an interactive diagram (React Flow or Mermaid).
- **Entry points:** detect `main`, CLI commands, HTTP route decorators, and public API exports as starting points.
- **Flow walkthroughs:** trace the call graph from each major entry point (for example, request comes in, gets routed, is authenticated, handler runs, response goes out) and turn the path into ordered steps, each with a code snippet and a verified citation.
- **Reading order:** a suggested first-week reading list ranked by centrality (PageRank on the graph) and churn from git history.
- Tours are cached per commit and regenerated only for clusters that changed (reuses F3).

Done when: a tour for the target repo renders end to end, every step's citation passes F4, and a small user test (a few classmates new to the repo) rates it useful.

## Tech stack and repo layout

Python backend with FastAPI, a Next.js frontend, and GitHub Actions for indexing. Keep every model and store behind an interface so ablations can swap them.

| Layer          | Choice                                                                               | Why / alternative                                |
| -------------- | ------------------------------------------------------------------------------------ | ------------------------------------------------ |
| Parsing        | Tree-sitter (py-tree-sitter + language grammars)                                     | Robust, multi-language AST                       |
| Orchestration  | LlamaIndex or LangChain for retrieval glue only; agent loop written by hand          | A hand-written loop is easier to debug and trace |
| Vector store   | FAISS (local)                                                                        | Qdrant if you need metadata filtering at scale   |
| Lexical search | `rank_bm25` or Tantivy                                                               | Tantivy for speed on large repos                 |
| Graph          | NetworkX, persisted to SQLite                                                        | Neo4j only if graph queries get complex          |
| Embeddings     | A code embedding model (e.g. an open code-embedding model via sentence-transformers) | Compare 2 models in the eval                     |
| Reranker       | Cross-encoder (e.g. a BGE reranker)                                                  | Skip in the ablation to measure its value        |
| LLM            | Gemini Flash for answers and tours                                                   | Swappable behind one interface                   |
| API            | FastAPI with server-sent events for streaming                                        |                                                  |
| Frontend       | Next.js + Monaco (code view) + React Flow (tour maps)                                | Streamlit for an early prototype                 |
| CI/CD          | GitHub Actions: tests, lint, incremental index job, eval on PRs                      |                                                  |
| Metadata DB    | SQLite (chunks, commits, tours cache)                                                | Postgres if deployed for many users              |

Suggested repo layout:

```
codeatlas/
  CLAUDE.md              # instructions for Claude Code
  ingest/                # tree-sitter parsing, chunking, graph build
  index/                 # bm25, faiss, graph store, incremental updater
  retrieve/              # hybrid search, fusion, expansion, reranker, HyDE
  agent/                 # tool definitions, agent loop, router
  verify/                # citation parser and checker
  tours/                 # clustering, entry points, flow tracing, tour cache
  eval/                  # datasets, runners, metrics, ablation configs
  api/                   # FastAPI app
  web/                   # Next.js frontend
  .github/workflows/     # ci.yml, index-on-push.yml, eval-on-pr.yml
  tests/
```

Check the latest versions and model names before starting; this list reflects common choices, not a verified current benchmark.

## Evaluation plan

The headline result is an ablation table showing how much each component improves retrieval and answer quality. Build the harness in the first phase so every later feature is measured the day it lands.

**Datasets**

- **SWE-bench Lite (file localization):** for each real GitHub issue, does the system retrieve the files the gold patch edits? This is a public, respected benchmark and needs no hand labeling.
- **Repo QA set:** 100 to 200 questions on the target repo. Generate candidates from docstrings, PR descriptions and README sections with an LLM, then have the team hand-check each answer location. Tag each as single-hop or multi-hop.
- **Tour check set:** 5 to 10 known main flows in the target repo, written by hand, to test whether F6 finds them.

**Metrics**

| Metric                        | Measures                                                         | Applies to |
| ----------------------------- | ---------------------------------------------------------------- | ---------- |
| Recall@k (k = 1, 5, 10)       | Correct file or function in top k                                | F1, F2     |
| MRR                           | Rank of first correct hit                                        | F1, F2     |
| Answer faithfulness           | Claims supported by cited code (LLM judge + hand-checked sample) | F2, F4     |
| Citation validity             | Share of citations passing the F4 checker                        | F4         |
| Abstention accuracy           | Abstains on unanswerable questions, answers answerable ones      | F4         |
| Re-index time per commit      | Seconds for a typical one-file commit vs full re-index           | F3         |
| Latency and cost per question | Median seconds, tokens                                           | F2         |
| Tour flow coverage            | Hand-written main flows the tour recovers                        | F6         |

**Ablation ladder** (each row adds one component):

1. Baseline: fixed-size chunks, dense only
2. AST chunks, dense only
3. - BM25 hybrid with fusion
4. - graph expansion
5. - cross-encoder reranker
6. - HyDE query rewriting
7. - agentic retrieval

Run the eval in CI on every PR that touches `retrieve/` or `agent/`, with a small fixed subset so it stays cheap; run the full set before each milestone.

## Phased build plan

Four phases of about three weeks each, gated so the project is demoable at every stage. F2 and F6 start only after the retrieval core and eval harness pass their gate.

&#91;embedded content: build roadmap · 4 phases, 3 gates\]

The gates are the checkpoints: don't start a phase until the one before it passes.

**Workstreams** (three members; merge B and C if you're two, split C if you're four)

| Member                    | Owns                                                                                                           | Phase focus                              |
| ------------------------- | -------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| A: Ingestion and indexing | Tree-sitter parsing, AST chunks, code graph, incremental updater (F3), GitHub Actions workflows                | Heavy in phases 1 and 2                  |
| B: Retrieval and agent    | Hybrid search, fusion, graph expansion, reranker, HyDE (F1), agent loop and router (F2), citation checker (F4) | Steady across all phases                 |
| C: Eval and product       | Eval harness and datasets (F5), onboarding tours (F6), FastAPI + Next.js UI                                    | Eval in phase 1, tours and UI in 3 and 4 |

Week 1 is shared: agree on the data contracts (`Chunk`, `GraphEdge`, `Citation`, `ToolResult`) and write `CLAUDE.md` together.

## Working with Claude Code

Claude Code makes writing code fast, so the team's time goes into specs, review and evaluation. Treat this doc as the source of truth and feed it in section by section.

**Set up once**

- Put a `CLAUDE.md` at the repo root with: the one-paragraph overview, the repo layout, coding conventions (type hints, docstrings, pytest), the commands to run tests and eval, and a rule that every new module ships with tests.
- Commit this spec as `docs/SPEC.md` and point `CLAUDE.md` at it.
- Define shared data contracts first (the `Chunk`, `GraphEdge`, `Citation` and `ToolResult` types) so work in parallel stays compatible.

**Per feature**

1. Ask Claude Code to plan the feature from its spec section before writing code; review the plan as a team.
2. Build on a branch, one module at a time, with tests.
3. Run the eval subset; paste the numbers into the PR description.
4. A teammate who did not write it reviews the PR.

**Guardrails**

- Everyone on the team should be able to explain every module in a viva or interview; generated code nobody understands is a liability.
- Keep the agent loop, citation checker and eval metrics small and hand-reviewed line by line, since they decide the results.
- Never let generated code change eval datasets or metric definitions without a reviewed PR.

## Risks and mitigations

The biggest risk is scope: six features can leave six half-finished pieces. Each phase ends with something demoable, so the project is presentable at any point.

| Risk                                                                                 | Mitigation                                                                                          |
| ------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| Scope creep leaves nothing finished                                                  | Phase gates; F1 + F4 + F5 must be solid before F2 and F6 start                                      |
| Call graph is wrong for dynamic Python (decorators, `getattr`, dependency injection) | Treat graph edges as hints for expansion, not ground truth; test on the target repo's real patterns |
| LLM API cost from agentic mode and eval runs                                         | Cache LLM calls by prompt hash; small eval subset in CI; router skips the agent for simple lookups  |
| Index drifts from the repo after many incremental updates                            | CI consistency test: incremental result must equal a fresh full index                               |
| LLM judge inflates faithfulness scores                                               | Hand-check a random sample and report agreement with the judge                                      |
| Tours read as generic summaries                                                      | Every tour step must carry a verified citation; drop steps that fail F4                             |
| Code nobody on the team understands                                                  | Guardrails in the Claude Code section; rotate PR reviewers                                          |
