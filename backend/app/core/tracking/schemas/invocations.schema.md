# Invocation Event Schema (`invocations.jsonl`)

This document defines the canonical event schema for tracking invocation lifecycle records.

## Event Types

- `start_invocation`
- `end_invocation`

## Validation Behavior

- Validation is best effort.
- Records are always written when possible.
- Validation issues are recorded in `schema_errors`.
- `schema_errors` entries use structured objects:
  - `code` (string)
  - `field` (string)
  - `expected` (json value)
  - `actual` (json value)
  - optional: `message` (string)
  - optional: `details` (object)

## `start_invocation`

Required fields:

- `ts` (string, UTC ISO timestamp)
- `event` (`"start_invocation"`)
- `invocation_id` (string)
- `turn_id` (int or null)
- `purpose` (string)
- `model` (string, may be empty at start)
- `meta` (object; at least `{}`)

Optional fields:

- `run_id` (string)
- `schema_errors` (array of schema error objects)

## `end_invocation`

Required fields:

- `ts` (string, UTC ISO timestamp)
- `event` (`"end_invocation"`)
- `invocation_id` (string)
- `turn_id` (int or null)
- `purpose` (string)
- `model` (string)
- `prompt_tokens_reported` (int)
- `completion_tokens_reported` (int)
- `total_tokens_reported` (int)
- `usage_is_estimate` (bool)
- `usage_source` (`"provider"` | `"estimate"` | `"zero_fallback"`)
- `timing.ttlt_ms` (int)
- `timing.ttfb_ms` (int or null)
- `start_ts` (string, UTC ISO timestamp)
- `end_ts` (string, UTC ISO timestamp)
- `first_token_ts` (string or null)
- `meta` (object; at least `{}`)

Optional fields:

- `run_id` (string)
- `usage_estimate_method` (string or null)
- `schema_errors` (array of schema error objects)

## Invariants

- `purpose` is taken from invocation state established at start.
- `model` may be backfilled once at end when missing at start.
- Conflicting end model/purpose values are logged as schema errors.
- `usage_source="provider"` implies `usage_is_estimate=false`.
- `usage_source in {"estimate","zero_fallback"}` implies `usage_is_estimate=true`.
- `timing` is the canonical location for invocation latency fields.
- Top-level `ttfb_ms` and `ttlt_ms` are deprecated and are not emitted.
