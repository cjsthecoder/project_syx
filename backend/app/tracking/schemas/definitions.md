# Instrumentation Field Definitions

Schema version: `1.0`

This file is the canonical data dictionary for instrumentation fields emitted to:

- `turns.jsonl`
- `run.json`
- `benchmark_results.jsonl` / `web_benchmark_results.jsonl`
- `web_turns.jsonl` (synthetic `end_turn` stream from web extractor)

## Field Dictionary (v1.0)

Use grouped field cards below for readability (no wide tables).

## Field Sets by Stream (v1)

This section defines required field sets per emitted record type to avoid partial-record drift.

### `turns.jsonl` -> `start_turn`

Required:
- `ts`
- `event` = `start_turn`
- `run_id`
- `turn_id`

Optional:
- `user_meta`

### `turns.jsonl` -> `stage`

Required:
- `ts`
- `event` = `stage`
- `run_id`
- `turn_id`
- `name` (`retrieval_selection_expansion` | `prompt_assembly`)
- `data` (object)

Constraints:
- `data` must not include envelope keys: `run_id`, `turn_id`, `ts`, `event`.

### `turns.jsonl` -> `end_turn`

Required top-level:
- `ts`
- `event` = `end_turn`
- `run_id`
- `turn_id`
- `prompt_system_tokens_est`
- `prompt_history_tokens_est`
- `prompt_rag_tokens_est`
- `prompt_profile_tokens_est`
- `prompt_other_tokens_est`
- `route`
- `rag_enabled`
- `retrieved_count`
- `kept_count`
- `expanded_unique_chunks_after_merge`
- `final_context_tokens_est`
- `final_context_clipped`
- `main_total_tokens_reported`
- `mini_prompt_tokens_reported`
- `mini_completion_tokens_reported`
- `turn_total_tokens_reported`
- `turn_usage_source`
- `turn_usage_is_estimate`
- `provider_tokens_total`
- `estimated_tokens_total`
- `zero_fallback_tokens_total`
- `ttfb_ms_main` (nullable)
- `ttlt_ms_main`
- `ttlt_ms_turn_total`
- `invocations_count_total`
- `main_invocations_count`
- `mini_invocations_count`

Conditionally required:
- `rag_skip_reason` when `rag_enabled=false`

### `web_benchmark_results.jsonl` -> `benchmark_result` (web extractor)

Required:
- `case_id`
- `system`
- `model_id` (nullable)
- `timestamp`
- `prompt_text`
- `response_text`
- `run_id` (nullable)
- `turn_id` (nullable)
- `main_total_tokens_reported` (nullable)
- `turn_total_tokens_reported` (nullable)
- `latency_ms` (nullable)
- `metrics_source`
- `completeness`
- `missing_fields`

### `web_turns.jsonl` -> synthetic `end_turn` (web extractor)

Required top-level:
- `ts`
- `event` = `end_turn`
- `system` = `chatgpt_web`
- `run_id`
- `turn_id`
- `prompt_system_tokens_est`
- `prompt_history_tokens_est`
- `prompt_rag_tokens_est`
- `prompt_profile_tokens_est`
- `prompt_other_tokens_est`
- `route`
- `rag_enabled`
- `retrieved_count`
- `kept_count`
- `expanded_unique_chunks_after_merge`
- `final_context_tokens_est`
- `final_context_clipped`
- `main_total_tokens_reported`
- `mini_prompt_tokens_reported`
- `mini_completion_tokens_reported`
- `turn_total_tokens_reported`
- `main_prompt_tokens_reported`
- `main_completion_tokens_reported`
- `turn_usage_source`
- `turn_usage_is_estimate`
- `provider_tokens_total`
- `estimated_tokens_total`
- `zero_fallback_tokens_total`
- `ttfb_ms_main` (nullable)
- `ttlt_ms_main`
- `ttlt_ms_turn_total`
- `invocations_count_total`
- `main_invocations_count`
- `mini_invocations_count`

### A) Core Envelope and IDs

#### `run_id`
- Type and units: string
- Exact meaning: Unique run identifier for one process run.
- Where measured: `start_run` boundary; copied into all streams.
- How computed: Generated once at run start and reused.
- Invariants / tolerance: Stable across run; should match run folder name.

#### `turn_id`
- Type and units: int (count) or null (maintenance/sleep invocations)
- Exact meaning: Interactive turn index for turn-scoped records.
- Where measured: `start_turn`, `record_stage`, `end_turn`; invocation start/end.
- How computed: Provided by caller for turns; captured active turn for invocations.
- Invariants / tolerance: Strictly increasing is required for `start_turn`; duplicates/regressions are detected against last seen turn id in instrumentation, warning-logged, and the duplicate/regressed `start_turn` write is dropped (non-silent data loss).

#### `system`
- Type and units: string enum-like
- Exact meaning: Source system label for cross-system comparison streams.
- Where measured: Benchmark/web extraction boundary (`benchmark_results.jsonl`, `web_benchmark_results.jsonl`, `web_turns.jsonl`).
- How computed: Set by producer (`syx`, `chatgpt`, `chatgpt_web`, etc.).
- Invariants / tolerance: Must be stable and explicit for a given stream to support joins/plot splits.

