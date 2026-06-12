# Syx Architecture

Syx is a local AI chat and memory system built around a React frontend, a FastAPI backend, project-scoped persistence, FAISS-backed retrieval, and a memory lifecycle that moves information from active chat into durable markdown artifacts.

This document is a readable system overview. For detailed behavioral requirements, see `docs/REQUIREMENTS.md` and `docs/DELTAS.md`. When those files conflict, `docs/DELTAS.md` is the current source of truth.

## System Shape

Syx runs as one application server in normal use:

```text
Browser
  |
  | React/Vite app
  v
FastAPI backend
  |
  |-- SQLite project/chat/file metadata
  |-- data/memory/{project_id}/ project artifacts
  |-- FAISS indexes for retrieval
  |-- LLM and embedding provider factories
  |-- Sleep/Dream maintenance pipelines
  |-- runtime logs and instrumentation artifacts
```

The frontend is built with Vite and emitted into `backend/app/static`. FastAPI serves the built frontend at `/` and exposes API routes under the same server, so local and Docker deployments use a single port.

## Frontend

The frontend lives under `frontend/` and is a React + TypeScript application. The top-level page is `frontend/src/pages/App.tsx`.

The frontend is responsible for:

- Rendering the chat interface and message history.
- Selecting the active project and model.
- Uploading files to a project.
- Managing project settings, system prompt, personality, and user profile dialogs.
- Starting and monitoring Sleep.
- Reviewing Dream outputs.
- Streaming chat responses from the backend.

API calls are kept under `frontend/src/pages/app/api.ts` and related helpers. Shared behavior is factored into hooks such as `frontend/src/hooks/useProjectData.ts` and `frontend/src/hooks/useChatStream.ts`.

## Backend Entry Point

The backend lives under `backend/app/`. The FastAPI application is created in `backend/app/main.py`.

Startup performs the main process initialization:

- Initializes SQLite via SQLModel/Alembic.
- Ensures the default `Main` project exists.
- Builds LLM and embedding clients through provider factories.
- Initializes instrumentation when enabled.
- Clears or restores Sleep lock state.
- Backfills project defaults.
- Seeds the default user profile upload for `Main` when needed.
- Optionally rebuilds project RAG indexes at startup.
- Starts the scheduled Sleep cycle when enabled.

FastAPI includes routers for chat, projects, files, Sleep, Dream, model discovery, and the local agent-memory interface.

## API Boundaries

The main API modules are:

- `backend/app/api/chat.py` — chat and streaming chat endpoints.
- `backend/app/api/projects.py` — project CRUD, chat history, project stats, profile/personality, and Dream review operations.
- `backend/app/api/files.py` — project file upload, file metadata, and RAG rebuild triggering.
- `backend/app/api/sleep.py` — manual Sleep cycle control.
- `backend/app/api/dream.py` — Dream-related API operations.
- `backend/app/api/llm_models.py` — available model discovery.
- `backend/app/agent_interface/router.py` — local read-only agent memory search.

During Sleep, a middleware in `backend/app/main.py` rejects mutating requests with HTTP 423 while still allowing GET requests and a small recovery allowlist.

## Provider Factories

Syx keeps LLM and embedding provider selection behind factory modules:

- `backend/app/llm_model/factory.py`
- `backend/app/embedding/factory.py`

Runtime code should call factory entry points instead of directly constructing provider SDK clients. This keeps provider/model changes configuration-driven through environment settings such as:

- `LLM_PROVIDER`
- `MODEL_NAME`
- `LLM_MINI_MODEL`
- `BUILDER_MODEL`
- `TAGGER_MODEL`
- `DREAM_MODEL`
- `EMBEDDING_PROVIDER`
- `EMBEDDING_MODEL`
- `SENTENCE_TRANSFORMERS_MODEL_ID`

Configuration is centralized in `backend/app/core/config.py`.

## Persistence Model

Syx uses SQLite through SQLModel for structured metadata. The database setup is in `backend/app/core/database.py`, and table models live in `backend/app/core/db_models.py`.

Core tables include:

- `Project` — project identity, description, system-project flag, Daily memory toggle, and recent semantic handle.
- `File` — uploaded file metadata, token/page counts, and indexing status.
- `ChatMessage` — active project chat rows, including role, content, forget/keep flags, and tagger metadata.

The configured SQLite path defaults under `data/db/`. Runtime defaults are defined by `Settings` in `backend/app/core/config.py`.

## Project Storage

Each project owns a filesystem area under the configured `MEMORY_ROOT`, normally `data/memory/{project_id}/`.

Common project artifacts include:

- `uploads/` — user-uploaded documents and generated Sleep/Dream artifacts.
- `faiss/` — long-term-memory FAISS index files and sidecars.
- `daily.json` — authoritative structured Daily memory metadata.
- `daily.md` — human-readable and agent-readable Daily memory artifact.
- `open_questions.jsonl` — append-only question stream used by Dream.
- `dream.json` — pending Dream output.
- `latest_sleep_summary.md` — latest user-facing Sleep summary.
- `debug/` — optional prompt, retrieval, Dream, and agent-interface debug artifacts.

Generated memory and debug files may contain sensitive content. They should be treated as local/private data.

## Chat Flow

A normal chat turn flows through the backend roughly as:

