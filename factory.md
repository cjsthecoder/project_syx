# Factory Migration Log

## Step A - Baseline inventory
- Mapped all LLM call paths (chat runtime, streaming, builder, tagger, dream).
- Mapped all embedding call paths (RAG rebuild, daily cache rebuild, query embedding).
- Confirmed all LangChain runtime imports and direct `OpenAI(...)` callsites.

## Step B - LLM factory contract
- Added provider-agnostic interfaces in `backend/app/llm_model/base.py`.
- Added usage/response envelopes (`LLMUsage`, `LLMResponse`) for plain-data boundaries.

## Step C - LLM provider package
- Added `backend/app/llm_model/providers/openai_provider.py`.
- Added `backend/app/llm_model/factory.py` with main/mini client factory functions.
- Updated `backend/app/llm_model/__init__.py` exports.

## Step D - Chat/runtime migration
- Replaced `backend/app/core/llm.py` LangChain runtime with factory-based runtime.
- Updated `backend/app/api/chat.py` streaming and non-streaming paths to use the factory client.
- Removed LangChain imports and callback/message dependencies from chat API runtime.

## Step E - Mini-model caller migration
- Updated `backend/app/core/query_builder.py` to use `get_llm_client_mini()` responses calls.
- Updated `backend/app/tagging/tagger.py` to use `get_llm_client_mini()` responses calls.
- Added explicit `TAGGER_MODEL` usage in tagger flow.

## Step F - Embedding factory contract
- Added embedding interface/envelope in `backend/app/embedding/base.py`.
- Added `backend/app/embedding/factory.py`.

## Step G - OpenAI embedding provider
- Added `backend/app/embedding/providers/openai_provider.py`.
- Migrated RAG embedding callsites to `get_embedding_client()`:
  - `backend/app/rag/manager.py`
  - `backend/app/rag/daily_store.py`

## Step H - Local embedding provider slot
- Added `backend/app/embedding/providers/local_provider.py` stub.
- Added provider selection wiring for `EMBEDDING_PROVIDER=local` (stub not yet implemented).

## Step I - Config/env surface
- Updated `backend/app/core/config.py` with factory-oriented keys:
  - `LLM_PROVIDER`, `LLM_MAIN_MODEL`, `LLM_MINI_MODEL`
  - `EMBEDDING_PROVIDER`
  - `TAGGER_MODEL`
- Updated defaults to GPT-5.4 where requested.
- Updated `Makefile` `.env` generation keys and defaults.

## Step J - LangChain dependency removal
- Removed LangChain packages from `requirements.txt`.
- Removed remaining LangChain runtime imports/usages in core chat paths.
- Updated logging/health naming to generic `llm` labels where relevant.

## Step K - GPT-5.4 default alignment
- Updated default main model to GPT-5.4 in config and Makefile env template.
- Updated mini/tagger defaults to GPT-5.4-mini.
- Updated dream default model to GPT-5.4.
- Updated README environment variable docs accordingly.

## Step L - Verification and compatibility updates
- Added/updated test coverage for new `core.llm` factory integration in `tests/test_llm.py`.
- Kept compatibility shim:
  - `backend/app/llm_model/llm_client.py` now delegates to embedding factory.
- Verification executed:
  - `python3 -m compileall backend/app`
  - `pytest tests/test_llm.py` (passes)
  - IDE lints on touched files (no new diagnostics)
