# Engineering Deltas

## How To Read This File

[`docs/REQUIREMENTS.md`](REQUIREMENTS.md) is the consolidated as-built specification for Syx.
This file is the active change layer: it records newer engineering decisions,
migrations, or requirement updates that have not yet been fully rolled into the
requirements baseline.

When [`docs/REQUIREMENTS.md`](REQUIREMENTS.md) and this file conflict, follow this file for current
implementation work. Once a delta is fully incorporated into
[`docs/REQUIREMENTS.md`](REQUIREMENTS.md), it can be removed from this active layer or retained only
as design history.

## Delta Status Summary

This summary is intended for public readers who need the current state without
reading every detailed requirement section first.

| Delta | Public status | Notes |
| --- | --- | --- |
| `DELTA-A.1` Markdown Artifact Naming Cutover | Implemented in current code | New generated Daily, Sleep, and Dream memory artifacts use `.md` names. Existing `.txt` files may remain as normal RAG-ingested documents. |
| `DELTA-A.2` Source-Neutral Memory IDs and Syx Entry Boundaries | Implemented in current code | Generated memory artifacts include stable IDs and Syx begin/end boundaries for entry-level parsing. |
| `DELTA-A.3` Syx Boundary Metadata in RAG Chunk Indexing | Implemented in current code | RAG indexing preserves available Syx boundary metadata for downstream retrieval and expansion. |
| `DELTA-A.4` Agent Memory Search Endpoint and CLI Bridge | Implemented in current code | The local read-only `/agent/memory/search` endpoint and CLI/tooling bridge exist. |
| `DELTA-A.5` Agent Full-Entry Expansion | Implemented in current code | Agent memory search can expand bounded Syx results into complete memory entries. |
| `DELTA-A.6` External Agent Memory Add Endpoint | Future-facing | Captured as planned write-back work; not part of the current public endpoint surface. |
| `DELTA-A.7` Cursor MCP Wrapper | Future-facing | Captured as planned MCP wrapper work. Current tooling uses local CLI/scripts. |
| `DELTA-B.1` Multi-Provider LLM Model Support | Draft | Refactor the LLM factory boundary and move provider/model role defaults into an app-owned registry so OpenAI, Anthropic, and future providers can be selected coherently. |

# DELTA-A — Markdown-Based Syx Memory Artifacts

## Status

Accepted

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

## Delta Roadmap

DELTA-A is being implemented as a staged migration from plain text memory artifacts toward markdown-based, agent-readable Syx memory. The early steps preserve existing retrieval behavior while adding the structure needed for later agent search, entry-level expansion, and Cursor/MCP integration.

### DELTA-A.1 — Markdown Artifact Naming Cutover

Newly generated Syx memory artifacts use `.md` instead of `.txt`.

This step changes artifact names only. Existing `.txt` files remain valid RAG inputs, but new Daily, Sleep, and Dream memory artifacts are written as markdown files going forward.

### DELTA-A.2 — Source-Neutral Memory IDs and Syx Entry Boundaries

Each memory entry receives a stable `memory_id` and explicit Syx begin/end boundary markers.

This step makes memory entries identifiable independently of file name, lifecycle stage, or markdown heading structure. It also allows nested markdown inside user and assistant messages without confusing Syx entry parsing.

### DELTA-A.3 — Syx Boundary Metadata in RAG Chunk Metadata

RAG indexing parses Syx markdown boundaries and attaches available entry metadata to generated chunks.

This step should not change retrieval scoring, ranking, selection, or expansion behavior. It only enriches chunk metadata with fields such as `memory_id`, `entry_type`, `source_scope`, `current_scope`, `semantic_handle`, topics, and entry line bounds when available.

### DELTA-A.4 — Agent-Memory Route and Entry-Boundary Expansion

Introduce an internal `agent_memory` retrieval route that uses the existing retrieval pipeline but expands selected results to full Syx memory entries.

Normal chat remains chunk-budgeted. The agent-memory route becomes entry-budgeted, selecting a smaller number of unique memory entries and expanding each selected result from Syx begin/end boundaries.

### DELTA-A.5 — External Agent Memory Search Endpoint

Expose the agent-memory route through a local search endpoint for trusted external agents.

This endpoint allows tools such as Cursor to query Syx project memory and receive ranked, provenance-rich memory entries. It is read-only and does not write, update, or delete memory.

### DELTA-A.6 — External Agent Memory Add Endpoint

Add a controlled write-back endpoint for trusted local agents.

This allows Cursor or another agent to write concise implementation notes, decisions, bug fixes, test results, or open questions into Daily memory. Agent writes are provenance-tagged and enter the normal sleep/consolidation lifecycle instead of writing directly to LTM.

### DELTA-A.7 — Cursor MCP Wrapper

Expose Syx memory search and add operations through a local MCP wrapper.

This makes Syx usable as an external memory substrate for Cursor. Cursor can search prior design decisions before implementation and write back useful implementation summaries after meaningful changes.

---

# DELTA-A.1 — Markdown Artifact Naming Cutover

## Status

Accepted

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

Accepted

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

When Syx-bounded memory artifacts are indexed, chunks inside a Syx boundary SHALL carry boundary-derived metadata when available:

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

This A.2.11 preparation rule is superseded by DELTA-A.3 for files that contain valid Syx boundary blocks.

Under A.3, unbounded envelope text outside valid Syx boundary blocks SHALL NOT be indexed as standalone memory content.

Files without Syx boundaries SHALL continue to use the existing whole-file chunking behavior.

If Syx boundary markers are malformed, the indexer SHOULD log a warning and fall back conservatively according to the A.3 malformed boundary handling rule.

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


Note:

A.3 is being added because A.2 created stable Syx memory entry boundaries, but the RAG index still needs to understand those boundaries structurally. If `memory_id` only exists as text inside the markdown, later expansion has to rely on chunk indexes and source-file scanning, which is fragile.

The goal of A.3 is to make Syx-bounded memory entries first-class indexing regions. Each bounded entry should be chunked independently, carry its own metadata, and use a `source_document_id` that includes the `memory_id`. This lets the existing expansion logic stay inside one memory entry today, and makes future agent-memory expansion much easier because a hit can be expanded to the full entry without guessing boundaries.

# DELTA-A.3 — Syx Boundary Metadata in RAG Chunk Indexing

## Status

Accepted

## Intent

Update RAG indexing so Syx-bounded markdown memory entries are indexed as independent expansion-safe document regions with structured metadata attached to each chunk.

A.1 changed generated memory artifacts from `.txt` to `.md`.

A.2 added stable `memory_id` values, fenced YAML metadata, and Syx begin/end boundary markers.

A.3 makes the RAG index aware of those boundaries without changing retrieval scoring, ordering, ranking, selection, or normal chat behavior.

## Background

Syx RAG expansion currently works by retrieving chunks, ordering candidates by similarity, deduplicating and grouping adjacent chunks, then expanding around each selected chunk using `source_document_id` and `chunk_index`.

For LTM, expansion uses an item identity pattern similar to:

```text
source_document_id::chunk=<seq>
```

Neighbors are found by using the same `source_document_id` and nearby integer chunk indexes.

This works well for ordinary files, but Syx markdown memory artifacts now contain multiple bounded entries inside a single file. If the whole file is indexed as one document, expansion can cross from one memory entry into another.

A.3 changes indexing for Syx-bounded artifacts so each bounded memory entry becomes its own `source_document_id`.

## Core Decision

For Syx memory artifacts with valid Syx entry boundaries, each bounded entry SHALL be indexed as an independent document region.

The `source_document_id` for chunks inside a bounded entry SHALL include both the artifact path and the entry `memory_id`.

Example:

```text
sleep/sleep_2026-05-07T16-07-12.md::memory_id=mem_20260507_194952_1e34f15f
```

Chunks for that entry SHALL be numbered locally inside the entry:

```text
sleep/sleep_2026-05-07T16-07-12.md::memory_id=mem_20260507_194952_1e34f15f::chunk=0
sleep/sleep_2026-05-07T16-07-12.md::memory_id=mem_20260507_194952_1e34f15f::chunk=1
sleep/sleep_2026-05-07T16-07-12.md::memory_id=mem_20260507_194952_1e34f15f::chunk=2
```

This preserves the existing adjacency expansion mechanism while preventing expansion across Syx memory-entry boundaries.

## Non-Goals

This delta does not:

- add external agent endpoints
- add MCP integration
- add Cursor write-back
- implement full-entry expansion
- change similarity scoring
- change candidate ranking
- change candidate ordering
- change normal chat context assembly
- change route policies
- change chunk size or overlap
- move memory into a database
- add decay or utility scoring

## A.3.1 Syx Boundary Detection During Indexing

