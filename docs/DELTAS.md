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
* Open-question candidate tracking is maintained in dedicated project artifact streams and is not required to be serialized in `daily.txt` pair headers.

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
* Any structured outputs emitted by tagging at ingest time (for example, question candidates) SHALL be derived from this same tagging input contract.

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
* Open-question candidate extraction/processing is handled outside retrieval candidate shaping; it is not a required `daily` candidate metadata field in this step.
* For `ltm` candidates, missing metadata fields are allowed and SHALL be left absent/null. No parsing from retrieved text is performed in this step.
* Auxiliary semantic artifact streams used by maintenance/dream workflows are out of scope for retrieval-stage shaping and MUST NOT be required inputs for A.4.1 candidate construction.

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
  * Open-question candidate fields are optional/out-of-band and are not required members of this retrieval metadata contract.

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

Accepted

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
* A route-derived retrieval policy (system-wide `route_policy.json`)
* Environment-level configuration values

---

### Selection Policy Parameters

Selection behavior is controlled by the following parameters:

* BASE_TOP_K
  Environment-level constant that defines the baseline retrieval size

* RETRIEVAL_MULTIPLIER
  Route-specific scalar applied to BASE_TOP_K

* MAX_KEEP
  Route-specific absolute cap on the number of candidates retained. This is the **initial** effective keep limit; it may be increased during selection when the adjacent-chunk rule applies (see Selection Process).

Derived value:

RETRIEVAL_K = ceil(BASE_TOP_K * RETRIEVAL_MULTIPLIER * N_SOURCES)

Where N_SOURCES reflects the number of retrieval sources attempted (queried), such as Daily and LTM.

Note: MAX_KEEP exists as a per-route policy input and is enforced by A.4.3 selection to bound retained candidates.

---

### Selection Process

1. Candidates are processed in the order produced by A.4.2, from highest to lowest similarity score.
2. An **effective keep limit** is maintained, initially equal to MAX_KEEP.
3. For each candidate in order:
   * If the number of candidates already retained is at least the effective keep limit, selection stops.
   * If the ordered candidate list is exhausted, selection stops.
   * Otherwise, append the candidate to the retained list.
   * **Adjacent-chunk rule:** If the candidate just retained is **directly adjacent** to the previously retained candidate (same `source_document_id`, and `chunk_index` differs by exactly 1), add 1 to the effective keep limit. This compensates for the fact that adjacent chunks from the same document are largely deduplicated in A.4.4.3, so retaining an extra slot when we see adjacency increases breadth (more distinct sources or regions) without unbounded growth.
4. Selection stops when either the retained count reaches the current effective limit or the list is exhausted.

No reordering, skipping, thresholding, boosting, or deduplication occurs during this step.

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
* If policy configuration is missing or invalid, the system MUST fail fast on startup (no per-request fallbacks).
* Selection failure does not block request execution.
* Unknown or new routes MUST fall back to OTHER (stable compatibility behavior).

---

### Invariants

* Selection is positional and deterministic.
* Higher-ranked candidates are always retained before lower-ranked candidates.
* The number of retained candidates is at least 0 and at most the length of the ordered list; it is at least MAX_KEEP when the list is long enough and no adjacent-chunk bonuses apply, and may exceed MAX_KEEP when the adjacent-chunk rule applies.
* Context size is bounded before prompt assembly (expansion and deduplication in A.4.4 further reduce effective size when many retained candidates are adjacent).
* Identical inputs and configuration produce identical outputs.

---

### Rationale

Without an explicit selection step, retrieval pipelines tend to rely on implicit truncation or prompt-length side effects, leading to unpredictable behavior and silent relevance loss.

A.4.3 makes context budgeting explicit and observable, enabling later rehydration and expansion in A.4.4 without destabilizing retrieval correctness.

---

### Implementation Notes

