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

Draft

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
