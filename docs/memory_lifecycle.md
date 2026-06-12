# Memory Lifecycle

Syx treats memory as a lifecycle, not a single vector store. Information starts in active chat, rolls into Daily memory, is consolidated by Sleep, may be interpreted by Dream, and is finally indexed into long-term project retrieval.

This document describes the current operational flow. [`docs/DELTAS.md`](DELTAS.md) overrides older behavior in [`docs/REQUIREMENTS.md`](REQUIREMENTS.md), especially around markdown artifacts.

## Lifecycle Summary

```text
Chat messages
  |
  | active working memory + SQLite ChatMessage rows
  v
Daily memory
  |
  | daily.json + daily.md + in-memory Daily FAISS
  v
Sleep cycle
  |
  | sleep_summary.md -> uploads/sleep/sleep_{cycle_ts}.md
  v
Dream cycle
  |
  | dream.json / dream_summary.md -> uploads/dream/dream_{cycle_ts}.md
  v
Long-term RAG
  |
  | FAISS index + docstore + sidecar metadata
  v
Future chat and agent-memory retrieval
```

## Storage Roots

Runtime storage is project-scoped under the configured `MEMORY_ROOT`, normally:

```text
data/memory/{project_id}/
```

Common paths:

```text
data/memory/{project_id}/daily.json
data/memory/{project_id}/daily.md
data/memory/{project_id}/sleep_summary.md
data/memory/{project_id}/dream_summary.md
data/memory/{project_id}/dream.json
data/memory/{project_id}/open_questions.jsonl
data/memory/{project_id}/latest_sleep_summary.md
data/memory/{project_id}/uploads/
data/memory/{project_id}/uploads/sleep/
data/memory/{project_id}/uploads/dream/
data/memory/{project_id}/faiss/
data/memory/{project_id}/debug/
data/memory/{project_id}/state/
```

Generated memory, uploads, debug files, logs, and RAG artifacts may contain sensitive data. Treat them as local/private runtime state.

## Active Chat Memory

Active chat is persisted in SQLite as `ChatMessage` rows. The model is defined in `backend/app/core/db_models.py`.

Each message belongs to a project. Assistant messages may also carry:

- `forget` — skip Daily memory persistence.
- `keep` — user preference propagated into memory metadata.
- `namespace` — primary namespace captured during response generation.
- `tags_meta_json` — tagger metadata such as topics, intent, type, and semantic handle.
- `semantic_handle` — a short phrase naming the exchange.

`backend/app/core/memory.py` mirrors the active rows into per-project in-memory deques for prompt history. When the active pair limit is exceeded, the oldest complete user/assistant pair rolls off into Daily memory.

## Rolloff to Daily Memory

Daily rolloff happens in two main places:

- During normal chat pruning when active memory exceeds the configured pair limit.
- At the start of Sleep, when remaining active pairs are flushed into Daily memory.

During rolloff, Syx:

1. Finds a complete user/assistant pair.
2. Skips persistence if the assistant message has `forget=true`.
3. Reuses stored tagger metadata when available.
4. Prunes assistant text for memory when needed.
5. Builds a pair body:

   ```text
   User: ...
   Assistant: ...
   ```

6. Prepends tag lines to the embedded text when tag metadata exists:

   ```text
   #topics: ...
   #intent: ...
   #type: ...
   #semantic_handle: ...
   ```

7. Appends the entry to Daily memory.
8. Removes the source chat rows after successful append.

## Daily Memory Artifacts

Daily memory has three parts:

```text
daily.json = authoritative structured Daily metadata
daily.md   = human-readable and agent-readable mirror
Daily FAISS = rebuildable in-memory cache
```

`daily.json` is the structured source of truth for Daily entries. It records entry metadata, text, embedding text, token counts, memory ids, day sequence, scopes, tags, and related lifecycle fields.

`daily.md` is the readable artifact. It is intended for human inspection, git diffs, and future agent workflows. It is not the only source of truth.

The Daily FAISS cache is in memory. It is rebuilt from `daily.json` and is not persisted as a durable Daily index.

## Daily RAG

Daily RAG is the retrieval bridge for recent rolled-off memory that has not yet been merged into long-term memory.

`backend/app/rag/daily_store.py` owns:

- Daily metadata load/save.
- `daily.md` rendering.
- Daily cache rebuilds.
- Daily vector lookup.
- Daily adjacency lookup by `day_sequence`.

Daily cache behavior:

- Cold cache: schedule a background rebuild and return no Daily source for the current request.
- Model mismatch: schedule a background rebuild and return no Daily source for the current request.
- Warm cache: provide a ready vector source to canonical retrieval.