* Selection logic should be implemented as a standalone function or module.
* Instrumentation hooks are expected immediately before and after selection to record candidate counts and applied policy values.
* `route_policy.json` is loaded and validated once at startup and cached for process lifetime (reload on restart only).
* A.4.3 is intended to be completed before introducing any rehydration or adjacency expansion logic in A.4.4.

### DELTA-A.4.4 — Context Rehydration and Chunk Expansion

#### Status

Planned

#### Affected Requirements

* FR-007 — File Upload and RAG Initialization (chunk identity/metadata)
* FR-2.3.1.7 — Retrieval Order and Context Assembly

#### Intent

Rehydrate selected retrieval candidates into semantically complete context by expanding from matched chunks to adjacent chunks while preserving meaning across chunk boundaries.

This delta introduces controlled chunk expansion and context assembly rules that guarantee semantic completeness without introducing retrieval-stage intelligence or ambiguity.

A.4.4 explicitly separates:

* **Retrieval and selection** (A.4.1–A.4.3)
* **Context reconstruction** (A.4.4)

No relevance scoring, ranking, or pruning decisions are introduced in this delta.

---

### A.4.4.1 — Minimal Chunk Adjacency and Full-Chunk Retrieval

#### Status

Accepted

#### Intent

Implement the minimal functionality required to support safe context rehydration by:

1. Enabling deterministic lookup of neighboring chunks.
2. Ensuring that any retrieved chunk is always consumed in full, never as a partial slice.

This sub-delta intentionally does **not** address policy, expansion depth, token budgets, or optimization. Its purpose is to make later expansion *possible*, not *smart*.

---

#### Core Requirements

The system SHALL:

1. **Provide a stable chunk adjacency index**

   * The system MUST be able to determine, for any chunk:

     * The immediately previous chunk (if any)
     * The immediately next chunk (if any)
   * Adjacency is defined **only within the same source document** (no cross-file adjacency).
   * For PDFs, adjacency is defined **only within the same page** (no cross-page adjacency). Each `(filename, page_number)` is treated as its own source document for adjacency purposes.
   * This MAY be implemented as:

     * Sequence numbers
     * Linked identifiers (`prev_id` / `next_id`)
     * Absolute offsets
   * The canonical model is a per-document linear sequence:

     * `doc_id` identifies the source document (for PDFs: `(filename, page_number)`).
     * `chunk_seq` is a **monotonic, gap-free** integer sequence within a `doc_id`.
     * `prev` and `next` are resolved structurally as `chunk_seq - 1` / `chunk_seq + 1` within the same `doc_id`.
   * Adjacency resolution MUST be deterministic and order-preserving.

2. **Expose adjacency metadata at retrieval time**

   * Retrieved candidates MUST include sufficient metadata to allow lookup of neighboring chunks.
   * This metadata MUST be available without additional semantic inference.
   * At minimum, retrieved snippets MUST carry `doc_id` and `chunk_seq` (or equivalent fields sufficient to deterministically derive previous/next within the source document).

3. **Return full chunks, not match slices**

   * When a chunk is retrieved due to a similarity match, the system SHALL return the **entire chunk**.
   * Retrieval MUST NOT return text starting at the match offset or ending early.
   * Partial reads based on match position are prohibited.

4. **Allow assembly-time expansion to neighboring chunks**

   * Given a retrieved chunk and its adjacency metadata, the system MUST be able to fetch:

     * The previous chunk
     * The next chunk
   * Expansion MUST NOT cross a `doc_id` boundary (no cross-file expansion; for PDFs, no cross-page expansion).
   * Expansion is optional and deferred to later stages (A.4.4.2+).

5. **Preserve original chunk text verbatim**

   * Chunk text MUST be returned exactly as stored.
   * No rewriting, trimming, summarization, or deduplication occurs in A.4.4.1.

