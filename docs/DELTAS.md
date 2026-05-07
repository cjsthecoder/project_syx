# Engineering Deltas

# DELTA-A — Markdown-Based Syx Memory Artifacts

## Status

Draft

## Intent

Convert Syx durable memory artifacts from plain `.txt` files to markdown-compatible `.md` files while preserving structured metadata, existing retrieval behavior, and sleep-cycle consolidation semantics.

This delta establishes markdown as the durable human-readable and agent-readable artifact format for Syx memory.

## Background

Syx currently writes Daily memory to `daily.txt` as a human-readable mirror of `daily.json`, while `daily.json` remains the persistent metadata store and Daily FAISS is a rebuildable in-memory cache. The current sleep pipeline rolls Daily text artifacts into LTM-upload artifacts such as `sleep_*.txt`.

Markdown-based artifacts are a better fit for:

- external coding agents
- future MCP memory tools
- Obsidian-style workflows
- human review
- git diffing
- structured entry boundaries
- future entry-level expansion

Markdown is not the source of truth by itself. It is the readable artifact format. Syx metadata remains authoritative for identity, provenance, lifecycle state, and future expansion.

## Core Principle

Markdown is the carrier format.

Syx metadata defines identity, source, boundaries, provenance, and lifecycle.

## Non-Goals

This delta does not introduce:

- MCP integration
- external agent endpoints
- Cursor write-back
- user-curated notes
- maintained files such as `Decisions.md`
- database-backed memory records
- decay or strength scoring
- new retrieval ranking behavior
- direct LTM write APIs

Those belong in later deltas.

---

# DELTA-A.1 — Markdown Artifact Naming Cutover

## Status

Draft

## Intent

Change Syx durable memory artifacts from `.txt` files to `.md` files for all newly generated Daily, Sleep, and Dream memory artifacts.

This is a forward-only naming and artifact-format cutover. The system does not need to support switching back to `.txt` at runtime.

## Background

Syx currently maintains a plain-text Daily memory mirror at:

```text
memory/{project}/daily.txt
```

This file is generated from rolled-off chat pairs and used as deterministic input to the nightly sleep pipeline. `daily.json` remains the authoritative structured Daily memory store.

Syx also currently emits per-cycle Sleep and Dream artifacts as `.txt` files under project upload artifact folders. Existing `.txt` files already present on disk may remain in place and can continue to be ingested by RAG as normal files.

## Core Decision

Going forward, Syx SHALL generate markdown memory artifacts using `.md` filenames.

The system SHALL NOT provide a runtime configuration flag to switch newly generated memory artifacts back to `.txt`.

## Artifact Naming Changes

The system SHALL change newly generated artifact names as follows:

```text
memory/{project}/daily.txt
    -> memory/{project}/daily.md

memory/{project}/uploads/sleep/sleep_{cycle_ts}.txt
    -> memory/{project}/uploads/sleep/sleep_{cycle_ts}.md

memory/{project}/sleep_summary.txt
    -> memory/{project}/sleep_summary.md

memory/{project}/dream_summary.txt
    -> memory/{project}/dream_summary.md

memory/{project}/uploads/dream/dream_{cycle_ts}.txt
    -> memory/{project}/uploads/dream/dream_{cycle_ts}.md
```

If other generated memory artifacts use `.txt` as part of the Daily, Sleep, or Dream lifecycle, they SHOULD be converted to `.md` as part of this delta unless explicitly out of scope.

## Source of Truth

This delta does not change source-of-truth rules.

For Daily memory:

```text
daily.json = authoritative structured store
daily.md   = human-readable and agent-readable mirror
Daily FAISS = rebuildable in-memory cache
```

For Sleep and Dream artifacts:

```text
sleep_*.md = per-cycle LTM artifact
dream_*.md = per-cycle Dream artifact
```

## Existing `.txt` Files

Existing `.txt` files SHALL NOT require migration.

Existing `.txt` files MAY remain in place.

Existing `.txt` files MAY continue to be ingested by RAG through the normal file ingestion path.

No backfill or conversion of historical `.txt` files is required in this delta.

## Removed Compatibility Requirements

This delta explicitly removes the need for:

- `MEMORY_ARTIFACT_FORMAT`
- `MEMORY_WRITE_LEGACY_TXT`
- dual-writing `.txt` and `.md`
- runtime switching between `.txt` and `.md`
- migration of existing `.txt` files

The cutover is forward-only for newly generated artifacts.