Normal retrieval can merge Daily results and long-term memory results so chat can use both recent rolled-off memory and older indexed artifacts.

## Markdown Artifact Rules

Per [`docs/DELTAS.md`](DELTAS.md), Syx now generates markdown memory artifacts for new Daily, Sleep, and Dream outputs.

Current rule:

```text
New Daily artifact: memory/{project}/daily.md
New Sleep artifact: memory/{project}/uploads/sleep/sleep_{cycle_ts}.md
New Dream artifact: memory/{project}/uploads/dream/dream_{cycle_ts}.md
```

The system does not provide a runtime switch back to `.txt`.

Existing `.txt` files already on disk do not require migration. RAG ingestion continues to support historical `.txt` artifacts where they exist, but newly generated Syx memory artifacts should use `.md`.

## Syx Memory Entry Boundaries

Markdown memory entries use stable source-neutral memory ids and explicit Syx boundaries:

```md
<!-- begin syx:memory_id=mem_YYYYMMDD_HHMMSS_abcd1234 -->
...
<!-- end syx:memory_id=mem_YYYYMMDD_HHMMSS_abcd1234 -->
```

Entries can carry structured metadata, including:

- `memory_id`
- `entry_type`
- `source`
- `source_agent`
- `source_scope`
- `current_scope`
- `timestamp`
- `route`
- `topics`
- `intent`
- `type`
- `semantic_handle`
- `day_sequence`
- `accepted_item_id`
- `dream_output_type`
- `origin_memory_ids`

RAG indexing parses these boundaries. A well-formed bounded entry can be indexed as its own expansion-safe document region, which lets the agent-memory interface return fuller memory entries instead of only chunk fragments.

## Uploaded Files and Long-Term RAG

User uploads and generated Sleep/Dream artifacts both live under a project's `uploads/` tree.

Current file upload behavior accepts `.txt` and `.md` files. The active upload path rejects unsupported file types. Older requirements mentioned PDFs, but the current code path treats PDFs as unsupported.

When files are uploaded or generated artifacts are merged, Syx rebuilds the project's long-term FAISS index from `uploads/`.

The rebuild pipeline in `backend/app/rag/manager_rebuild.py`:

1. Walks the project upload tree.
2. Reads supported `.txt` and `.md` files.
3. Parses bounded Syx memory entries when present.
4. Falls back to whole-file indexing for ordinary or legacy files.
5. Chunks text using configured chunk size and overlap.
6. Embeds chunks through the embedding provider factory.
7. Writes FAISS index files and sidecars under `faiss/`.
8. Updates file token/page stats in SQLite.

Long-term RAG sidecars include:

- FAISS index file.
- Row-to-id mapping.
- Docstore.
- Manifest.
- Adjacency index.

## Sleep Cycle

Sleep is the consolidation phase. It can be scheduled or manually triggered.

At a high level, Sleep:

1. Engages the global Sleep lock.
2. Flushes active chat pairs into Daily memory.
3. Backfills `daily.md` from `daily.json` if needed.
4. For each project with non-empty `daily.md`, writes `sleep_summary.md`.
5. Runs Dream and optional Dream auto-accept.
6. Writes per-cycle upload artifacts.
7. Rebuilds the long-term FAISS index.
8. Verifies the rebuilt index when enabled.
9. Cleans up consumed Daily and summary artifacts after a successful merge.
10. Releases the Sleep lock.

During Sleep, mutating API requests are blocked with HTTP 423. Read-only inspection remains available.

## Sleep Artifacts

Sleep reads:

```text
data/memory/{project_id}/daily.md
```

Sleep writes an intermediate summary:

```text
data/memory/{project_id}/sleep_summary.md
```

Then, during merge, Sleep writes a per-cycle upload artifact:

```text
data/memory/{project_id}/uploads/sleep/sleep_{cycle_ts}.md
```

After a successful FAISS rebuild and verification, Sleep removes consumed intermediate artifacts and clears Daily state:

- Removes `sleep_summary.md`.
- Removes `daily.json`.
- Removes `daily.md`.
- Clears the in-memory Daily cache.

The per-cycle `uploads/sleep/sleep_{cycle_ts}.md` artifact remains and becomes part of long-term RAG.

## Open Questions

Open questions are tracked separately from the human-readable Sleep artifact.

The project-level stream is:

```text
data/memory/{project_id}/open_questions.jsonl
```

