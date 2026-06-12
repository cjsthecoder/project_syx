# Dream Cycle

Dream is Syx's post-Sleep reasoning phase. It runs after Sleep has produced `sleep_summary.md` and before Sleep merges per-cycle artifacts into long-term RAG.

Dream is experimental. It is intended to explore how a system can interpret consolidated memory, surface unresolved questions, and create candidate insights for later review or persistence.

## Relationship to Sleep

Dream is not a standalone scheduler. It is invoked from the Sleep pipeline for each project that has non-empty Daily memory.

The order is:

```text
Sleep flushes active chat to Daily
  |
  v
Sleep writes sleep_summary.md
  |
  v
Dream runs questions / idea / research stages
  |
  v
Dream writes dream.json
  |
  v
Sleep may auto-accept dream.json into dream_summary.md
  |
  v
Sleep writes uploads/sleep and uploads/dream artifacts
  |
  v
Sleep rebuilds FAISS
```

Dream failures are logged as non-fatal to Sleep. Sleep continues to merge Sleep artifacts even when Dream fails.

## Enable and Disable

Dream is controlled by:

```text
ENABLE_DREAM=true|false
```

When `ENABLE_DREAM=false`, the Dream orchestrator returns without running any Dream stages.

Related settings:

- `DREAM_MODEL`
- `DREAM_TEMPERATURE`
- `DREAM_MAX_TOKENS`
- `DREAM_ENABLE_REMOTE_RESEARCH`
- `DREAM_REMOTE_CONTEXT_MAX_TOKENS`
- `AUTO_ACCEPT_DREAMS`
- `GENERATE_DEBUG_FILES`

Runtime defaults live in `backend/app/core/config.py`, and the public environment template is `.env.example`.

## Inputs

Dream uses project memory artifacts produced or prepared by Sleep:

```text
data/memory/{project_id}/sleep_summary.md
data/memory/{project_id}/open_questions_consolidated.json
data/memory/{project_id}/open_questions.jsonl
```

`sleep_summary.md` is the main memory context for Dream.

Open questions begin in `open_questions.jsonl`, an append-only project stream. Sleep consolidates that stream before Dream runs, and Dream consumes the consolidated question input.

Dream may also retrieve supporting context from project RAG for user profile, project system rules, and topic enrichment.

## Dream Stages

The main orchestrator lives in `backend/app/dream/dreams.py`.

Dream currently runs three main stages:

1. Questions stage
2. Idea stage
3. Research stage

Each stage writes debug artifacts for local inspection.

## Questions Stage

The Questions stage reads consolidated question input:

```text
data/memory/{project_id}/open_questions_consolidated.json
```

It runs the Questions Agent and produces an in-memory questions result for the rest of Dream.

Debug artifacts include:

```text
debug/dreaming/{timestamp}_questions_in.txt
debug/dreaming/{timestamp}_questions_out.txt
```

## Dream Context

Before the Idea stage, Dream builds a context block in `backend/app/dream/context.py`.

The context can include:

- User profile context.
- Project system prompt context.
- A generated project context summary from `sleep_summary.md`.
- Question/answer results from the Questions stage.
- Daily memory text from `sleep_summary.md`.
- RAG enrichment based on topics found in `sleep_summary.md`.

Dream context generation can call the configured Dream model to summarize project context. If that model call fails, the failure is logged and Dream continues with a fallback string.

## Idea Stage

The Idea stage receives the Dream context and runs the Idea Agent.

It then:

- Attaches source-resolution information to generated items.
- Filters idea items to known questions.
- Bridges remote-backed questions into idea items so Research can process them.
- Writes a bridge report.

Debug artifacts include:

```text
debug/dreaming/{timestamp}_dream_context.txt
debug/dreaming/{timestamp}_idea_output.txt
debug/dreaming/{timestamp}_bridge_report.txt
```

## Research Stage

The Research stage receives bridged idea data and the project summary text.

It:

- Builds a research plan.
- Runs the Research Agent.
- Optionally uses remote research when enabled.
- Writes final Dream output to `dream.json`.

Debug artifacts include:

```text
debug/dreaming/{timestamp}_research_plan.txt
debug/dreaming/{timestamp}_research_results.txt
debug/dreaming/{timestamp}_research.txt
debug/dreaming/{timestamp}_dream_write.txt
```

The final pending Dream output is:

```text
data/memory/{project_id}/dream.json
```

## Remote Research

Remote research is controlled by:

```text
DREAM_ENABLE_REMOTE_RESEARCH=true|false
DREAM_REMOTE_CONTEXT_MAX_TOKENS=32000
```

When remote research is enabled, the Research Agent may use remote research capabilities for questions that require outside context. When disabled, remote-backed items should not rely on remote lookup.

Any content sent to external providers is subject to the provider's policies. Do not use remote research with private or regulated data unless you have reviewed the provider terms and your deployment constraints.

## Dream Output

Dream writes:

```text
data/memory/{project_id}/dream.json
```

`dream.json` contains a project summary and pending Dream items. It is the UI-facing review artifact for Dream.

The frontend can read it through project Dream APIs and present items for review. Pending items can later be remembered or filtered out.

If `dream.json` already exists, new Dream output merges with existing pending items instead of blindly discarding them.

## Auto-Accept

Auto-accept is controlled by:

```text
AUTO_ACCEPT_DREAMS=true|false
```

When enabled, Sleep processes pending `dream.json` items after Dream runs.

Auto-accept:

1. Reads `dream.json`.
2. Filters remote items that lack valid research evidence.
3. Converts processable items into memory pairs.
4. Tags each memory pair.
5. Appends the pair into Daily memory as Dream-originated memory.
6. Writes `dream_summary.md`.
7. Rebuilds the Daily cache.
8. Deletes `dream.json` only after a clean successful run.

Malformed or failed `dream.json` processing can quarantine the file as `bad_dream_{timestamp}.json`.

## Dream Summary and Long-Term Memory

Accepted Dream items can be rendered into:

```text
data/memory/{project_id}/dream_summary.md
```

During the Sleep merge phase, `dream_summary.md` is written to:

```text
data/memory/{project_id}/uploads/dream/dream_{cycle_ts}.md
```

Then Sleep rebuilds FAISS, and the Dream artifact becomes part of long-term project retrieval.

After successful consolidation, `dream_summary.md` is removed. The per-cycle upload artifact remains.

## Latest Sleep Summary

When Dream items are accepted, Syx can write:

```text
data/memory/{project_id}/latest_sleep_summary.md
```

This gives the UI a compact summary of accepted Dream/Sleep outcomes even after `dream.json` has been deleted.

## Debug Files

Dream debug output is local runtime data and may contain sensitive content.

Common debug paths:

```text
data/memory/{project_id}/debug/dreaming/
data/memory/{project_id}/debug/prompts/
data/memory/{project_id}/debug/rag/
```

Debug files may contain:

- Dream prompts.
- Model outputs.
- Research plans.
- Research results.
- RAG context.
- Project summaries.
- Question inputs and outputs.

Do not commit Dream debug files unless they are intentionally sanitized examples.

## Failure Handling

Dream is best-effort and non-fatal to Sleep:

- If `ENABLE_DREAM=false`, Dream does nothing.
- If one Dream stage fails, the failure is logged.
- Dream exceptions are swallowed at the boundary so Sleep can continue.
- `dream.json` write failures are logged and suppressed.
- Auto-accept accumulates errors instead of raising.
- Failed auto-accept can mark Sleep partial, but should not crash the process.

## Security and Privacy

Dream reads project memory and can send prompts to configured model providers. It may also use remote research when enabled.

Treat the following as sensitive:

- `sleep_summary.md`
- `dream.json`
- `dream_summary.md`
- `uploads/dream/*.md`
- Dream debug artifacts
- Research outputs
- RAG context used for Dream

For project-level security guidance, see `SECURITY.md`.

## How to Verify Dream Ran

After a Sleep cycle processes a project, inspect:

```text
data/memory/{project_id}/dream.json
data/memory/{project_id}/dream_summary.md
data/memory/{project_id}/uploads/dream/
data/memory/{project_id}/debug/dreaming/
data/memory/{project_id}/latest_sleep_summary.md
```

Depending on settings and whether Dream produced/accepted items:

- `dream.json` may exist with pending review items.
- `dream_summary.md` may exist temporarily before merge.
- `uploads/dream/dream_{cycle_ts}.md` may exist after accepted Dream memory is consolidated.
- `latest_sleep_summary.md` may describe accepted items.
- Debug files may exist when debug output is enabled.

## Relationship to Other Docs

- `docs/memory_lifecycle.md` explains where Dream fits in the overall memory flow.
- `docs/sleep_cycle.md` explains how Sleep invokes Dream.
- `docs/agent_interface.md` explains how external local tools can later retrieve Dream artifacts through RAG.
