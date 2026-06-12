# Sleep Cycle

The Sleep cycle is Syx's memory-consolidation maintenance phase. It moves active project chat into Daily memory, turns Daily memory into per-cycle long-term artifacts, runs Dream when enabled, rebuilds retrieval indexes, and clears consumed staging state.

For the broader memory flow, see `docs/memory_lifecycle.md`.

## What Sleep Is For

Sleep exists to keep long-running project memory usable over time.

During normal chat, Syx keeps a limited active working-memory window. Older user/assistant pairs roll into Daily memory. Sleep periodically takes that staged Daily memory, writes durable markdown artifacts, rebuilds long-term retrieval, and resets the Daily staging area for the next cycle.

## How Sleep Starts

Sleep can start in two ways:

- Manually, through `POST /sleep/start`.
- Automatically, through the scheduler initialized at backend startup when `ENABLE_SCHEDULER=true`.

The scheduler uses:

- `SLEEP_CYCLE_HOUR`
- `SLEEP_CYCLE_MINUTE`

The actual worker runs in a background daemon thread. If Sleep is already running, a new start request is rejected or skipped.

Useful endpoints:

```text
POST /sleep/start
GET  /sleep/status
POST /sleep/unlock
```

There are also older `/sleep_cycle/*` cleanup/status endpoints in the codebase. Those are legacy/stub cleanup surfaces and should not be confused with the active Sleep runner exposed by `/sleep/start`.

## Locking Behavior

Sleep uses an in-process state flag plus an on-disk lock file:

```text
runtime/state/sleep.lock
```

While Sleep is active:

- New mutating requests are blocked by FastAPI middleware with HTTP 423.
- GET requests remain available.
- `POST /sleep/unlock` remains available as a recovery path.
- `POST /agent/memory/search` remains available as a read-only/recovery path.

The lock is always released in the Sleep worker's `finally` block. Startup also restores lock state from disk and can clear stale locks before a scheduled run.

## High-Level Pipeline

The Sleep worker runs this sequence:

```text
engage lock
  |
  v
flush active chat pairs into Daily memory
  |
  v
backfill daily.md from daily.json if needed
  |
  v
for each project:
  consolidate open questions
  read daily.md
  write sleep_summary.md
  run Dream and optional auto-accept
  write per-cycle upload artifacts
  rebuild FAISS
  verify rebuild
  clean consumed staging files
  |
  v
release lock
```

Per-project failures are logged and downgrade the run to partial success where possible. A project failure should not prevent other projects from being processed.

## Active Pair Flush

At the beginning of Sleep, Syx flushes active chat pairs from SQLite `ChatMessage` rows into Daily memory for each project with Daily memory enabled.

For each ordered user/assistant pair:

1. If the assistant has `forget=true`, the pair is deleted without Daily append.
2. Otherwise, Syx prepares a memory payload.
3. Existing tagger metadata is reused when present.
4. Missing tagger metadata is generated.
5. Assistant text may be pruned before memory persistence.
6. The pair is appended to Daily memory.
7. Source chat rows are deleted after successful append.

Sleep also clears in-memory working caches so future requests reload fresh project state.

## Daily Backfill

Daily memory is represented by:

```text
daily.json = authoritative structured store
daily.md   = readable markdown mirror
Daily FAISS = rebuildable in-memory cache
```

Sleep backfills `daily.md` from `daily.json` when `daily.md` is missing and structured Daily entries exist. This preserves the current markdown artifact rule without requiring a legacy `.txt` file.

## Project Processing

For each project, Sleep looks for:

```text
data/memory/{project_id}/daily.md
```

If `daily.md` is missing or empty, the project is skipped and counted as `skipped_no_daily`.

If Daily memory exists, Sleep:

1. Normalizes the Daily artifact into a Sleep artifact shape.
2. Writes `sleep_summary.md`.
3. Runs Dream and optional auto-accept.
4. Writes per-cycle upload artifacts.
5. Rebuilds the long-term RAG index.

Current Sleep consolidation is deterministic. It does not call a Sleep summarization LLM.

## Generated Artifacts

Intermediate project artifacts:

```text
data/memory/{project_id}/sleep_summary.md
data/memory/{project_id}/dream_summary.md
```

Durable per-cycle upload artifacts:

```text
data/memory/{project_id}/uploads/sleep/sleep_{cycle_ts}.md
data/memory/{project_id}/uploads/dream/dream_{cycle_ts}.md
```

`sleep_summary.md` is written from `daily.md`. `dream_summary.md` is written when Dream items are accepted into memory.

The per-cycle files under `uploads/` are the artifacts that remain and become part of long-term RAG.

## Dream During Sleep

Dream runs after `sleep_summary.md` is written and before the per-cycle merge/RAG rebuild.

Sleep calls Dream for each processed project. Dream failures are logged but do not abort the whole Sleep cycle.

If `AUTO_ACCEPT_DREAMS=true`, Sleep also attempts to process pending `dream.json` items into Dream memory and `dream_summary.md`.

See `docs/dream_cycle.md` for Dream-specific details.

## Merge and FAISS Rebuild

After Sleep and Dream artifacts are prepared, Sleep writes the durable upload artifacts and rebuilds the project FAISS index once.

The merge phase:

1. Writes `uploads/sleep/sleep_{cycle_ts}.md` when Sleep text exists.
2. Writes `uploads/dream/dream_{cycle_ts}.md` when Dream summary text exists.
3. Rebuilds the project FAISS index from `uploads/`.
4. Optionally verifies that the rebuilt index can be loaded.
5. Cleans consumed staging artifacts on success.

The FAISS rebuild is performed after both Sleep and Dream upload artifacts are written, so the index only needs one rebuild per processed project.

## Cleanup and Reset

After a successful merge and verification, Sleep removes consumed staging state:

- `sleep_summary.md`
- `dream_summary.md` when it was consolidated into an upload artifact
- `daily.json`
- `daily.md`
- in-memory Daily cache

It does not remove the durable per-cycle artifacts under `uploads/sleep/` or `uploads/dream/`.

## Logs and Debug Output

Sleep emits logs with tags such as:

```text
[SLEEP]
[SLEEP][FLUSH]
[SLEEP][FORMAT]
[SLEEP][QUESTIONS]
[SLEEP][DREAM]
[SLEEP][MERGE]
[SLEEP][CLEANUP]
[VERIFY]
```

When debug files are enabled with `GENERATE_DEBUG_FILES=true`, Sleep and Dream stages may write debug artifacts under:

```text
data/memory/{project_id}/debug/
```

Debug artifacts may include prompt text, retrieved context, memory content, and model outputs. Do not commit them unless intentionally sanitized.

## Failure Handling

Sleep is designed to be best-effort across projects:

- A failed project generally marks the run partial and processing continues.
- A failed Daily append prevents deletion of that source pair.
- A failed Dream run is logged and does not abort Sleep.
- A failed FAISS rebuild prevents cleanup of consumed staging artifacts for that merge.
- The global Sleep lock is released even when the worker fails.

The run tracks internal status such as `success`, `partial`, or `failed`, along with error tags.

## How to Verify a Run

After starting Sleep, check:

```bash
curl http://127.0.0.1:8000/sleep/status
```

Expected while running:

```json
{
  "sleeping": true,
  "since": "...",
  "lock_path": "..."
}
```

Expected after completion:

```json
{
  "sleeping": false,
  "since": null,
  "lock_path": "..."
}
```

For a processed project, inspect:

```text
data/memory/{project_id}/uploads/sleep/
data/memory/{project_id}/uploads/dream/
data/memory/{project_id}/faiss/
data/memory/{project_id}/latest_sleep_summary.md
```

You should see a new `sleep_{cycle_ts}.md` artifact for projects with non-empty Daily memory. If Dream accepted items, you may also see a matching `dream_{cycle_ts}.md` artifact.

## Relevant Configuration

Sleep-related settings live in `backend/app/core/config.py` and can be set through `.env`:

- `ENABLE_SCHEDULER`
- `SLEEP_CYCLE_HOUR`
- `SLEEP_CYCLE_MINUTE`
- `VERIFY_RAG`
- `FORCE_RAG_REBUILD_ON_STARTUP`
- `CHAT_HISTORY_LIMIT_PAIRS`
- `ENABLE_DREAM`
- `AUTO_ACCEPT_DREAMS`
- `GENERATE_DEBUG_FILES`

The public environment template is `.env.example`.
