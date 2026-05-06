# Engineering Deltas

## DELTA-LLM-001 — Dream LLM Calls Use Core Runtime

Dream agents no longer expose or call a `dream_llm_call` wrapper. Dream LLM access now calls `backend.app.core.llm.generate_text_response` directly so runtime model/provider access stays centralized in core and `llm_model.factory`.

Dream-specific prompt and usage artifacts remain owned by the Dream package in `backend.app.dream.debug`; core LLM code must not know about Dream debug filenames or `dream_purpose` metadata. Dream prompt-to-execute snapshots are written under `debug/dreaming/`; `debug/prompts/` remains reserved for core chat, builder, tagger, and pruning prompt snapshots.

## DELTA-LLM-002 — Model Defaults and Main Model Key

`MODEL_NAME` is the authoritative main chat/reasoning model key. `LLM_MAIN_MODEL` is removed and must not be used by runtime code, generated environment files, or frontend defaults.

Default model values:
- Main chat/reasoning and Dream: `gpt-5.5`
- Mini/helper client, Builder, and Tagger: `gpt-5-mini`

## DELTA-DREAM-001 — Accepted Research Topics in Summary Card

`latest_sleep_summary.txt` remains the source for the project Dream summary card. When Dream research items are accepted, either by sleep auto-accept or the manual Dream keep endpoint, the summary file appends a `[RESEARCH]` block containing deduplicated accepted research topics in first-seen order:

```
[RESEARCH]
Topic: ...
Topic: ...
```

The block is omitted when no accepted research topics are present.