#### `ts`
- Type and units: string (UTC ISO timestamp)
- Exact meaning: Timestamp when an instrumentation record is written.
- Where measured: Record write boundary in all streams.
- How computed: Current UTC time at emit.
- Invariants / tolerance: Must be valid UTC ISO string.

#### `event`
- Type and units: enum string
- Exact meaning: Record type discriminator in each stream.
- Where measured: Record write boundary.
- How computed: Set by lifecycle method (`start_turn`, `end_invocation`, etc.).
- Invariants / tolerance: Must be valid for stream type.

### C) Stage Fields (`turns.jsonl`, `event="stage"`)

#### `name`
- Type and units: enum string
- Exact meaning: Stage boundary name.
- Where measured: `record_stage`.
- How computed: Passed by caller.
- Invariants / tolerance: Allowed: `retrieval_selection_expansion`, `prompt_assembly`.

#### `data.module`
- Type and units: string
- Exact meaning: Prompt assembly source module tag.
- Where measured: `prompt_assembly` stage.
- How computed: Caller-provided module label.
- Invariants / tolerance: Informational only.

#### `data.message_count`
- Type and units: int (count)
- Exact meaning: Number of messages in final LLM message list.
- Where measured: `prompt_assembly`, pre-send boundary.
- How computed: `len(msgs)` of assembled model messages.
- Invariants / tolerance: Non-negative.

#### `data.project_id`
- Type and units: string
- Exact meaning: Project identifier tied to retrieval execution.
- Where measured: `retrieval_selection_expansion` stage.
- How computed: Caller-provided project id.
- Invariants / tolerance: Informational; may be absent in non-project paths.

#### `data.daily_enabled`
- Type and units: boolean
- Exact meaning: Whether daily memory source participated in retrieval.
- Where measured: `retrieval_selection_expansion` stage.
- How computed: Retrieval pipeline source gating decision.
- Invariants / tolerance: Informational.

#### `data.per_source_k`
- Type and units: int (count)
- Exact meaning: Per-source retrieval candidate limit used by query.
- Where measured: `retrieval_selection_expansion`, pre-retrieval.
- How computed: Route-policy-derived `PER_SOURCE_K`.
- Invariants / tolerance: Non-negative integer.

#### `data.max_keep`
- Type and units: int (count)
- Exact meaning: Selection keep cap in effect before adjacency bonus adjustments.
- Where measured: `retrieval_selection_expansion`, selection boundary.
- How computed: Route policy `max_keep`.
- Invariants / tolerance: Non-negative integer.

#### `data.retrieved_count`
- Type and units: int (count)
- Exact meaning: Candidate count before selection and before expansion.
- Where measured: `retrieval_selection_expansion`, pre-selection, pre-expansion, pre-dedupe.
- How computed: **Sum of raw candidates returned from stores (daily/LTM) before merge/dedupe; then globally sorted into the ordered list; count emitted from that ordered pre-selection list.**
- Invariants / tolerance: Non-negative; must be `>= kept_count`.

#### `data.selected_count`
- Type and units: int (count)
- Exact meaning: Selected candidate count after policy selection.
- Where measured: `retrieval_selection_expansion`, post-selection, pre-expansion.
- How computed: Count of candidates retained by selection policy.
- Invariants / tolerance: Non-negative; should be `<= data.retrieved_count`.

#### `data.snippet_count_after_merge`
- Type and units: int (count)
- Exact meaning: Snippet/group count after merge/collapse formatting stage.
- Where measured: `retrieval_selection_expansion`, post-expansion assembly path.
- How computed: Count of snippet blocks injected into context body.
- Invariants / tolerance: Non-negative.

#### `data.expanded_unique_chunks_after_merge`
- Type and units: int (count)
- Exact meaning: Unique chunk count after expansion and identity dedupe.
- Where measured: `retrieval_selection_expansion`, post-expansion, post-dedupe.
- How computed: Keyed unique count using identity key `(source_document_id, chunk_index)` with first-seen-wins dedupe in the expanded stream.
- Invariants / tolerance: Non-negative; zero when `rag_enabled=false`; semantics assume `source_document_id` is collision-safe across contributing stores. Sparse/legacy chunks without valid key parts are preserved but are not counted in keyed-unique total.

#### `data.adjacent_bonus`
- Type and units: int (count)
- Exact meaning: Additional keep budget granted by adjacent-chunk rule.
- Where measured: `retrieval_selection_expansion`, selection pass.
- How computed: Increment count when adjacency condition fires.
- Invariants / tolerance: Non-negative.

#### `data.main_hits`
- Type and units: int (count)
- Exact meaning: Number of retained/referenced LTM-source snippets.
- Where measured: `retrieval_selection_expansion`, post assembly.
- How computed: Count of LTM-side snippet contributions.
- Invariants / tolerance: Non-negative.

#### `data.daily_hits`
- Type and units: int (count)
- Exact meaning: Number of retained/referenced daily-source snippets.
- Where measured: `retrieval_selection_expansion`, post assembly.
- How computed: Count of daily-side snippet contributions.
- Invariants / tolerance: Non-negative.

#### `data.total_hits`
- Type and units: int (count)
- Exact meaning: Combined hit count for retrieval context reporting.
- Where measured: `retrieval_selection_expansion`, post assembly.
- How computed: `main_hits + daily_hits`.
- Invariants / tolerance: Should equal sum of `main_hits` and `daily_hits`.