6. **Support structured snippet representation**

   * The system MAY reformat retrieved chunk content into a structured representation (for example, JSON) containing:

     * Chunk ID
     * Chunk text
     * Adjacency references
     * Source metadata
   * Formatting MUST NOT alter semantic content.

---

#### Explicit Non-Goals

A.4.4.1 MUST NOT:

* Decide how many neighboring chunks to include
* Remove overlap or deduplicate text
* Enforce token budgets
* Perform relevance scoring or reranking
* Perform semantic merging or summarization

---

#### New Invariants

* A retrieved chunk is always consumed as a whole.
* Match position within a chunk never affects returned text.
* Adjacency lookup is purely structural, not semantic.
* Any loss of adjacency metadata MUST result in less expansion, never partial context.

---

#### Rationale

Most boundary-related retrieval failures come from returning only the locally matched portion of a chunk, which discards setup and assumptions that precede the match.

By guaranteeing whole-chunk retrieval and deterministic adjacency lookup, A.4.4.1 establishes a safe foundation for later expansion and optimization without risking semantic loss.

---

#### Implementation Notes

* Chunk adjacency metadata SHOULD be stored alongside embeddings.
* Adjacency lookup SHOULD be O(1).
* Chunk text SHOULD be treated as immutable once written.
* Any structured (JSON) representation SHOULD be generated at retrieval or assembly time, not stored as canonical memory.
* Adjacency metadata MUST be rebuilt when any of the following change:

  * uploads added/removed/modified for a project
  * `chunk_size` or `chunk_overlap`
  * adjacency metadata is missing or corrupt **for an index that claims A.4.4.1+ compliance**
* `embedding_model` changes do **not** invalidate adjacency (though embeddings/vectors may still require rebuild for retrieval correctness).
* Legacy compatibility:

  * Indexes that are explicitly marked as **legacy** may omit adjacency fields; absence is treated as expected and MUST NOT auto-trigger rebuild.
  * If an index is marked A.4.4.1+ and adjacency is missing/invalid at query time, the system MUST degrade to full-chunk-only retrieval for that request and trigger a background rebuild (no in-request retry/blocking).

---

#### Completion Criteria

A.4.4.1 is complete when:

* Any retrieved chunk is returned in full.
* Neighboring chunks can be deterministically identified.
* Retrieved snippets include sufficient metadata to enable later expansion.
* No semantic content is dropped due to match offsets or chunk boundaries.


#### A.4.4.2 — Rank-Weighted Adjacency Expansion

##### Status

Accepted

##### Intent

Determine which adjacent chunks should be requested for each retained retrieval candidate by applying a deterministic, rank-weighted expansion policy. This stage expresses **expansion intent only** and does not assemble text, deduplicate content, or enforce token budgets.

A.4.4.2 consumes the ordered, pruned candidate list produced by A.4.3 (i.e. `kept_candidates`) and emits an ordered list of requested chunk identifiers, with per-candidate identifiers generated in **before…central…after** order. Identifiers may repeat across candidates; consolidation and deduplication occur in later stages.

Implementations MAY materialize the requested identifiers immediately into a single expanded string per candidate, as long as:

* no relevance scoring/reranking is introduced
* no deduplication occurs (A.4.4.3)
* no token-budget enforcement occurs (A.4.4.4)

##### Scope

This sub-delta applies only to adjacency expansion decisions within a single source document. Retrieval, scoring, ranking, selection, deduplication, and trimming behavior are unchanged.

##### Inputs

* Ordered list of retained retrieval candidates from A.4.3
* Per-candidate metadata including:

  * `source_document_id`
  * `chunk_index` (0-based within the document)
* Route-derived expansion parameters

This stage applies to both `ltm` and `daily` candidates. For `daily`, the document boundary is the synthetic `source_document_id = "daily"` stream and `chunk_index` corresponds to `day_sequence`.

##### Expansion Parameters (Route Policy)

Each route defines maximum adjacency depth via:

```json
"expansion": {
  "max_before": <int>,
  "max_after": <int>
}
```

