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

## Dream: agent pipeline with faked LLM/RAG boundaries

For `app/dream/` the agents and orchestration are heavy on LLM and retrieval
calls, so the discipline is to fake **only** those boundaries and drive the real
validation/branching logic with crafted payloads:

- **Pure helpers tested directly**: `common` (id collection, resolution
  normalization, research filtering, pair expansion, tag-block formatting,
  markdown assembly), `prompts`/`agents/prompts` (f-string builders — one call
  each), `debug` (artifact writers with `write_debug_file` faked), and the many
  `dreams` helpers (fuzzy question matching, JSON read, research-plan rows,
  resolution attach/filter, remote-question bridging).
- **Agents fake `generate_text_response`** (return a `SimpleNamespace(text=...,
  usage=...)` or raise) plus `retrieve_dream_context`, `fetch_remote_research`,
  and the debug writers. The Idea/Research/Questions validation branches are
  exercised by feeding crafted JSON/text responses, never a model. `rag.py` fakes
  `get_route_policy`/`merge_daily_and_main` (and uses the real `db` fixture for
  the daily-flag lookup) so FAISS/embeddings/network are never touched.
- **`context.build_dream_context`** writes file sources under a temp memory root
  and fakes the RAG/LLM/debug boundaries; the minimal DAILY-MEMORY-only fallback
  (and the fallback-where-daily-also-fails) are covered by making the section
  helpers raise.
- **`auto_accept`** keeps its existing module-injection harness; the added tests
  call the helpers directly (`_bad_dream_path` collision, `_rename_bad_dream`/
  `_delete_dream_file` OSError logging, legacy-lock migration, empty-pair skip,
  tagger-failure-persists-without-tags) and drive the quarantine / no-items /
  rebuild-failure / delete-failure branches of `auto_accept_dreams`.
- **`caplog.set_level(logging.INFO)`** is required for the INFO-level branches
  (e.g. the missing-summary-mirror notice in `_run_research_stage`).
- **Genuinely unreachable guards** are `# pragma: no cover` with justification:
  the Idea Agent's redundant required-field re-checks (the earlier required-key
  guards already guarantee presence; `_normalize_recommended_research` never
  returns `None`) and the `=== TOPIC: ===` title-slice `except` in
  `context._extract_rag_topics` (string slicing cannot raise).

## Embedding: fake only the SDK client and the backoff sleeps

`app/embedding/providers/openai_provider.py` looks network-bound but is very
testable without a mock-provider subclass:

- **Fake just the SDK boundary**: `patch.object(provider_mod, "OpenAI")` so
  `__init__` builds a fake client, then set
  `client.embeddings.create.side_effect` to a list of crafted responses /
  exceptions (`SimpleNamespace(data=[...])`, a `_RateLimitError` with
  `status_code=429`, a `TimeoutError`, or a generic `RuntimeError`).