#### `data.tokens_used`
- Type and units: int (tokens)
- Exact meaning: Estimated tokens consumed by assembled retrieval context text.
- Where measured: `retrieval_selection_expansion`, post context assembly.
- How computed: Sum of token estimates for injected snippet text/headers.
- Invariants / tolerance: Non-negative.

### D) Turn End Fields (`turns.jsonl`, `event="end_turn"`)

#### `route`
- Type and units: string enum-like
- Exact meaning: Builder route chosen for the turn.
- Where measured: Retrieval stage then persisted at `end_turn`.
- How computed: Stage route value or fallback `OTHER`.
- Invariants / tolerance: Must be present on `end_turn` (fallback allowed).

#### `rag_enabled`
- Type and units: boolean
- Exact meaning: Whether retrieval path was enabled/attempted.
- Where measured: Retrieval stage then persisted at `end_turn`.
- How computed: Stage/runtime retrieval path decision.
- Invariants / tolerance: If false, `rag_skip_reason` required and RAG counters must be zeroed.

#### `rag_skip_reason`
- Type and units: enum string
- Exact meaning: Reason RAG was skipped when `rag_enabled=false`.
- Where measured: `end_turn`.
- How computed: Propagated from retrieval path decision.
- Invariants / tolerance: Required when `rag_enabled=false`; allowed set: `disabled_by_route`, `budget_zero`, `retrieval_error`, `no_candidates`.

#### `prompt_system_tokens_est`
- Type and units: int (tokens)
- Exact meaning: Estimated system prompt contribution in final prompt.
- Where measured: `prompt_assembly` stage, pre-send.
- How computed: Estimate over base system prompt text.
- Invariants / tolerance: Non-negative; part of prompt-sum invariant.

#### `prompt_history_tokens_est`
- Type and units: int (tokens)
- Exact meaning: Estimated history contribution in final prompt.
- Where measured: `prompt_assembly` stage, pre-send.
- How computed:
  - Syx: estimate over serialized conversation history included in the final prompt payload.
  - Web synthetic (`web_turns.jsonl`): estimate over all prior visible extracted user prompts and assistant responses (`history_text_parts` replay), excluding current-turn prompt/response.
- Invariants / tolerance: Non-negative; part of prompt-sum invariant.

#### `prompt_rag_tokens_est`
- Type and units: int (tokens)
- Exact meaning: Estimated retrieved context contribution in final prompt.
- Where measured: `prompt_assembly` stage, pre-send.
- How computed: Estimate over RAG context block only.
- Invariants / tolerance: Non-negative; must be 0 when `rag_enabled=false`.

#### `prompt_profile_tokens_est`
- Type and units: int (tokens)
- Exact meaning: Estimated profile/hint contribution in final prompt.
- Where measured: `prompt_assembly` stage, pre-send.
- How computed: Estimate over assistant hint/profile text.
- Invariants / tolerance: Non-negative; part of prompt-sum invariant.

#### `prompt_other_tokens_est`
- Type and units: int (tokens)
- Exact meaning: Estimated uncategorized contribution (typically user message).
- Where measured: `prompt_assembly` stage, pre-send.
- How computed: Estimate over user message/other remaining blocks.
- Invariants / tolerance: Non-negative; part of prompt-sum invariant.

#### `final_context_tokens_est`
- Type and units: int (tokens)
- Exact meaning: Estimated total final prompt context sent to main model.
- Where measured: `end_turn`, post prompt assembly.
- How computed: `prompt_system + prompt_history + prompt_rag + prompt_profile + prompt_other` on the final prompt payload sent to the main model.
- Invariants / tolerance: Prompt-sum invariant (v1 exact): `final_context_tokens_est == prompt_system_tokens_est + prompt_history_tokens_est + prompt_rag_tokens_est + prompt_profile_tokens_est + prompt_other_tokens_est`.

#### `final_context_clipped`
- Type and units: boolean
- Exact meaning: Whether final prompt context was clipped by budget limits.
- Where measured: `end_turn`, post budget enforcement.
- How computed: Pass-through from upstream prompt/RAG assembly path (`rag_turn_metrics.final_context_clipped`), default false.
- Invariants / tolerance: Boolean only. Component-level clipping attribution is not emitted in v1 (no `clipped_components` field). Eligibility of specific components is owned by upstream assembly logic; instrumentation does not currently encode per-component clipping source.

#### `retrieved_count`
- Type and units: int (count)
- Exact meaning: Candidate count before selection/expansion.
- Where measured: `end_turn` rollup from retrieval stage.
- How computed: Carried from `data.retrieved_count` semantics above.
- Invariants / tolerance: Non-negative; must be `>= kept_count`.

#### `kept_count`
- Type and units: int (count)
- Exact meaning: Selected candidate count before expansion.
- Where measured: `end_turn` rollup from retrieval stage.
- How computed: Carried from retrieval `selected_count`.
- Invariants / tolerance: Non-negative; must be `<= retrieved_count`.

#### `expanded_unique_chunks_after_merge`
- Type and units: int (count)
- Exact meaning: Unique expanded chunk count post-dedupe.
- Where measured: `end_turn` rollup from retrieval stage.
- How computed: Carried from retrieval stage keyed dedupe count where identity key is `(source_document_id, chunk_index)` (first-seen wins).
- Invariants / tolerance: Non-negative; must be 0 when `rag_enabled=false`; assumes cross-store-safe `source_document_id` identity. Sparse/legacy chunks lacking valid key parts are preserved in output but excluded from keyed-unique count.