These values represent upper bounds for the highest-ranked candidate. Lower-ranked candidates receive proportionally reduced expansion.

##### Expansion Algorithm

Given an ordered candidate list of size `K`, candidates are partitioned into three rank tiers:

* **Tier 1 (top third)**: ranks `i < ceil(K / 3)`
* **Tier 2 (middle third)**: `ceil(K / 3) ≤ i < ceil(2K / 3)`
* **Tier 3 (bottom third)**: `i ≥ ceil(2K / 3)`

`K` MUST be the actual runtime length of the retained candidate list (i.e. `K = len(kept_candidates)`), and tiering is computed over that list.

For each retained candidate, requested adjacency counts are computed based on its tier:

* **Tier 1**:

  * `before_count = max_before`
  * `after_count  = max_after`

* **Tier 2**:

  * `before_count = ceil(max_before / 2)`
  * `after_count  = ceil(max_after / 2)`

* **Tier 3**:

  * `before_count = min(1, max_before)`
  * `after_count  = min(1, max_after)`

Requested chunk identifiers are then generated:

* Central chunk: `(source_document_id, chunk_index)`
* Preceding chunks: `(source_document_id, chunk_index - n)` for `n` in `1..before_count`
* Following chunks: `(source_document_id, chunk_index + n)` for `n` in `1..after_count`

Any out-of-range indices are skipped. Expansion does not cross document boundaries.

##### Output

The output of A.4.4.2 is an ordered list of requested chunk identifiers, expressed as:

* `(source_document_id, chunk_index)`

For each candidate, identifiers MUST be generated in **before…central…after** order. Identifiers may appear multiple times across candidates; consolidation and deduplication occur in later stages.

##### Invariants

* Higher-ranked candidates always request equal or greater adjacency than lower-ranked candidates.
* Expansion intent is deterministic for identical inputs and configuration.
* Absence of adjacency metadata results in fewer requested chunks, never partial content.

Behavior on missing/invalid adjacency:

* If adjacency is unavailable for a given candidate, A.4.4.2 MUST degrade to requesting the central chunk only (no neighbors).
* For LTM indexes that claim A.4.4.1+ compliance, missing/corrupt adjacency metadata SHOULD trigger a best-effort background rebuild (no in-request blocking/retry).
* For legacy indexes (pre-A.4.4.1), absence is expected; expansion is treated as disabled (central-only) and MUST NOT auto-trigger rebuild.
* If a requested neighbor cannot be fetched/materialized, it is a non-fatal skip-neighbor event.
* If the daily cache is cold/unavailable, skip daily neighbors for that request (no rebuild trigger).

---

##### Route Policy Extension (A.4.4.2)

Each route in `route_policy.json` SHALL define maximum adjacency values used by A.4.4.2:

```
"expansion": {
  "max_before": <int>,
  "max_after": <int>
}
```

Example defaults:

* DIRECT: `{ "max_before": 0, "max_after": 2 }`
* PROCEDURAL: `{ "max_before": 1, "max_after": 3 }`
* EXPLORATORY: `{ "max_before": 1, "max_after": 4 }`
* SYNTHESIS: `{ "max_before": 2, "max_after": 5 }`
* OTHER: `{ "max_before": 1, "max_after": 2 }`

CHITCHAT MUST omit expansion entirely by virtue of `retrieval_multiplier = 0`.

These values express intent only; actual materialization is subject to later deduplication and token-budget enforcement.

Route policy validation: routes MUST include `expansion.max_before` and `expansion.max_after` (validated at startup alongside existing route policy fields).

#### Status

Accepted

#### Affected Requirements

* FR-2.3.1.7 — Retrieval Order and Context Assembly

#### Intent

Rehydrate selected retrieval candidates into semantically complete context by expanding from matched chunks to adjacent chunks while preserving meaning across chunk boundaries.