During RAG rebuild/indexing, the indexer SHALL detect Syx entry boundary markers in memory artifacts that can be read as text.

Boundary format:

```markdown
<!-- begin syx:memory_id=mem_20260507_194952_1e34f15f -->
...
<!-- end syx:memory_id=mem_20260507_194952_1e34f15f -->
```

If a `.txt` or `.md` file contains one or more valid Syx boundary blocks and no malformed Syx boundary markers, the file SHALL be treated as a Syx-bounded memory artifact.

If a file contains no valid Syx boundary blocks, the file SHALL be indexed using the existing whole-file indexing behavior.

A.3 does not add or restore PDF extraction support. PDF handling remains outside this delta.

## A.3.2 Bounded Entry Indexing

For Syx-bounded memory artifacts, the indexer SHALL:

1. Parse the file into bounded Syx memory entries.
2. Ignore unbounded envelope text outside entries for indexing.
3. Chunk each bounded entry independently.
4. Reset `chunk_index` to `0` at the start of each bounded entry.
5. Attach entry metadata to every chunk created from that entry.
6. Preserve the existing text splitter behavior inside each entry.

Chunks SHALL NOT span across Syx entry boundaries.

## A.3.3 Source Document ID Construction

For chunks created from a bounded Syx entry, `source_document_id` SHALL be constructed as:

```text
<artifact_relative_path>::memory_id=<memory_id>
```

Example:

```text
dream/dream_2026-05-07T16-07-12.md::memory_id=mem_20260507_160709_1aebd6c4
```

The docstore item ID SHALL continue to use the existing chunk identity pattern:

```text
<source_document_id>::chunk=<chunk_index>
```

Example:

```text
dream/dream_2026-05-07T16-07-12.md::memory_id=mem_20260507_160709_1aebd6c4::chunk=0
```

This ensures existing expansion code can retrieve neighboring chunks by `source_document_id` and `chunk_index` without crossing into another memory entry.

## A.3.4 Metadata Attached to Chunks

For each chunk produced from a bounded Syx entry, the indexer SHALL attach available entry metadata.

Required when available:

```yaml
memory_id: mem_20260507_160709_1aebd6c4
entry_type: dream_output
source: dream
source_agent: syx
source_scope: daily
current_scope: dream
timestamp: 05-07-2026_16:07:09
semantic_handle: reliability of answer-source overlap for evidence support
```

Recommended when available:

```yaml
artifact_type: dream_memory
artifact_path: dream/dream_2026-05-07T16-07-12.md
entry_start_line: 10
entry_end_line: 83
route: other
keep: false
topics:
  - token overlap
  - semantic similarity
  - entailment
accepted_item_id: dream_20260507_support_overlap_not_causation
dream_output_type: open_question
```

For chat pairs, metadata SHOULD include:

```yaml
entry_type: chat_pair
source: chat
source_agent: syx
source_scope: daily
current_scope: ltm
route: synthesis
intent: ask for research plan
type: research
day_sequence: 1
```

For uploads, if later represented as bounded entries, metadata SHOULD include:

```yaml
entry_type: upload
source: upload
source_scope: ltm
current_scope: ltm
filename: example.md
file_type: md
```

## A.3.5 Fenced YAML Metadata Parsing

The indexer SHALL parse the fenced YAML block immediately following `### Syx Metadata` inside each bounded entry.

Example:

````markdown
### Syx Metadata

```yaml
memory_id: mem_20260507_160709_1aebd6c4
entry_type: dream_output
source: dream
source_agent: syx
source_scope: daily
current_scope: dream
timestamp: 05-07-2026_16:07:09
topics:
  - token overlap
  - semantic similarity
semantic_handle: reliability of answer-source overlap for evidence support
```
````

The parser SHALL treat this fenced YAML block as the structured metadata source for chunk metadata.

The parser SHALL NOT rely on markdown headings to determine entry identity or lifecycle metadata.

If a bounded entry has valid Syx begin/end boundaries but the fenced metadata block is missing, invalid, or unreadable, the indexer SHALL still index that bounded entry using boundary-derived metadata such as `memory_id`, `artifact_path`, `entry_start_line`, and `entry_end_line`.

Invalid or unreadable fenced YAML metadata SHOULD be logged as a warning, but it SHALL NOT by itself cause a whole-file fallback when Syx begin/end boundaries are structurally valid.

### Topic Metadata Retrieval Requirement

Topics are a primary retrieval signal in Syx memory.

For bounded Syx memory entries, the `topics` field SHALL remain inside the fenced YAML metadata block and SHALL be included in the text that is chunked and embedded.

The indexer SHALL also parse `topics` into structured chunk metadata.

This means topics are intentionally stored in two forms:

- embedded text, to preserve semantic retrieval behavior
- structured metadata, to support filtering, provenance, diagnostics, and future agent search

A.3 SHALL NOT remove, strip, normalize away, or omit topics from embedded memory text.

## A.3.6 Boundary-Contained Expansion Compatibility

This delta does not change runtime expansion logic.

However, by setting `source_document_id` to include `memory_id`, the existing expansion behavior becomes naturally boundary-contained.

Current expansion can still expand by:

```text
same source_document_id
nearby chunk_index values
```

but the source document now represents one Syx memory entry rather than the whole artifact file.

Therefore, expansion can retrieve neighboring chunks within the matched memory entry but cannot cross into the previous or next memory entry.

## A.3.7 Mixed Bounded and Unbounded Files

If a file contains one or more valid Syx boundary blocks, the indexer SHALL index bounded entries only.

Unbounded text outside Syx boundaries SHALL NOT be indexed as standalone memory content for Syx memory artifacts.

This usually includes:

- YAML frontmatter
- document title
- blank lines
- file-level envelope text

If a file contains no Syx boundary blocks, the indexer SHALL use existing whole-file indexing behavior.

## A.3.8 Legacy Files

Existing legacy `.txt` files without Syx boundary markers SHALL continue to index using the existing whole-file behavior.

If a legacy `.txt` file has been processed by the legacy boundary-tagging utility and contains valid Syx boundary markers, the indexer SHALL treat it as a Syx-bounded memory artifact.

This delta does not require old `.txt` files to be migrated or boundary-tagged.

## A.3.9 Malformed Boundary Handling

If a file contains malformed Syx boundary markers, the indexer SHALL log a warning.

Malformed cases include:

- begin marker without matching end marker
- end marker without matching begin marker
- duplicate `memory_id` values in the same artifact

For files with malformed Syx boundary markers, the indexer SHALL:

1. Log a warning.
2. Treat the whole file as structurally corrupt for bounded indexing.
3. Fall back to existing whole-file indexing for that file.
4. Continue the rebuild for other files.

Malformed fenced YAML metadata is not a malformed Syx boundary marker. See A.3.5 for metadata fallback behavior.

Tests for newly generated Syx artifacts SHOULD fail if malformed boundaries are produced.

## A.3.10 No Retrieval Behavior Change

A.3 SHALL NOT change retrieval behavior.

The following behavior remains unchanged:

- query embedding
- semantic search
- similarity score computation
- candidate ordering
- candidate ranking
- max_keep behavior
- adjacent bonus behavior
- existing dedupe/grouping behavior
- normal chat expansion
- context assembly
- route policy parameters

The only intended runtime effect is that bounded Syx memory artifacts now produce chunks whose `source_document_id` prevents expansion from crossing entry boundaries.

## A.3.10.1 Retrieval Candidate Metadata Exposure

When LTM retrieval returns a chunk whose docstore metadata contains parsed Syx metadata, the retrieval candidate SHALL expose that metadata directly through the candidate metadata field.

Required when available:

- `memory_id`
- `entry_type`
- `source`
- `source_agent`
- `source_scope`
- `current_scope`
- `semantic_handle`
- `topics`
- `artifact_path`
- `entry_start_line`
- `entry_end_line`

This metadata exposure SHALL NOT affect similarity scoring, ranking, ordering, or selection in A.3.

The purpose is to carry Syx memory identity and provenance forward for diagnostics, audit logs, future route-specific expansion, and external agent search.

## A.3.11 Future Agent Expansion Preparation

A later delta will introduce an agent-memory route that expands selected results to full Syx entries.

A.3 prepares for that by making each bounded entry identifiable in chunk metadata and by making all chunks for an entry share the same `source_document_id`.

Future full-entry expansion can gather all chunks for:

```text
<artifact_path>::memory_id=<memory_id>
```

instead of scanning the artifact from an arbitrary chunk position.

A.3 does not implement that full-entry expansion.

## Invariants

