# Testing Plan

Status: living document. This plan tracks recommended test-coverage and
test-infrastructure improvements for the Syx AGI Chatbot Framework. It exists to
make the project easier to maintain and more credible to external readers
(including prospective employers) as it moves toward open source.

## How tests run today

- Backend tests live in `tests/` and are run with:

  ```bash
  cd backend && python -m pytest ../tests/ -v
  ```

  (see the `test` target in the `Makefile`). The working directory is `backend/`,
  so the importable package is `app.*` and storage paths resolve relative to
  `backend/`.
- All test modules must import via `app.…`, never `backend.app.…`. Mixing the two
  import roots loads SQLModel table classes twice and triggers
  `InvalidRequestError: Table 'project' is already defined`.

## Baseline (at time of writing)

- ~111 test functions across ~20 files.
- Strong coverage: pruning pipeline, dream summary/writer/auto-accept, agent-memory
  search/expansion, RAG artifact parsing, markdown artifact cutover.
- Structural gaps:
  - No `tests/conftest.py` (shared fixtures, settings/memory-root isolation).
  - No CI workflow.
  - No frontend tests.
  - Thin coverage on critical modules: `rag/manager.py`, `core/memory.py`, the
    API endpoints, the LLM/embedding factories, and `tagging/tagger.py`.

## Conventions for new tests

- One test module per source module where practical: `tests/test_<area>.py`.
- Prefer fast, deterministic, offline tests. Never call real OpenAI endpoints;
  inject fakes/mocks at the client boundary.
- Use the shared fixtures in `tests/conftest.py` for filesystem and settings
  isolation rather than touching the global singleton directly.
- Each new source file still gets the standard copyright/SPDX header.

## Tiered backlog

### Tier 1 — high value, low effort (pure logic) — IN PROGRESS

- [x] `utils/tokens.py` — counting, trimming, message-content aggregation, fallbacks.
- [x] `utils/errors.py` — error response shape, status-code mapping, code lookup.
- [x] `security/agent_tokens.py` — authorization stub contract (regression guard).
- [x] `embedding/batching.py` — token-budget batching, boundaries, validation.
- [x] `core/query_builder.py` — `_slice_first_json`, `_filter_route_only`,
      `_cache_key`, `format_contextual_turn` (pure helpers; LLM path excluded).
- [x] `core/personality.py` — `_normalize_personality`, size validation, save/load
      round-trip with cache invalidation.

### Tier 2 — core behavior & API contracts — DONE

- [x] `api/projects.py` — create/list/switch/rename/delete, system-project guards.
- [x] `api/files.py` — upload limits, batch limits, storage-limit enforcement,
      list/delete (FAISS rebuild patched to a no-op).
- [x] `api/chat.py` — request validation (422) and health/stats contracts
      (`get_llm_health` patched; full LLM pipeline left for Tier 3).
- [x] `core/memory.py` — working-memory append/read, pair-based roll-off
      (daily-RAG disabled so no embeddings/network).
- [x] `core/config.py` — field validators, `compute_per_source_k`, model/key
      resolution, derived stage config.

Test infrastructure added for this tier (in `tests/conftest.py`): a `db` fixture
that swaps the SQLModel engine for an isolated temp SQLite file, a
`fresh_memory_manager` fixture that resets the manager singleton, and a
`reset_projects_state` fixture for the router's in-memory pointer.

### Tier 3 — deep / complex subsystems — DONE

- [x] `rag/manager.py` — candidate metadata mapping, snippet headers, threshold
      filtering + fallback in `retrieve_context`, and selection/min-score gating
      in `merge_daily_and_main` (`canonical_retrieve_candidates` patched, so no
      embeddings/FAISS/network).
- [x] `sleep/cycle.py` — router contract endpoints, start/lock branching (mocked),
      and the worker's lock-release-in-`finally` skeleton on an empty DB.
- [x] `tagging/tagger.py` — prompt-assembly helpers, center-chop, `_slice_first_json`,
      and `tag_pair` parsing/normalization via a fake mini-LLM client.
- [x] LLM/embedding factories — provider selection, singleton caching/reset,
      openai-key requirement, and unknown-provider errors (provider classes faked).

Note: the embedding-factory tests load the real factory from source with fake
provider modules injected first, because several legacy test modules permanently
stub `app.embedding.factory`, `numpy`, and `faiss` in `sys.modules`.

### Tier 4 — frontend — DONE

- [x] Added Vitest + React Testing Library (`@testing-library/react`,
      `@testing-library/jest-dom`, `@testing-library/user-event`, jsdom).
      Config in `frontend/vitest.config.ts`; jest-dom matchers and per-test
      cleanup in `frontend/src/test/setup.ts`. Scripts: `npm run test`
      (watch), `npm run test -- --run` (CI/one-shot), `npm run coverage`.
- [x] Pure logic: `lib/utils.ts` (`cn`), `pages/app/request.ts`
      (error extraction, response parsing, `RequestError`), `pages/app/dream.ts`
      (`toDreamViewState`), `pages/app/api.ts` (fetch wrapper, mocked fetch).
- [x] Component: `components/ui/button.tsx` (render, className merge, ref
      forwarding, click + disabled behavior).
- [x] Hook: `hooks/useProjectData.ts` (mount load + name mapping, failure
      reset, create/validate/error paths) with the `api` module mocked.

Note: `make test-frontend` had a latent double-`cd frontend` bug that only
surfaced once a `test` script existed; fixed in the Makefile.

## Infrastructure

- [x] `tests/conftest.py` with shared fixtures (settings + memory-root isolation).
- [x] GitHub Actions CI: backend (`pytest`) and frontend (`vitest --run`) jobs
      on push/PR (`.github/workflows/ci.yml`).
- [ ] `pytest-cov` coverage reporting (and a coverage badge once CI exists).
- [ ] Consider `hypothesis` for property-based tests of tokenization/batching.

## Sequencing

1. Tier 1 + `conftest.py` (done).
2. CI workflow so the suite runs on every push/PR (done).
3. Tier 2 API/contract tests (done).
4. Tier 3 subsystem tests (done).
5. Tier 4 frontend tests (done).