This delta introduces controlled chunk expansion and context assembly rules that guarantee semantic completeness without introducing retrieval-stage intelligence or ambiguity.

A.4.4 explicitly separates:

* **Retrieval and selection** (A.4.1–A.4.3)
* **Context reconstruction** (A.4.4)

No relevance scoring, ranking, or pruning decisions are introduced in this delta.


#### A.4.4.3 — Structural Deduplication and Assembly (Staged)

##### Intent

Collapse redundant context produced by adjacency expansion into a single, coherent, non-repeating sequence of chunks while preserving all semantic content and narrative order.

A.4.4.3 is explicitly staged to reduce risk and to keep each transformation easy to reason about and debug.

---

##### A.4.4.3.1 — Structured Expansion Materialization (First Pass)

###### Goal

Establish a canonical, chunk-structured handoff artifact between adjacency expansion and deduplication so downstream stages operate on explicit chunk identities rather than flattened text blobs.

This step is a structural normalization pass only. It does not deduplicate, reorder across candidates, trim text, or enforce token budgets.

###### Inputs

* Ordered list of retained candidates (`kept_candidates`) from A.4.3
* Per-candidate expansion intent from A.4.4.2
* Source-owned adjacency lookup/materialization mechanisms

###### Procedure

1. Iterate retained candidates in the same order as `kept_candidates`.
2. For each candidate, materialize an ordered list of chunk objects in **before…central…after** order (consistent with A.4.4.2).
3. Emit each chunk object using canonical fields:

   * `source_document_id`
   * `chunk_index`
   * `text`
4. Preserve candidate-level ordering and per-candidate chunk ordering exactly as materialized.
5. Do not deduplicate repeated chunk identities in this step.
6. Do not modify chunk text.

###### Error and Degrade Behavior

* If adjacency is unavailable for a candidate, emit central chunk only (no neighbors), consistent with A.4.4.2.
* Missing neighbors are non-fatal skip-neighbor events.
* Rebuild/repair remains source-owned; this step does not introduce in-request retries.

###### Output

* A list of expanded results, one per retained candidate, where each expanded result contains an ordered list of chunk objects with:

  * `source_document_id`
  * `chunk_index`
  * `text`
* Candidate order matches `kept_candidates`.
* No deduplication has been applied yet.

###### Invariants

* Expansion output is structured and identity-addressable.
* Per-candidate chunk order is deterministic and preserved.
* No chunk text is altered.
* No chunk identity is dropped by this stage except through existing A.4.4.2 degrade/skip-neighbor behavior.

###### Rationale

A.4.4.2 may be implemented as immediate text materialization, but A.4.4.3 requires identity-level operations. This pass creates a stable, explicit data contract so chunk-identity deduplication can be implemented deterministically and debugged safely.

##### A.4.4.3.2 — Chunk Identity Deduplication (Second Pass)

###### Goal

Eliminate duplicate chunks arising from overlapping expansions across multiple retained candidates. This step operates strictly at the **chunk identity level** and makes no modifications to chunk text.

The output of this step guarantees that each `(source_document_id, chunk_index)` pair appears at most once in the working set.

###### Inputs

* List of expanded results produced by iterating over `kept_candidates`
* Each expanded result contains an ordered list of chunks with:

  * `source_document_id`
  * `chunk_index`
  * `text`

###### Procedure

1. Initialize an empty ordered mapping:

   * Key: `(source_document_id, chunk_index)`
   * Value: chunk object

2. Iterate expanded results **in the same order as `kept_candidates`**.

3. For each chunk encountered:

   * If the key is not present in the mapping, insert it.
   * If the key is already present, skip the chunk.

4. Do not merge, trim, or modify chunk text.

First-seen chunks win by construction, preserving relevance priority without requiring score comparisons.

###### Output

* A collection of unique chunks keyed by `(source_document_id, chunk_index)`
* Chunk text remains unmodified
* Ordering across documents is not yet enforced

