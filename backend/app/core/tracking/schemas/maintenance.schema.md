# Maintenance Event Schema (`maintenance.jsonl`)

This document defines the canonical maintenance record schema for instrumentation.

## Scope

- v1 is scoped to sleep maintenance only (`job_type="sleep"`).
- Additional maintenance job types are out of scope for this phase.

## Validation Behavior

- Validation is best effort.
- Records are written whenever possible.
- Validation issues are recorded in `schema_errors`.
- `schema_errors` entries use structured objects:
  - `code` (string)
  - `field` (string)
  - `expected` (json value)
  - `actual` (json value)
  - optional: `message` (string)
  - optional: `details` (object)

## Canonical Fields

Required fields:

- `ts` (string, UTC ISO timestamp)
- `event` (`"maintenance"`)
- `run_id` (string)
- `job_id` (string)
- `job_type` (`"sleep"`)
- `status` (`"success"` | `"partial"` | `"failed"`)
- `start_ts` (string, UTC ISO timestamp)
- `end_ts` (string, UTC ISO timestamp)
- `after_turn` (int or null)
- `prompt_tokens_reported` (int)
- `completion_tokens_reported` (int)
- `total_tokens_reported` (int)
- `usage_source` (`"provider"` | `"estimate"` | `"zero_fallback"`)
- `usage_estimate_method` (string or null)
- `usage_is_estimate` (bool)
- `duration_ms` (int)
- `invocations_query` object with:
  - `job_id` (string)
  - `purpose` (`"sleep"`)

Optional fields:

- `items_in` (int)
- `items_out` (int)
- `provider_tokens_total` (int)
- `estimated_tokens_total` (int)
- `zero_fallback_tokens_total` (int)
- `invocation_count_sleep` (int)
- `invocation_ids_sample` (array of strings)
- `meta` (object; diagnostics/counters only, not canonical fields)
- `schema_errors` (array of schema error objects)

## Invariants

- Canonical schema fields must be top-level and must not be duplicated inside `meta`.
- `total_tokens_reported = prompt_tokens_reported + completion_tokens_reported`.
- `usage_source="provider"` only when all included usage is provider-reported.
- `usage_source="estimate"` when any estimate component exists.
- `usage_source="zero_fallback"` when zero fallback is used and no estimate component exists.
- `usage_is_estimate=true` whenever any estimated or zero-fallback component exists.
- `invocations_query` is the canonical reconciliation pointer in v1.

## Starter `schema_errors[].code` Set

- `missing_required_key`
- `type_mismatch`
- `enum_mismatch`
- `token_total_mismatch`
- `timestamp_order_violation`
- `duration_mismatch`
- `counts_invariant_violation`
- `invocation_reconciliation_mismatch`
- `usage_provenance_missing`
