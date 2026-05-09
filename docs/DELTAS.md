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

# DELTA-A.2 — Source-Neutral Memory IDs and Syx Entry Boundaries

## Status

Draft

## Intent

Introduce source-neutral memory IDs and explicit Syx entry boundary markers for markdown memory artifacts.

A.1 changed newly generated memory artifacts from `.txt` to `.md`. A.2 defines how individual memory entries inside those artifacts are identified, bounded, and made suitable for future entry-level expansion.

## Background

Legacy Daily and Sleep artifacts use delimiter blocks such as:

```text
=== BEGIN DAILY PAIR ===
...
=== END DAILY PAIR ===
```

Those delimiters are readable, but they are tied to Daily pair terminology and do not provide a stable source-neutral identity that can survive movement into LTM, future database storage, or external agent retrieval.

A.2 introduces a stable memory identity layer:

```text
memory_id = stable identity
boundary comments = authoritative entry boundary
metadata = source, scope, type, route, semantic handle, etc.
```

## Core Principle

The memory entry is the durable unit.

File names, lifecycle stage, and markdown headings may change.

The `memory_id` must remain stable.

## Non-Goals

This delta does not:

- change artifact file extensions
- change retrieval ranking
- add external agent endpoints
- add MCP integration
- implement entry-level expansion
- migrate memory into a database
- introduce decay or strength scoring

## A.2.1 Memory ID Format

Each Syx memory entry SHALL have a source-neutral `memory_id`.

Format:

```text
mem_<YYYYMMDD>_<HHMMSS>_<shortid>
```

Example:

```text
mem_20260507_214200_a8f3
```

The `memory_id` SHALL be:

- stable across lifecycle transitions
- unique within a project
- suitable for future database use
- independent of file path
- independent of source scope
- independent of entry type
- independent of Daily/LTM naming

The `memory_id` SHOULD be generated when the memory entry is first created.

For chat pairs, the timestamp portion SHOULD be based on the pair timestamp.

The `<shortid>` SHOULD be short, deterministic when practical, and collision-resistant enough for project-local use.

Recommended implementation:

```text
shortid = first 4 to 8 hex characters of a stable hash over:
project_id + timestamp + source + canonical entry text
```

The existing Daily metadata `id` field remains a local Daily identifier. A.2 adds `memory_id` as a separate stable identity field.

For chat pairs, the timestamp portion of `memory_id` SHALL use the local rendered Daily timestamp format:

```text
MM-DD-YYYY_HH:MM:SS
```

The `memory_id` itself SHALL continue using compact sortable form:

```text
mem_YYYYMMDD_HHMMSS_<shortid>
```

### Canonical Hash Payload

The deterministic `<shortid>` SHALL be derived from a canonical logical payload, not from the rendered markdown entry.

For `chat_pair` entries, the canonical payload SHOULD include:

- `project_id`
- `timestamp`
- `source`
- `entry_type`
- `route`, if present
- `semantic_handle`, if present
- stored user message text
- stored assistant message text

The canonical payload SHALL NOT include:

- generated `memory_id`
- Syx begin/end boundary comments
- markdown headings added by the renderer
- YAML frontmatter
- artifact path
- line numbers
- `current_scope`
- `source_scope`
- generated sequence numbers

Line endings SHOULD be normalized to `\n`. Internal markdown content SHOULD be preserved.

For `dream_output` entries, the canonical payload SHOULD be based on the stable logical dream record, not the rendered Daily pair wrapper.

For `dream_output` entries, use:

- `project_id`
- `timestamp`
- `source: dream`
- `entry_type: dream_output`
- `dream_output_type`, if present
- `accepted_item_id`, if present
- origin memory IDs, if present
- stored dream title or `semantic_handle`, if present
- stored dream content that will become the memory text

For legacy artifacts, the canonical payload MAY be the legacy Daily Pair block content excluding any existing Syx boundary comments.

## A.2.2 Boundary Marker Format