###### Invariants

* No chunk identity appears more than once
* No chunk text is altered
* No overlap trimming occurs
* No token counting or budgeting occurs

###### Rationale

This step removes the largest source of redundancy introduced by adjacency expansion while remaining completely lossless and reversible. It intentionally avoids narrative concerns, which are addressed in later stages.

##### A.4.4.3.3 — Source-Document Ordering and Narrative Coherence (Third Pass)

###### Goal

Organize the unique chunk set from A.4.4.3.2 into a structured, ordered result where each source document forms an independent timeline and chunks within a source are in narrative order. The output remains chunk-based and identity-addressable while becoming narratively coherent.

###### Inputs

* Collection of unique chunks from A.4.4.3.2 (keyed by `(source_document_id, chunk_index)`; chunk text unmodified)
* No cross-document ordering is defined by A.4.4.3.2; this pass introduces it.

###### Procedure

1. **Extract the set of source documents**

   * From the unique chunk collection, determine the distinct set of `source_document_id` values.
   * Chunks with missing or null `source_document_id` (sparse/legacy) are handled per compatibility policy (e.g., grouped under a synthetic source or appended in first-seen order).

2. **Treat each source_document_id as an independent timeline**

   * Each source document has its own linear sequence of chunks, ordered by `chunk_index` within that source only.
   * No ordering constraint is imposed between different source documents; implementation may use a deterministic rule (e.g., first-seen source, alphabetical, or stable sort by source_document_id).

3. **For each source**

   * Collect all chunks belonging to that source.
   * Sort them by `chunk_index` ascending.
   * Emit them in that order as a contiguous segment of the result.

4. **Emit a structured, ordered result**

   * The result is an ordered sequence of chunks (or of per-source ordered segments).
   * Chunk shape is unchanged: each item remains identity-addressable (`source_document_id`, `chunk_index`, `text`) and no chunk text is merged, trimmed, or altered.

###### Output

* A structured, ordered list of chunks (or equivalent representation, e.g., ordered segments per source).
* Within each source, chunks are in ascending `chunk_index` order (narratively coherent within document).
* Across sources, order is deterministic and implementation-defined.
* Output remains chunk-based and identity-addressable; no token budgeting or trimming in this step.

###### Invariants

* Every unique chunk from A.4.4.3.2 appears exactly once in the output.
* Within a given `source_document_id`, chunks are sorted by `chunk_index` ascending.
* No chunk text is altered.
* No token counting or budgeting occurs in this step.

###### Rationale

A.4.4.3.2 produces a flat unique set with no document-level ordering. This pass adds narrative coherence within each source timeline so that downstream prompt assembly or formatting receives chunks in document order, improving readability and semantic continuity without changing the chunk identity contract.

##### A.4.4.3.4 — Adjacent Chunk Overlap Trimming (Fourth Pass)

###### Goal

Remove redundant overlap text at boundaries between adjacent chunks within the same document. This is the first stage that modifies chunk text; it is safe because order, uniqueness, and adjacency are already established. Overlap is provably redundant and may be trimmed without removing meaning.

###### Inputs

* Ordered, unique, chunk-structured list from A.4.4.3.3 (narratively coherent within each source)
* Configuration: `chunk_overlap` (and optionally `chunk_size`) as used by the encoder/splitter when the index was built

###### Scope

* Operates **only within a document**: consider only consecutive pairs of chunks that share the same `source_document_id`.
* Operates **only on adjacent chunks**: for each such pair (A, B), at most the **prefix of B** is trimmed (the suffix of A is kept; the duplicate prefix of B is removed).
* Chunk identity and order are **never** changed.
* Only **exact duplicate** text at the boundary is removed; no fuzzy or semantic trimming.

###### Procedure