- Syx bounded entries are the indexing unit for Syx memory artifacts.
- Chunks must not span across Syx entry boundaries.
- `source_document_id` for bounded entries includes `memory_id`.
- `chunk_index` is local to the bounded entry.
- Files without Syx boundaries index as before.
- Retrieval scoring and ranking remain unchanged.
- Normal chat behavior remains unchanged.
- A.3 enriches chunk metadata but does not introduce agent endpoints.

## Implementation Notes

Likely implementation work:

1. Reuse or extend the A.2 Syx boundary parser.
2. Detect valid bounded entries before normal whole-file chunking.
3. Parse the fenced YAML metadata block for each entry.
4. Chunk each entry independently using the existing text splitter.
5. Build `source_document_id` as `<artifact_path>::memory_id=<memory_id>`.
6. Store chunks using existing `::chunk=<chunk_index>` item IDs.
7. Attach parsed metadata to chunk metadata.
8. Fall back to existing whole-file indexing for files without boundaries.
9. Preserve existing tests for ordinary uploads.
10. Add tests for bounded Syx artifacts.

## Test Targets

Tests SHOULD cover:

- bounded dream artifact indexing
- bounded sleep/daily artifact indexing
- chunk indexes reset per memory entry
- chunks do not span across entries
- `source_document_id` includes `memory_id`
- docstore item IDs use `source_document_id::chunk=<n>`
- metadata includes `memory_id`
- metadata includes `entry_type`
- metadata includes `source_scope` and `current_scope`
- metadata includes topics as a list
- metadata includes `semantic_handle`
- ordinary `.md` uploads without Syx boundaries index as before
- ordinary `.txt` uploads without Syx boundaries index as before
- malformed boundary markers are logged
- duplicate `memory_id` values are detected
- current retrieval ranking tests continue to pass

## Acceptance Criteria

1. RAG indexing detects valid Syx begin/end boundary markers.
2. Each bounded Syx entry is chunked independently.
3. Chunks do not span across Syx entry boundaries.
4. `source_document_id` for bounded-entry chunks includes `memory_id`.
5. `chunk_index` resets within each bounded memory entry.
6. Chunk metadata includes parsed Syx metadata when available.
7. Files without Syx boundaries index exactly as before.
8. Existing `.txt` legacy files remain ingestible.
9. Existing retrieval scoring, ranking, ordering, and selection behavior remain unchanged.
10. Existing normal chat expansion continues to work.
11. Expansion for bounded Syx entries cannot cross into adjacent memory entries.
12. Future agent-memory full-entry expansion can use the indexed `memory_id` and shared `source_document_id`.


# DELTA-A.4 — Agent Memory Search Endpoint and CLI Bridge

## Status

Accepted

## Intent

Expose a local agent-facing memory search endpoint that returns Syx retrieval results as JSON without running the normal chat response pipeline.

A.4 creates the first practical external-agent bridge. It allows tools such as Cursor to query Syx project memory through a local endpoint or CLI command before MCP support exists.

## Background

A.1 changed newly generated Syx memory artifacts from `.txt` to `.md`.

A.2 added stable `memory_id` values, fenced YAML metadata, and Syx begin/end entry boundaries.

A.3 made RAG indexing boundary-aware by indexing each bounded Syx memory entry as its own expansion-safe document region and attaching parsed Syx metadata to chunks.

A.4 exposes retrieval through an agent-facing interface.

The endpoint is retrieval-only. It does not generate a chat answer and does not write memory.

## Core Rule

The request category selects the existing retrieval policy.

The agent endpoint selects the response shape.

```text
category = retrieval policy knobs
agent endpoint = structured JSON snippets response
```

## Request Shape

The agent memory search endpoint SHALL accept a JSON request using `project_name`, not `project_id`.

```json
{
  "project_name": "Project_Syx",
  "query": "Project mission, scope, architecture, current requirements, major design decisions, and non-goals.",
  "model": "...",
  "category": "SYNTHESIS",
  "agent_token": "..."
}
```

## Response Shape

The endpoint SHALL return JSON.

A.4 returns structured `snippets` as the canonical retrieval payload.

A.4 SHALL NOT return both a prompt-shaped `content` field and a `snippets` array containing the same retrieval text.

The prompt-shaped retrieval text MAY be reconstructed by clients, CLI tools, or future MCP wrappers from the `snippets` array.

```json
{
  "project_name": "Project_Syx",
  "project_id": "ce667335-ae8e-41d7-b810-59627cd8d67a",
  "category": "SYNTHESIS",
  "query": "Project mission, scope, architecture, current requirements, major design decisions, and non-goals.",
  "model": "optional-model-name",
  "snippet_count": 3,
  "bounded_result_count": 2,
  "unbounded_result_count": 1,
  "snippets": [
    {
      "snippet_number": 1,
      "source": "ltm",
      "cos": 0.6662,
      "score": 0.8331,
      "file": "dream_2026-05-07T16-07-12.md",
      "page": null,
      "source_document_id": "dream/dream_2026-05-07T16-07-12.md::memory_id=mem_20260507_160709_1aebd6c4",
      "chunk_index_start": 0,
      "chunk_index_end": 2,
      "chunk_index_range": "0..2",
      "memory_id": "mem_20260507_160709_1aebd6c4",
      "entry_type": "dream_output",
      "source_agent": "syx",
      "source_scope": "daily",
      "current_scope": "dream",
      "semantic_handle": "reliability of answer-source overlap for evidence support",
      "topics": [
        "token overlap",
        "semantic similarity",
        "entailment"
      ],
      "artifact_path": "dream/dream_2026-05-07T16-07-12.md",
      "result_mode": "bounded_entry",
      "text": "<retrieved expanded snippet text without the leading Snippet N (...) line>"
    }
  ]
}
```

For unbounded ordinary upload or legacy results, `result_mode` SHALL be:

```text
unbounded_chunk_group
```

The endpoint SHALL NOT use a `fallback` response field in A.4. `result_mode` is the response field for bounded versus unbounded result shape.

If retrieval succeeds but returns no context/snippets, the endpoint SHALL return `200 OK` with:

```json
{
  "snippet_count": 0,
  "bounded_result_count": 0,
  "unbounded_result_count": 0,
  "snippets": []
}
```

When `model` is provided, the endpoint MAY echo it in the response. A.4 SHALL NOT validate `model` against the chat model whitelist and SHALL NOT use `model` for retrieval behavior.

## Non-Goals

A.4 does not:

- implement full-entry expansion
- write memory
- add Cursor write-back
- add MCP integration
- add agent-owned memory inventory
- add memory delete
- add memory summarize
- change route classification for normal chat
- change semantic scoring
- change candidate ordering
- change existing normal chat expansion
- change Daily memory storage
- change LTM indexing
- introduce database-backed memory

Full-entry expansion is deferred to A.5.

## A.4.1 Endpoint

Add a local endpoint:

```text
POST /agent/memory/search
```

The endpoint SHALL be retrieval-only.

It SHALL return retrieved memory results as JSON.

It SHALL NOT generate an assistant answer.

It SHALL NOT write memory.

## A.4.2 Query Field

The endpoint SHALL use `query`, not `message`.

The endpoint is a retrieval interface, not a chat interface.

`query` SHALL be used as the retrieval query text.

## A.4.3 Project Name Resolution

The endpoint SHALL accept a human-readable `project_name`.

The endpoint SHALL resolve `project_name` to the internal `project_id` before retrieval.

Project name matching SHALL be trimmed and case-insensitive, matching current project creation uniqueness semantics.

The response SHALL return the exact request `project_name` string supplied by the caller.

If multiple legacy project rows match the trimmed case-insensitive `project_name`, the endpoint SHALL pick the first match and log a warning.

Processing order:

1. Validate request shape.
2. Resolve `project_name` to internal `project_id`.
3. Validate that `agent_token` is authorized for the resolved `project_id`.
4. Use `project_id` for retrieval, logging, and internal processing.
5. Return both `project_name` and `project_id` in the response.

If `project_name` is unknown, return:

```text
404 Not Found
```

Example response:

```json
{
  "error": "project_not_found",
  "message": "No project exists with the requested project_name.",
  "project_name": "Project_Syx"
}
```

## A.4.4 Agent Token

The endpoint SHALL include an agent security token in the request contract from the beginning.

Initial request shape includes:

```json
{
  "agent_token": "..."
}
```

A.4 SHALL call an agent-token authorization function after `project_name` has been resolved to `project_id`.

The authorization function boundary SHALL exist in A.4.

Initial authorization code SHOULD live behind a boundary such as:

```text
backend/app/security/agent_tokens.py
```

In A.4, the authorization implementation MAY be stubbed to pass for local development. The call site SHALL still exist so future requirements can replace the stub with real token validation and project access checks without changing the endpoint contract.

