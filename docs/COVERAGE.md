# Test Coverage Rules & Conventions

This document captures the Syx testing and coverage policy. It is descriptive of
the standards the project expects contributors to follow, not a checklist for
padding metrics. It also keeps living notes from real coverage work so future
contributors understand why the conventions exist. Update it as the policy
evolves.

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
- **For API routers, mount one router at a time** onto a bare `FastAPI()` with a
  `TestClient`, patch the FAISS rebuild to a no-op/raiser, and inject fake
  pipeline/memory/instrumentation stubs — the LLM and network are never called.
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
  `--cov-config=../pyproject.toml` (the `Makefile` `coverage-backend` target), 
  otherwise the `omit` list is
  not discovered.
- Generate viewer-friendly reports (`term-missing`, `html`, `xml`, `lcov`) via
  `make coverage-backend` for line-level inspection.

## Notable deviations & gotchas

Things worth remembering that are not obvious from the tests themselves:

- **We refactored `app/main.py` to make it testable** (the one place we changed
  source structure for coverage). It was a conservative, behavior-preserving
  cleanup: imports consolidated, dead module-level `logger` removed, the
  monolithic `lifespan` split into named startup helpers, and the `__main__`
  block extracted into module-level `LoggingRedirect`,
  `_flush_and_close_log_handlers()`, and `run_server()`. The
  `if __name__ == "__main__": run_server()` entry point is preserved so
  `python -m app.main` (Dockerfile/Makefile) still works.
- **Dead code is deleted, not pinned with a test.** `memory.store_conversation`
  called a `MemoryManager.store_message` method removed back in Oct 2025 (so it
  always raised `AttributeError`) and had no callers — it was removed outright.
- **`/sleep_cycle*` endpoints return HTTP 507, not 500**, because their failures
  route through `handle_memory_error`. Assert on 507.
- **`caplog` defaults to capturing WARNING.** For any branch that logs at INFO or
  DEBUG you must `caplog.set_level(logging.INFO)` (or `DEBUG`) or the record is
  silently missed.
- **`KeyboardInterrupt` is a `BaseException`** and escapes `except Exception`. To
  test an interrupted-sleep / best-effort `except Exception` branch, raise a plain
  `Exception`, not `KeyboardInterrupt`.
- **`tokens._resolve_encoding` is `lru_cache`d.** Use a unique `encoding_name` per
  test (and/or `cache_clear()` in a `finally`) so a fake encoder does not leak via
  the cache.
- **`numpy`/`faiss` stubs must be guarded** (see "Test isolation" above). A blind
  `sys.modules.setdefault` once shadowed real `numpy` and produced an
  `AttributeError: module 'numpy' has no attribute 'linalg'` only in the full
  suite.

## Intentional pragma inventory

Most `# pragma: no cover` in the backend are **routine best-effort / defensive
guards** that follow the policy above — `except Exception` blocks that only log
(debug logging, neighbor/meta lookups, malformed-docstore/manifest reads) and
never block the request. The bulk live in `rag/manager.py` and `app/api/*`; each
carries an inline justification at the call site.

The table below lists the **noteworthy** pragmas — the logic-specific
"provably unreachable" branches and the environment/system guards — since those
are the ones worth a second look if the surrounding code changes:

| Location | Why |
| --- | --- |
| `llm_model/llm_client.py` (whole module) | Thin re-export shim; only exercised via the preferred import path. |
| `rag/manager_index_io.build_ltm_adjacency_lists` `if not pairs:` | Unreachable — every doc_id provably has at least one pair. |
| `agent_interface/parser.parse_prompt_context_to_snippets` unparseable-block raise | `parts` always begin with a matched header, so the raise cannot fire. |
| `agent_interface/parser` `int()` except | Guarded by `_INT_RE`, so the value always parses. |
| `core/query_builder._parse_builder_response` json-decode except | Diagnostics on string slices cannot fail. |
| `core/memory._append_pair_to_daily` tags-block except | Dict comes from `json.loads`, so `.get`/`str` cannot raise. |
| `dream/agents/idea_agent.py` required-field re-checks (×5) | Earlier required-key guards already guarantee presence; `_normalize_recommended_research` never returns `None`. |
| `dream/context._extract_rag_topics` title-slice except | String slicing cannot raise. |
| `embedding/.../openai_provider._extract_retry_after_seconds` `float(...)` except | The regex only matches a parseable number. |
| `sleep/questions_consolidation` `if not key:` | The key always contains the `"||"` separator, so it is never falsy. |
| `llm_model/.../openai_provider._extract_text_parts` `output_text` append | Redundant fallback — non-empty `text` is already captured just above. |
| `pruning/.../config.merge_rules` `ValidationError` re-raise | Every input rule set has at least one valid section, so the merge is always valid. |
| `pruning/.../units._next_blank_line_index` trailing `return None` | The loop always returns earlier once a newline is seen, or `None` before. |
| `utils/tokens` `tiktoken` import guard | Environment-dependent import. |
| `utils/logging` `ctypes` import block + Windows `GetConsoleMode` call | Environment-specific (Windows console API). |
| `main.py` import-time route-policy fail-fast guard | Only reachable at import with a broken `route_policy.json`. |
| `main.py` `except KeyboardInterrupt` in `run_server` | OS interrupt signal. |
| `main.py` `if __name__ == "__main__"` | Process entry point. |