1. Walk the ordered chunk list in sequence.
2. For each consecutive pair (A, B) where `source_document_id` of A equals that of B (and both are valid):
   * Let `max_overlap = min(chunk_overlap, len(A.text), len(B.text))` (cap using config and chunk lengths).
   * Find the **longest** length `k` in `1 .. max_overlap` such that `A.text[-k:] == B.text[:k]` (exact string match).
   * If `k > 0`: set `B.text = B.text[k:]`. If `k == len(B.text)` (B would become empty), do not trim (leave B unchanged or use a minimal placeholder per implementation policy).
3. Chunks with missing or invalid `source_document_id` (sparse/legacy) are skipped for adjacency: do not trim them based on neighbors; do not use them to trim a neighbor.
4. Single-chunk documents and the last chunk in a document require no trim (no following same-doc chunk).

###### Output

* Same list of chunks, same order, same identities.
* Zero or more chunks have had their `text` field shortened by removal of a duplicate prefix (the overlapping suffix of the previous chunk).
* No chunk is reduced to empty by this step.

###### Invariants

* Chunk identity (`source_document_id`, `chunk_index`) and list order are unchanged.
* Only exact duplicate boundary text is removed; no non-redundant content is removed.
* Trimming is deterministic for identical inputs and configuration.
* No token counting or budgeting occurs in this step.

###### Edge Handling

* **End of file / last chunk**: No following chunk; nothing to trim. When the last chunk is B, overlap may be shorter than `chunk_overlap`; the longest exact match within the cap is used.
* **Chunk shorter than overlap**: Cap `max_overlap` by `min(chunk_overlap, len(A), len(B))` so short chunks are handled correctly.
* **No match**: If no exact suffix-of-A equals prefix-of-B in the window, trim length is 0; leave B unchanged.
* **Overlap smaller than configured**: Splitter may use sentence or paragraph boundaries; longest exact match within the cap yields the true boundary.

###### Rationale

Chunking with overlap produces redundant text at boundaries. Once order and adjacency are known, that redundancy is safe to remove: it reduces token usage and avoids double-weighting the same phrase. Using `chunk_overlap` as a cap and detecting the actual overlap by exact match keeps behavior correct for end-of-file, short chunks, and variable splitter boundaries.

##### A.4.4.3.5 — Snippet-Group Collapse (Fifth Pass)

###### Goal

Collapse the ordered, trimmed chunk list from A.4.4.3.4 into a list of **snippet groups**: consecutive chunks from the same document (same `source_document_id` and same `source`) become a single entry with concatenated text. Downstream prompt assembly and debug dumps then see one entry per adjacent set, so one "Snippet N" header and one separator per group instead of per chunk.

###### Inputs

* Ordered, unique, chunk list from A.4.4.3.4 (each item: `source`, `score`, `text`, `metadata` with `source_document_id`, `chunk_index`; overlap already trimmed).

###### Procedure

1. Walk the chunk list in order.
2. **Group** consecutive chunks that share the same `(source_document_id, source)`:
   * Chunks with missing or invalid `source_document_id` (sparse/legacy) do not merge with neighbors; each forms its own single-chunk group.
   * Different `source` (e.g. ltm vs daily) never merge.
3. **For each group**, produce one entry:
   * `source`, `score`: from the first chunk in the group (all chunks in an expanded set share the same score).
   * `text`: concatenation of all chunk texts in the group (single newline `\n` between chunks; no extra spacing).
   * `metadata`: from the first chunk in the group; may include a display-friendly range for `chunk_index` when the group has more than one chunk (e.g. `"199..201"` or equivalent) so debug and logs show the span.
4. **Output** is the list of these group entries; this list replaces the per-chunk list as the value of `kept_candidates` (or equivalent) for all downstream consumers (prompt formatting, debug file dumps).

###### Output

* A list of snippet-group entries (one per adjacent same-document run).
* Each entry has the same shape as a single chunk (`source`, `score`, `text`, `metadata`) but `text` is the concatenated content of the group.
* Prompt assembly emits one "Snippet N" and one separator per entry; token counting uses the concatenated text once per group.