If the JSON request does not include the `agent_token` field, the endpoint SHALL log a warning and return:

```text
401 Unauthorized
```

Response body:

```json
{
  "error": "unauthorized",
  "message": "Missing agent token."
}
```

If `agent_token` is present but is an empty string, the A.4 local-development stub MAY authorize it.

Future deltas may move token handling to:

```text
Authorization: Bearer <agent_token>
```

If token validation is enabled and the token is missing or invalid, return:

```text
401 Unauthorized
```

Example response:

```json
{
  "error": "unauthorized",
  "message": "Missing or invalid agent token."
}
```

If the token is valid but does not have access to the resolved project, return:

```text
403 Forbidden
```

Example response:

```json
{
  "error": "forbidden",
  "message": "Agent token does not have access to the requested project.",
  "project_name": "Project_Syx"
}
```

## A.4.5 Category

The endpoint SHALL accept a `category` field.

The category SHOULD be one of the existing route categories:

- `DIRECT`
- `PROCEDURAL`
- `EXPLORATORY`
- `SYNTHESIS`
- `OTHER`

The endpoint SHALL NOT run the normal route-classification prompt.

The provided `category` SHALL be normalized to uppercase before use.

When the normalized category is known, it SHALL select the existing route policy values for retrieval breadth and candidate selection.

If category is missing, the endpoint SHOULD default to:

```text
OTHER
```

If category is invalid, the endpoint SHALL fall back to `OTHER`.

Invalid category SHALL NOT return `400` in A.4.

## A.4.5.1 Model Field

The agent memory search endpoint MAY accept a `model` field for request-contract stability and future compatibility.

A.4 SHALL NOT use `model` to generate an answer.

A.4 SHALL NOT validate `model` against the chat model whitelist.

A.4 SHALL NOT use `model` to select retrieval behavior.

If provided, `model` MAY be echoed in the response and written to debug output.

If omitted, the endpoint SHALL still process the request normally.

Retrieval knobs SHALL come from:

```text
category + route policy
```

## A.4.6 Pipeline Boundary

The endpoint SHALL reuse only the retrieval-side pipeline.

It MAY reuse:

- query embedding
- route policy lookup using the provided category
- Daily/LTM retrieval
- candidate scoring
- candidate ordering
- dedupe/grouping
- existing expansion behavior
- backend debug logging

It SHALL NOT reuse:

- normal route classification
- assistant prompt assembly
- model answer generation
- chat response streaming
- memory write-back

Normal chat behavior SHALL remain unchanged.

A.4 SHOULD leave the existing retrieval/chat pipeline behavior intact and build the agent JSON response as an endpoint-specific final response-shaping step.

In A.4, the endpoint MAY parse the prompt-shaped retrieval context returned by the existing retrieval path to build structured snippets.

## A.4.7 Retrieval Behavior

The endpoint SHALL use the provided `category` to select the existing route policy.

The route policy SHALL include a per-route `min_score` field. During retrieval selection, candidates whose normalized retrieval `score` is not greater than the selected route's `min_score` SHALL be skipped before `max_keep` and adjacency expansion are applied.

The endpoint SHALL run existing retrieval, ordering, dedupe/grouping, and existing expansion behavior.

The endpoint SHALL preserve snippet order exactly as returned by the prompt context.

Until A.5, each snippet `text` MAY be the same expanded chunk/group content that the retrieval pipeline already produces.

When converting prompt-shaped retrieval context into snippets, the endpoint SHALL strip the leading snippet label line such as:

```text
Snippet 5 (source=ltm, cos=0.6411, score=0.8206, file=sleep_2026-05-06T16-50-51.txt, page=None, chunk_index=0..1)
```

The endpoint SHALL keep any Syx fenced YAML metadata block that appears inside the retrieved snippet text.

A.4 SHALL NOT require full Syx entry expansion.

## A.4.8 Result Metadata

When available, each snippet SHOULD expose parsed Syx metadata.

In A.4, Syx metadata MAY be extracted best-effort from fenced YAML inside the retrieved snippet text.

If YAML is absent or a field is missing, the endpoint SHALL skip that field rather than fail the request.

Recommended fields:

- `snippet_number`
- `source`
- `cos`
- `score`
- `file`
- `page`
- `source_document_id`
- `chunk_index_start`
- `chunk_index_end`
- `chunk_index_range`
- `memory_id`
- `entry_type`
- `source_agent`
- `source_scope`
- `current_scope`
- `semantic_handle`
- `topics`
- `artifact_path`
- `result_mode`
- `text`

Each A.4 snippet SHALL include stable retrieval identity fields when available:

- `source_document_id`
- chunk index fields

For collapsed snippet groups, A.4 snippets SHALL expose chunk indexes as numeric range fields when available:

- `chunk_index_start`
- `chunk_index_end`

If the snippet contains a single chunk, `chunk_index_start` and `chunk_index_end` SHALL be the same value.

A.4 snippets MAY also include a display-only `chunk_index_range` string such as `0..11`.

Tooling SHOULD rely on numeric `chunk_index_start` and `chunk_index_end`, not on parsing `chunk_index_range`.

If a future retrieval path produces non-contiguous collapsed chunks, that path SHOULD expose `chunk_indexes` as a list of integers instead of using a contiguous range.

`result_mode` SHOULD use:

- `bounded_entry` when Syx boundary metadata is available
- `unbounded_chunk_group` when the result is ordinary upload, legacy text, or otherwise unbounded

Structured metadata SHOULD be exposed separately from `text`.

The `text` field is the retrieved text payload.

## A.4.8.1 Snippet Parse Failure

If retrieval succeeds but A.4 cannot convert the retrieved context into the required structured `snippets` response, the endpoint SHALL log a warning and return:

```text
500 Internal Server Error
```

Response body:

```json
{
  "error": "snippet_parse_failed",
  "message": "Agent memory search retrieved context but could not convert it to structured snippets.",
  "retryable": false
}
```

The backend debug file SHOULD include the raw retrieved context and parser failure details when available.

## A.4.9 Sleep and Index Lock Behavior

A.4 SHALL use the existing global sleep lock as the read-safety guard for the agent memory search endpoint.

The global sleep middleware SHOULD allow `POST /agent/memory/search` through so the endpoint can resolve `project_name`, return `project_id`, and produce the A.4-specific locked response shape.

For A.4 search:

```text
if global_sleep_lock == true:
    return 423 Locked
else:
    run retrieval
```

Recommended response:

```json
{
  "error": "memory_locked",
  "message": "Project memory is currently unavailable because sleep is running. Retry after sleep completes.",
  "project_id": "<project_id>",
  "project_name": "<project_name>",
  "retryable": true
}
```

The endpoint SHALL NOT block waiting for sleep completion.

A.4 SHALL NOT introduce a separate `memory_write_lock`.

Write-lock restructuring belongs in a later delta when agent write/add endpoints are introduced.

## A.4.10 CLI Bridge

A.4 SHALL include a local CLI utility for testing the agent memory search endpoint.

The CLI also serves as the first practical Cursor bridge because Cursor can run local shell commands before MCP support exists.

Example:

```bash
python tools/agent_memory_search.py \
  --project-name Project_Syx \
  --category SYNTHESIS \
  --query "Project mission, scope, architecture, current requirements, major design decisions, and non-goals." \
  --agent-token "$SYX_AGENT_TOKEN"
```

## A.4.11 CLI Inputs

Required inputs:

- `project-name`
- `query`
- `agent-token`

Optional inputs:

- `category`
- `model`
- `base-url`
- `debug-dir`
- `pretty`

The CLI MAY also read token from:

```text
SYX_AGENT_TOKEN
```

If `category` is not provided, the CLI SHOULD send:

```text
OTHER
```

## A.4.12 CLI Behavior

The CLI SHALL:

1. Build the same JSON request expected by `POST /agent/memory/search`.
2. Send the request to the local Syx backend.
3. Print the raw structured endpoint JSON returned by the backend to stdout.
4. Write a debug-style file containing:
   - request timestamp
   - endpoint URL
   - request JSON
   - response status
   - full response JSON
   - prompt-shaped text rendered from the structured snippets when practical
   - snippet count
   - memory IDs returned
   - bounded result count
   - unbounded result count
5. Return nonzero exit code on request failure or invalid response.

The debug file SHALL include both the query sent to the endpoint and the response returned by the endpoint.

The CLI debug file SHALL always be written by the CLI, independent of `GENERATE_DEBUG_FILES`.

The CLI debug file SHOULD be written under the provided `debug-dir` when supplied.

If no `debug-dir` is supplied, the CLI SHOULD write temporary debug output under:

```text
tools/agent_interface/
```

Generated debug output under `tools/agent_interface/` SHOULD be gitignored.