## Requirements

### A.1.1 Daily Markdown Path

The Daily human-readable memory mirror SHALL be written to:

```text
memory/{project}/daily.md
```

The system SHALL stop writing new Daily memory to:

```text
memory/{project}/daily.txt
```

### A.1.2 Daily Backfill Path

If `daily.md` is missing and `daily.json` contains entries, the system SHALL backfill `daily.md` from `daily.json`.

The system SHALL NOT backfill `daily.txt`.

### A.1.3 Sleep Input Path

The sleep pipeline SHALL use `daily.md` as the Daily text artifact input.

The sleep pipeline SHALL NOT require `daily.txt`.

### A.1.4 Sleep Artifact Output

The deterministic sleep summary intermediate SHALL be written to:

```text
memory/{project}/sleep_summary.md
```

instead of:

```text
memory/{project}/sleep_summary.txt
```

The sleep pipeline SHALL emit per-cycle sleep artifacts as:

```text
memory/{project}/uploads/sleep/sleep_{cycle_ts}.md
```

The sleep pipeline SHALL stop emitting new per-cycle sleep artifacts as `.txt`.

### A.1.5 Dream Summary Artifact

If Dream summary artifacts are enabled, Dream SHALL write:

```text
memory/{project}/dream_summary.md
```

instead of:

```text
memory/{project}/dream_summary.txt
```

### A.1.6 Dream Per-Cycle Artifact

The deterministic Dream summary consolidation step SHALL emit:

```text
memory/{project}/uploads/dream/dream_{cycle_ts}.md
```

instead of:

```text
memory/{project}/uploads/dream/dream_{cycle_ts}.txt
```

### A.1.7 RAG Ingestion

RAG ingestion SHALL continue to support both `.txt` and `.md` files.

This ensures existing `.txt` artifacts already on disk remain usable without migration.

### A.1.8 No Runtime Format Toggle

The system SHALL NOT introduce a runtime setting to switch memory artifacts back to `.txt`.

Markdown is the only newly generated memory artifact format after this delta.

## Non-Goals

This delta does not:

- define the full markdown entry structure
- add Syx begin/end entry boundary markers
- add `memory_id`
- change embedding text normalization
- add external agent endpoints
- add MCP integration
- add Cursor write-back
- add maintained files such as `Decisions.md`
- migrate old `.txt` files
- change retrieval ranking or selection

Those belong to later A.x steps or later deltas.

## Implementation Notes

Implementation should first update path constants and artifact references.

Likely affected areas:

- Daily memory append path
- Daily backfill path
- Sleep start path
- Sleep per-cycle artifact writer
- Dream summary writer
- Dream summary consolidation step
- Cleanup logic after sleep
- Tests expecting `.txt` artifact names
- Debug labels or log messages that mention `daily.txt`, `sleep_*.txt`, or `dream_summary.txt`

Search terms likely to find affected code:

```text
daily.txt
sleep_{cycle_ts}.txt
sleep_summary.txt
dream_summary.txt
uploads/sleep
uploads/dream
```

## Test Targets

Tests SHOULD verify:

- New roll-off writes to `daily.md`.
- New roll-off does not write to `daily.txt`.
- Sleep backfills `daily.md` from `daily.json` when missing.
- Sleep reads `daily.md`.
- Sleep writes `sleep_summary.md`.
- Sleep emits `sleep_{cycle_ts}.md`.
- Dream writes `dream_summary.md` when enabled.
- Dream consolidation emits `dream_{cycle_ts}.md`.
- Existing `.txt` files can still be ingested through normal RAG upload/indexing behavior.
- No configuration flag is required to enable markdown artifacts.

## Acceptance Criteria

1. New Daily memory writes create or append to `memory/{project}/daily.md`.
2. New Daily memory writes do not create or append to `memory/{project}/daily.txt`.
3. Sleep uses `daily.md` as its Daily artifact input.
4. Sleep generates `uploads/sleep/sleep_{cycle_ts}.md`.
5. Sleep intermediate summary generation uses `sleep_summary.md`.
6. Dream summary generation uses `dream_summary.md`.
7. Dream per-cycle consolidation uses `uploads/dream/dream_{cycle_ts}.md`.
8. Existing `.txt` files are left untouched.
9. Existing `.txt` files remain ingestible by RAG.
10. No runtime `.txt` compatibility toggle is introduced.
11. Existing `daily.json` authority and Daily FAISS rebuild behavior remain unchanged.

