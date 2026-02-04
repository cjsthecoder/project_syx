# Engineering Deltas

## DELTA-A — Unified Daily and LTM Retrieval Pipeline

### Intent

Unify Daily and LTM retrieval behavior so both memory tiers use the same retrieval, scoring, and selection logic, differing only by configuration. This delta represents an architectural convergence goal and is implemented incrementally via the sub-deltas below.

### DELTA-A.1 — Daily FAISS Converted to In-Memory Cache

#### Status

Implemented

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
* `daily.txt` continues to be written/used for the sleep pipeline; it may include tag metadata lines for rolled-off pairs.

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

Removed

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


### DELTA-A.3 — Previous Rolled-Off Pair Tracking and Tagging Context

#### Status

Implemented

#### Affected Requirements

* FR-3.4.2 — Tagging Prompt

#### Intent

Provide a stable, best-effort semantic context snippet for tagging by tracking the most recent prior rolled-off pair and supplying it to the tagging prompt.

#### State

* The system SHALL maintain an in-memory, per-project value `last_rolled_off_pair`.
* `last_rolled_off_pair` represents the most recent rolled-off pair with `forget=false`.
* This state is ephemeral and MUST NOT be persisted as a first-class memory object.

#### Roll-Off Processing Rules

For each rolled-off pair, the system SHALL resolve `previous_pair_text` using the following precedence:

1. The in-memory `last_rolled_off_pair`, if present for the project.
2. A best-effort fallback loaded from the most recent non-forgotten entry in `daily.json` for the project, using the canonical stored pair text (not embedding-augmented text).
3. `None` if neither source is available.

#### Forget Handling

* If the rolled-off pair has `forget=true`, the system SHALL:

  * NOT write the pair to daily memory.
  * NOT update `last_rolled_off_pair`.
  * Preserve the existing `last_rolled_off_pair` value for future roll-offs.

#### Tagging Input

* The system SHALL prepend `previous_pair_text` to the tagging prompt input before the current rolled-off pair when `previous_pair_text` is available.
* If `previous_pair_text` is unavailable, the system SHALL emit a debug log and tagging SHALL proceed with the current rolled-off pair alone (best-effort).

Anchors influence tagging input only and MUST NOT alter the stored text written to daily memory.

#### Update Rule

* `last_rolled_off_pair` SHALL be updated only when the rolled-off pair is actually persisted to daily memory (i.e., daily history is enabled for the project and the append operation reports success).
* The human-readable `daily.txt` write is best-effort and SHALL NOT gate updating `last_rolled_off_pair` if the daily-memory append otherwise succeeds.
* After processing a rolled-off pair with `forget=false` and successful daily persistence, the system SHALL set:

  * `last_rolled_off_pair = current_pair_text`
* `current_pair_text` SHALL be the canonical rolled-off pair text as used for daily memory storage (user + assistant, unmodified).

#### Multiple Roll-Offs in a Single Prune

* If multiple pairs roll off sequentially during a single pruning operation, the above logic SHALL be applied in order.
* Each roll-off MAY reference the immediately preceding rolled-off pair processed in the same operation.

#### Reset / Invalidation

* `last_rolled_off_pair` SHALL be cleared for a project when:

  * Daily memory is explicitly reset for that project.
  * The sleep-cycle flush step clears active in-memory chat state for that project.
  * The project is deleted.

#### Restart Semantics

* On process restart, `last_rolled_off_pair` SHALL be empty.
* When required and missing, the system MAY hydrate `last_rolled_off_pair` from `daily.json` as a best-effort fallback.
* Absence of an anchor MUST NOT block roll-off processing or tagging.

#### New Invariants

* Anchors follow semantic roll-off order, not conversational order.
* Anchors are ephemeral and are never persisted as independent memory entries.
* Anchors are used exclusively to improve tagging quality.

### DELTA-A.4 — Unified RAG Retrieval Pipeline for Daily and LTM

#### Status

Planned

#### Affected Requirements

* FR-2.3-3 — Retrieval Flow
* FR-2.3.1.7 — Retrieval Order and Context Assembly
* FR-2.5.3 — Retrieval Logic Update

#### Intent