```text
Frontend sends message
  |
  v
chat API validates model/API-key state
  |
  v
ChatPipeline loads project history, prompts, personality, and RAG context
  |
  v
LLM factory provides the configured model client
  |
  v
response streams or returns to frontend
  |
  v
working memory and DB are updated
  |
  v
older pairs roll off into Daily memory when limits are exceeded
```

The active chat window is persisted in `ChatMessage` rows and mirrored through the memory manager in `backend/app/core/memory.py`. Older prompt/response pairs can roll into Daily memory, where they become durable artifacts and retrievable context.

## RAG and FAISS

Long-term retrieval is managed under `backend/app/rag/`.

Uploaded files are stored under a project `uploads/` folder and then indexed by the RAG rebuild path. The index pipeline:

- Reads supported text/markdown inputs.
- Splits content into chunks.
- Embeds chunks through the embedding factory.
- Stores vectors in FAISS.
- Writes sidecar metadata such as docstore, row-to-id mapping, manifest, and adjacency information.

At query time, Syx retrieves candidates from the long-term index and, when available, Daily memory. Retrieval then applies ordering, filtering, expansion, deduplication, and snippet assembly before injecting context into the chat prompt.

## Daily Memory

Daily memory is the bridge between active chat and long-term project memory.

`backend/app/rag/daily_store.py` manages:

- `daily.json` structured metadata.
- `daily.md` readable memory artifacts.
- An in-memory FAISS Daily index.
- Append and rebuild operations for rolled-off chat pairs.

Per `docs/DELTAS.md`, markdown artifacts are the current readable carrier format for new Daily, Sleep, and Dream memory artifacts. Structured metadata remains authoritative for identity, provenance, lifecycle state, and future expansion.

## Sleep Cycle

Sleep is the maintenance phase that consolidates project memory. It can be triggered manually through the API or scheduled by the background scheduler initialized in `backend/app/main.py`.

Sleep is guarded by a global lock:

- New mutating requests are blocked while Sleep runs.
- GET requests remain available.
- Sleep runs on a background daemon thread when triggered asynchronously.

At a high level, Sleep:

- Flushes active project chat into Daily memory where appropriate.
- Processes project Daily artifacts.
- Writes per-cycle Sleep artifacts.
- Coordinates with Dream when Dream is enabled.
- Rebuilds or refreshes retrieval state after consolidation.
- Clears state so the next active cycle starts cleanly.

The Sleep API and worker entry points live under `backend/app/api/sleep.py`, `backend/app/sleep/worker.py`, and `backend/app/sleep/cycle.py`.

## Dream Cycle

Dream is a post-Sleep reasoning phase. Its orchestration lives under `backend/app/dream/`.

The current Dream pipeline can:

- Build project context.
- Consume the project open-question stream.
- Run questions, research, and idea agents.
- Write `dream.json`.
- Write debug artifacts when enabled.
- Produce items that can later be reviewed or persisted.

Dream is controlled by settings such as `ENABLE_DREAM`, `AUTO_ACCEPT_DREAMS`, `DREAM_MODEL`, `DREAM_TEMPERATURE`, `DREAM_MAX_TOKENS`, and `DREAM_ENABLE_REMOTE_RESEARCH`.

Dream is experimental. It is part of the current architecture, but its behavior should be understood as a research feature rather than a production workflow.

## Instrumentation

Instrumentation lives under `backend/app/tracking/`.

When enabled, Syx records file-backed run, turn, and invocation telemetry under the configured runs directory, normally `runtime/runs/`. The instrumentation layer is accessed through a shared facade so application code can record stages and usage without managing artifact files directly.

Instrumentation is intended for profiling and analysis of token usage, latency, retrieval behavior, and model calls. It is local runtime data and may contain sensitive derived metadata.

## Static Frontend Deployment

The React frontend is built by Vite into `backend/app/static`.

FastAPI:

- Mounts `/static` when the build output exists.
- Serves `index.html` at `/`.
- Keeps API documentation available at `/api/docs`.
- Supports single-server deployment for local and Docker use.

This avoids running separate frontend and backend servers for normal use. During frontend development, `make dev-frontend` can still run the Vite development server separately.

## Local Agent Memory Interface

The local agent-memory interface lives under `backend/app/agent_interface/`.

It provides a read-only search endpoint for trusted local tools that need project memory context. The request contract includes an `agent_token`, but current token validation is a local-development stub. See `SECURITY.md` before using this interface outside a trusted local environment.

## Generated Data Boundaries

The main generated-data roots are:

- `data/` — project memory, SQLite DB, uploads, FAISS indexes, generated memory artifacts.
- `runtime/` — logs, run artifacts, lock files, instrumentation output.
- `backend/app/static/` — generated frontend build output.
- `backend/htmlcov/`, `backend/coverage.xml`, `backend/lcov.info` — generated coverage reports.

These paths are operational artifacts, not source-of-truth code. Treat project memory, uploads, logs, and debug outputs as private unless they were intentionally sanitized for examples.

## Design Principles

Syx favors:

- Configuration-driven model/provider selection.
- Project-scoped memory ownership.
- Durable, inspectable markdown memory artifacts.
- Structured metadata for identity, provenance, and lifecycle.
- Local/trusted deployment assumptions.
- Deterministic tests around real behavior.
- Requirements and deltas as explicit AI-readable engineering context.
