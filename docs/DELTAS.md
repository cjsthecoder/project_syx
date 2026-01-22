# Engineering Deltas

## DELTA-A — Unified Daily and LTM Retrieval Pipeline

### Intent

Unify Daily and LTM retrieval behavior so both memory tiers use the same retrieval, scoring, and selection logic, differing only by configuration. This delta represents an architectural convergence goal and is implemented incrementally via the sub-deltas below.

### DELTA-A.1 — Daily FAISS Converted to In-Memory Cache

#### Status

Accepted

#### Affected Requirements

* FR-2.3.2 — Incremental Embedding → Daily FAISS
* FR-2.3-3 — Retrieval Flow
* FR-2.5.3 — Retrieval Logic Update

#### Change
 
Daily RAG FAISS indices are no longer treated as persistent state. The Daily FAISS index is an in-memory cache rebuilt from `daily.json` and maintained for the lifetime of the server process.

The `memory/{project}/daily_faiss/` directory is deprecated and must not be written going forward (no cleanup required for existing on-disk contents).

Per-append FAISS load/save behavior is removed.

The in-memory daily index should be **lazily warmed per project** on the first project-scoped request observed for that project after startup (i.e., “project selected” ≈ first request using `project_id`).

#### Rationale

Daily memory is ephemeral and bounded by the active day or sleep cycle. Persisting FAISS on every append caused unnecessary disk churn, introduced partial-write failure modes, and complicated correctness guarantees.

Treating FAISS as a rebuildable cache aligns Daily memory with episodic semantics and reduces divergence from LTM behavior, enabling later unification of retrieval pipelines.

#### New Invariants

* `daily.json` is the sole authoritative store for Daily memory.
* Daily FAISS indices may be discarded and rebuilt at any time without data loss.
* Loss or corruption of Daily FAISS data must never imply loss of memory.
* `daily.txt` behavior remains unchanged (it is still written/used exactly as it is today for the sleep pipeline).

#### Implementation Notes

* Maintain a single in-memory FAISS index per project during runtime.
* Continue using `daily.lock` to serialize writes to `daily.json` (no cross-worker coherency is required).
* Append new vectors only to the in-memory index, while also persisting metadata updates to `daily.json`.
* Rebuild the in-memory Daily FAISS index from `daily.json` when any of the following occurs:
  * The in-memory cache is not present yet for that project.
  * The runtime `EMBEDDING_MODEL` differs from the `embedding_model` recorded in `daily.json`.
  * An exception occurs during daily search/add operations.
  * The in-memory index appears corrupted or incompatible (e.g., dimension mismatch).
* On rebuild due to `EMBEDDING_MODEL` change:
  * Do not delete `daily.json`.
  * Re-embed from `daily.json` and update each entry’s `embedding_model` in `daily.json` to the new model.
* If a rebuild trigger occurs during an operation (retrieve/add), rebuild the cache but return empty/error for that request (do not automatically retry the operation).
* On sleep merge cleanup, clear the in-memory daily cache for the project being merged; other sleep cleanup behaviors remain unchanged.


### DELTA-A.2 — Roll-Off Ambiguity Detection and Anchor Resolution

#### Status

Draft

#### Affected Requirements

* FR-3.4.1 — Trigger
* FR-3.4.2 — Tagging Prompt

#### Change

Introduce an explicit ambiguity-detection step when a conversation pair rolls off the active context window.

Each rolled-off pair SHALL be evaluated to determine whether it is semantically self-contained or depends on prior conversational context for correct interpretation when retrieved later in isolation.

If the rolled-off pair is determined to be ambiguous, it SHALL be marked as requiring semantic anchoring for tagging. No anchor is attached at this stage.

#### Definition of Ambiguity

A rolled-off pair is considered *ambiguous* if important meaning depends on prior conversational context, even if the assistant response appears to answer the user question. Ambiguity includes unresolved references such as pronouns, ellipsis, or referential phrases (for example: "that", "this", "it", "why won’t it work").

Ambiguity detection is a semantic classification task and MUST NOT attempt to resolve, rewrite, or summarize content.

#### Anchor Selection Rules

No anchor selection or attachment occurs in this delta.

#### Processing Flow

1. A pair rolls off the active context window.
2. An ambiguity classifier evaluates the rolled-off pair.
3. If ambiguous:

   * Mark the pair as requiring semantic anchoring for tagging.
4. If not ambiguous:

   * Proceed using the rolled-off pair alone.
5. Pass the resolved semantic unit to the tagging pipeline.

#### Model and Configuration

* Ambiguity detection SHALL use the `gpt-5-nano` model by default.
* The ambiguity model MUST be configurable via environment variable.
* Configuration MUST follow the existing project pattern for model configuration, including:

  * Defining the environment variable in the Makefile (alongside other model variables)
  * Providing a default value and loader entry in `config.py`
* Do not introduce a new configuration mechanism; reuse the existing `.env` / Makefile / `config.py` pattern already used for builder and tagger models.

#### Prompt Management

* The ambiguity classifier prompt SHALL be defined directly in code, colocated with the ambiguity classifier implementation.
* Create a dedicated Python module (for example `backend/app/tagging/ambiguity.py`) that:

  * Defines the ambiguity-classifier prompt as a module-level constant
  * Formats inputs (user message and assistant message)
  * Executes the ambiguity classification call
  * Returns a boolean ambiguous/not-ambiguous result
* No external prompt file is required for ambiguity detection; prompt handling SHALL follow the same pattern used by existing tagging prompts.

#### Logging and Observability

* The ambiguity classifier MUST emit a debug-level log entry before returning its result.
* The log entry SHALL include both:

  * The resolved `AMBIGUOUS` boolean value
  * The accompanying `REASON` string produced by the classifier
* Logging MUST occur regardless of whether the result is ambiguous or not.
* Logging MUST NOT alter control flow or classifier output.

#### New Invariants

* Ambiguity detection occurs once per rolled-off pair within a single roll-off execution (best-effort; a crash/restart may cause re-run).
* Semantic resolution occurs before tagging and embedding.
* Daily memory entries MUST be semantically self-contained at retrieval time.
* The ambiguity classifier model and prompt MUST be externally configurable.

#### Implementation Notes

* The ambiguity classifier SHOULD bias toward false positives.
* The classifier output contract SHALL be strictly limited to a boolean result and a short reason string.
* On ambiguity-classifier timeout/error/invalid output, proceed with normal roll-off behavior and treat the result as `AMBIGUOUS=false`.
* No backfill/migration is required; ambiguity detection applies only to newly rolled-off pairs going forward.
* No regular-expression-only solution is sufficient for ambiguity detection.