Unify Daily and LTM retrieval into a single canonical RAG query path so that both sources are queried, ranked, and selected using the same retrieval logic, differing only by source metadata and weighting.

This delta eliminates divergent retrieval behavior and enables consistent ranking, tuning, and telemetry across all memory sources.

---

### A.4.1 — Canonical Retrieval Entry Point

#### Status

Accepted

#### Intent

Introduce a single, canonical retrieval entry point that queries both Daily and LTM memories using identical logic and produces a unified set of ranked retrieval candidates.

This step establishes the foundation for shared ranking, thresholding, and telemetry in later sub-deltas.

#### State

* The system SHALL define a single retrieval function responsible for all RAG memory queries.
* This function SHALL accept:

  * A normalized query string.
  * A list of memory sources to query (at minimum: Daily and LTM).
  * A retrieval configuration object (source-level limits and future ranking/threshold parameters).
* The canonical retrieval function MUST compute the query embedding exactly once (using `settings.embedding_model`) and reuse the same query vector across all queried sources.
* Candidate retrieval MUST NOT be controlled by route configuration (e.g., `meta_namespaces.json`); route/policy inputs are deferred to later stages (A.4.3+).
* Retrieval-stage limits SHALL be controlled only by:
  * `BASE_TOP_K`
  * `RETRIEVAL_MULTIPLIER`
  with per-source query limit:
  * `PER_SOURCE_K = ceil(BASE_TOP_K * RETRIEVAL_MULTIPLIER)`

#### Retrieval Behavior

* The canonical retrieval function SHALL:

  * Query Daily and LTM memories using the same semantic search mechanism, driven by the shared query vector.
  * Normalize all retrieved results into a single, canonical candidate shape containing:

    * Source identifier (`daily` or `ltm`)
    * Retrieved text
    * Associated metadata (see “Canonical Candidate Shape” below)
    * Raw similarity score from the underlying vector search (cosine similarity in the range 0.0–1.0)
  * Apply no namespace boosts or route-based eligibility pruning at this stage.

* The function SHALL NOT:

  * Apply source-specific branching logic.
  * Apply ranking or thresholding decisions at this stage.
  * Apply fallback behavior when no candidates meet a similarity threshold (thresholding does not occur in this step).
  * Inject retrieved content directly into the model prompt.
  * Apply route-based `rag_k` or `score_threshold` values at retrieval time.

#### Source Semantics

* Daily and LTM memories SHALL be treated as equivalent retrieval sources at the API level.
* Differences between sources (recency, priority, trust) SHALL be expressed only through metadata and scoring adjustments in later steps.
* For the purposes of unified retrieval, `ltm` SHALL include all content embedded in the project’s main FAISS index, regardless of origin (uploads, sleep summaries, dream artifacts, or other long-lived memory sources).
* For `daily` candidates, canonical metadata SHALL be sourced authoritatively from `daily.json` (not inferred from embedded text). A stable daily entry identifier MUST exist for each daily vector so candidates can be deterministically joined to `daily.json`.
* If a `daily` candidate cannot be deterministically joined to `daily.json`, it SHALL still be returned (lossless recall). In that case:
  * `metadata.id` SHALL be null/absent
  * Daily-only fields (e.g., `tags_meta`, `topics`, `intent`, `type`, `keep`, `day_sequence`, `pair_ids`) SHALL be null/absent
  * `metadata.route` MAY be populated best-effort from the FAISS document metadata namespace if present; otherwise null/absent
* For `ltm` candidates, missing metadata fields are allowed and SHALL be left absent/null. No parsing from retrieved text is performed in this step.

#### Ordering Guarantees

* The canonical retrieval function SHALL preserve:

  * The original retrieval order returned by the underlying vector search for each source.
  * Source attribution for every retrieved candidate.

* A.4.1 does not define a cross-source ordering rule for the combined candidate set; deterministic ordering is defined by A.4.2.

#### Output Contract

