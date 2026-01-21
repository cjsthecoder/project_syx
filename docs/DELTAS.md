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