Each markdown memory entry SHALL be wrapped in explicit Syx boundary comments.

Format:

```markdown
<!-- begin syx:memory_id=mem_20260507_214200_a8f3 -->
...
<!-- end syx:memory_id=mem_20260507_214200_a8f3 -->
```

The begin and end markers SHALL use the same `memory_id`.

The boundary marker SHALL use only the stable memory ID.

Other metadata belongs inside the entry metadata block.

## A.2.3 Boundary Authority

Syx begin/end comments are the authoritative memory-entry boundaries.

Markdown headings SHALL NOT define memory entry boundaries.

This is required because user and assistant messages may contain arbitrary markdown, including headings and fenced code blocks. Legacy sleep artifacts already include assistant-generated markdown such as headings, lists, and code blocks inside pair content.

The parser SHALL:

- identify entries by Syx boundary comments
- ignore markdown heading levels for boundary detection
- allow arbitrary markdown inside an entry
- allow fenced code blocks inside an entry
- preserve entry content verbatim
- report malformed or duplicate memory IDs

## A.2.4 Metadata Separation

The boundary marker identifies the entry.

The entry metadata describes the entry.

Markdown memory artifacts SHALL use document-level YAML frontmatter plus a markdown heading instead of legacy outer wrapper tags.

Example Dream artifact header:

```markdown
---
syx_artifact_type: dream_memory
project_id: syx
memory_date: 05-07-2026
format_version: 1
---

# Dream Memory: 05-07-2026
```

The system SHALL NOT emit legacy artifact wrapper tags for newly generated markdown memory artifacts:

```text
=== BEGIN DREAM MEMORY: 05/07/2026 ===
=== END DREAM MEMORY: 05/07/2026 ===
```

Each new markdown memory entry SHALL include a fenced YAML-like metadata block inside the entry under the heading `### Syx Metadata`.

Each entry SHALL include a markdown heading immediately after the Syx begin boundary marker.

The heading SHALL use the entry type as the label and the `semantic_handle` as the title when available:

```markdown
<!-- begin syx:memory_id=mem_20260507_153103_91d66141 -->

## Dream Output: assessing whether a retrieved memory actually helped

### Syx Metadata
```

The `semantic_handle` SHALL remain in the metadata block as well.

Example:

````markdown
### Syx Metadata

```yaml
memory_id: mem_20260507_214200_a8f3
entry_type: chat_pair
source: chat
source_agent: syx
source_scope: daily
current_scope: daily
timestamp: 05-07-2026_21:42:00
route: synthesis
keep: false
semantic_handle: markdown based memory artifacts
```
````

New `.md` entries SHALL NOT emit legacy `#timestamp`, `#route`, `#topics`, `#intent`, `#type`, or `#semantic_handle` lines.

Legacy `#key: value` lines remain supported only for parsing old artifacts and for the legacy boundary-tagging utility.

When multiple topics are available, `topics` SHALL be rendered as a YAML list, not as the old tagger-style scalar string.

Do not encode lifecycle-specific names such as `daily_pair_001` as the primary entry identity.

A local sequence MAY still be stored as metadata:

```yaml
day_sequence: 1
```

## A.2.5 Initial Entry Types

A.2 introduces the identity field needed to support multiple entry types.

Initial supported `entry_type` values:

```text
chat_pair
upload
agent_memory
note
sleep_summary
dream_output
```

A.2 does not require all entry types to be generated immediately.

For this delta, `chat_pair` is the primary required entry type.

`upload` is included so uploaded files can later be tagged into the same identity model without changing the schema.

## A.2.6 Source and Scope Fields

Source and lifecycle SHALL be separate concepts.

Recommended fields:

```yaml
source: chat
source_agent: syx
source_scope: daily
current_scope: ltm
```

Examples:

```yaml
entry_type: chat_pair
source: chat
source_agent: syx
source_scope: daily
current_scope: daily
```