* The function SHALL return a flat list of retrieval candidates with no filtering beyond source-level query execution limits (`PER_SOURCE_K` per queried source).
* An empty result set from one source SHALL NOT block retrieval from other sources.
* Failure to query one source SHALL degrade gracefully and SHALL NOT abort the overall retrieval operation.
* If query embedding fails, retrieval is unavailable for the request and the function SHALL return an empty candidate list.
* Rebuild/repair semantics are source-owned. On error querying a source or model mismatch for that source, the system SHALL:
  * Degrade gracefully and return an empty candidate set for that source for the current request (no automatic retry within the request)
  * Allow the owning source subsystem to trigger best-effort rebuild/repair asynchronously per its lifecycle rules

#### Canonical Candidate Shape

Every candidate MUST include the following uniform schema (missing fields are allowed and represented as null/absent):

* `source`: `daily` | `ltm`
* `text`: string
* `score`: float (raw cosine similarity in [0.0–1.0])
* `metadata`:
  * `id`: optional string
  * `timestamp`: optional string
  * `route`: optional string
  * `tags`: optional list
  * `topics`: optional list
  * `intent`: optional string
  * `type`: optional string
  * `tags_meta`: optional object
  * `keep`: optional boolean
  * `day_sequence`: optional integer
  * `pair_ids`: optional list

#### New Invariants

* All RAG retrieval passes through a single code path.
* Candidate shape is uniform across sources; enrichment is conditional.
* Retrieval consistency is guaranteed across memory tiers prior to ranking and selection.


### DELTA-A.4.2 — Deterministic Candidate Ordering by Similarity Score

#### Status

Accepted

#### Affected Requirements

* FR-2.3-3 — Retrieval Flow
* FR-2.3.1.4 — Metadata-Aware Reranking
* FR-2.3.1.5 — Query Expansion and Namespacing
* FR-2.3.1.7 — Retrieval Order and Context Assembly
* FR-2.5.3 — Retrieval Logic Update
* FR-2.5.4 — Namespace Boosting

#### Intent

Make retrieval relevance explicit and deterministic by ordering all retrieved RAG candidates by similarity score prior to any selection, truncation, or prompt assembly.

This step stabilizes behavior, removes accidental ordering bias, and prepares the pipeline for later pruning and token-budget decisions.

#### Scope

This requirement applies to **all RAG retrieval sources**, including:

* Daily memory retrieval
* Long-term memory (LTM) retrieval
* Any future memory sources introduced into the unified retrieval pipeline

#### Ordering Rule

* The system SHALL sort retrieved candidates in **descending order of similarity score** before context assembly.
* Ordering MUST be purely numeric and deterministic, using the canonical raw cosine similarity score (0.0–1.0) produced at the canonical retrieval boundary (no boosts/weights applied in A.4.2).
* Sorting uses full-precision floating point values (no rounding/normalization in A.4.2).
* No semantic inference, re-ranking, or model-based judgment is permitted at this stage.
* No candidates SHALL be dropped or filtered as part of A.4.2.

#### Note — Namespace Boosting Removed

Namespace-based score boosting has been removed. Importance is now expressed exclusively via route policy and selection logic.

This change supersedes REQUIREMENTS-era namespace routing/boosting requirements, including FR-2.5.4 and the meta-namespaces integration described in FR-2.5.3 and FR-2.3.1.5.

#### Tie Handling

* When two or more candidates have identical similarity scores, the system SHALL use a stable sort (preserve the original pre-sort candidate order; no additional tie-breaker is introduced in A.4.2).

#### Source Interaction

* A.4.2 does not define cross-source prioritization rules.
* A.4.2 supersedes A.4.1’s fixed per-source concatenation ordering by introducing a single global sort across all retrieved candidates (Daily and LTM may interleave purely by score).
* Daily vs. LTM preference, recency bias, or source weighting is explicitly deferred to later requirements (e.g., A.4.3).

#### Architectural Constraints

To prevent further entanglement of retrieval logic:

* Candidate retrieval, ordering, selection, and prompt assembly MUST be implemented as separate, single-responsibility stages.
* Ordering logic MUST be isolated in its own function or module.
* Retrieval-stage code MUST NOT:

  * Perform prompt formatting
  * Enforce token budgets
  * Apply selection or thresholding rules

Conversely:

* Prompt assembly code MUST NOT modify retrieval ordering or selection decisions.

#### Invariants