Suggested debug filename:

```text
agent_memory_search_YYYYMMDD_HHMMSS.json
```

## A.4.13 Cursor CLI Bridge

A Cursor rule or skill file MAY instruct Cursor to call the CLI when it needs Syx project memory.

Example Cursor-oriented command:

```bash
python tools/agent_memory_search.py \
  --project-name Project_Syx \
  --category PROCEDURAL \
  --query "Implementation guidance, requirements, constraints, and known pitfalls for the agent memory search endpoint A.4." \
  --agent-token "$SYX_AGENT_TOKEN"
```

This allows Cursor to retrieve Syx memory before MCP support is implemented.

## A.4.14 Agent Query Guidance

Agents SHOULD write retrieval-oriented queries.

Examples:

Broad project orientation:

```text
Project mission, scope, architecture, current requirements, major design decisions, and non-goals.
```

Implementation task:

```text
Implementation guidance, requirements, design decisions, constraints, and known pitfalls for <task>.
```

Specific lookup:

```text
<specific fact, requirement, decision, or file location to find>.
```

Design analysis:

```text
Design tradeoffs, prior decisions, open questions, and constraints related to <topic>.
```

Agents SHOULD include relevant project terms, feature names, requirement IDs, delta names, topics, and semantic handles when known.

## A.4.15 Endpoint Debug Files

When backend debug file generation is enabled, the endpoint SHOULD write timestamped debug files using the existing debug-file utility.

Suggested filenames:

```text
agent_interface/YYYYMMDD_HHMMSS_agent_query.txt
agent_interface/YYYYMMDD_HHMMSS_agent_response.txt
```

The endpoint SHALL NOT include debug file paths in the JSON response.

Endpoint debug files SHOULD include, when available:

- request timestamp
- resolved `project_id`
- request JSON
- raw prompt-shaped retrieval context before parsing
- parsed structured JSON response
- parser warnings or snippet parse failure details

## A.4.16 Implementation Organization

A.4 SHOULD keep endpoint-facing agent bridge code separate from normal chat routes.

Recommended backend package:

```text
backend/app/agent_interface/
```

This package MAY contain:

- endpoint router
- request and response schemas
- retrieval response adapter
- prompt-shaped context parser
- snippet rendering helpers for tests or CLI parity

Agent token authorization SHOULD live behind a security boundary:

```text
backend/app/security/agent_tokens.py
```

The CLI utility SHALL live under the existing root tools area:

```text
tools/agent_memory_search.py
```

Temporary CLI debug output SHOULD be written under:

```text
tools/agent_interface/
```

Generated CLI debug output under `tools/agent_interface/` SHOULD be gitignored.

## Invariants

- A.4 is retrieval-only.
- A.4 does not call the model to generate an answer.
- A.4 does not run the normal route classifier.
- A.4 uses caller-provided category to select existing retrieval policy.
- A.4 defaults missing category to `OTHER`.
- A.4 falls back invalid category to `OTHER`.
- A.4 accepts `project_name` and resolves it to `project_id`.
- A.4 includes `agent_token` in the request contract.
- A.4 calls an authorization function, even if authorization is stubbed in A.4.
- A.4 returns structured JSON snippets.
- A.4 does not return duplicate `content` and `snippets` payloads.
- A.4 does not write memory.
- A.4 does not implement full-entry expansion.
- Existing chat routes remain unchanged.
- The CLI prints the raw structured endpoint JSON to stdout.
- The CLI always writes a debug-style file containing the query and response.
- Endpoint debug files are written silently when backend debug files are enabled.

## Test Targets

Tests SHOULD cover:

- endpoint accepts valid request
- endpoint resolves `project_name` to `project_id`
- missing project returns `404`
- missing `agent_token` field returns `401`
- invalid token returns `401` when validation is enabled
- forbidden project access returns `403` when authorization is enabled
- authorization function is called after project resolution
- valid category selects existing route policy
- missing category defaults to `OTHER`
- invalid category falls back to `OTHER`
- model is accepted and echoed without whitelist validation
- endpoint skips route classifier
- endpoint does not call answer-generation model
- endpoint returns structured JSON snippets
- endpoint strips snippet header lines from snippet text
- endpoint keeps Syx YAML metadata in snippet text
- endpoint returns parsed Syx metadata when available
- missing Syx metadata fields are omitted best-effort
- retrieval success with no snippets returns `200` with empty snippets
- snippet parse failure returns `500`
- endpoint respects global sleep lock and returns `423`
- existing global sleep middleware allows `POST /agent/memory/search` through to the endpoint
- CLI can call endpoint
- CLI prints raw endpoint JSON to stdout
- CLI writes a debug-style file containing request and response
- CLI exits nonzero on endpoint failure
- existing chat endpoint behavior remains unchanged

## Acceptance Criteria

1. `POST /agent/memory/search` exists.
2. Request uses `project_name`, `query`, `category`, `model`, and `agent_token`.
3. `project_name` resolves to internal `project_id`.
4. Token authorization boundary exists.
5. The endpoint calls the authorization function, even if the implementation is stubbed.
6. The endpoint skips normal route classification.
7. The endpoint uses provided category for retrieval policy.
8. Missing category defaults to `OTHER`.
9. The endpoint runs retrieval-side pipeline only.
10. The endpoint returns structured JSON snippets.
11. The endpoint does not generate an assistant answer.
12. The endpoint does not write memory.
13. The endpoint returns parsed metadata when available, best-effort.
14. The endpoint handles the global sleep lock with retryable `423`.
15. A CLI tool can call the endpoint.
16. CLI output goes to stdout as raw structured JSON.
17. CLI always writes a debug-style file containing the query and response.
18. Existing chat behavior is unchanged.


# DELTA-A.5 — Agent Full-Entry Expansion

## Status

Accepted

## Intent

Update the agent memory search endpoint so bounded Syx results return the complete Syx memory entry instead of the partial expanded chunk/group text returned by A.4.

A.4 created the agent-facing retrieval endpoint and structured snippet response.

A.5 changes bounded snippet text from partial retrieval context to full bounded memory-entry content.

## Background

A.4 returns structured snippets from the retrieval-side pipeline. Each snippet includes metadata such as `memory_id`, `result_mode`, `source_document_id`, chunk index range, topics, and text.

A.4 explicitly deferred full-entry expansion to A.5.

The A.4 response uses:

```text
result_mode: bounded_entry
```

when Syx boundary metadata is available, and:

```text
result_mode: unbounded_chunk_group
```

for ordinary uploads, legacy text, or otherwise unbounded results.

A.4 snippet text may still be partial because it reflects the current expanded chunk/group payload.

A.5 makes bounded entries more useful to agents by returning the complete memory unit.

## Core Rule

For snippets with:

```text
result_mode = bounded_entry
memory_id present
```

A.5 SHALL replace `snippet.text` with the full bounded Syx memory entry body.

The full bounded entry is everything from:

```markdown
<!-- begin syx:memory_id=<memory_id> -->
```

through:

```markdown
<!-- end syx:memory_id=<memory_id> -->
```

excluding the begin and end markers.

The boundary markers SHALL be used for lookup and extraction but SHALL NOT be included in the returned agent-facing text.

The `memory_id` remains available as a structured field on the snippet.

For snippets with:

```text
result_mode = unbounded_chunk_group
```

A.5 SHALL leave `snippet.text` unchanged.

## Non-Goals

A.5 does not:

- add a new endpoint
- change request shape
- change CLI request behavior
- change route classification
- change scoring
- change ordering
- change dedupe/grouping
- change min-score filtering
- write memory
- add MCP integration
- add Cursor write-back
- add summarize/delete operations
- change normal chat behavior

## A.5.1 Full Entry Rehydration

For each A.4 snippet where `result_mode` is `bounded_entry`, the endpoint SHALL rehydrate the full Syx memory entry.

Preferred lookup inputs:

- `memory_id`
- `artifact_path`, when available
- `source_document_id`, when available

The rehydration logic SHALL locate the matching Syx boundary block and return the complete entry text.

Artifact lookup is intentionally scoped to long-term memory upload artifacts. A.5 SHALL resolve artifact reads strictly under:

```text
memory/{project}/uploads/
```

A.5 SHALL NOT search `daily.md`, `sleep_summary.md`, `dream_summary.md`, or other non-upload staging artifacts as part of full-entry expansion.

## A.5.2 Boundary-Based Read

The preferred implementation SHALL read the source artifact and extract the bounded entry by `memory_id`.

Given:

```text
memory_id = mem_20260509_160626_f2734468
```

the system SHALL return all text from:

```markdown
<!-- begin syx:memory_id=mem_20260509_160626_f2734468 -->
```

through:

```markdown
<!-- end syx:memory_id=mem_20260509_160626_f2734468 -->
```

The returned `text` SHALL exclude both boundary markers.

When `artifact_path` is available, it SHALL be treated as an upload-relative artifact path.

When `source_document_id` is used, the substring before `::memory_id=` SHALL be treated as upload-relative by default.

For example:

```text
source_document_id = sleep/sleep_2026-05-09T12-19-36.md::memory_id=mem_20260509_160626_f2734468
```

resolves to:

```text
memory/{project}/uploads/sleep/sleep_2026-05-09T12-19-36.md
```

A.5 SHALL reject unsafe artifact paths. If `artifact_path` or the path parsed from `source_document_id` is absolute, contains `..`, or otherwise resolves outside `memory/{project}/uploads/`, the endpoint SHALL:

1. log a warning
2. skip that path
3. continue to the next fallback step

If boundary extraction finds duplicate matching `memory_id` blocks in the same artifact, A.5 SHALL use the first valid block and log a warning.

## A.5.3 Fallback Behavior

If full-entry rehydration fails for a bounded snippet, the endpoint SHALL not fail the entire request.

Recommended fallback order:

1. Try artifact boundary extraction using `artifact_path` and `memory_id`.
2. Try artifact boundary extraction using `source_document_id` and `memory_id`.
3. Try docstore reconstruction using all chunks with the same `source_document_id`.
4. Fall back to the original A.4 snippet text.

Docstore reconstruction SHALL gather every available chunk with the same `source_document_id`, ordered by `chunk_index`, even if the original A.4 snippet covered a smaller chunk range.

Docstore reconstruction SHALL be considered a fallback path, even when all chunks for the same `source_document_id` are found. Only boundary extraction from the source artifact SHALL count as `expanded`.

If fallback occurs, the snippet SHOULD include:

```json
{
  "entry_expansion_status": "fallback"
}
```

and optionally:

```json
{
  "entry_expansion_error": "<short diagnostic>"
}
```

When docstore reconstruction is used, the snippet SHOULD include:

```json
{
  "entry_expansion_status": "fallback",
  "entry_expansion_method": "docstore_reconstruction"
}
```

If both `artifact_path` and a path parsed from `source_document_id` are available and resolve to different upload-relative artifact paths, A.5 SHALL log a warning before attempting expansion.

The warning SHOULD include:

- `project_id`
- `snippet_number`
- `memory_id`
- `artifact_path`
- parsed `source_document_id` path

A.5 SHALL treat the mismatch as suspicious but non-fatal. Expansion SHALL continue using the normal fallback order.

If expansion succeeds through the source-document-id path after an artifact path mismatch, the snippet SHOULD include:

```json
{
  "entry_expansion_status": "expanded",
  "entry_expansion_method": "source_document_id_boundary",
  "entry_expansion_warning": "artifact_path_source_document_id_mismatch"
}
```

## A.5.4 Response Shape

A.5 SHALL preserve the A.4 structured snippets response shape.

A.5 SHALL NOT add a duplicate top-level `content` field.

For bounded entries, `snippet.text` SHALL become the full bounded entry body without Syx boundary marker comments.

Example:

```json
{
  "snippet_number": 1,
  "source": "ltm",
  "source_document_id": "sleep/sleep_2026-05-09T12-19-36.md::memory_id=mem_20260509_160626_f2734468",
  "chunk_index_start": 0,
  "chunk_index_end": 4,
  "memory_id": "mem_20260509_160626_f2734468",
  "entry_type": "chat_pair",
  "semantic_handle": "summary of memory decay process",
  "topics": [
    "memory decay",
    "passive decay",
    "interference",
    "active forgetting",
    "memory consolidation"
  ],
  "result_mode": "bounded_entry",
  "entry_expansion_status": "expanded",
  "entry_expansion_method": "artifact_path_boundary",
  "text": "<full bounded entry body without begin/end markers>"
}
```

For unbounded snippets:

```json
{
  "snippet_number": 2,
  "memory_id": null,
  "result_mode": "unbounded_chunk_group",
  "entry_expansion_status": "not_applicable",
  "entry_expansion_method": "not_applicable",
  "text": "<existing expanded chunk/group text>"
}
```

## A.5.5 Expansion Status

Each A.5 snippet SHALL include `entry_expansion_status`.

For bounded snippets, the field is required.

For unbounded snippets, the field SHOULD be set to `not_applicable`.

The field SHALL NOT be omitted merely for old-client compatibility. A.5 changes the response schema intentionally, and clients can safely ignore unknown fields.

Allowed values:

```text
expanded
expanded_truncated
not_applicable
fallback
failed
```

Meaning:

```text
expanded:
  bounded entry was successfully extracted from the source artifact using memory_id begin/end markers

expanded_truncated:
  bounded entry was successfully extracted from the source artifact using memory_id begin/end markers, but the returned payload was truncated because it exceeded the configured maximum size

not_applicable:
  result is unbounded and no full-entry expansion applies

fallback:
  source artifact boundary extraction failed, but docstore reconstruction or original A.4 text was returned

failed:
  bounded entry expansion failed and no usable text could be returned
```

A.5 SHOULD avoid `failed` unless the snippet cannot safely return any text.

## A.5.5.1 Expansion Method

Each A.5 snippet SHALL include `entry_expansion_method`.

Allowed values:

```text
artifact_path_boundary
source_document_id_boundary
docstore_reconstruction
original_snippet
not_applicable
```

Meaning:

```text
artifact_path_boundary:
  full entry was extracted from the source artifact using artifact_path and memory_id boundary markers

source_document_id_boundary:
  full entry was extracted by resolving the artifact from source_document_id and using memory_id boundary markers

docstore_reconstruction:
  source artifact boundary extraction failed, and text was reconstructed from docstore chunks with the same source_document_id

original_snippet:
  expansion failed or was unavailable, and the endpoint returned the original A.4 snippet text

not_applicable:
  snippet is unbounded and full-entry expansion does not apply
```

Recommended pairings:

```text
expanded:
  entry_expansion_method = artifact_path_boundary
  or source_document_id_boundary

expanded_truncated:
  entry_expansion_method = artifact_path_boundary
  or source_document_id_boundary

fallback:
  entry_expansion_method = docstore_reconstruction
  or original_snippet

not_applicable:
  entry_expansion_method = not_applicable

failed:
  entry_expansion_method = original_snippet
  or omitted only if no method was attempted
```

## A.5.6 Ordering and Counts

A.5 SHALL preserve snippet order from A.4.

A.5 SHALL preserve:

- `snippet_count`
- `bounded_result_count`
- `unbounded_result_count`

Full-entry expansion SHALL NOT change ranking, filtering, or ordering.

## A.5.7 Size Guard

A.5 SHALL include a configurable maximum expanded entry size.

Setting:

```text
AGENT_MEMORY_MAX_ENTRY_CHARS
```

Default:

```text
25000
```

The setting SHALL be added to backend configuration and local developer configuration helpers such as the Makefile.

`AGENT_MEMORY_MAX_ENTRY_CHARS` applies to the full serialized snippet object, not only to `snippet.text`.

If a source-artifact boundary expansion would cause the serialized snippet object to exceed the configured maximum, the endpoint SHALL truncate safely and mark:

```json
{
  "entry_expansion_status": "expanded_truncated"
}
```

If a docstore reconstruction or original-snippet fallback would cause the serialized snippet object to exceed the configured maximum, the endpoint SHALL truncate safely while preserving:

```json
{
  "entry_expansion_status": "fallback"
}
```

Fallback truncation SHALL still include the truncation-specific metadata below.

When `expanded_truncated` is used, `snippet.text` SHALL NOT synthesize begin or end markers. It SHALL include:

1. a prefix of the entry body
2. a clear truncation notice

The truncation notice SHALL make clear that the returned text is not the complete original entry body.

For docstore reconstruction fallback, A.5 SHALL also respect `AGENT_MEMORY_MAX_ENTRY_CHARS` and use the same truncation metadata when reconstructed text exceeds the configured limit. The status SHALL remain `fallback`.

`entry_expansion_returned_chars` SHALL count the final returned `snippet.text`, including the truncation notice.

`entry_expansion_error` SHALL be used for expansion failures or fallback diagnostics.

It SHOULD be present when:

```text
entry_expansion_status = fallback
entry_expansion_status = failed
```

`entry_expansion_error` SHALL NOT be used for normal truncation. Truncation is a controlled size-guard behavior, not an expansion error.

If text is truncated, the snippet SHOULD include truncation-specific metadata:

```json
{
  "entry_expansion_status": "expanded_truncated",
  "entry_expansion_truncated": true,
  "entry_expansion_original_chars": 42850,
  "entry_expansion_returned_chars": 12000,
  "entry_expansion_max_chars": 12000,
  "entry_expansion_truncation_reason": "max_chars_exceeded"
}
```

For fallback truncation, the same truncation metadata applies, but `entry_expansion_status` SHALL remain `fallback`.

## A.5.8 Debug Output

The endpoint or CLI debug output SHOULD record:

- number of bounded snippets
- number successfully expanded
- number expanded with truncation
- number using fallback
- number failed
- memory IDs expanded
- boundary lookup failures
- path containment rejections
- artifact/source-document path mismatches
- whether any entry was truncated

## A.5.9 Existing A.4 Behavior Preserved

A.5 SHALL preserve all A.4 endpoint behavior except bounded snippet text expansion.

A.5 SHALL continue to:

- accept `project_name`
- resolve `project_id`
- require `agent_token` field
- use provided category
- skip route classification
- skip answer generation
- return structured JSON snippets
- enforce min-score behavior
- return empty snippets when no results pass threshold
- respect global sleep lock

## Test Targets

Tests SHOULD cover:

- bounded snippet expands to full begin/end entry
- expanded text includes begin marker
- expanded text includes end marker
- expanded text includes content beyond original chunk range
- unbounded snippet text remains unchanged
- ordering is preserved
- counts are preserved
- expansion fallback returns original snippet text
- missing artifact path falls back safely
- missing boundary returns fallback status
- no top-level duplicate `content` field is added
- CLI debug file records expansion status
- CLI debug file records expansion method
- size guard truncates oversized bounded entries
- truncated text excludes begin and end Syx markers
- truncation metadata is returned for `expanded_truncated`
- `entry_expansion_error` is not used for normal truncation
- unsafe artifact paths are rejected and fall back safely
- duplicate matching `memory_id` blocks use the first block and log a warning
- docstore reconstruction gathers chunks with the same `source_document_id` ordered by `chunk_index`
- docstore reconstruction is reported as fallback
- normal chat behavior remains unchanged

## Acceptance Criteria

1. Bounded snippets return full Syx memory entries in `text`.
2. Full bounded entry text excludes begin and end Syx markers.
3. Unbounded snippets remain unchanged.
4. A.4 response shape is preserved.
5. Snippet ordering is preserved.
6. Counts are preserved.
7. Expansion failures do not fail the whole request.
8. Expansion status is exposed per snippet.
9. Expansion method is exposed per snippet.
10. Bounded artifact paths are resolved only under `memory/{project}/uploads/`.
11. Unsafe paths are rejected and fall back safely.
12. Oversized expanded payloads respect `AGENT_MEMORY_MAX_ENTRY_CHARS`.
13. Truncated bounded text excludes begin and end Syx markers and includes truncation metadata.
14. Docstore reconstruction is treated as fallback.
15. No memory is written.
16. Normal chat behavior is unchanged.

# DELTA-B — Multi-Provider LLM Model Support

## Status

Accepted

## Intent

Allow Syx to support multiple LLM providers and model families behind one provider-agnostic runtime boundary.

The first target is Anthropic support alongside the existing OpenAI support. Before adding Anthropic-specific code, the LLM factory must stop leaking the concrete OpenAI provider type into the application boundary.

## Background

Syx currently has provider-oriented package structure under `backend/app/llm_model/`, but the factory still returns `OpenAILLMProvider` directly:

```python
def get_llm_client() -> OpenAILLMProvider:
```

That means the current implementation centralizes construction, but it does not fully enforce a provider-agnostic application contract. Runtime code can still become coupled to OpenAI-shaped behavior, and adding Anthropic would layer a second provider onto an abstraction that already leaks the first provider.

The UI model selector currently selects a model id from `/models`. It does not select a provider. Helper models such as builder and tagger are configured by environment variables (`BUILDER_MODEL`, `TAGGER_MODEL`, and mini-client defaults) rather than by the UI.

That creates a multi-provider problem: switching from OpenAI to Anthropic cannot require the user to manually rewrite every helper-model environment variable. Main chat, mini/helper defaults, builder, tagger, and Dream model choices must be resolved as a coherent provider-scoped model set.

## Core Decision

Syx SHALL support multiple LLM providers through explicit provider interfaces and a factory/registry boundary.

Application code SHALL depend on provider-agnostic LLM interfaces, not concrete provider classes.

Provider-specific SDK imports and request/response adaptation SHALL remain behind provider implementation modules.

## B.1.1 Provider-Agnostic Factory Boundary

### Intent

Refactor the current LLM factory so it returns provider-agnostic interfaces instead of `OpenAILLMProvider`.

This is a prerequisite for Anthropic support.

### Requirements

1. `backend/app/llm_model/factory.py` SHALL NOT expose concrete provider classes in public return types for `get_llm_client()` or `get_llm_client_mini()`.
2. The factory SHALL return a provider-agnostic interface that supports the current runtime call surface:
   - `generate_chat`
   - `stream_chat`
   - `generate_response`
3. The provider-agnostic factory return type SHALL be a new combined protocol in `backend/app/llm_model/base.py` that includes `generate_chat`, `stream_chat`, and `generate_response`.
4. Provider-specific request shapes SHALL NOT leak into application code. In particular, OpenAI-shaped tool payloads such as `tools=[{"type": "web_search"}]` SHALL remain behind the provider implementation boundary rather than becoming the provider-agnostic application contract.
5. Remote/web research SHALL be represented as a provider-agnostic LLM capability, such as `generate_response_research`, so callers can request research without knowing how a concrete provider implements it.
6. Concrete provider classes such as `OpenAILLMProvider` SHALL remain implementation details behind the factory boundary.
7. Existing main and mini client caching behavior SHALL be preserved unless explicitly superseded by a later B.1 requirement.
8. `reset_llm_clients()` SHALL continue to clear all cached LLM clients used by the factory.
9. Unsupported `LLM_PROVIDER` values SHALL fail clearly or be handled by an explicitly documented fallback policy. Silent provider fallback SHOULD NOT be introduced for multi-provider support.
10. Existing OpenAI runtime behavior SHALL remain unchanged after the factory boundary refactor.

### Non-Goals

B.1.1 does not:

- add Anthropic API calls
- add Anthropic configuration
- change the UI model selector
- make provider selection per-model in the UI
- change builder, tagger, or Dream model routing
- change request or response shapes for chat endpoints

### Test Targets

Tests SHOULD cover:

- `get_llm_client()` returns an object satisfying the provider-agnostic LLM interface
- `get_llm_client_mini()` returns an object satisfying the provider-agnostic LLM interface
- OpenAI remains the default provider when `LLM_PROVIDER=openai`
- main and mini clients remain separately cached
- `reset_llm_clients()` clears both cached clients
- unsupported provider handling is explicit and deterministic
- application call sites do not import or require `OpenAILLMProvider`
- application call sites do not pass OpenAI-shaped tool payloads for research

### Acceptance Criteria

1. Factory public return types are provider-agnostic.
2. OpenAI-specific SDK and provider implementation details remain behind the provider module boundary.
3. Existing OpenAI chat, streaming, builder, tagger, and Dream paths continue to use the same call contracts, with OpenAI-specific research/tool adaptation hidden behind the provider boundary.
4. Existing tests for the OpenAI factory path continue to pass.
5. The codebase is ready for an Anthropic provider implementation without changing application call sites again.

## B.1.2 Provider Model Registry and Runtime Model Sets

### Status

Draft

### Intent

Make main and helper model selection provider-scoped so a user can switch supported providers without manually editing each model environment variable.

The UI model selector SHALL carry provider identity as part of the selection. Selecting a model from a provider SHALL select the provider, make that model the main chat model, and resolve mini/helper, builder, tagger, and Dream defaults from the same provider's registry entry.

The model/provider inventory SHALL live in an app-owned JSON registry, not in `.env`.

### Requirements

1. Syx SHALL add an app-owned LLM model registry JSON file under `backend/app/config/`.
2. The default registry path SHOULD be:

   ```text
   backend/app/config/llm_models.json
   ```

3. The model registry SHALL define a provider-scoped runtime model set for each supported LLM provider.
4. Each provider entry SHALL include:
   - provider id
   - provider display label
   - provider implementation key used by the factory
   - selectable main chat models
   - default main chat model
   - role defaults for helper/runtime model roles
5. The runtime model roles SHALL include at least:
   - main chat model
   - mini/default helper model
   - builder/router model
   - tagger model
   - Dream model