#### `main_total_tokens_reported`
- Type and units: int (tokens)
- Exact meaning: Total tokens from main invocation(s) for turn.
- Where measured: `end_turn`, post invocation rollup.
- How computed: Sum `total_tokens_reported` where `purpose=main`.
- Invariants / tolerance: Exactly one main invocation required in v1.

#### `mini_prompt_tokens_reported`
- Type and units: int (tokens)
- Exact meaning: Total interactive non-main prompt tokens for turn.
- Where measured: `end_turn`, post invocation rollup.
- How computed: Sum `prompt_tokens_reported` for non-main, non-maintenance invocations.
- Invariants / tolerance: Non-negative; contributes to `turn_total_tokens_reported`.

#### `mini_completion_tokens_reported`
- Type and units: int (tokens)
- Exact meaning: Total interactive non-main completion tokens for turn.
- Where measured: `end_turn`, post invocation rollup.
- How computed: Sum `completion_tokens_reported` for non-main, non-maintenance invocations.
- Invariants / tolerance: Non-negative; excluded from `turn_total_tokens_reported`.

#### `turn_total_tokens_reported`
- Type and units: int (tokens)
- Exact meaning: Total interactive turn token usage.
- Where measured: `end_turn`.
- How computed: `main_total_tokens_reported + mini_prompt_tokens_reported`.
- Invariants / tolerance: Must match exact sum.

#### `main_prompt_tokens_reported`
- Type and units: int or null (tokens)
- Exact meaning: Main invocation prompt tokens copied to turn summary.
- Where measured: `end_turn`, post main invocation.
- How computed:
  - Syx: from main invocation usage payload.
  - Web synthetic (`web_turns.jsonl`): set to `final_context_tokens_est`.
- Invariants / tolerance: If both this and completion are present, their sum must equal `main_total_tokens_reported`.

#### `main_completion_tokens_reported`
- Type and units: int or null (tokens)
- Exact meaning: Main invocation completion tokens copied to turn summary.
- Where measured: `end_turn`, post main invocation.
- How computed:
  - Syx: from main invocation usage payload.
  - Web synthetic (`web_turns.jsonl`): estimated response tokens for the current turn.
- Invariants / tolerance: If both this and prompt are present, their sum must equal `main_total_tokens_reported`.

### H) Benchmark/Web Comparison Fields

#### `case_id`
- Type and units: string
- Exact meaning: Stable identifier for a benchmark case/turn candidate.
- Where measured: Benchmark extraction/capture boundary.
- How computed: Producer-defined stable id (for web extractor: `<input_base>:turn:<n>`).
- Invariants / tolerance: Must be unique within output file and stable for scorer joins.

#### `metrics_source`
- Type and units: string enum-like
- Exact meaning: Provenance of usage/latency metrics in benchmark rows.
- Where measured: Benchmark extraction/capture boundary.
- How computed: Set by producer (`syx_instrumentation`, `html_extracted`, etc.).
- Invariants / tolerance: Must reflect real provenance; do not fabricate provider metrics.

#### `completeness`
- Type and units: enum (`full` | `partial`)
- Exact meaning: Whether all expected benchmark fields are present with non-null values.
- Where measured: Benchmark extraction/capture boundary.
- How computed: Derived from missing/nullability policy at record build time.
- Invariants / tolerance: Must align with `missing_fields`.

#### `missing_fields`
- Type and units: array[string]
- Exact meaning: Explicit list of intentionally unavailable fields in a benchmark record.
- Where measured: Benchmark extraction/capture boundary.
- How computed: Enumerated during record construction.
- Invariants / tolerance: Empty when `completeness=full`; may be non-empty for external/manual sources.

#### `prompts.json.system_prompt.known_component`
- Type and units: string (prompt text)
- Exact meaning: User-controlled system-instruction component used for benchmark runs.
- Where measured: Benchmark input configuration (`prompts.json`) and web extractor synthesis boundary.
- How computed:
  - Syx: treated as system prompt content and counted within prompt/system token accounting.
  - ChatGPT web synthetic: mapped to Custom Instructions text and counted as the visible system component only.
- Invariants / tolerance: For ChatGPT web runs, this field represents only the known/visible portion of the effective system prompt; hidden platform/system layers are not observable and are intentionally excluded from token accounting.

#### `turn_usage_source`
- Type and units: enum (`provider` | `estimate` | `zero_fallback`)
- Exact meaning: Provenance class for turn-level aggregated usage.
- Where measured: `end_turn`, post invocation aggregation.
- How computed: Derived from contributing interactive invocations using precedence: `provider` only when all contributing invocations are provider-reported; otherwise `zero_fallback` if any contributor used zero fallback; otherwise `estimate` if any contributor used estimates.
- Invariants / tolerance: Worst provenance wins (`zero_fallback` > `estimate` > `provider`).

#### `turn_usage_is_estimate`
- Type and units: boolean
- Exact meaning: Whether turn aggregate includes estimate/fallback usage.
- Where measured: `end_turn`.
- How computed: `turn_usage_source != "provider"`.
- Invariants / tolerance: Must match `turn_usage_source`.