Before Dream runs, Sleep consolidates this stream into deterministic question input for Dream. Dream consumes the consolidated question data rather than extracting questions from `sleep_summary.md`.

## Dream Cycle

Dream runs after Sleep creates `sleep_summary.md` and before the per-cycle merge/rebuild.

Dream can:

- Read consolidated open-question input.
- Build context from `sleep_summary.md`.
- Run Questions, Idea, and Research stages.
- Write local debug artifacts.
- Write `dream.json`.

Primary Dream output:

```text
data/memory/{project_id}/dream.json
```

`dream.json` contains pending Dream items for review or acceptance. The frontend can display this file through the Dream review UI.

## Dream Acceptance and Dream Memory

Dream items can be remembered manually through the UI or automatically during Sleep when `AUTO_ACCEPT_DREAMS=true`.

Accepted Dream items are converted into memory pairs and appended into Daily memory as Dream-originated entries. They can also be rendered into:

```text
data/memory/{project_id}/dream_summary.md
```

During the Sleep merge phase, `dream_summary.md` can be written into:

```text
data/memory/{project_id}/uploads/dream/dream_{cycle_ts}.md
```

After successful consolidation into the upload artifact and FAISS rebuild, `dream_summary.md` is removed. The per-cycle `uploads/dream/dream_{cycle_ts}.md` artifact remains and becomes part of long-term RAG.

## Long-Term Retrieval After Sleep

Once Sleep writes the per-cycle artifacts and rebuilds FAISS, the project's long-term index includes:

- User-uploaded `.txt`/`.md` files.
- Sleep artifacts under `uploads/sleep/`.
- Dream artifacts under `uploads/dream/`.
- Parsed bounded Syx entries from markdown artifacts.
- Legacy ordinary text/markdown files already present under uploads.

At that point, the memory has moved from Daily into long-term project retrieval. Future chat turns and agent-memory searches can retrieve it through the normal RAG pipeline.

## Retrieval Flow

At chat or agent-search time, Syx can retrieve from:

- Daily memory, if the in-memory Daily cache is warm and enabled for the project.
- Long-term memory, if the project FAISS index exists.

The retrieval pipeline:

1. Embeds the query.
2. Searches available Daily and long-term sources.
3. Orders candidates by similarity score.
4. Applies route policy thresholds and keep limits.
5. Expands adjacent chunks when policy allows.
6. Deduplicates and collapses snippet groups.
7. Returns prompt context for chat or structured snippets for the agent interface.

Normal chat then uses the retrieved context in prompt assembly. The agent-memory endpoint returns structured JSON snippets and does not generate an answer.

## Cleanup and Durability

Daily memory is intentionally transitional:

- `daily.json` is authoritative while memory is in Daily.
- `daily.md` is readable while memory is in Daily.
- Daily FAISS is rebuildable in-memory cache.
- After successful Sleep merge, Daily state is removed and the per-cycle upload artifact becomes the durable long-term artifact.

Long-term memory is durable through:

- Upload artifacts under `uploads/`.
- FAISS index files under `faiss/`.
- SQLite metadata for projects, files, and active chat.

If the FAISS index is missing or stale, it can be rebuilt from the upload artifacts.

## Configuration Touchpoints

Important lifecycle settings include:

- `MEMORY_ROOT`
- `DB_PATH`
- `CHAT_HISTORY_LIMIT_PAIRS`
- `RAG_ON_CHAT`
- `BASE_TOP_K`
- `RETRIEVAL_MULTIPLIER`
- `CHUNK_SIZE`
- `CHUNK_OVERLAP`
- `EMBEDDING_PROVIDER`
- `EMBEDDING_MODEL`
- `SENTENCE_TRANSFORMERS_MODEL_ID`
- `ENABLE_SCHEDULER`
- `SLEEP_CYCLE_HOUR`
- `SLEEP_CYCLE_MINUTE`
- `ENABLE_DREAM`
- `AUTO_ACCEPT_DREAMS`
- `GENERATE_DEBUG_FILES`

Runtime defaults live in `backend/app/core/config.py`. `.env.example` is the public environment template.

## Practical Mental Model

Think of Syx memory in layers:

- **Active chat** is what the user is doing now.
- **Daily memory** is recent rolled-off chat waiting for consolidation.
- **Sleep artifacts** are consolidated memory snapshots.
- **Dream artifacts** are generated insights and unresolved-question outputs.
- **Uploads** are the durable source set for long-term RAG.
- **FAISS** is the rebuilt retrieval index over that durable source set.

Daily memory is the staging area. Upload artifacts are the long-term record. FAISS is the searchable cache built from that record.
