# Turn Event Schema (`turns.jsonl`)

This document defines the canonical turns stream schema for instrumentation.

## Event Types

- `start_turn`
- `stage`
- `end_turn`

## Validation Behavior

- `start_turn` writes are best effort.
- `stage` writes are allowlisted and best effort:
  - unknown stage names are warned and dropped
  - missing active `turn_id` is warned and dropped
- `end_turn` writes are strict:
  - required invariant failures are warned
  - invalid `end_turn` records are skipped (not written)
- `turns.jsonl` does not emit per-record `schema_errors` arrays in v1.

## `start_turn`

Required fields:

- `ts` (string, UTC ISO timestamp)
- `event` (`"start_turn"`)
- `run_id` (string)
- `turn_id` (int)

Optional fields:

- `user_meta` (object)

Rules:

- `turn_id` must be monotonic within a run.
- Duplicate or non-monotonic `turn_id` values are warned and dropped.

## `stage`

Required fields:

- `ts` (string, UTC ISO timestamp)
- `event` (`"stage"`)
- `run_id` (string)
- `turn_id` (int)
- `name` (`"retrieval_selection_expansion"` | `"prompt_assembly"`)
- `data` (object)

Rules:

- `data` must not include envelope keys: `run_id`, `turn_id`, `ts`, `event`.
- Unknown `name` values are warned and dropped.
- Stage payloads are normalized at instrumentation boundary where needed:
  - retrieval stage emits canonical counters (`retrieved_count`, `selected_count`, `snippet_count_after_merge`, `expanded_unique_chunks_after_merge`)
  - deprecated retrieval keys are removed from emitted stage `data`

## `end_turn`

Required fields:

- `ts` (string, UTC ISO timestamp)
- `event` (`"end_turn"`)
- `run_id` (string)
- `turn_id` (int)
- `prompt_system_tokens_est` (int)
- `prompt_history_tokens_est` (int)
- `prompt_rag_tokens_est` (int)
- `prompt_profile_tokens_est` (int)
- `prompt_other_tokens_est` (int)
- `route` (string)
- `rag_enabled` (bool)
- `retrieved_count` (int)
- `kept_count` (int)
- `expanded_unique_chunks_after_merge` (int)
- `final_context_tokens_est` (int)
- `final_context_clipped` (bool)
- `main_total_tokens_reported` (int)
- `mini_prompt_tokens_reported` (int)
- `mini_completion_tokens_reported` (int)
- `turn_total_tokens_reported` (int)
- `turn_usage_source` (`"provider"` | `"estimate"` | `"zero_fallback"`)
- `turn_usage_is_estimate` (bool)
- `provider_tokens_total` (int)
- `estimated_tokens_total` (int)
- `zero_fallback_tokens_total` (int)
- `ttfb_ms_main` (int or null)
- `ttlt_ms_main` (int)
- `ttlt_ms_turn_total` (int)
- `invocations_count_total` (int)
- `main_invocations_count` (int)
- `mini_invocations_count` (int)

Conditionally required fields:

- `rag_skip_reason` is required when `rag_enabled=false` and must be one of:
  - `disabled_by_route`
  - `budget_zero`
  - `retrieval_error`
  - `no_candidates`

Optional fields:

- `turn_start_ts` (string, UTC ISO timestamp)
- `main_prompt_tokens_reported` (int or null)
- `main_completion_tokens_reported` (int or null)
- `response_len` (int)
- `finish_reason` (string)

## Invariants

- `turn_total_tokens_reported = main_total_tokens_reported + mini_prompt_tokens_reported`
- prompt estimate sum must match:
  - `final_context_tokens_est = prompt_system_tokens_est + prompt_history_tokens_est + prompt_rag_tokens_est + prompt_profile_tokens_est + prompt_other_tokens_est`
- retrieval counters must be non-negative
- `kept_count <= retrieved_count`
- when `rag_enabled=false`:
  - `retrieved_count = 0`
  - `kept_count = 0`
  - `expanded_unique_chunks_after_merge = 0`
  - `prompt_rag_tokens_est = 0`
- exactly one main invocation is required per interactive turn:
  - `main_invocations_count = 1`
- invocation counter reconciliation:
  - `invocations_count_total = main_invocations_count + mini_invocations_count`
- `ttlt_ms_main` is required
- for streaming main turns, `ttfb_ms_main` is required (non-null)

## Removed / Restricted Fields (v1)

- `rag_tokens_injected_est` must not be emitted.
- `output_meta` must not be emitted.
- turn-level `token_accounting_errors` and `schema_errors` arrays are out of scope.