###### Invariants

* No chunk content is dropped; concatenation preserves order within each group.
* Group boundaries are determined only by consecutive same `(source_document_id, source)`; no token budgeting or trimming in this step.
* Deterministic for identical input order and grouping rules.

###### Edge Handling

* **Single-chunk document or run**: Group has one chunk; output entry is that chunk with unchanged text.
* **Sparse/legacy chunk**: Forms a one-chunk group; does not merge with preceding or following chunk even if same file (per 4.4.3.4 policy).

###### Rationale

Expanded retrieval produces multiple adjacent chunks per hit; showing a separate "Snippet N" header for each chunk duplicates the same label and adds visual noise. Collapsing at this stage keeps a single contract: one kept_candidates entry per logical snippet (one per adjacent set from a file), so prompt and debug both treat "one big concatenated chunk" per group without special-case formatting logic later.


### DELTA-A.5 — Promptless Sleep Semantic Consolidation

#### Status

Planned

#### Affected Requirements

* FR-3.x Sleep-cycle pruning/formatting prompt flow
* FR-4.1.x Open Questions extraction and Dream question handoff
* FR-2.3.x Daily/LTM operational merge and maintenance lifecycle

#### Intent

Reduce maintenance-token overhead by removing LLM prompt-heavy sleep summarization/pruning/formatting steps while preserving the sleep lifecycle orchestration (flush, deterministic consolidation, merge/rebuild, verification, cleanup).

Keep semantic extraction close to turn-time tagging and move open-question handoff to append-only project artifacts consumed by Dream.

#### A.5.1 — Minimal Migration Shape (Safe)

##### A.5.1.1 — Tagger Enrichment at Pair Time

The tagger output contract SHALL be extended to include:

* Question candidates extracted from the current pair (and optional short anchor context).

These additions are pair-local signals and MUST NOT require full-memory/global resolution in the tagger step.

Tagger SHALL keep existing fields and add questions in the same JSON object (single response contract).

Canonical output contract (extension):

```json
{
  "topics": "",
  "intent": "",
  "type": "",
  "semantic_handle": "",
  "questions": [
    {
      "question": "<exact or naturally rewritten question>",
      "topic": "<topic title where the question originated>",
      "resolution": "<ignore | answer_local | answer_remote>"
    }
  ]
}
```

Contract notes:

* `questions` MAY be empty (`[]`) when no question candidates are present.
* `resolution` values are candidate hints at tag-time; final open/answered resolution remains a deterministic cross-turn consolidation step in sleep/dream.

##### A.5.1.4 — Research-First Dream Narrowing

Dream generation is narrowed to question/research usefulness:

* `remind_user` is removed from the active Dream question pipeline contract.
* Idea Agent output should prioritize open questions where additional information helps user decisions.
* Remote-backed questions (`answer_remote`) must flow through to research output deterministically.
* Dream debug artifacts should be written as human-readable `.txt` files with labeled input/decision/output sections.

##### A.5.1.2 — Per-Project Append-Only Semantic Artifacts

The system SHALL write project-scoped append-only artifacts at tag/ingest time:

* `open_questions.jsonl` (required): canonical input stream for the Dream question pipeline.

Each record SHOULD include stable provenance fields (for example project id, timestamp, source pair/message identifiers, topic/route metadata) so downstream consolidation is deterministic and auditable.

##### A.5.1.3 — Sleep Uses Artifacts + Deterministic Consolidation

During sleep, the system SHALL:

1. Read the project artifact stream (`open_questions.jsonl`).
2. Perform deterministic consolidation and status resolution (no LLM prompt for this stage).
3. Continue existing maintenance operations unchanged:
   * merge/upload artifacts
   * FAISS rebuild/verification
   * cleanup/reset lifecycle behaviors