```yaml
entry_type: chat_pair
source: chat
source_agent: syx
source_scope: daily
current_scope: ltm
```

```yaml
entry_type: upload
source: upload
source_scope: ltm
current_scope: ltm
```

Future external-agent write-backs can use:

```yaml
entry_type: agent_memory
source: external_agent
source_agent: cursor
source_scope: daily
current_scope: daily
```

## A.2.7 Daily Entry Behavior

For new Daily markdown entries, the system SHALL:

1. Generate a `memory_id` when the pair is first persisted to Daily memory.
2. Store that `memory_id` in the Daily structured metadata store as a new field while preserving the existing local `id`.
3. Render begin/end Syx boundary comments around the entry in `daily.md`.
4. Preserve the same `memory_id` during backfill from `daily.json`.
5. Preserve forget behavior unchanged.

If `daily.json` does not yet contain `memory_id` for older entries, backfill MAY generate memory IDs deterministically from stored metadata and text.

New markdown Daily chat entries SHALL use Syx-owned markdown headings:

```markdown
### User Message
### Assistant Message
```

New `.md` entries SHALL NOT emit legacy pair delimiters:

```text
=== BEGIN DAILY PAIR ===
=== END DAILY PAIR ===
```

Legacy separators remain parseable only for old `.txt` artifacts, A.1 `.md` artifacts, and the legacy boundary-tagging utility.

## A.2.8 Sleep Entry Behavior

When Daily entries are rolled into Sleep/LTM artifacts, the system SHALL preserve the existing `memory_id`.

Sleep SHALL NOT generate a new memory ID for a Daily-originated entry unless no ID exists.

When moving into Sleep/LTM artifact context:

```yaml
source_scope: daily
current_scope: ltm
```

The memory identity remains unchanged.

The scope rewrite to `current_scope: ltm` occurs in `uploads/sleep/sleep_{cycle_ts}.md`.

`sleep_summary.md` may preserve Daily text before final upload emission.

For `dream_output` entries persisted through Daily, use:

```yaml
entry_type: dream_output
source: dream
source_agent: syx
source_scope: dream
current_scope: dream
```

When Sleep moves or indexes a `dream_output` entry into LTM, it SHALL preserve the same `memory_id` and update:

```yaml
current_scope: ltm
```

`dream_output` entries may be stored briefly in Daily structures as a persistence path, but their source scope remains `dream`.

## A.2.8.1 Dream Entry Behavior

`dream_summary.md` and `uploads/dream/dream_{cycle_ts}.md` SHALL use Syx memory IDs and boundary markers.

Each accepted Dream item SHALL be rendered as its own bounded `dream_output` memory entry.

## A.2.9 Malformed Boundary Handling

If a begin marker exists without a matching end marker, the parser SHOULD:

1. log a warning
2. skip that malformed entry for entry-boundary expansion
3. continue parsing later valid entries when safe

If an end marker exists without a matching begin marker, the parser SHOULD log a warning.

If duplicate `memory_id` values appear in the same artifact, the artifact validator MUST report an error. Runtime readers SHOULD skip only duplicate entries with warnings rather than blocking existing retrieval behavior.

## A.2.10 Legacy Boundary Tagging Utility

### Intent

Provide a one-time utility to add Syx memory boundary markers to existing legacy `.txt` Daily/Sleep artifacts and A.1 `.md` artifacts after the `memory_id` and boundary marker format is defined.

This allows old chat history to support future entry-level expansion without requiring full markdown conversion.

### Behavior

The utility SHALL be exposed as a script under `tools/`.

The utility SHALL scan legacy memory artifacts for pair blocks:

```text
=== BEGIN DAILY PAIR ===
...
=== END DAILY PAIR ===
```

For each pair, the utility SHALL wrap the block with Syx boundary comments:

```markdown
<!-- begin syx:memory_id=<memory_id> -->
=== BEGIN DAILY PAIR ===
...
=== END DAILY PAIR ===
<!-- end syx:memory_id=<memory_id> -->
```