#### `provider_tokens_total`
- Type and units: int (tokens)
- Exact meaning: Turn-interactive token subtotal from provider-reported invocations.
- Where measured: `end_turn` aggregation.
- How computed: Sum totals where invocation `usage_source=provider` and interactive turn-scoped.
- Invariants / tolerance: Non-negative.

#### `estimated_tokens_total`
- Type and units: int (tokens)
- Exact meaning: Turn-interactive token subtotal from estimate-derived invocations.
- Where measured: `end_turn` aggregation.
- How computed: Sum totals where invocation `usage_source=estimate` and interactive turn-scoped.
- Invariants / tolerance: Non-negative.

#### `zero_fallback_tokens_total`
- Type and units: int (tokens)
- Exact meaning: Turn-interactive token subtotal from zero-fallback invocations.
- Where measured: `end_turn` aggregation.
- How computed: Sum totals where invocation `usage_source=zero_fallback` and interactive turn-scoped.
- Invariants / tolerance: Non-negative.

#### `ttfb_ms_main`
- Type and units: int (ms) or null
- Exact meaning: Main invocation TTFB copied to turn record.
- Where measured: `end_turn`, post main invocation finalize.
- How computed: Copied from main invocation `timing.ttfb_ms`.
- Invariants / tolerance: Required for streaming main; null for non-streaming.

#### `ttlt_ms_main`
- Type and units: int (ms)
- Exact meaning: Main invocation TTLT copied to turn record.
- Where measured: `end_turn`, post main invocation finalize.
- How computed: Copied from main invocation `timing.ttlt_ms`.
- Invariants / tolerance: Required; missing value causes turn write skip.

#### `ttlt_ms_turn_total`
- Type and units: int (ms)
- Exact meaning: End-to-end interactive request-path wall time.
- Where measured: `end_turn`.
- How computed: Monotonic delta from turn start to turn end.
- Invariants / tolerance: Non-negative integer.

#### `turn_start_ts`
- Type and units: string (UTC ISO timestamp) or null
- Exact meaning: Start timestamp captured for turn wall-time context.
- Where measured: `start_turn`, propagated at `end_turn`.
- How computed: Captured at turn start.
- Invariants / tolerance: Informational; may be absent in error paths.

#### `invocations_count_total`
- Type and units: int (count)
- Exact meaning: Total interactive invocation count attributed to turn.
- Where measured: `end_turn`, post invocation aggregation.
- How computed: `main_invocations_count + mini_invocations_count`.
- Invariants / tolerance: Must equal component sum exactly.

#### `main_invocations_count`
- Type and units: int (count)
- Exact meaning: Count of `purpose=main` invocations for turn.
- Where measured: `end_turn`.
- How computed: Aggregated from turn-scoped invocation records.
- Invariants / tolerance: Must equal 1 in v1. Current runtime behavior on violation is warn + skip `end_turn` write (record omitted), which can create gaps in downstream plots.

#### `mini_invocations_count`
- Type and units: int (count)
- Exact meaning: Count of non-main interactive invocations for turn.
- Where measured: `end_turn`.
- How computed: Aggregated from turn-scoped invocation records excluding maintenance purposes.
- Invariants / tolerance: Non-negative; part of invocation-count invariant.

#### `response_len`
- Type and units: int (chars)
- Exact meaning: Assistant response length at turn completion.
- Where measured: `end_turn`.
- How computed: Caller-provided response character length.
- Invariants / tolerance: Optional; non-negative when present.

#### `finish_reason`
- Type and units: string
- Exact meaning: Provider/model stop reason for completion.
- Where measured: `end_turn`.
- How computed: Caller-provided completion metadata.
- Invariants / tolerance: Optional informational field.

#### `user_meta.project_id`
- Type and units: string or null
- Exact meaning: Project id for the interactive request.
- Where measured: `start_turn`.
- How computed: Copied from request metadata.
- Invariants / tolerance: Informational.

#### `user_meta.conversation_id`
- Type and units: string or null
- Exact meaning: Conversation/session id associated with request.
- Where measured: `start_turn`.
- How computed: Copied from request metadata.
- Invariants / tolerance: Informational.

#### `user_meta.message_len`
- Type and units: int (chars)
- Exact meaning: Input user message length.
- Where measured: `start_turn`.
- How computed: Character length of request message.
- Invariants / tolerance: Non-negative.

#### `user_meta.streaming`
- Type and units: boolean
- Exact meaning: Whether request used streaming response path.
- Where measured: `start_turn`.
- How computed: Request metadata flag.
- Invariants / tolerance: Informational.

### F) Run Metadata (`run.json`)

#### `mode`
- Type and units: string
- Exact meaning: Instrumentation operating mode for run.
- Where measured: `start_run`.
- How computed: From instrumentation config.
- Invariants / tolerance: Informational.

#### `started_at`
- Type and units: string (UTC ISO timestamp)
- Exact meaning: Run start timestamp.
- Where measured: `start_run`.
- How computed: Captured at run initialization.
- Invariants / tolerance: Must be valid timestamp.

#### `ended_at`
- Type and units: string (UTC ISO timestamp) or null
- Exact meaning: Run completion timestamp.
- Where measured: `end_run`.
- How computed: Captured at run finalization.
- Invariants / tolerance: Null until end-run; should be >= `started_at`.

