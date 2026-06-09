# Test Coverage Rules & Conventions

This document captures the working policy we are applying as we raise backend test
coverage for open-sourcing. It is descriptive of what we have actually done so far,
not aspirational. Update it as the policy evolves.

## Goal

Raise coverage by testing **real behavior**, not by padding metrics. A module at
100% should mean its logic and error paths are genuinely exercised — never that
hard branches were silently hidden.

## `# pragma: no cover` policy

Reserve `# pragma: no cover` for code that is genuinely not worth (or not possible)
to test directly. Every pragma must carry an inline comment justifying it.

Acceptable to pragma:

- **Defensive guards against Python-internal / practically-unreachable states**
  (e.g. a `try/except` around a dict lookup that can only fail if an invariant is
  already violated).
- **Thin re-export shims** whose statements are only exercised via the preferred
  import path (e.g. `app/llm_model/llm_client.py`).
- **Truly unreachable branches** that exist for safety but cannot occur given the
  surrounding logic (e.g. `if not pairs:` where every key in the map provably has
  at least one entry — see `manager_index_io.build_ltm_adjacency_lists`).

Not acceptable to pragma:

- Real business logic, retrieval/index assembly, parsing, scope/heading rules,
  cache lifecycle decisions, or any branch a caller can reach with valid input.
  Write a test instead.

When a pragma'd `except Exception` turns out to be reachable (e.g. an `int()` that
can raise `TypeError`/`ValueError` on real input), **remove the pragma and narrow
the exception** rather than keeping a broad catch.

## Exception handling (aligns with the repo exception rules)

- Catch **specific** exception types when you can name them; otherwise let it raise.
- Every `except` block must `log`, `re-raise`, or `return an explicit fallback`.
  Never a blind `pass`.
- Prefer narrowing (`except (TypeError, ValueError)`) over `except Exception`
  whenever the failure modes are known. Tests should cover the narrowed paths.

## What to test directly

- **Pure helpers**: split/trim/collapse, timestamp/date coercion, id generation,
  YAML metadata parsing (including malformed fences, missing/empty keys), scope and
  heading rules. These are cheap and high-value.
- **I/O helpers** with `tmp_path`: atomic JSON write, tolerant JSON load, manifest /
  adjacency sidecar writes, daily.json load/save, daily.md append/backfill.
- **Pipelines** with real FAISS + NumPy and faked boundaries: index assembly from
  embedding results, daily cache warm/rebuild/model-mismatch/incremental-add,
  parallel embed batching (happy, throttle, and failure paths).
- **Error / log branches**: assert on `caplog` records for best-effort failures
  (header render failure, adjacency write failure, db backfill failure, etc.).

## Test design conventions

- **Use the real `faiss` and `numpy`** wherever they are installed. Only fake the
  *boundaries*: the embedding client, `get_settings`, `get_active_embedding_model`,
  the DB session, and `write_debug_file`.
- **Fake clients are small stubs**, e.g. an `embed()` that returns fixed-dim vectors
  (or `[]` / raises, to drive the empty/error paths).
- **Reset module-level global state between tests** with an autouse fixture (e.g.
  `daily_store._CACHE`, `_WARMING`, `_PROJECT_LOCKS`). Tests must not leak state.
- **Make background work deterministic**: replace `threading.Thread` with a
  synchronous stand-in (run target on `start()`) when testing rebuild scheduling,
  or monkeypatch the scheduled function to a recorder.
- **Bypass Pydantic validation with `model_construct(...)`** only to reach defensive
  branches that valid construction cannot produce (e.g. an "invalid merged result").
- Prefer **one assertion target per test** and a short comment explaining the branch
  being exercised, especially for non-obvious edge cases.

## Test isolation: stub install guard

Some legacy tests stub `numpy`/`faiss` in `sys.modules` to avoid heavy deps. Stubs
must be installed **only if the real package is absent**, never with a blind
`sys.modules.setdefault(...)`, which can permanently shadow the real module
depending on collection order. Use the guarded helper pattern:

```python
def _install_stub_if_missing(name, module):
    if name not in sys.modules:
        sys.modules[name] = module
```

This was the root cause of an `AttributeError: module 'numpy' has no attribute
'linalg'` that only appeared in the full suite — fixed by guarding the stubs.

## Coverage configuration

- **Omit I/O-heavy telemetry** rather than padding it with brittle tests. The whole
  `app/tracking/` directory is excluded via `[tool.coverage.run] omit` in
  `pyproject.toml`. Keep that list narrow and justified.
- When running coverage from the `backend/` directory, pass the config explicitly:
  `--cov-config=../pyproject.toml` (the `Makefile` `coverage-backend` target and the
  ad-hoc command in `questions.txt` already do this), otherwise the `omit` list is
  not discovered.
- Generate viewer-friendly reports (`term-missing`, `html`, `xml`, `lcov`) via
  `make coverage-backend` for line-level inspection.

## API routers: test boundaries, not the LLM

For `app/api/` we kept the same "fake only the boundaries" discipline:

- **Mount one router at a time** onto a bare `FastAPI()` app with a `TestClient`,
  using the shared `db` / `temp_memory_root` / `reset_projects_state` fixtures for
  isolation. The FAISS rebuild is patched to a no-op (or a raiser) so create/upload
  flows never reach embeddings or the network.
- **The LLM is never called.** Endpoints already delegate to
  `generate_chat_response` / `get_llm_client`; tests inject a `FakePipeline`,
  recording fake memory manager/instrumentation, and small streaming-client stubs.