* Higher similarity score always implies earlier presentation to the model.
* Ordering behavior MUST be reproducible across identical inputs.
* The model MUST NOT be relied upon to infer relevance ordering from unsorted context.

#### Rationale

LLMs are position-sensitive. Presenting higher-relevance snippets earlier improves consistency, reduces anchoring errors, and makes future pruning behavior safe and explainable.

A.4.2 introduces no new intelligence; it encodes explicit policy for attention ordering.


## DELTA-A.4.3 — Policy-Driven Candidate Selection and Pruning

### Status

Planned

### Affected Requirements

* FR-2.3-3 — Retrieval Flow
* FR-2.3.1.4 — Metadata-Aware Reranking
* FR-2.3.1.7 — Retrieval Order and Context Assembly
* FR-2.5.3 — Retrieval Logic Update

---

### Intent

Apply deterministic, policy-driven pruning to the globally ordered retrieval candidate list produced by A.4.2 in order to bound context size and control downstream prompt assembly.

This delta introduces selection policy, not retrieval intelligence. It defines how many candidates are retained after ordering, without changing how candidates are retrieved or scored.

A.4.3 formalizes the separation between:

* Retrieval (A.4.1)
* Ordering (A.4.2)
* Selection (A.4.3)
* Rehydration and expansion (A.4.4)

---

### Scope

This delta applies only to the selection and truncation of retrieval candidates that have already been retrieved and globally ordered.

The logic in this step operates on list position and policy configuration only. It does not introduce semantic reasoning or content expansion.

---

### Inputs

A.4.3 consumes the following inputs:

* A globally ordered list of retrieval candidates from A.4.2
* A route-derived retrieval policy
* Environment-level configuration values

---

### Selection Policy Parameters

Selection behavior is controlled by the following parameters:

* BASE_TOP_K
  Environment-level constant that defines the baseline retrieval size

* RETRIEVAL_MULTIPLIER
  Route-specific scalar applied to BASE_TOP_K

* MAX_KEEP
  Route-specific absolute cap on the number of candidates retained

Derived value:

RETRIEVAL_K = ceil(BASE_TOP_K * RETRIEVAL_MULTIPLIER * N_SOURCES)

Where N_SOURCES reflects the number of retrieval sources queried, such as Daily and LTM.

Note: MAX_KEEP exists as a per-route policy input and is currently used for recording and telemetry. It defines the intended upper bound for retained candidates but does not alter retrieval behavior itself.

---

### Selection Process

1. Candidates are processed in the order produced by A.4.2, from highest to lowest similarity score.
2. Candidates are appended to the retained list sequentially.
3. Selection stops when either:

   * MAX_KEEP candidates have been retained, or
   * The ordered candidate list is exhausted.

No reordering, skipping, or conditional filtering occurs during this step.

---

### Source Handling

Candidates from different retrieval sources, such as Daily and LTM, are treated uniformly during selection.

Source attribution is preserved but does not influence selection order or retention count.

---

### Output

The output of A.4.3 is a truncated, ordered list of retrieval candidates.

Each retained candidate preserves:

* Original text
* Similarity score
* Source attribution
* Associated metadata

No new metadata is introduced during this step.

---

### Error and Edge Handling

* If the ordered candidate list is empty, the output is an empty list.
* If policy configuration is missing or invalid, default configuration values are applied and recorded via telemetry.
* Selection failure does not block request execution.

---

### Invariants

* Selection is positional and deterministic.
* Higher-ranked candidates are always retained before lower-ranked candidates.
* Context size is bounded before prompt assembly.
* Identical inputs and configuration produce identical outputs.

---

### Rationale

Without an explicit selection step, retrieval pipelines tend to rely on implicit truncation or prompt-length side effects, leading to unpredictable behavior and silent relevance loss.

A.4.3 makes context budgeting explicit and observable, enabling later rehydration and expansion in A.4.4 without destabilizing retrieval correctness.

---

### Implementation Notes

* Selection logic should be implemented as a standalone function or module.
* Instrumentation hooks are expected immediately before and after selection to record candidate counts and applied policy values.
* A.4.3 is intended to be completed before introducing any rehydration or adjacency expansion logic in A.4.4.