#### `summary`
- Type and units: object
- Exact meaning: End-of-run summary payload.
- Where measured: `end_run`.
- How computed: Caller-supplied summary object.
- Invariants / tolerance: Optional keys are run-context dependent.

#### `summary.reason`
- Type and units: string
- Exact meaning: High-level end-run reason code.
- Where measured: `end_run`.
- How computed: Caller sets from shutdown/termination context.
- Invariants / tolerance: Optional informational field.

#### `models_observed`
- Type and units: object (`purpose -> [model_id]`)
- Exact meaning: Purpose-native map of models observed during run.
- Where measured: `end_run`, post invocation scan.
- How computed: Aggregated unique model ids from invocation records by purpose.
- Invariants / tolerance: Keys remain purpose-native (`main`, `router`, `tagger`, `sleep`, ...).

#### `project_observed`
- Type and units: object
- Exact meaning: Runtime-observed project context and personality snapshot for the run.
- Where measured: `start_turn` (first/next observed project IDs for the run).
- How computed: Captures first observed `project_id` from turn metadata and snapshots normalized personality once for reproducibility.
- Invariants / tolerance: Runtime metadata only; not part of immutable startup snapshot.

#### `project_observed.project_id`
- Type and units: string or null
- Exact meaning: First project id observed in run turn metadata.
- Where measured: First `start_turn` with non-empty `user_meta.project_id`.
- How computed: Value copied from incoming turn metadata.
- Invariants / tolerance: Null until first project-scoped turn.

#### `project_observed.projects_seen`
- Type and units: array[string]
- Exact meaning: Unique set of project ids observed during run.
- Where measured: `start_turn`.
- How computed: Append-only unique list from incoming `user_meta.project_id`.
- Invariants / tolerance: Includes `project_id` and any additional project ids seen later.

#### `project_observed.multi_project_run`
- Type and units: boolean
- Exact meaning: Whether more than one distinct project id was observed during the run.
- Where measured: `start_turn`.
- How computed: Set true when an observed project id differs from first `project_id`.
- Invariants / tolerance: Monotonic false->true.

#### `project_observed.as_run_personality`
- Type and units: object or null
- Exact meaning: Normalized personality snapshot used for the run project.
- Where measured: First project capture in `start_turn`.
- How computed: Loaded via project personality loader; falls back to default personality when project file is absent/unreadable.
- Invariants / tolerance: Captured once per run for first observed project id.

#### `project_observed.as_run_personality_sha256`
- Type and units: string (hex) or null
- Exact meaning: Stable SHA-256 digest of canonical personality JSON snapshot.
- Where measured: First project capture in `start_turn`.
- How computed: Hash over sorted/minified canonical JSON representation.
- Invariants / tolerance: Null when snapshot unavailable.

#### `project_observed.personality_captured_at`
- Type and units: string (UTC ISO timestamp) or null
- Exact meaning: Snapshot capture timestamp.
- Where measured: First project capture in `start_turn`.
- How computed: Current UTC timestamp at snapshot write.
- Invariants / tolerance: Null when snapshot unavailable.

#### `project_observed.personality_source`
- Type and units: string enum
- Exact meaning: Provenance of captured personality snapshot.
- Where measured: First project capture in `start_turn`.
- How computed: `project_file` when `memory/{project_id}/personality.json` exists, `default_fallback` when loader falls back to defaults, `unavailable` on snapshot failure.
- Invariants / tolerance: One of `project_file`, `default_fallback`, `unavailable`.

#### `config_snapshot`
- Type and units: object
- Exact meaning: Immutable startup configuration snapshot for reproducibility.
- Where measured: `start_run`.
- How computed: Normalized startup config written once.
- Invariants / tolerance: Must not be mutated mid-run.

### G) `config_snapshot` Fields (actual emitted)

#### `config_snapshot.models_configured.main_model`
- Type and units: string
- Exact meaning: Configured default main chat model at startup.
- Where measured: Startup snapshot.
- How computed: Settings at process start.
- Invariants / tolerance: Informational; may differ from observed model overrides.

#### `config_snapshot.models_configured.builder_model`
- Type and units: string
- Exact meaning: Configured builder/router model at startup.
- Where measured: Startup snapshot.
- How computed: Settings at process start.
- Invariants / tolerance: Informational.

#### `config_snapshot.models_configured.tagger_model`
- Type and units: string
- Exact meaning: Configured tagger model at startup.
- Where measured: Startup snapshot.
- How computed: Settings at process start.
- Invariants / tolerance: Informational.

#### `config_snapshot.prompt_budgeting.model_context_window_tokens`
- Type and units: int (tokens) or null
- Exact meaning: Known model context window token limit.
- Where measured: Startup snapshot.
- How computed: Captured from settings when available.
- Invariants / tolerance: Null when unknown.

#### `config_snapshot.prompt_budgeting.max_output_tokens_requested`
- Type and units: int (tokens) or null
- Exact meaning: Requested max output tokens configured at startup.
- Where measured: Startup snapshot.
- How computed: From settings (`max_output_tokens` legacy normalized here).
- Invariants / tolerance: If clamp absent, should equal effective value.

#### `config_snapshot.prompt_budgeting.max_output_tokens_effective`
- Type and units: int (tokens) or null
- Exact meaning: Effective max output tokens after runtime normalization/clamp.
- Where measured: Startup snapshot.
- How computed: Normalized from requested value / clamp path.
- Invariants / tolerance: If no clamp, equals requested.

