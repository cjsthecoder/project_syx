# Run Metadata Schema (`run.json`)

This document defines the canonical run-level metadata schema.

## Scope

- One `run.json` file per instrumentation run.
- Captures immutable startup configuration plus end-of-run summary metadata.

## Canonical Top-Level Fields

Required fields:

- `run_id` (string)
- `mode` (string)
- `started_at` (string, UTC ISO timestamp)
- `ended_at` (string or null, UTC ISO timestamp)
- `config_snapshot` (object)
- `models_observed` (object)
- `summary` (object)

Rules:

- `config_snapshot` is the only canonical startup configuration object.
- top-level duplicate startup aliases (for example `config`) must not be emitted.
- `config_snapshot` represents startup values only and must not be mutated mid-run.

## `config_snapshot` Required Sections

- `models_configured` (object)
- `prompt_budgeting` (object)
- `retrieval_static` (object)
- `route_policy` (object)
- `maintenance` (object)
- `instrumentation` (object)
- reproducibility metadata:
  - `git_commit` (string)
  - `git_dirty` (bool)

## `config_snapshot` Notes

- `models_observed` inside `config_snapshot` is optional helper metadata.
- runtime-observed models are canonically written at top-level `models_observed` when the run ends.
- `prompt_budgeting` should include:
  - `model_context_window_tokens`
  - `max_output_tokens_requested`
  - `max_output_tokens_effective`
  - `target_max_prompt_tokens`
  - `history_max_tokens`
  - `rag_max_tokens` (if enforced)
  - `profile_max_tokens` (if enforced)
  - `system_max_tokens` (if enforced)
  - `prompt_budgeting_known` (bool)
- if any key budget values are unknown, `prompt_budgeting_known=false` and unknown fields should be `null`.
- if no clamp is applied in runtime, `max_output_tokens_effective` should equal `max_output_tokens_requested`.

## `models_observed` (Top Level)

- Mapping of invocation purpose -> array of model ids seen during this run.
- Purpose keys remain purpose-native (for example `main`, `router`, `tagger`, `sleep`).
- Empty purpose buckets may be omitted.

## Lifecycle Semantics

- At run start:
  - `ended_at` is `null`
  - `models_observed` is empty
  - `summary` is empty object
- At run end:
  - `ended_at` is populated
  - `models_observed` is finalized from invocation records
  - `summary` is written from `end_run(summary=...)`

## Invariants

- `started_at` and `ended_at` are UTC ISO timestamps when present.
- if `git_dirty=true`, `git_commit` is still required (must not be nulled).
- `run_id` must match the containing run folder name.