6. `LLM_PROVIDER` SHALL select the startup/default provider by provider id.
7. The UI model selector SHALL expose provider-aware model choices from the registry. It SHOULD present providers first and then provider-scoped models (for example, a provider dropdown whose hover/menu exposes that provider's models, or an equivalent grouped selector).
8. The model selection value sent to the backend SHALL include both provider id and model id. A compact string form such as `provider/model` is acceptable if it is parsed and validated explicitly; a structured `{ provider, model }` contract is also acceptable if the request/response schemas are updated accordingly.
9. When the UI selects a provider/model pair, Syx SHALL treat the selected provider as the runtime provider for that chat request/session, treat the selected model as the main chat model, and resolve mini/helper, builder, tagger, and Dream model defaults from that provider's registry entry unless the user has explicitly configured compatible role-specific overrides.
10. A requested chat model SHALL be valid only when it belongs to the selected provider's selectable main chat models. Model ids from other registry providers SHALL be rejected unless a later requirement introduces cross-provider per-request routing.
11. When only `LLM_PROVIDER` is configured and no UI provider/model selection is supplied, Syx SHALL resolve the default main model and all runtime model roles from the selected provider's registry entry.
12. `.env.example` and `make setup-env` SHALL NOT hard-code `AVAILABLE_MODELS` as the source of truth for the UI selector once the registry is implemented.
13. `AVAILABLE_MODELS` SHALL be removed, deprecated, or treated only as an explicit advanced override after the registry exists. The default path SHALL be registry-driven.
14. Main, mini/helper, builder, tagger, and Dream model defaults SHALL be resolved from the selected provider's registry entry. The normal setup path SHALL NOT require `MODEL_NAME`, `LLM_MINI_MODEL`, `BUILDER_MODEL`, `TAGGER_MODEL`, or `DREAM_MODEL`.
15. The mini client SHALL not be treated as a provider-independent OpenAI-only fallback. Its default model SHALL be resolved from the selected provider's helper-model defaults.
16. The system SHALL expose enough configuration metadata for local setup tooling to generate a coherent `.env` template for the selected provider.
17. If a role-specific model override is configured but does not belong to the selected provider's allowed model set, startup or request preflight SHALL fail clearly with a provider/model compatibility error.
18. Provider-scoped defaults SHALL preserve the current OpenAI defaults when `LLM_PROVIDER=openai`.
19. If the registry is missing, malformed, or lacks the selected provider, startup SHALL fail clearly before accepting chat requests.

### Registry Shape

The registry SHOULD use a shape close to:

```json
{
  "providers": {
    "openai": {
      "label": "OpenAI",
      "factory_provider": "openai",
      "default_model": "gpt-5.5",
      "models": [
        { "id": "gpt-5.5", "label": "GPT-5.5" },
        { "id": "gpt-5-mini", "label": "GPT-5 Mini" }
      ],
      "roles": {
        "mini": "gpt-5-mini",
        "builder": "gpt-5-mini",
        "tagger": "gpt-5-mini",
        "dream": "gpt-5.5"
      }
    }
  }
}
```

The exact JSON schema MAY evolve during implementation, but the registry SHALL remain the canonical source for provider-owned default model lists and role defaults.

### Environment Policy

`.env` SHOULD carry provider selection and credentials, not the default model inventory.

Recommended baseline:

```text
LLM_PROVIDER=openai
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
```

Role-specific environment variables such as `MODEL_NAME`, `LLM_MINI_MODEL`, `BUILDER_MODEL`, `TAGGER_MODEL`, and `DREAM_MODEL` are no longer part of the normal setup path once the registry exists. `LLM_PROVIDER` selects the startup/default provider, and the registry supplies the provider's default runtime model set.

When a provider/model pair is supplied by the UI, that selection takes precedence over the startup `LLM_PROVIDER`/`MODEL_NAME` pair for the main chat model and provider-scoped runtime model set.

### Non-Goals

B.1.2 does not require maintaining multiple provider clients hot in memory before a provider/model pair is selected.

B.1.2 does not require the UI to expose builder, tagger, Dream, or mini model controls.

B.1.2 does not implement the Anthropic SDK provider; that belongs to B.1.3.

### Test Targets

Tests SHOULD cover:

- OpenAI provider resolves the existing OpenAI main/helper defaults.
- Anthropic provider resolves Anthropic-compatible main/helper defaults once Anthropic support exists.
- `/models` reads provider-aware selectable model data from the registry rather than `AVAILABLE_MODELS`.
- UI model selection carries provider id and model id to the backend.
- selected provider/model pairs resolve a coherent provider-scoped runtime model set.
- model validation rejects a model id that does not belong to the selected provider.
- normal setup does not require `MODEL_NAME`, `LLM_MINI_MODEL`, `BUILDER_MODEL`, `TAGGER_MODEL`, or `DREAM_MODEL`.
- generated local environment defaults stay internally coherent for the selected provider.
- malformed or missing registry entries fail clearly.

### Acceptance Criteria

1. Provider selection determines a coherent default model set for all runtime LLM roles.
2. Helper model defaults are no longer accidentally tied to OpenAI when another provider is selected.
3. Users can switch to a supported provider/model pair from the UI without manually editing each helper model.
4. Existing OpenAI defaults and behavior remain unchanged unless explicitly overridden.
5. The UI model inventory is provider-aware and registry-driven, not `.env` `AVAILABLE_MODELS` driven.
6. `make setup-env` and `.env.example` no longer present `AVAILABLE_MODELS` as the normal source of selectable chat models.

## B.1.3 Anthropic Provider Support

### Status

Implemented

### Intent

Add an Anthropic-backed LLM provider implementation behind the B.1.1 provider-agnostic factory boundary.

### Requirements

1. Syx SHALL add configuration for Anthropic credentials without reusing OpenAI-specific settings names.
2. `LLM_PROVIDER=anthropic` SHALL construct an Anthropic provider through the same factory boundary used by OpenAI.
3. Anthropic request and response envelopes SHALL be normalized into the same project `LLMResponse` and `LLMUsage` structures used by existing code.
4. Provider-specific preflight checks SHALL replace OpenAI-only key validation for chat startup and request handling.
5. Main, mini, builder, tagger, and Dream model configuration SHALL use the provider-scoped model resolution defined in B.1.2 before Anthropic is enabled for those paths.
6. B.1.3 SHALL use `ANTHROPIC_API_KEY` for Anthropic credentials.
7. The Anthropic registry entry SHALL use:
   - main: `claude-sonnet-4-6`
   - mini/helper: `claude-haiku-4-5-20251001`
   - builder: `claude-haiku-4-5-20251001`
   - tagger: `claude-haiku-4-5-20251001`
   - Dream: `claude-sonnet-4-6`
8. The Anthropic registry entry SHALL also expose selectable frontier models:
   - `claude-fable-5`
   - `claude-opus-4-8`
9. Anthropic remote research SHOULD use Anthropic's server-side web search tool when available behind `generate_response_research`.

### Non-Goals

B.1.3 does not require changing the B.1.2 provider/model selection contract.

### Acceptance Criteria

1. `LLM_PROVIDER=anthropic` constructs an Anthropic provider through `llm_model.factory`.
2. Anthropic chat, streaming, prompt/response, and research calls return normalized `LLMResponse` and `LLMUsage` envelopes.
3. Chat preflight and app health validate the active provider key instead of assuming OpenAI.
4. `/models` exposes Anthropic provider-qualified model choices without changing the B.1.2 response shape.

## B.1.4 Advanced Provider-Aware Model Selection

### Status

Future-facing

### Intent

Refine provider-aware model selection beyond the B.1.2 baseline when Syx needs richer multi-provider UX, per-request routing, or concurrent provider clients.

### Notes

B.1.2 introduces the required baseline: registry-backed provider/model choices and a backend contract that carries provider id plus model id. B.1.4 is reserved for advanced behavior beyond that baseline.

### Requirements

1. Syx MAY add richer provider metadata such as credential status, provider health, model capabilities, context limits, or research/tool support.
2. Syx MAY support caching multiple provider clients concurrently, keyed by provider and role.
3. Syx MAY add per-request provider routing for conversations that intentionally switch providers within one server process.
4. Syx MAY add UI affordances for comparing providers, pinning provider/model defaults per project, or exposing helper-role defaults for advanced users.
5. Any advanced behavior SHALL preserve the B.1.2 provider/model selection contract or explicitly migrate it with backward-compatible API handling.

### Future Work

A later advanced provider-aware selector may need:

- provider-specific credential status in health checks
- provider-specific client caching keyed by provider
- clear behavior for helper models that are not selected by the UI
- per-project persisted provider/model preferences
- explicit model capability metadata

### Acceptance Criteria

1. Advanced provider metadata is exposed without regressing the B.1.2 selection contract.
2. Concurrent provider-client caching, if added, is keyed by provider and role.
3. Per-request provider routing, if added, validates provider/model compatibility clearly.