#### `config_snapshot.prompt_budgeting.target_max_prompt_tokens`
- Type and units: int (tokens) or null
- Exact meaning: Target max prompt budget cap.
- Where measured: Startup snapshot.
- How computed: Captured from settings when available.
- Invariants / tolerance: Null when unknown/not enforced.

#### `config_snapshot.prompt_budgeting.history_max_tokens`
- Type and units: int (tokens) or null
- Exact meaning: History component token cap.
- Where measured: Startup snapshot.
- How computed: Captured from settings when available.
- Invariants / tolerance: Null when unknown/not enforced.

#### `config_snapshot.prompt_budgeting.rag_max_tokens`
- Type and units: int (tokens) or null
- Exact meaning: RAG component token cap.
- Where measured: Startup snapshot.
- How computed: Captured from settings when available.
- Invariants / tolerance: Null when unknown/not enforced.

#### `config_snapshot.prompt_budgeting.profile_max_tokens`
- Type and units: int (tokens) or null
- Exact meaning: Profile/hint component token cap.
- Where measured: Startup snapshot.
- How computed: Captured from settings when available.
- Invariants / tolerance: Null when unknown/not enforced.

#### `config_snapshot.prompt_budgeting.system_max_tokens`
- Type and units: int (tokens) or null
- Exact meaning: System prompt component token cap.
- Where measured: Startup snapshot.
- How computed: Captured from settings when available.
- Invariants / tolerance: Null when unknown/not enforced.

#### `config_snapshot.prompt_budgeting.prompt_budgeting_known`
- Type and units: boolean
- Exact meaning: Whether prompt budgeting key values are fully known at startup snapshot.
- Where measured: Startup snapshot normalization.
- How computed: True only when key budgeting fields are non-null or explicitly set true.
- Invariants / tolerance: False when key prompt budget values are unknown.

#### `config_snapshot.retrieval_static.base_top_k`
- Type and units: int (count)
- Exact meaning: Baseline retrieval K before multipliers.
- Where measured: Startup snapshot.
- How computed: From retrieval settings.
- Invariants / tolerance: Non-negative.

#### `config_snapshot.retrieval_static.retrieval_multiplier_default`
- Type and units: float
- Exact meaning: Default retrieval multiplier applied when route policy does not override.
- Where measured: Startup snapshot.
- How computed: From retrieval settings.
- Invariants / tolerance: Non-negative.

#### `config_snapshot.retrieval_static.embedding_model`
- Type and units: string
- Exact meaning: Embedding model id used for retrieval indices/query embedding.
- Where measured: Startup snapshot.
- How computed: From settings.
- Invariants / tolerance: Informational.

#### `config_snapshot.retrieval_static.chunk_size`
- Type and units: int (tokens/chars by splitter config)
- Exact meaning: Configured chunk size for indexing/splitting.
- Where measured: Startup snapshot.
- How computed: From settings.
- Invariants / tolerance: Non-negative.

#### `config_snapshot.retrieval_static.chunk_overlap`
- Type and units: int (tokens/chars by splitter config)
- Exact meaning: Configured chunk overlap for indexing/splitting.
- Where measured: Startup snapshot.
- How computed: From settings.
- Invariants / tolerance: Non-negative.

#### `config_snapshot.route_policy.<route>.retrieval_multiplier`
- Type and units: float
- Exact meaning: Route-specific retrieval multiplier.
- Where measured: Startup snapshot.
- How computed: Loaded route policy.
- Invariants / tolerance: Non-negative.

#### `config_snapshot.route_policy.<route>.max_keep`
- Type and units: int (count)
- Exact meaning: Route-specific selection keep cap.
- Where measured: Startup snapshot.
- How computed: Loaded route policy.
- Invariants / tolerance: Non-negative.

#### `config_snapshot.route_policy.<route>.expansion.max_before`
- Type and units: int (count)
- Exact meaning: Route-specific maximum adjacency expansion before central chunk.
- Where measured: Startup snapshot.
- How computed: Loaded route policy.
- Invariants / tolerance: Non-negative.

#### `config_snapshot.route_policy.<route>.expansion.max_after`
- Type and units: int (count)
- Exact meaning: Route-specific maximum adjacency expansion after central chunk.
- Where measured: Startup snapshot.
- How computed: Loaded route policy.
- Invariants / tolerance: Non-negative.

#### `config_snapshot.deprecated_or_ignored.rag_score_threshold`
- Type and units: float
- Exact meaning: Legacy threshold preserved for visibility but not enforced in current route-selection flow.
- Where measured: Startup snapshot.
- How computed: From config passthrough.
- Invariants / tolerance: Informational (non-enforced section).

#### `config_snapshot.deprecated_or_ignored.daily_rag_score_threshold`
- Type and units: float
- Exact meaning: Legacy daily threshold preserved for visibility but not enforced in current route-selection flow.
- Where measured: Startup snapshot.
- How computed: From config passthrough.
- Invariants / tolerance: Informational (non-enforced section).

#### `config_snapshot.deprecated_or_ignored.note`
- Type and units: string
- Exact meaning: Human note explaining non-enforced/deprecated config scope.
- Where measured: Startup snapshot.
- How computed: Config snapshot note text.
- Invariants / tolerance: Informational.