### Memory ID Generation

If the pair contains a `#timestamp` line, the utility SHALL generate a source-neutral memory ID using:

```text
mem_<YYYYMMDD>_<HHMMSS>_<shortid>
```

The `<shortid>` SHOULD be derived from a stable hash of the pair content so repeated runs produce the same ID.

### Idempotency

The utility SHALL be idempotent.

If a pair already contains matching Syx begin/end markers, the utility SHALL NOT add duplicate markers.

### Scope

The utility MAY support:

```text
--file <path>
--dir <path>
--dry-run
--in-place
--backup
```

### Non-Goals

The utility SHALL NOT:

- convert `.txt` files to `.md`
- rewrite pair content
- rewrite metadata sections
- rebuild RAG indexes
- modify `daily.json`
- change retrieval behavior

### Acceptance Criteria

1. Legacy Daily Pair blocks can be wrapped with Syx boundary markers.
2. Generated `memory_id` values are stable across repeated runs.
3. Running the utility twice does not duplicate markers.
4. Malformed pair blocks are logged and skipped.
5. Original content remains unchanged except for inserted boundary comments.

## A.2.11 Index Metadata Preparation

When markdown memory artifacts are indexed, chunks inside a Syx boundary SHALL carry boundary-derived metadata when available:

```yaml
memory_id: mem_20260507_214200_a8f3
entry_type: chat_pair
source: chat
source_scope: daily
current_scope: ltm
semantic_handle: markdown based memory artifacts
```

If available, chunks SHOULD also carry:

```yaml
artifact_path: memory/{project}/uploads/sleep/sleep_2026-05-07.md
entry_start_line: 12
entry_end_line: 95
route: synthesis
topics:
  - Syx
  - markdown
  - memory artifacts
```

This delta only prepares metadata for future entry-level expansion.

It does not require the retrieval pipeline to expand by memory boundary yet.

### Boundary-Aware Chunking Rule

When indexing a markdown memory artifact that contains valid Syx entry boundary blocks, the indexer SHALL split the artifact into bounded entries first.

Each bounded entry SHALL then be chunked independently using the existing text splitter.

Chunks SHALL NOT span across Syx entry boundaries.

Each chunk produced from a bounded entry SHALL receive that entry's metadata, including `memory_id`, `entry_type`, `source`, `source_scope`, `current_scope`, `route`, `topics`, `semantic_handle`, `entry_start_line`, and `entry_end_line` when available.

Unbounded text regions outside valid Syx boundary blocks SHALL still be indexed using the existing whole-file behavior, without duplicating bounded entry text.

Files without Syx boundaries SHALL continue to use the existing whole-file chunking behavior.

If a boundary block is malformed, the indexer SHOULD log a warning and fall back conservatively for that malformed region.

## Invariants

- `memory_id` is the stable identity of a memory entry.
- `memory_id` is not tied to Daily, LTM, file path, or markdown heading.
- Syx begin/end comments are the authoritative memory boundaries.
- Markdown headings inside entries are content, not structure.
- Daily-to-LTM movement preserves memory identity.
- Legacy boundary tagging is idempotent.
- Existing retrieval behavior remains unchanged.

## Acceptance Criteria

1. New Daily markdown entries include Syx begin/end boundary markers.
2. New entries use `memory_id` values in the required format.
3. Boundary markers use only `memory_id`.
4. Entry metadata separates identity, entry type, source, source scope, and current scope.
5. Daily-to-Sleep movement preserves existing `memory_id` values.
6. Backfill from `daily.json` can preserve or deterministically generate `memory_id`.
7. User and assistant markdown content does not affect boundary parsing.
8. Duplicate memory IDs in a single artifact are detected.
9. Legacy `.txt` pair blocks can be tagged with boundary markers using the utility.
10. Existing retrieval ranking, ordering, and selection behavior remain unchanged.