- **`ChatPipeline` is unit-tested directly** (no TestClient), faking
  `get_memory_manager`, `get_session`, `build_query`, `get_route_policy`,
  `merge_daily_and_main`, `get_instrumentation`, and `write_debug_file`.
- **Best-effort log branches**: assert on `caplog`. Remember to
  `caplog.set_level(logging.INFO)` (or `DEBUG`) for branches that log below
  WARNING — the default capture level is WARNING and will silently miss them.
- **Defensive debug-logging guards** (e.g. `except Exception: logger.debug(...)`
  wrapping only a debug/`clear_namespace` call) are the rare `# pragma: no cover`
  cases here; everything reachable with a real request is tested.

## Agent interface: pure helpers + faked retrieval boundaries

For `app/agent_interface/` the same discipline applied, with two wrinkles:

- **`parser.py` is a pure module** (only depends on the snippet model). Test its
  helpers directly — header/YAML metadata parsing, scalar coercion, chunk-index
  parsing, topics/page normalization, and the round-trip renderer — rather than
  only through the public `parse_prompt_context_to_snippets`. A couple of header
  predicates (`_is_context_delimited_snippet_start`) are easiest to cover by
  calling them directly with crafted line lists.
- **`retrieval.py` fakes only the boundaries**: `get_session`,
  `merge_daily_and_main`, the parser, the entry expander, the route policy, and
  `write_debug_file`. `resolve_project_name` uses the real `db` fixture; the rest
  monkeypatch the module-level names so FAISS/embeddings/network are never hit.
- **`entry_expansion.py`**: exercise artifact-boundary, source_document_id, docstore
  reconstruction, and original-snippet fallbacks against real `tmp_path` artifacts.
  Syx markers require a real-format `mem_YYYYMMDD_HHMMSS_<hex>` id or the parser
  rejects them. The one defensive branch the real parser can't reach (it dedupes
  duplicate `memory_id`s before returning entries) is covered by faking
  `parse_syx_entries` to return duplicates — not pragma'd.
- **Genuinely unreachable defensive guards** are `# pragma: no cover` (the
  unparseable-block raise in `parse_prompt_context_to_snippets`, whose `parts`
  always begin with a matched header; the `int()` except guarded by `_INT_RE`).

## Core: pure helpers, faked DB/LLM, and module-global state isolation

For `app/core/` the same boundary discipline applied:

- **Pure helpers tested directly**: `route_policy` coercers/loader (monkeypatch
  `_policy_path` to a temp file to drive every fail-fast branch),
  `query_builder` JSON slicing/route filtering/`build_query` (fake
  `get_llm_client_mini` + `get_instrumentation`, no network), `config` validators
  and `compute_per_source_k` fallbacks, `similarity`.
- **`llm_service` instrumented branches**: the real no-op instrumentation returns
  an empty invocation id, so the start/end-invocation usage payloads stay
  uncovered. Inject a `_FakeInstr` that returns a real id (and optionally raises
  in `end_invocation`) to exercise the usage/finalize/finalize-error paths;
  `get_llm_client` is faked so no model is ever called.
- **`memory` boundaries faked**: `get_session` (swapped to the temp-DB engine by
  the `db` fixture, or monkeypatched to raise for the error branches), `tag_pair`,
  `_prune_assistant_for_tagger`, `append_pair`, and `write_debug_file`. Internal
  methods (`_append_pair_to_daily`, `_persist_assistant_row`, `_cleanup_unpaired_edges`,
  `_rolloff_oldest_pair`) are unit-tested directly with crafted deques/rows rather
  than only through the full append flow.
- **Module-global state isolation**: `state.py` keeps a process-global sleeping
  flag and a module-level `_LOCK_PATH`; an autouse fixture monkeypatches the lock
  path to a temp file and resets the flag per test. `database.py` fakes Alembic
  (`alembic.config.Config` / `alembic.command.upgrade`) and points `create_all`
  at an in-memory engine so no real migration runs.
- **Genuinely unreachable guards** are `# pragma: no cover`: the json-decode
  diagnostics `except` in `query_builder._parse_builder_response` (string slicing
  cannot fail) and the tags-block `except` in `memory._append_pair_to_daily`
  (the dict is sourced from `json.loads`, so `.get`/`str` cannot raise).
- **Dead code removed, not pinned**: writing tests exposed `memory.store_conversation`,
  which called a `MemoryManager.store_message` method deleted back in Oct 2025
  (so it always raised `AttributeError`). With no callers anywhere in the tree it
  was deleted outright rather than covered.

## Status so far

- `app/rag/` — entire directory at **100%** (chunk_utils, manager, manager_index_io,
  manager_rebuild, syx_memory_artifact, daily_store).
- `app/api/` — entire directory at **100%** (chat, chat_pipeline, chat_prompting,
  projects, files, dream, llm_models, sleep).
- `app/agent_interface/` — entire directory at **100%** (parser, retrieval,
  entry_expansion, router, models).
- `app/core/` — entire directory at **100%** (config, database, llm_service, memory,
  personality, query_builder, route_policy, similarity, state, plus the already-100%
  db_models/models/retrieval_ordering).
- `app/pruning/light_response_pruner/rules.py`,
  `app/embedding/providers/sentence_transformers_provider.py` — **100%**.
- `app/llm_model/llm_client.py` — excluded (re-export shim).
- `app/tracking/` — omitted from measurement.
