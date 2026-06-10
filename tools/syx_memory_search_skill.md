## Purpose

Use the approved local Syx memory search wrapper to query project memory and turn results into Obsidian notes, maps, summaries, research traces, and topic-walk outputs.

This skill is for read-only retrieval from Syx memory. It does not modify Syx runtime memory.
## Approved Command  

Use only this command for Syx memory search:

```bash

tools/syx_memory_search.sh --project-name "<project>" --query "<query>" --category "<category>"

```

Run the command from the Syx repository root, or call it by absolute path from
another working directory. The wrapper resolves the repository path from its own
location by default.

Example:

```bash

tools/syx_memory_search.sh \

--project-name "Main" \

--query "Find early AGI architecture memories. Context: AGI origin notes. Include: modular architecture, memory, curiosity, sleep cycle, symbolic reasoning." \

--category "SYNTHESIS"

```

## Categories

Use one of the following categories:

- `DIRECT` for narrow factual lookups with a specific target.

- `PROCEDURAL` for implementation, configuration, setup, or execution guidance.

- `EXPLORATORY` for investigation, comparison, or broad understanding.

- `SYNTHESIS` for design synthesis, planning, tradeoffs, idea evolution, and architecture mapping.

- `OTHER` only as a fallback when no better category fits.

Default to `SYNTHESIS` for Syx architecture, AGI, memory, dream, sleep, topic-walk, and idea-evolution work.

## Rules

- Do not call `tools/agent_memory_search.py` directly.

- Do not access the Syx application repo directly unless explicitly instructed.

- Do not modify Syx runtime memory.

- Do not run sleep, dream, prune, rebuild, delete, or write commands.

- Treat the wrapper output as read-only retrieval results.

- Preserve memory IDs, source filenames, semantic handles, topics, decisions, and open questions when present.

- Mark uncertainty when results are weak, incomplete, or conflicting.

- Write generated notes only inside the current note workspace.

- Do not inspect any `archive/` folder unless explicitly instructed.

- Do not edit `REQUIREMENTS.md` or `DELTAS.md` unless explicitly instructed.

## Query Pattern

Use queries in this form:

```text

<retrieval objective>. Context: <project, source article, semantic handle, or topic cluster>. Include: <known terms, requirement IDs, deltas, files, decisions, constraints>.

```

Examples:

```text

Find early AGI architecture memories. Context: AGI origin notes. Include: modular architecture, memory, curiosity, sleep cycle, symbolic reasoning.

```

```text

Find implementation guidance, requirements, design decisions, constraints, and known pitfalls for the agent memory search endpoint. Context: DELTA-A.4 external agent memory search.

```

```text

Find prior decisions and constraints about memory decay, pruning, sleep cycle, and reconsolidation. Context: research plan for memory reconsolidation neuroscience.

```

```text

Find file locations, requirements, and behavior for full Syx memory entry expansion. Context: DELTA-A.5 bounded entry expansion agent memory.

```

## Topic Walk Process

Use this process when asked to explore memory from seed topics or source articles.

1. Identify the project name to query.

2. Extract seed terms from the user request, source article, title, headings, repeated phrases, named concepts, strong claims, and unusual terminology.

3. Group seed terms into 3 to 6 topic clusters.

4. Run one memory search per topic cluster.

5. Inspect returned memory IDs, topics, decisions, open questions, source filenames, and semantic handles.

6. Extract high-value related topics from the results.

7. Run at most one follow-up query per high-value related topic.

8. Stop when the query budget is reached or no new high-value topics appear.

9. Create generated notes in the requested output folder.
## Topic Walk Stop Rules

- Max initial topic-cluster queries: 6.

- Max follow-up queries: 8.

- Max total queries: 14.

- Do not recursively expand forever.

- Maintain a visited topic list.

- Maintain a visited memory/source list.

- Prefer fewer high-quality notes over many shallow notes.
## Output Expectations

When creating notes from memory search results, include:

- search objective

- project queried

- queries run

- key memory IDs

- source files or semantic handles

- topics discovered

- decisions found

- open questions found

- synthesis

- uncertainty notes

## Human-Readable Note Format

Generated chat notes should be readable first and auditable second.

Put memory IDs, source handles, exact queries, scores, and expansion statuses in an `Evidence Appendix` at the end of the note unless the user specifically asks for an audit-first format.

Preferred order:

1. Human summary
2. How the idea evolved
3. Key Syx connections
4. Decisions and open questions
5. Uncertainty notes
6. Evidence appendix

Do not lead with memory IDs unless creating a debugging report.
## Suggested Output Structure

For article-evolution or AGI/Syx synthesis work, use:

```text

generated/article_evolution/

Article_Topic_Walk_Map.md

Idea_Evolution_Summary.md

Lessons_Learned.md

topics/

<Topic_Name>.md

```

For general topic-walk work, use:

```text

generated/topic_walks/

<Topic>_Topic_Walk_Map.md

<Topic>_Lessons_Learned.md

```

## Lessons Learned Notes

When the goal is experimental, create a `Lessons_Learned.md` file that answers:

- What terms worked as seeds?

- What terms were noisy?

- Which topics acted as bridges?

- Which memory IDs looked central?

- Where did the search need full record expansion?

- What should `topic_graph.json` expose?

- What should `GET /memory/{memory_id}` return?

## Restrictions

- Read-only Syx memory access only.

- Do not modify Syx runtime memory.

- Do not run sleep, dream, prune, rebuild, delete, or write commands.

- Do not edit linked project files unless explicitly instructed.

- Do not invent decisions.

- Preserve uncertainty.

## Backend Expansion Semantics

The Syx agent memory endpoint may return bounded-entry results.

Important fields:

- `bounded_result_count`: number of results resolved to Syx memory boundaries.
- `unbounded_result_count`: number of fallback/unbounded results.
- `entry_expansion_status`: expansion state for each snippet.
- `entry_expansion_status = expanded`: the backend expanded the full bounded memory entry.
- `entry_expansion_status = expanded_truncated`: the backend found and expanded the bounded entry, but the returned text was truncated due to max character limits.
- `entry_expansion_status = fallback`: the backend could not expand from a Syx boundary and returned fallback chunk text.
- `entry_expansion_status = failed`: expansion failed.

Do not say a memory "was not expanded" merely because `semantic_handle`, `topics`, or other metadata fields are missing.

Use this wording instead:

- If `expanded`: "bounded memory entry expanded"
- If `expanded_truncated`: "bounded memory entry expanded but truncated"
- If metadata is missing: "metadata field not returned"
- If fallback: "returned as fallback chunk, not bounded expansion"
- If failed: "entry expansion failed"