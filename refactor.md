# Refactor Execution Log

## Ticket 1 - Create target packages

- Created package directories with `__init__.py`:
  - `backend/app/rag/__init__.py`
  - `backend/app/embedding/__init__.py`
  - `backend/app/sleep/__init__.py`
  - `backend/app/tagging/__init__.py`
- No import graph changes required in this ticket.

## Ticket 2 - Move tagger module

- Moved file:
  - `backend/app/core/tagger.py` -> `backend/app/tagging/tagger.py`
- Updated import paths in moved module:
  - `..core.config`
  - `..core.tracking`
- Updated callers/imports:
  - `backend/app/core/memory.py`
  - `backend/app/api/projects.py`
  - `backend/app/api/sleep.py`

## Ticket 3 - Move rag_manager module

- Moved file:
  - `backend/app/core/rag_manager.py` -> `backend/app/rag/manager.py`
- Updated moved module imports from `core` package locations:
  - `config`, `embed_batching`, `database`, `db_models`, `retrieval_ordering`, `tracking`, `vector_index`
  - runtime imports to `core.daily_rag` and `core.route_policy`
- Updated callers/imports:
  - `backend/app/main.py`
  - `backend/app/api/chat.py`
  - `backend/app/api/files.py`
  - `backend/app/api/projects.py`
  - `backend/app/api/sleep.py`
  - `backend/app/core/dream/context.py`
  - `backend/app/core/dream/agents/questions_agent.py`

## Ticket 4 - Move daily_rag module

- Moved file:
  - `backend/app/core/daily_rag.py` -> `backend/app/rag/daily_store.py`
- Updated moved module imports from `core` package locations:
  - `config`, `embed_batching`, `vector_index`
- Updated callers/imports:
  - `backend/app/api/chat.py`
  - `backend/app/api/projects.py`
  - `backend/app/api/sleep.py`
  - `backend/app/core/memory.py`
  - `backend/app/rag/manager.py`

## Ticket 5 - Move embedding utilities

- Moved files:
  - `backend/app/core/embed_batching.py` -> `backend/app/embedding/batching.py`
  - `backend/app/core/vector_index.py` -> `backend/app/embedding/vector_index.py`
- Updated callers/imports:
  - `backend/app/rag/manager.py`
  - `backend/app/rag/daily_store.py`

## Ticket 6 - Move sleep orchestration module

- Moved file:
  - `backend/app/api/sleep.py` -> `backend/app/sleep/cycle.py`
- Added thin API wrapper:
  - `backend/app/api/sleep.py` now re-exports router and orchestration entrypoints from `app.sleep.cycle`
- Result:
  - sleep orchestration lives in the `sleep` package
  - API layer remains a thin wrapper module

## Ticket 7 - Remove dream bridge wrappers

- Removed obsolete bridge modules:
  - `backend/app/core/dream_context.py`
  - `backend/app/core/dream_llm.py`
  - `backend/app/core/dream_prompts.py`
  - `backend/app/core/dream_research.py`
- Verified there are no remaining imports of those bridge modules; Dream code imports directly from `backend/app/core/dream/*`.

## Ticket 8 - Introduce configured path roots

- Added new path settings in `backend/app/core/config.py`:
  - `data_root`
  - `runtime_root`
  - `memory_root`
  - `runs_dir`
  - `logs_dir`
  - `lock_dir`
- Replaced hardcoded runtime/data path literals in key modules with settings-driven paths:
  - `backend/app/core/state.py`
  - `backend/app/core/tracking/instrumentation.py`
  - `backend/app/main.py`
  - `backend/app/api/files.py`
  - `backend/app/api/projects.py`
  - `backend/app/core/memory.py`
  - `backend/app/core/personality.py`
  - `backend/app/core/dream/context.py`
  - `backend/app/core/dream/dreams.py`
  - `backend/app/core/dream/agents/questions_agent.py`
  - `backend/app/rag/manager.py`
  - `backend/app/rag/daily_store.py`
  - `backend/app/sleep/cycle.py`
