# Config Settings Matrix

This matrix reconciles `Makefile` `setup-env` values with `backend/app/core/config.py` and runtime usage.

## Source of truth
- Runtime defaults are defined in `backend/app/core/config.py` (`Settings`).
- `Makefile` `setup-env` should mirror those defaults for generated `.env` values.

## Removed as unused

These settings were present in `Makefile` and/or `config.py` but had no runtime consumers in backend code:

- `LOG_FORMAT`
- `DATA_ROOT`
- `RUNTIME_ROOT`
- `PAYLOAD_MAX_BYTES`
- `DAILY_RAG_ENABLED` (global config flag; per-project DB flag remains authoritative)
- `DAILY_RAG_WEIGHT`
- `DEDUPE_EXACT`
- `DEDUPE_NEAR`
- `DEDUPE_SIMILARITY_THRESHOLD`
- `DEDUPE_KEEP_DAILY`
- `BUILDER_CONFIDENCE_MIN`
- `TOPIC_BOOST`
- `DECISION_BOOST`
- `QUESTION_BOOST`
- `STREAM_FLUSH_MS`
- `STREAM_TIMEOUT_MS`
- `MAX_WORKERS`
- `DREAM_TOPIC_BOOST`

## Defaults aligned

The following generated `.env` defaults were aligned to `config.py` defaults:

- `MODEL_MAX_TOKENS=32000`
- `CHUNK_SIZE=800`
- `CHUNK_OVERLAP=100`
- `MAX_EMBED_TOKENS_PER_REQUEST=250000`
- `RAG_EMBED_REBUILD_WORKERS=1`
- `BASE_TOP_K=5`
- `CHAT_HISTORY_LIMIT_PAIRS=10`
- `DEFAULT_SYSTEM_PROMPT_PATH=backend/app/config/defaults/system_prompt.txt`
- `DEFAULT_PERSONALITY_PROMPT_PATH=backend/app/config/defaults/personality.json`
- `FORCE_RAG_REBUILD_ON_STARTUP=false`
- `GENERATE_DEBUG_FILES=false`

## Operational fixes

- Replaced hardcoded API key in `Makefile` template with `your-openai-api-key-here`.
- Corrected `make run` docs URL output to `/api/docs`.
- Kept `VITE_SHOW_DEBUG_VALUES` as frontend-only and explicitly non-runtime in backend config.