- **Neutralize the backoff** by monkeypatching `provider_mod.time.sleep` (and the
  retry loop's `random.uniform` jitter is harmless), so retry/exhaustion paths
  run instantly and deterministically.
- **Helpers tested directly**: `_is_rate_limit_error` (429 status, non-numeric
  status → message fallback, unrelated → False), `_is_timeout_error`,
  `_extract_retry_after_seconds` (dict headers, object-with-`.get` headers, a
  header value that fails `float()`, the "try again in Ns" message hint, and the
  no-hint `None`), `_parse_embedding_vectors`, and `_rate_limit_base_wait_seconds`.
- **`_sleep_quietly`'s interrupted branch** is covered by making `time.sleep`
  raise a regular `Exception` (not `KeyboardInterrupt`, which is a
  `BaseException` and would escape the `except Exception`); the log is INFO-level
  so `caplog.set_level(logging.INFO)` is required.
- **Genuinely unreachable guard** is `# pragma: no cover`: the `float(m.group(1))`
  except in `_extract_retry_after_seconds`, since the regex only matches a
  parseable number.

## Sleep: orchestration helpers with every external stage faked

`app/sleep/` is one large orchestration module (`cycle.py`) plus a thread
launcher (`worker.py`) and a deterministic consolidator
(`questions_consolidation.py`). The discipline is to fake **every** boundary —
DB session, memory manager, tagger, pruner, daily store, dream/auto-accept,
FAISS rebuild/load, debug writers — and use a temp memory root, so no model,
FAISS, or network is ever touched:

- **Pure helpers tested directly**: `_public_tags_meta`, `_build_pair_tags_block`,
  `_summary_content_only` (existing), plus `_prepare_pair_for_daily` (stored-
  tags-json reuse, malformed-json fallback to the tagger, pruning that mutates
  the meta) and `_delete_pair_rows`.
- **Per-stage helpers driven in isolation**: `_flush_active_pairs` (disabled-
  project skip, rebuild-failure → `partial`, cache-clear failure log, per-project
  and global failure containment), `_backfill_daily_md`, `_run_dream_and_auto_accept`
  (disabled/success/failed/raises), `_post_merge_cleanup` (each inner remove
  failure logged), `_write_merge_artifacts_and_rebuild` (write sleep+dream,
  clobber-avoidance, `verify_rag` pass/fail, rebuild failure, legacy-lock
  migration failure), and `_run_project_summary_pipeline` (no-daily skip,
  consolidate failure, happy path, read failure, dream-summary consumption +
  debug write, empty-summary skip, merge/dream replace failures, outer failure).
- **`_sleep_cycle_worker` orchestration** is asserted by faking the stage
  functions and checking call order (`engage → flush → backfill → pipe* →
  release`), plus the project-query-failure → empty-rows, fatal-failure-still-
  releases, and release-failure-logged branches.
- **Endpoints** use a FastAPI `TestClient`; the stub `get_memory_manager`/
  `cleanup_old_memories` are faked for happy paths, and the error handlers are
  reached by making those (or `is_sleeping`/`release_lock`) raise. Note the
  `/sleep_cycle*` endpoints route failures through `handle_memory_error`, so they
  return **507**, not 500. The purely-static `GET /sleep_cycle/schedule` has no
  external call, so its `except` is exercised by monkeypatching `cycle.JSONResponse`
  to raise only on the `status_code=200` construction (the handler then builds the
  500 response with the real class).
- **`worker.py`** double-checked locking: the early skip, the inside-lock skip
  (an `is_sleeping` iterator returning `False` then `True`), and the real thread
  start (joined on a `threading.Event` so no daemon thread leaks).
- **Genuinely unreachable guard** is `# pragma: no cover`: the `if not key:`
  check in `questions_consolidation` (the key always contains the `"||"`
  separator, so it is never falsy).

## Tagging: pure prompt helpers + a faked mini-LLM and instrumentation

`app/tagging/tagger.py` is one module: pure prompt-assembly/parse helpers plus
`tag_pair`, which calls the mini/tagger LLM. The discipline is to test the
helpers directly and fake only the LLM + instrumentation + debug-writer
boundaries for `tag_pair`:

- **Pure helpers tested directly**: `_slice_first_json` (balanced slice, empty
  input, escaped-quote/brace-inside-string scanning, unbalanced → input
  unchanged), `_safe_percent`/`_safe_min_len` coercion, `_middle_cut_assistant_text`
  (short unchanged, long elision, `cut<=0` no-op, and the min-side-restore path
  that collapses back to the original), `_extract_prev_tag_value`,
  `_build_previous_turn_block` (the leading-`\n` regex vs the no-newline fallback,
  and rendering every `#route/#keep/#topics/#intent/#type/#semantic_handle` tag
  line), `_extract_tagger_fields`, and `_tagger_usage_from_response`.
- **Debug dump helpers** (`_write_tagger_success_debug` / `_write_tagger_failure_debug`)
  are called directly with `write_debug_file` faked: the body runs only when
  `project_id` is truthy (no-op otherwise), and the best-effort `except` is hit
  by making the writer raise.
- **`tag_pair` faked boundaries**: `get_settings`, `get_instrumentation` (a
  `_FakeInstr` returning a truthy invocation id, optionally raising in
  `end_invocation`), `get_llm_client_mini` (returns a `SimpleNamespace` response),
  and `write_debug_file`. This covers the success-debug write with a real
  `project_id`, the contained summary-log failure (monkeypatch `logger.info` to
  raise), and the error path's invocation finalize (non-JSON output → `ValueError`)
  including the finalize-failure log.

## LLM provider: fake the SDK client, drive the version-compat fallbacks

`app/llm_model/providers/openai_provider.py` wraps the OpenAI Chat Completions
and Responses APIs and is full of SDK-version-tolerance branches. Same pattern
as the embedding provider — fake only the SDK boundary:

- **Pure envelope helpers tested directly**: `_as_mapping` (dict passthrough,
  `model_dump` success / non-dict / raises / absent), `_coerce_int`,
  `_extract_text_parts` (bare string, non-string, list of strings, the
  text/text-dict/`output_text` content-part shapes), `_safe_usage_from_chat`
  (legacy `prompt/completion`, `input/output` fallback, parse-failure estimate),
  `_safe_usage_from_responses` (extra-detail collection, a per-field access that
  raises is skipped, parse-failure estimate), and `_responses_output_text`
  (`output_text` preferred, structured-output walk, `output` via mapping
  fallback, and both best-effort `except` logs).
- **Provider methods fake the client**: `patch.object(provider_mod, "OpenAI", MagicMock())`
  so `__init__` builds a fake client, then set
  `client.chat.completions.create` / `client.responses.create` `return_value`
  (or `side_effect` lists/iterators). This drives the temperature-retry and
  non-temperature-reraise paths (chat + stream), the `content`-via-mapping and
  contained text-parse-failure branches, the streaming text/usage/skip/chunk-
  failure paths, and `generate_response`'s optional-kwarg wiring plus the
  `input`-flatten and `text.format`-drop SDK fallbacks (and the other-error
  reraise).
- **Genuinely unreachable guard** is `# pragma: no cover`: the
  `if md.get("type") == "output_text":` append in `_extract_text_parts` is a
  redundant fallback — any non-empty `text` is already captured by the generic
  text handling immediately above, so the append can never run.

## Pruning: small direct tests for the remaining error/edge branches

`app/pruning/light_response_pruner/` already had broad behavior tests
(`test_pruning.py`); the gaps were fail-fast guards and low-level span helpers.
`test_pruning_coverage.py` fills them with small, direct tests:

- **config**: `validate_rules` passthrough/invalid, `load_rule_file`
  missing/invalid-JSON/non-object/comment-strip, `merge_rules`
  empty/combine/union, the conflicting-`cut_mode` raises for front and end
  sections (use `model_construct` to bypass the `Literal` validator and force
  the conflict branch), the empty-section `None` returns, `_merge_prefix_lists`
  dedup, `_normalize_sources` wrap/list/empty, and `_coerce_rule_source`
  passthrough.
- **models**: the `_dedupe_prefixes` blank-raises / dedup paths via
  `FrontRuleSection`, and all three `trimmed_side` computed-field branches
  (front-only, end-only, none).
- **pruner**: the `PrunerConfig` type/range guards (parametrized),
  `from_file`/`from_files`, the `prune` non-string and oversized-input guards
  (the latter asserts the warning), `prune_response`, and the `_prune_end`
  fenced-code skip (a matching paragraph that sits inside an open fence but
  does not itself start with a structural marker) plus the safety-block path.
- **units / similarity / whitespace**: span helpers driven directly —
  `leading_sentence_span` (blank, non-terminal dot), `paragraph_spans`
  (leading-blank skip + trailing-ws trim), `_is_inside_fenced_code_block`,
  `_starts_with_ordered_list_marker`, `prune_similar_sentences` (blank
  passthrough + dup-before-fence newline reinsertion), `_sentence_spans` blank,
  and `compact_whitespace` blank.
- **Genuinely unreachable guards** are `# pragma: no cover`: the merged-rules
  `ValidationError` re-raise in `config.merge_rules` (every input rule set has
  at least one valid section, so the merge is always valid) and the trailing
  `return None` in `units._next_blank_line_index` (the loop always returns once
  a newline is seen, or `None` earlier).

## Status so far

- `app/pruning/light_response_pruner/` — entire package at **100%** (config,
  models, pruner, units, similarity, whitespace, markdown, normalize, rules).
- `app/llm_model/` — entire directory at **100%** (providers/openai_provider,
  base, factory; `llm_client.py` excluded as a re-export shim).
- `app/tagging/` — `tagger.py` at **100%**.
- `app/sleep/` — entire directory at **100%** (cycle, worker,
  questions_consolidation).
- `app/embedding/` — entire directory at **100%** (openai_provider,
  sentence_transformers_provider, base, batching, factory, vector_index).
- `app/dream/` — entire directory at **100%** (dreams, context, auto_accept,
  common, rag, research, debug, prompts, and the idea/questions/research agents
  + their prompt builders).
- `app/rag/` — entire directory at **100%** (chunk_utils, manager, manager_index_io,
  manager_rebuild, syx_memory_artifact, daily_store).
- `app/api/` — entire directory at **100%** (chat, chat_pipeline, chat_prompting,
  projects, files, dream, llm_models, sleep).
- `app/agent_interface/` — entire directory at **100%** (parser, retrieval,
  entry_expansion, router, models).
- `app/core/` — entire directory at **100%** (config, database, llm_service, memory,
  personality, query_builder, route_policy, similarity, state, plus the already-100%
  db_models/models/retrieval_ordering).
- `app/llm_model/llm_client.py` — excluded (re-export shim).
- `app/tracking/` — omitted from measurement.