#### `config_snapshot.maintenance.sleep_enabled`
- Type and units: boolean
- Exact meaning: Whether sleep maintenance is enabled.
- Where measured: Startup snapshot.
- How computed: From maintenance settings.
- Invariants / tolerance: Informational.

#### `config_snapshot.maintenance.enable_scheduler`
- Type and units: boolean
- Exact meaning: Whether sleep scheduler is enabled.
- Where measured: Startup snapshot.
- How computed: From maintenance settings.
- Invariants / tolerance: Informational.

#### `config_snapshot.maintenance.sleep_cycle_hour`
- Type and units: int (hour)
- Exact meaning: Scheduler hour for sleep cycle trigger.
- Where measured: Startup snapshot.
- How computed: From maintenance settings.
- Invariants / tolerance: 0-23 expected.

#### `config_snapshot.maintenance.sleep_cycle_minute`
- Type and units: int (minute)
- Exact meaning: Scheduler minute for sleep cycle trigger.
- Where measured: Startup snapshot.
- How computed: From maintenance settings.
- Invariants / tolerance: 0-59 expected.

#### `config_snapshot.maintenance.verify_rag`
- Type and units: boolean
- Exact meaning: Whether maintenance verifies RAG artifacts/state.
- Where measured: Startup snapshot.
- How computed: From maintenance settings.
- Invariants / tolerance: Informational.

#### `config_snapshot.maintenance.force_rag_rebuild_on_startup`
- Type and units: boolean
- Exact meaning: Whether startup forces RAG rebuild.
- Where measured: Startup snapshot.
- How computed: From maintenance settings.
- Invariants / tolerance: Informational.

#### `config_snapshot.maintenance.dream_enabled`
- Type and units: boolean
- Exact meaning: Whether dream pipeline is enabled.
- Where measured: Startup snapshot.
- How computed: From maintenance settings.
- Invariants / tolerance: Informational.

#### `config_snapshot.maintenance.reporting_scope`
- Type and units: enum-like string
- Exact meaning: Scope marker for maintenance reporting.
- Where measured: Startup snapshot normalization.
- How computed: Defaults/normalization (v1: `sleep_only`).
- Invariants / tolerance: Should be `sleep_only` in current phase.

#### `config_snapshot.instrumentation.enabled`
- Type and units: boolean
- Exact meaning: Whether instrumentation writes are enabled.
- Where measured: Startup snapshot.
- How computed: From instrumentation config.
- Invariants / tolerance: Informational.

#### `config_snapshot.instrumentation.mode`
- Type and units: string
- Exact meaning: Instrumentation mode string.
- Where measured: Startup snapshot.
- How computed: From instrumentation config.
- Invariants / tolerance: Should align with top-level `mode`.

#### `config_snapshot.instrumentation.run_id_override`
- Type and units: string or null
- Exact meaning: Optional run id prefix override.
- Where measured: Startup snapshot.
- How computed: From instrumentation config.
- Invariants / tolerance: Informational.

#### `config_snapshot.instrumentation.runs_dir`
- Type and units: string
- Exact meaning: Output directory for run artifacts.
- Where measured: Startup snapshot.
- How computed: From instrumentation config.
- Invariants / tolerance: Informational.

#### `config_snapshot.instrumentation.validation.prompt_tol_abs_tokens`
- Type and units: int (tokens)
- Exact meaning: Absolute tolerance for prompt-estimate accounting checks.
- Where measured: Startup snapshot.
- How computed: From validation settings.
- Invariants / tolerance: Non-negative.

#### `config_snapshot.instrumentation.validation.prompt_tol_pct`
- Type and units: float
- Exact meaning: Relative tolerance for prompt-estimate accounting checks.
- Where measured: Startup snapshot.
- How computed: From validation settings.
- Invariants / tolerance: Non-negative.

#### `config_snapshot.git_commit`
- Type and units: string (git SHA)
- Exact meaning: Git commit hash at startup snapshot.
- Where measured: Startup snapshot normalization.
- How computed: Detected via git command at startup.
- Invariants / tolerance: Required in v1; should be non-empty.

#### `config_snapshot.git_dirty`
- Type and units: boolean
- Exact meaning: Whether working tree had uncommitted changes at startup snapshot.
- Where measured: Startup snapshot normalization.
- How computed: Detected via `git status --porcelain`.
- Invariants / tolerance: Required in v1.

#### `config_snapshot.python_version`
- Type and units: string
- Exact meaning: Python runtime version string.
- Where measured: Startup snapshot.
- How computed: Captured from runtime.
- Invariants / tolerance: Informational.

## Counter Map (Pipeline Boundaries)

- A.4.1 retrieval output (`ordered` pre-selection list): `retrieved_count`
  - Boundary: after retrieval and global ordering, before A.4.3 selection.
- A.4.3 selection survivors: `kept_count` (from `selected_count`)
  - Boundary: after selection, before A.4.4 expansion.
- A.4.4 expansion + identity dedupe result: `expanded_unique_chunks_after_merge`
  - Boundary: after expansion and post-dedupe keyed unique counting.

## Notes

- This dictionary is normative for field semantics in schema version `1.0`.
- Field additions in future versions should be append-only where possible.
- Breaking semantic changes require a schema version bump.
