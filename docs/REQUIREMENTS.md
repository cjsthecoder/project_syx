# Syx

## Project Overview
Syx is a modular system that provides a web-based chat interface backed by a FastAPI server and provider-based LLM/embedding factories.  

**Version 1 Goal:** Establish a working chatbot with a GUI and stable backend interfaces that can be extended later with RAG, memory pruning, and multi-project support.  
**Version 2 Goal:** Add persistent Project Management, File Upload + RAG initialization, and dynamic Model Selection.
**Version 3 Goal:** Implement autonomous long-term memory consolidation through a nightly Sleep Cycle that prunes, summarizes, and rebuilds each project’s RAG automatically. This release transforms Syx from a reactive chat system into one that learns and maintains knowledge over time, preparing the foundation for Dreaming (creative synthesis) in version 4.
**Version 4 Goal:** Introduce the Dream Cycle as a post Sleep reasoning phase capable of autonomously analyzing the nightly memory summary and generating structured insight outputs. Version 4 establishes the Dream Orchestrator, the Dream Agent framework, and the first Dream function: extracting all open questions into a unified artifact. This transforms Syx from a system that only consolidates memory into one that begins to interpret, organize, and act on unresolved knowledge gaps during nightly maintenance.
**Version 5 Goal:** Introduces Instrumentation as a first-class telemetry layer for Syx. Instrumentation collects structured, end to end metrics across the multi-module pipeline, including interactive chat turns and internal helper model calls. Its purpose is to generate defensible evidence for token usage and latency behavior over time, and to support profiling and optimization without changing core routing, retrieval, or memory logic.

---

# Version 1 — Core Chat & Stubs

## Purpose
Establish a working chatbot with a web UI and stable backend interfaces, laying the foundation for future RAG, memory, and multi‑project features.

### Functional Requirements

#### 1. Chat Interface (FR-001)
**Priority:** High  
- **Requirement:** Provide a web-based chat UI for user ↔ AI interaction.  
- **Frontend:** Built in React with Shadcn/UI.  
- **Features:**
  - Message history displayed in chat bubbles.  
  - Input box for sending messages.  
  - Basic UI controls for triggering stubbed actions (`query_rag`, `switch_project`).  
- **Success Criteria:** User can hold a conversation with the chatbot via the web UI.

---

#### 2. Chat Endpoint (FR-002)
**Priority:** High  
- **Requirement:** Backend endpoint for handling user messages.  
- **Implementation:** FastAPI `/chat` route.  
- **Flow:** Receive message → Forward to LLM provider selected by `llm_model.factory` → Return response.  
- **Validation:** Must return a valid response for every valid request.  
- **Success Criteria:** End-to-end chat works (UI → FastAPI → LLM factory/provider → UI).

---

#### 3. LLM Provider Factory Integration (FR-003)
**Priority:** High  
- **Requirement:** Use the internal provider factory (`backend.app.llm_model.factory`) as the abstraction layer for LLM providers.  
- **Factory Functions (authoritative entry points):**
  - `get_llm_client()` — primary chat/reasoning client.
  - `get_llm_client_mini()` — secondary/lightweight client for helper calls.
- **Default Provider:** OpenAI GPT-5.  
- **Future Proofing:** Should support Anthropic, LLaMA, etc. with minimal change.  
- **Invariant:** Runtime LLM calls MUST resolve through `llm_model.factory`; request-path modules MUST NOT instantiate provider SDK clients directly.
- **Invariant:** Provider/model swaps are configuration-driven (`LLM_PROVIDER`, `MODEL_NAME`, `LLM_MINI_MODEL`) and MUST NOT require endpoint-level refactors.
- **Success Criteria:** Responses are generated via provider-selected clients exposed by `get_llm_client()` / `get_llm_client_mini()`.

---

#### 4. Stubbed Feature Hooks (FR-004)
**Priority:** Medium  
- **Requirement:** Provide backend routes for future functionality.  
- **Endpoints:**
  - `/query_rag` → currently returns “RAG not implemented.”  
  - `/projects` → list/switch projects (stub).  
  - `/sleep_cycle` → trigger pruning job (stub).  
- **Success Criteria:** Stubs exist, return placeholder responses, and can be called from frontend buttons.

---

#### 5. Project Awareness (FR-005)
**Priority:** Medium  
- **Requirement:** Define project-based separation of future memory indexes.  
- **Implementation:** Project ID included in requests (stub only in V1).  
- **Success Criteria:** API supports project context, even if unused in V1.

---

### Acceptance Criteria
- End-to-end chat works between UI and FastAPI via the provider factory layer.
- Stub endpoints respond with placeholders and are invokable from the UI.
- Requests accept `project_id` to establish future project context.

## Technical Requirements (V1)

### 1. Backend (TR-001)
**Priority:** High  
- **Framework:** FastAPI with Uvicorn.  
- **Endpoints:** `/chat`, `/query_rag`, `/projects`, `/sleep_cycle`.  
- **Response Format:** JSON with `{"response": "...text..."}`.  
- **Success Criteria:** Stable backend routes with predictable JSON outputs.

---

### 2. Frontend (TR-002)
**Priority:** High  
- **Framework:** React (built with Vite) + Shadcn/UI.  
- **Build Tool:** Vite for fast build/dev times and clean setup.  
- **UI Library:** Shadcn/UI installed manually via CLI (modular, open source, no lock-in).  
- **Features:** Chat message list, input box, action buttons.  
- **API Calls:** Fetch from FastAPI endpoints.  
- **Success Criteria:** Chat UI responds to user input and displays backend replies.

---

### 3. LLM Provider (TR-003)
**Priority:** High  
- **Interface:** `backend.app.llm_model.factory` + provider implementation (default OpenAI provider).  
- **Entry Points:** `get_llm_client()` (main) and `get_llm_client_mini()` (mini); all runtime LLM usage routes through these.
- **Flexibility:** Must support provider swap by config, not refactor.  
- **Invariant:** Runtime LLM calls MUST resolve through `llm_model.factory`, not direct third-party SDK imports or framework adapters in request-path modules.
- **Success Criteria:** Swapping OpenAI → Anthropic requires configuration changes only.

---

### 4. Configuration (TR-004)
**Priority:** High  
- **Env Variables:**
  - `OPENAI_API_KEY` (required)
  - `LLM_PROVIDER` (default: `openai`)
  - `MODEL_NAME` (default: `gpt-5.5`)
  - `LLM_MINI_MODEL` (default: `gpt-5-mini`)
  - `MODEL_TEMPERATURE` (default: `1.0`)
  - `MODEL_MAX_TOKENS` (default: `128000`)
  - `DB_PATH` (e.g., `backend/app/data/syx.db`)
  - `MAX_UPLOAD_MB` (per-file limit; default `10`)
  - `MAX_BATCH_MB` (per-request batch limit; default `50`)
  - `STORAGE_LIMIT_MB` (per-project storage cap; default `500`)
  - `EMBEDDING_PROVIDER` (default: `openai`)
  - `EMBEDDING_MODEL` (default: `text-embedding-3-large`)
  - `SENTENCE_TRANSFORMERS_MODEL_ID` (default: `BAAI/bge-m3`)
  - `CHUNK_SIZE` (default: `600`)
  - `CHUNK_OVERLAP` (default: `80`)
- **Invariant:** Provider/model selection for both LLM (`LLM_PROVIDER`, `MODEL_NAME`, `LLM_MINI_MODEL`) and embeddings (`EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `SENTENCE_TRANSFORMERS_MODEL_ID`) is driven entirely by the above environment keys; swaps MUST NOT require endpoint-level refactors.
- **Success Criteria:** No API key leakage, flexible configuration per environment.

---

### 5. Error Handling (TR-005)
**Priority:** Medium  
- Must handle API errors and invalid inputs gracefully.  
- Fallback: return error JSON instead of crashing.  
- **Success Criteria:** System never crashes on bad input or API errors.

---

### 6. Unified Deployment (TR-006)
**Priority:** High  
- **Requirement:** Bundle React frontend into FastAPI for unified deployment.  
- **Implementation:**
  - Build React app with `npm run build` (Vite).  
  - Copy React’s `dist/` output to FastAPI’s `/static` folder.  
  - Configure FastAPI to serve static files and handle SPA routing.  
  - Manual build process with make target for automation.  
- **Benefits:**
  - Simplified deployment (single server).  
  - No CORS issues in production.  
  - Easier containerization and scaling.  
  - Single port for all services.  
- **Success Criteria:**
  - FastAPI serves React app at root URL (`/`).  
  - API endpoints accessible at direct paths (`/chat`, `/query_rag`, etc.).  
  - React routing works with FastAPI catch-all route to `index.html`.  
  - Single command deployment (`python main.py`).

### Acceptance Criteria
- Backend exposes the required endpoints with consistent JSON shapes.
- Frontend renders core chat UI and successfully calls the API.
- Configuration is driven by `.env` without hardcoding secrets.
- A single FastAPI server serves both API and built frontend.

---

# Version 2 — Project Management and Model Selection

## Overview
Version 2 introduces persistent **Project Management**, **File Upload + RAG Initialization**, and a **Dynamic Model Selector**.  
These upgrades make Syx a multi-project, persistent knowledge system.

---

### Core Functional Additions

#### 1. Project Management (FR-006)
**Priority:** High  
- Full CRUD for projects.  
- **Frontend:** Project management via Shadcn Dialog modals from the chat header.  
- **Backend Endpoints:**
  - `GET /projects` – List all projects.  
  - `POST /projects` – Create project.  
  - `GET /projects/{id}` – Get details.  
  - `GET /projects/{id}/files` – List files for a project.  
  - `POST /projects/{id}/files` – Upload files.  
  - `DELETE /projects/{id}` – Delete project.  
- **Persistence:** SQLite (via SQLModel).  
- **Success Criteria:** Projects persist and populate dropdown menus dynamically.

- **Project Fields Policy:**
  - `id` (string): unique; must not already exist in DB
  - `include_in_every_project` (boolean): optional, used to mark global inclusion
  - Deletion policy: hard delete (remove DB rows and all files under `memory/{project_id}`)

---

#### 2. File Upload and RAG Initialization (FR-007)
**Priority:** High  
- Upload documents to embed and index in each project’s FAISS store.  
- **Flow:**
  1. Upload → save to `memory/{project_id}/uploads/`.  
  2. Process synchronously and embed via the embedding provider factory (`backend.app.embedding.factory`, entry point `get_embedding_client()`).  
  3. Store vectors in FAISS index at `memory/{project_id}/faiss/`.  
- **Formats:** `.txt`, `.md`, `.pdf`.  
- **Invariant:** Runtime embedding calls MUST resolve through `embedding.factory`; request-path modules MUST NOT instantiate embedding provider SDK clients directly.
- **Invariant:** Embedding provider/model swaps are configuration-driven (`EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `SENTENCE_TRANSFORMERS_MODEL_ID`) and MUST NOT require endpoint-level refactors.
- **Success Criteria:** Uploaded content retrievable via future `/query_rag`.

- **Embedding & RAG Policy (V2):**
  - Embedding model: `text-embedding-3-large` (3072D)
  - Chunking: size `800`, overlap `100` using `RecursiveCharacterTextSplitter`
  - Metadata per chunk: `project_id`, `filename`, `page_number`, `chunk_id`, `timestamp`, `doc_id`, `chunk_seq`
    - `doc_id` identifies the source document for adjacency purposes (for PDFs: `(filename, page_number)`; for other formats: `filename`). Required for FR-2.3-3.4.1 compliance.
    - `chunk_seq` is a monotonic, gap-free integer sequence within a `doc_id`, enabling O(1) adjacency resolution (`prev = chunk_seq - 1`, `next = chunk_seq + 1`). Required for FR-2.3-3.4.1 compliance.
  - Reindex behavior: recreate FAISS index on each upload for consistency
  - PDF parsing: `pypdf`

---

#### 3. Model Selector (FR-008)
**Priority:** Medium  
- Dropdown in top-right toolbar (Shadcn `Select`).  
- **Backend Changes:**
  - `GET /models` → return whitelist of available models.  
  - Each `/chat` request includes `model` field.  
  - Validate against `config.py` list (hardcoded whitelist).  
- **Default Models:** `["gpt-4o-mini", "gpt-4o", "claude-3-opus", "mistral-small"]`.  
- **Success Criteria:** User-selected model applied on next chat prompt without restart.

---

### Technical Additions

#### 1. Database Layer (TR-007)
- `app/core/database.py` using SQLModel with SQLite and Alembic migrations.  
- Tables: `Project`, `File`.

#### 2. File Upload Handling (TR-008)
- FastAPI `UploadFile` processed synchronously.  
- Store under `memory/{project_id}/uploads/`; FAISS index under `memory/{project_id}/faiss/`.  
- Sequential processing per project (no parallel uploads for a given project).

#### 3. Frontend Routing (TR-009)
- Use Shadcn components (`Card`, `Button`, `Input`, `Dialog`, `Table`, `Select`).  
- Actions via modals: **Create Project**, **Rename Project**, **Delete (confirm)**, **Upload Files**.  
- Other interactions use inline UI (buttons, dropdowns, tables).  
- Show stats in header, including total memory size per project.

#### 4. Model Selector Integration (TR-010)
- Component: `ModelSelector.tsx`.  
- Update `useChatAPI.ts` to include `model` in payload.  
- Maintain state across pages.

---

### API Shapes & Pagination Policy (V2)
- `GET /projects`, `GET /projects/{id}/files`, and `GET /models` return flat lists (no pagination in V2).
- Requests and responses use explicit Pydantic schemas with snake_case keys.
- Future versions (V3+) may add pagination parameters (`limit`, `offset`).

### Limits & Error Handling Policy (V2)
- Uploads: Max `MAX_UPLOAD_MB` per file (default 10MB), `MAX_BATCH_MB` per request (default 50MB).
- Concurrency: Sequential processing per project; no rate limiting in V2.
- Errors: Backend returns JSON `{ "error": "..." }` or `{ "status": "ok" }`.
- Frontend displays messages via Shadcn `useToast()` with success/warning/error styles.

### Security & Deployment
- No multi-tenant or auth in V2.
- Unified deployment: FastAPI serves the built React app under `/static/` with SPA catch‑all.
- HTTPS/Proxy: Not required in V2; can be added in future or via external reverse proxy.

---

## Directory Structure Changes
```bash
backend/
  app/
    api/
      files.py          # File upload endpoints
      models.py         # /models endpoint
    core/
      database.py       # SQLModel + SQLite setup
      projects.py       # Project CRUD logic
      rag_manager.py    # FAISS and embedding management
  memory/
    {project_id}/
      uploads/          # Raw uploaded documents
      faiss/            # FAISS index artifacts
frontend/
  src/pages/Projects.tsx
  src/components/ProjectCard.tsx
  src/components/FileUploadDialog.tsx
  src/components/ModelSelector.tsx
```

---

## Success Metrics (V2)
- Projects persist across restarts (verified via SQLite).  
- Files upload and index successfully.  
- User can select/switch LLM models dynamically.  
- All features integrated with existing chat flow and React UI.

## Version 2.1 - Project Management UX Refinement

Goal:
Simplify project creation and management by keeping all interactions in the main chat view.
Remove the separate “Projects” page and integrate project creation and file management directly within the chat interface.

Frontend Behavior

Project Selector (existing):

Located at the top of the chat window.

Shows the currently active project.

Selecting a project changes context for all /chat and /query_rag calls.

Buttons (new):

New Project: Opens a modal to create a new project.

Inputs: name, optional description.

Calls POST /projects.

On success → adds new project to dropdown and selects it automatically.

Manage Project: Opens a modal for the currently selected project.

Displays:

Project name, description, and creation date.

File list (GET /projects/{id}/files).

Provides actions:

Add Files → opens file picker, uploads to /projects/{id}/files.

Delete Project → confirmation dialog, calls DELETE /projects/{id}.

On success → closes modal, refreshes dropdown and file list.

Toasts:

Success toast after create/upload/delete.

Error toast for failed actions (e.g., “File too large,” “No project selected”).

Backend Requirements

All operations remain the same (/projects, /projects/{id}, /projects/{id}/files),
but now they’re called directly from the main chat interface.

The backend must validate that a project is selected for all file actions.

### Version 2.1 — Detailed Specifications

#### System Project (Continuum)
- Default project name: "Continuum" (non-deletable, non-renamable; can accept files)
- Seeded via Alembic migration if missing
- Identification: selected by `name == "Continuum"` on first load
- Schema flag: `system: true` to protect from delete/rename

#### Project Schema and Rules
- Fields: `id` (uuid4, server-generated), `name` (<=255, unique case-insensitive), `description` (<=500), `created_at`, `updated_at`, `system` (default false)
- Remove legacy `include_in_all`/`include_in_every_project`
- Name uniqueness enforced at app-level (case-insensitive); on conflict return 409
- `PATCH /projects/{id}`: allow changing `name`, `description` only (blocked if `system == true`)
- Delete behavior: hard delete (DB rows + `memory/{project_id}`), blocked for `system == true`
- New project auto-select after creation
- If active project deleted, fallback to Continuum

#### Files and Uploads
- Allowed types: `.txt`, `.md`, `.pdf`
- Drag-and-drop and multi-file upload supported
- Limits: `MAX_UPLOAD_MB` per file; `MAX_BATCH_MB` per request; `STORAGE_LIMIT_MB` per project
- Upload handling: synchronous; rebuild FAISS immediately after successful upload
- File metadata (DB): `id`, `project_id`, `filename`, `size_bytes`, `content_type`, `created_at`, `embedding_status` (pending|indexed|failed), `page_count` (PDF pages or 1), `token_count`
- `uploaded_at` in responses maps to DB `created_at` (no DB column rename)
- Token counting: use `tiktoken` on extracted text during indexing
- File delete: `DELETE /projects/{id}/files/{file_id}` removes disk file and DB row, then synchronously rebuilds FAISS

#### RAG Indexing and Search
- Per-project FAISS index at `memory/{project_id}/faiss/`
- Embeddings: OpenAI `text-embedding-3-large`
- Chunking: `CHUNK_SIZE` 800, `CHUNK_OVERLAP` 100
- Metadata per chunk: `project_id`, `filename`, `page_number`, `chunk_id`, `timestamp`
- FAISS vectors are L2-normalized for cosine similarity scoring
- Rebuild policy: recreate index on each upload/delete

#### RAG on Chat
- Enabled only when the active project's index exists with ≥1 vector; otherwise disabled
- Fallback: if no project selected, use Continuum for RAG
- Retrieval runs through the unified RAG pipeline (FR-2.3-3); per-source K, retained count, and adjacency expansion come from `route_policy.json` (FR-2.3-3.3). No similarity threshold is applied in V2.5+; ranking is purely score-based (FR-2.3-3.2) and bounded by `max_keep` (FR-2.3-3.3).
- Injection: prepend a single system message with a "Context:" block containing concatenated snippet groups (FR-2.3-3.4.3 pass 5), separated clearly; cap the context block at `RAG_CONTEXT_MAX_TOKENS`.
- If retrieval returns zero candidates, proceed without RAG
- Do not index chat transcripts in V2.1

Env controls:
- `RAG_ON_CHAT=true`
- `BASE_TOP_K=5`
- `RAG_SNIPPET_MAX_TOKENS=500`
- `RAG_CONTEXT_MAX_TOKENS=5000`

#### Endpoints (Shapes)
- `POST /projects` → returns: `id`, `name`, `description`, `created_at`, `updated_at`, `storage_bytes` (0), `token_count` (0), `file_count` (0)
- `PATCH /projects/{id}` → updates `name`, `description` (blocked if `system`)
- `GET /projects/{id}/files` → returns: `project_id`, `files: [{ id, filename, size_bytes, uploaded_at, embedding_status, page_count, token_count }]`, plus aggregates: `storage_bytes`, `token_count`
- `POST /projects/{id}/files` → returns: `project_id`, `uploaded: [{ filename, status, size_bytes, token_count }]`, `index_dir`, `rebuild_status`, `total_files`, `total_tokens`
- `DELETE /projects/{id}/files/{file_id}` → sync rebuild; returns updated aggregates and `rebuild_status`
- `GET /projects/{id}/stats` → returns: `storage_bytes`, `index_size_bytes` (size of `memory/{project_id}/faiss/`), `tokens_indexed` (sum of file token_count), `context_tokens` (tokens in last chat excluding RAG), `file_count`

#### Error Codes and Conventions
- 409: duplicate project name (case-insensitive)
- 404: missing entities
- 400: validation errors (size limits, missing project)
- JSON keys in `snake_case`; include `project_id` in file-related responses; sizes in bytes; timestamps ISO 8601 UTC

Persistent Chats and Working Memory
Overview

Version 2.2 introduces persistent chat history and a unified short-term memory system that maintains up to N recent messages per project.
This memory is mirrored in both an in-memory buffer (for speed) and the database (for persistence and multi-tab consistency).
Older messages automatically roll out of the active buffer and will later be moved into long-term memory (RAG) in Version 2.3.

1️⃣ Database Layer

Add a new table to persist chat messages:

class ChatMessage(SQLModel, table=True):
id: int | None = Field(default=None, primary_key=True)
project_id: str = Field(foreign_key="project.id")
role: str # "user" | "assistant" | "system"
content: str
created_at: datetime = Field(default_factory=datetime.utcnow)

Each message (user, assistant, or system) is stored as a separate row.

Messages are ordered chronologically for replay.

Retains only the last N messages per project (short-term window).

On insertion, if message count > N, the oldest message is removed from DB and flagged for RAG embedding (in V2.3).

2️⃣ Backend Integration

On startup:

Load the most recent N messages for the active project into an in-memory deque buffer.

The buffer and DB always contain the same messages.

On /chat:

Insert the user message into DB.

Generate assistant response via `llm_model.factory` → provider-selected client (default OpenAI).

Insert assistant message into DB.

Append both to the memory buffer.

If buffer exceeds N, pop the oldest message:

Delete it from DB.

(Future) enqueue it for RAG embedding.

On shutdown:

No flush required — DB is always consistent.

On load or multi-tab access:

Each request fetches the latest N messages from DB, ensuring all tabs are synchronized automatically.

3️⃣ Frontend Updates

Chat UI loads the full working memory (last N messages) on startup using:

GET /projects/{id}/chats

Messages are rendered chronologically.

On sending a message:

POST to /chat.

Append both user and assistant messages to UI state.

Optionally refresh the chat list after reply to ensure sync with DB.

No threading or WebSockets needed in V2.2 — the DB ensures state consistency across sessions.

4️⃣ Configuration Variables

Environment configuration for chat memory:

CHAT_HISTORY_LIMIT=20

Number of messages (total user + assistant) kept in working memory per project
5️⃣ API Endpoints

GET /projects/{id}/chats
Returns the most recent N messages in chronological order.
Example:
{
"project_id": "proj_20251008_001",
"messages": [
{ "role": "user", "content": "What model is active for this project?", "created_at": "2025-10-08T10:00:00Z" },
{ "role": "assistant", "content": "The active model comes from the configured LLM provider/model settings.", "created_at": "2025-10-08T10:00:01Z" }
]
}

POST /chat
Receives user message, generates assistant reply, stores both, and returns the reply.

Request:
{
"project_id": "proj_20251008_001",
"message": "Explain FAISS indexing."
}

Response:
{
"response": "FAISS is a library for vector search.",
"stored": true
}

6️⃣ Implementation Notes

Use an in-memory deque (Python collections.deque) to maintain the rolling short-term buffer.

Keep DB and memory synchronized — both capped to CHAT_HISTORY_LIMIT.

Use timestamps for ordering and pruning.

The backend should always rebuild the buffer on project load from DB.

No Alembic migration beyond creating the ChatMessage table is required for V2.2.

7️⃣ Future Integration (V2.3 Preview)

Messages rolled out of the DB (older than N) will be embedded and appended to each project’s chat_faiss/ index.

Nightly “sleep cycle” will prune, summarize, and merge chat RAG into long-term FAISS memory.

The same ChatMessage records will include optional embedded and pruned flags for that lifecycle.

✅ Success Criteria
Requirement	Success Metric
Persistent chat memory	Survives restarts and reloads
Working memory cap	Always maintains exactly N most recent messages
Multi-tab consistency	All tabs see identical conversation state
Crash safety	No manual save or flush required
RAG-ready structure	Rolled-off messages easily convertible into embeddings


## Version 2.3 — Rolling Context → Daily RAG Bridge

### Purpose
Extend Syx’ working memory by continuously off-loading the oldest prompt/response pairs from the live chat buffer and database into a persistent daily RAG file.
This yields an effectively unlimited context window while isolating transient data from the long-term project memory (merged later during 3.0 sleep cycle).

### Functional Requirements

#### FR-2.3.1 — Rolling Window by Pair Count
Maintain an in-memory deque of the most recent N prompt/response pairs.

- Configurable limit: `CHAT_HISTORY_LIMIT_PAIRS=10` (replaces `CHAT_HISTORY_LIMIT` from V2.2)
- On each new completed exchange:
  - Insert the pair `[user, assistant]` at the end of the deque
  - If deque > N, remove the oldest pair
  - Delete the corresponding `ChatMessage` records from the database for that pair (pair-level prune)
  - Concatenate prompt + response text and hand off to the embedding pipeline (→ FR-2.3-2)
- Unpaired trailing messages:
  - On startup/load, if a trailing unpaired user message exists, delete it
  - If an orphan assistant message is detected, delete it as well (rare)

#### FR-2.3.2 — Incremental Embedding → Daily FAISS (In-Memory Cache)
Each project maintains a single Daily FAISS index as an **in-memory cache** rebuilt from `memory/{project_id}/daily.json`. The Daily FAISS index is not persisted to disk; the legacy directory `memory/{project_id}/daily_faiss/` is deprecated and MUST NOT be written going forward (no cleanup required for any pre-existing contents).

- **Authoritative store:** `memory/{project_id}/daily.json` is the sole authoritative persistent store for Daily memory. Daily FAISS data may be discarded and rebuilt at any time without data loss.
- **Incremental adds:** Embed each rolled-off prompt/response pair as a single chunk (do not apply file `CHUNK_SIZE`/`CHUNK_OVERLAP`); use the currently configured `EMBEDDING_MODEL`. Append the new vector to the in-memory index and append the corresponding metadata entry to `daily.json`.
- **Daily metadata schema:** Maintain one entry per embedded pair in `daily.json` using:
  {
    "id": "<uuid or sequential int>",
    "project_id": "<project_name_or_uuid>",
    "created_at": "<ISO8601 timestamp>",
    "pair_ids": ["<user_msg_id>", "<assistant_msg_id>"],
    "text": "<full prompt + response text>",
    "tokens": <approx_token_count>,
    "embedding_model": "text-embedding-3-large",
    "source": "chat",
    "scope": "daily",
    "score_at_insert": <float, optional>,
    "confidence": 1.0,
    "tags": ["rolled_off"],
    "day_sequence": <integer incrementing for chronological ordering>
  }
- **Write strategy:** Per-append FAISS load/save is removed. Persist only the `daily.json` update after each add, serialized with `daily.lock` to prevent concurrent write corruption to `daily.json`. No file locking is required for the in-memory index.
- **Cache warming (lazy, per project):** The in-memory Daily FAISS index for a project is warmed on the first project-scoped request observed for that project after startup (i.e., "project selected" ≈ first request using `project_id`). A single in-memory FAISS index is maintained per project during runtime.
- **Rebuild triggers:** Rebuild the in-memory Daily FAISS index from `daily.json` when any of the following occurs:
  - The in-memory cache is not present yet for that project.
  - The runtime `EMBEDDING_MODEL` differs from the `embedding_model` recorded in `daily.json`.
  - An exception occurs during daily search/add operations.
  - The in-memory index appears corrupted or incompatible (e.g., dimension mismatch).
- **Embedding model change:** On rebuild triggered by `EMBEDDING_MODEL` change:
  - Do NOT delete `daily.json`.
  - Re-embed from `daily.json` and update each entry's `embedding_model` field to the new model.
  - The main index is unaffected.
- **Rebuild during an operation:** If a rebuild trigger fires during an active operation (retrieve/add), rebuild the cache but return empty/error for that request; do not automatically retry the operation.
- **Sleep interaction:** On sleep merge cleanup, clear the in-memory Daily cache for the project being merged. Other sleep cleanup behaviors remain unchanged.
- **Failure path (embedding/index write):** If embedding/index add fails, log error, drop the pair from memory, delete its two DB rows, and do not retry.

#### FR-2.3-3 — Unified RAG Retrieval Pipeline
On every `/chat` call, retrieval is performed by a single canonical pipeline that is applied uniformly to Daily and LTM (main project FAISS) sources. The pipeline has four ordered stages:

1. Canonical Retrieval Entry Point — FR-2.3-3.1
2. Deterministic Score Ordering — FR-2.3-3.2
3. Policy-Driven Selection & Pruning — FR-2.3-3.3
4. Rehydration & Chunk Expansion — FR-2.3-3.4 (materialization → identity dedup → per-source ordering → boundary overlap trimming → snippet-group collapse)

Policy inputs come from the system-wide `route_policy.json` (see FR-2.3-3.3) and the environment (see FR-2.3.5). The builder route (FR-2.3.1.2) selects the policy row. If `rag=false` (or the policy row has `retrieval_multiplier = 0`, e.g. `CHITCHAT`), retrieval is skipped entirely. Otherwise the pipeline runs end-to-end and the final snippet-group list is injected as a single `Context:` system message before user input, subject to `RAG_CONTEXT_MAX_TOKENS`.

##### FR-2.3-3.1 — Canonical Retrieval Entry Point
A single retrieval function is responsible for all RAG memory queries. It accepts a normalized query string, the list of memory sources to query (at minimum: `daily` and `ltm`), and a retrieval configuration object.

- The query embedding MUST be computed exactly once via `embedding.factory` (FR-007) using `settings.embedding_model`, and the same query vector MUST be reused across all queried sources.
- Retrieval-stage limits are controlled only by:
  - `BASE_TOP_K` (environment)
  - `retrieval_multiplier` (per-route, from `route_policy.json`)
  - Derived: `PER_SOURCE_K = ceil(BASE_TOP_K * retrieval_multiplier)`
- Each source is queried with `PER_SOURCE_K`. Results are normalized to a single canonical candidate shape:
  - `source`: `"daily"` | `"ltm"`
  - `text`: string
  - `score`: float (raw cosine similarity in `[0.0, 1.0]`)
  - `metadata`:
    - `id`: optional string
    - `timestamp`: optional string
    - `route`: optional string
    - `tags`: optional list
    - `topics`: optional list
    - `intent`: optional string
    - `type`: optional string
    - `tags_meta`: optional object
    - `keep`: optional boolean
    - `day_sequence`: optional integer
    - `pair_ids`: optional list
    - `source_document_id`: optional string (required for adjacency; see FR-2.3-3.4.1)
    - `chunk_index`: optional integer (required for adjacency; see FR-2.3-3.4.1)
- For `daily` candidates, canonical metadata is sourced authoritatively from `daily.json` via a stable daily entry identifier joined to the retrieved vector. If the join fails (lossy recall), the candidate is still returned with `metadata.id` absent and daily-only fields (`tags_meta`, `topics`, `intent`, `type`, `keep`, `day_sequence`, `pair_ids`) absent; `metadata.route` MAY be populated best-effort from the FAISS document metadata namespace if present.
- For `ltm` candidates, missing metadata fields are permitted and left absent; no parsing from retrieved text is performed in this stage.
- `ltm` includes all content embedded in the project's main FAISS index regardless of origin (uploads, sleep summaries, dream artifacts, etc.).

Behavior and boundaries (this stage):
- No namespace boosts, thresholding, route-based `rag_k`, score filtering, source branching, deduplication, or prompt injection are performed.
- An empty result from one source MUST NOT block other sources.
- If querying a source fails, that source degrades to an empty candidate list for the current request (no in-request retry). Rebuild/repair is owned by the source subsystem and runs best-effort asynchronously.
- If query embedding fails, retrieval is unavailable for the request and the function returns an empty candidate list.

Output contract:
- A flat list of retrieval candidates with no filtering beyond per-source query execution limits (`PER_SOURCE_K`).
- Per-source original retrieval order is preserved; source attribution is preserved on every candidate. Cross-source ordering is defined by FR-2.3-3.2, not here.

Invariants:
- All RAG retrieval MUST pass through this single code path.
- Candidate shape is uniform across sources; enrichment is conditional on source metadata availability.
- Retrieval consistency is guaranteed across memory tiers prior to ordering and selection.

##### FR-2.3-3.2 — Deterministic Score Ordering
- All candidates produced by FR-2.3-3.1 MUST be sorted in descending order of the raw cosine similarity score (`[0.0, 1.0]`) prior to any selection, truncation, or prompt assembly.
- Sorting uses full-precision floating-point values with no rounding, boosts, or weights applied.
- Sort MUST be stable: for ties, the pre-sort order from FR-2.3-3.1 is preserved. No additional tie-breaker is introduced.
- No candidates are dropped or filtered at this stage.
- This produces a single global ordering across all sources; Daily and LTM candidates MAY interleave purely by score.

Architectural constraints:
- Candidate retrieval, ordering, selection, and prompt assembly MUST be implemented as separate, single-responsibility stages.
- Ordering logic MUST be isolated in its own function or module.
- Retrieval-stage code MUST NOT perform prompt formatting, enforce token budgets, or apply selection/thresholding rules.
- Prompt assembly code MUST NOT modify retrieval ordering or selection decisions.

Invariants:
- Higher similarity score always implies earlier presentation to the model.
- Ordering is reproducible across identical inputs.
- The model MUST NOT be relied upon to infer relevance ordering from unsorted context.

##### FR-2.3-3.3 — Policy-Driven Selection & Pruning
Inputs:
- The globally ordered candidate list from FR-2.3-3.2.
- The route-derived retrieval policy from `route_policy.json` (loaded and validated once at startup; cached for process lifetime; reload on restart only).
- Environment-level configuration (`BASE_TOP_K`).

Per-route policy parameters:
- `retrieval_multiplier`: scalar applied to `BASE_TOP_K` for per-source K (also consumed by FR-2.3-3.1).
- `max_keep`: absolute initial cap on retained candidates. The effective keep limit MAY grow via the adjacent-chunk rule below.
- `expansion.max_before` / `expansion.max_after`: adjacency depth (consumed by FR-2.3-3.4.2).

Derived:
- `RETRIEVAL_K = ceil(BASE_TOP_K * retrieval_multiplier * N_SOURCES)` where `N_SOURCES` is the number of sources attempted.

Selection process:
1. Maintain an effective keep limit, initially equal to `max_keep`.
2. Iterate candidates in FR-2.3-3.2 order (highest score first).
3. For each candidate:
   - If retained count ≥ effective keep limit, stop.
   - If the ordered list is exhausted, stop.
   - Otherwise append the candidate to the retained list.
   - **Adjacent-chunk rule**: if the candidate just retained is directly adjacent to the previously retained candidate (same `source_document_id` AND `chunk_index` differs by exactly 1), increment the effective keep limit by 1. This compensates for downstream identity dedup in FR-2.3-3.4.3 (pass 2) and increases breadth across distinct sources without unbounded growth.
4. No reordering, skipping, thresholding, boosting, or deduplication occurs in this stage.

Source handling:
- Candidates from different sources (Daily, LTM) are treated uniformly during selection.
- Source attribution is preserved but does not influence order or retention count.

Output:
- A truncated, ordered list of retained candidates (`kept_candidates`), each preserving text, score, source, and metadata. No new metadata is introduced.

`route_policy.json` — canonical schema:

```json
{
  "<ROUTE>": {
    "retrieval_multiplier": <number>,
    "max_keep": <int>,
    "expansion": { "max_before": <int>, "max_after": <int> }
  }
}
```

Routes and defaults (current baseline; tunable via configuration):

| Route       | retrieval_multiplier | max_keep | expansion.max_before | expansion.max_after |
|-------------|----------------------|----------|----------------------|---------------------|
| CHITCHAT    | 0                    | 0        | 0                    | 0                   |
| DIRECT      | 1                    | 12       | 0                    | 2                   |
| PROCEDURAL  | 1.5                  | 16       | 1                    | 3                   |
| EXPLORATORY | 2                    | 20       | 1                    | 4                   |
| SYNTHESIS   | 2.5                  | 24       | 2                    | 4                   |
| OTHER       | 1.75                 | 10       | 1                    | 2                   |

Validation and fallback:
- `route_policy.json` MUST be loaded and validated at startup. Missing or invalid policy MUST fail fast on startup (no per-request fallbacks).
- Every route entry MUST include `retrieval_multiplier`, `max_keep`, `expansion.max_before`, and `expansion.max_after`.
- `CHITCHAT` has `retrieval_multiplier = 0`, which disables retrieval for that turn (equivalent to `rag=false`).
- Unknown or new routes fall back to `OTHER` at runtime (stable compatibility behavior).

Error and edge handling:
- If the ordered candidate list is empty, the output is an empty list.
- Selection failure does not block request execution (best-effort with empty result as the degraded path).

Invariants:
- Selection is positional and deterministic.
- Higher-ranked candidates are always retained before lower-ranked candidates.
- Retained count is between `0` and `len(ordered_list)`; at least `max_keep` when the list is long enough and no adjacency bonuses apply, possibly greater than `max_keep` when the adjacency bonus applies.
- Context size is bounded before prompt assembly.
- Identical inputs and configuration produce identical outputs.

##### FR-2.3-3.4 — Rehydration & Chunk Expansion
After selection, the pipeline rehydrates `kept_candidates` into semantically complete context by expanding to adjacent chunks and collapsing the expanded set into coherent snippet groups. No relevance scoring, ranking, or pruning decisions are introduced at this stage. Rehydration is staged:

###### FR-2.3-3.4.1 — Chunk Adjacency & Full-Chunk Return
- The system MUST maintain a stable chunk adjacency index enabling deterministic O(1) lookup of the previous and next chunk of any retrieved chunk.
- Adjacency is defined only within the same source document.
  - For PDFs, adjacency is defined only within the same `(filename, page_number)`; each such pair is treated as its own source document. No cross-page adjacency.
- Canonical model is a per-document linear sequence:
  - `doc_id` identifies the source document (for PDFs: `(filename, page_number)`).
  - `chunk_seq` is a monotonic, gap-free integer sequence within a `doc_id`.
  - `prev` / `next` resolve structurally as `chunk_seq - 1` / `chunk_seq + 1` within the same `doc_id`.
- Retrieved candidates MUST carry sufficient metadata (`source_document_id` / `doc_id` and `chunk_index` / `chunk_seq`) to deterministically derive neighbors without semantic inference.
- When a chunk is retrieved due to a similarity match, the entire chunk MUST be returned. Partial reads based on match offset are prohibited; match position MUST NOT affect returned text.
- Chunk text MUST be returned verbatim. No rewriting, trimming, summarization, or deduplication at this stage.
- Implementations MAY reformat retrieved chunk content into a structured representation (e.g. JSON with `chunk_id`, `text`, adjacency refs, source metadata) at retrieval/assembly time, but MUST NOT alter semantic content.

Rebuild and compatibility:
- Adjacency metadata MUST be rebuilt when any of the following change:
  - uploads added / removed / modified for a project
  - `CHUNK_SIZE` or `CHUNK_OVERLAP`
  - adjacency metadata is missing or corrupt for an index claiming FR-2.3-3.4.1 compliance
- `EMBEDDING_MODEL` changes MUST NOT invalidate adjacency (though embeddings may still be rebuilt for retrieval correctness).
- Legacy-compat: indexes that predate adjacency MAY omit adjacency fields; absence is treated as expected and MUST NOT auto-trigger rebuild. If an FR-2.3-3.4.1-compliant index has missing/invalid adjacency at query time, the system MUST degrade to full-chunk-only retrieval for that request and trigger a best-effort background rebuild (no in-request retry/blocking).

Invariants:
- A retrieved chunk is always consumed as a whole.
- Match position within a chunk never affects returned text.
- Adjacency lookup is purely structural, not semantic.
- Any loss of adjacency metadata MUST result in less expansion, never partial context.

###### FR-2.3-3.4.2 — Rank-Weighted Adjacency Expansion
Inputs:
- The ordered retained candidate list `kept_candidates` from FR-2.3-3.3.
- Per-candidate `source_document_id` and `chunk_index` (0-based).
- Per-route `expansion.max_before` / `expansion.max_after` from `route_policy.json`.

Tiering over `kept_candidates` (let `K = len(kept_candidates)`):
- Tier 1 (top third): `i < ceil(K / 3)` — full expansion.
- Tier 2 (middle third): `ceil(K / 3) ≤ i < ceil(2K / 3)` — half expansion.
- Tier 3 (bottom third): `i ≥ ceil(2K / 3)` — minimal expansion.

Per-candidate counts:
- Tier 1: `before_count = max_before`, `after_count = max_after`.
- Tier 2: `before_count = ceil(max_before / 2)`, `after_count = ceil(max_after / 2)`.
- Tier 3: `before_count = min(1, max_before)`, `after_count = min(1, max_after)`.

Requested chunk identifiers:
- Central: `(source_document_id, chunk_index)`.
- Preceding: `(source_document_id, chunk_index - n)` for `n` in `1..before_count`.
- Following: `(source_document_id, chunk_index + n)` for `n` in `1..after_count`.
- Out-of-range indices are skipped. Expansion MUST NOT cross document boundaries.
- Identifiers are emitted in **before…central…after** order per candidate. Identifiers MAY repeat across candidates; consolidation and deduplication occur in FR-2.3-3.4.3.

Scope:
- Applies to both `ltm` and `daily` candidates.
- For `daily`, the document boundary is the synthetic `source_document_id = "daily"` and `chunk_index` corresponds to `day_sequence`.

Missing/invalid adjacency:
- If adjacency is unavailable for a candidate, expansion MUST degrade to the central chunk only (no neighbors).
- For LTM indexes claiming FR-2.3-3.4.1 compliance, missing/corrupt adjacency SHOULD trigger a best-effort background rebuild (no in-request blocking/retry).
- For legacy indexes (pre-FR-2.3-3.4.1), absence is expected; expansion is treated as disabled (central-only) and MUST NOT auto-trigger rebuild.
- If a requested neighbor cannot be fetched, it is a non-fatal skip-neighbor event.
- If the in-memory Daily FAISS cache is cold/unavailable, skip Daily neighbors for that request (no rebuild trigger).

Output:
- An ordered list of requested chunk identifiers (duplicates permitted across candidates), or — if the implementation materializes expansion inline — per-candidate ordered chunk lists, provided no relevance scoring, deduplication, or token-budget enforcement is introduced at this step.

Invariants:
- Higher-ranked candidates always request equal or greater adjacency than lower-ranked candidates.
- Expansion intent is deterministic for identical inputs and configuration.
- Absence of adjacency metadata results in fewer requested chunks, never partial content.

###### FR-2.3-3.4.3 — Structural Dedup & Assembly (Five Passes)
The expansion-intent output from FR-2.3-3.4.2 is collapsed into a single, coherent, non-repeating chunk sequence by five ordered passes. The staging exists to keep each transformation easy to reason about and debug.

**Pass 1 — Structured Expansion Materialization.**
Iterate retained candidates in the order of `kept_candidates`. For each candidate, materialize an ordered list of chunk objects in **before…central…after** order. Each chunk object uses canonical fields `source_document_id`, `chunk_index`, `text`. Candidate-level ordering and per-candidate chunk ordering are preserved exactly as materialized. No deduplication, cross-candidate reordering, text modification, or token budgeting at this pass. If adjacency is unavailable for a candidate, emit the central chunk only (consistent with FR-2.3-3.4.2).

**Pass 2 — Chunk Identity Deduplication.**
Walk the expanded results in `kept_candidates` order. Maintain an ordered mapping keyed by `(source_document_id, chunk_index)`. For each chunk:
- If the key is not present in the mapping, insert it.
- Otherwise skip the chunk (first-seen wins, preserving relevance priority without requiring score comparisons).
No merging, trimming, or text modification occurs. Output is a collection of unique chunks keyed by `(source_document_id, chunk_index)`. Cross-document ordering is not yet enforced.

**Pass 3 — Source-Document Ordering & Narrative Coherence.**
Organize the unique chunk set into per-source timelines:
- Determine the distinct set of `source_document_id` values. Chunks with missing/null `source_document_id` (sparse/legacy) are handled per compatibility policy — grouped under a synthetic source or appended in first-seen order.
- Each `source_document_id` is an independent timeline; within a source, chunks are sorted by `chunk_index` ascending.
- Across sources, ordering is deterministic and implementation-defined (e.g. first-seen, alphabetical, or stable sort by `source_document_id`).
- Emit an ordered sequence of chunks (or per-source ordered segments). Chunk shape, identity, and text are unchanged. No token budgeting.

**Pass 4 — Adjacent Chunk Overlap Trimming.**
Inputs: ordered, unique, narratively-coherent chunk list from Pass 3; `CHUNK_OVERLAP` (and optionally `CHUNK_SIZE`) used by the encoder/splitter when the index was built.

Scope: operates only within a document, only on adjacent chunks. Only the prefix of the second chunk is trimmed (the suffix of the first chunk is kept). Chunk identity and order are never changed. Only exact-duplicate boundary text is removed; no fuzzy or semantic trimming.

Procedure for each consecutive same-`source_document_id` pair `(A, B)`:
1. `max_overlap = min(CHUNK_OVERLAP, len(A.text), len(B.text))`.
2. Find the longest `k` in `1..max_overlap` such that `A.text[-k:] == B.text[:k]` (exact string match).
3. If `k > 0`: set `B.text = B.text[k:]`. If `k == len(B.text)` (B would become empty), do not trim (leave B unchanged or use a minimal placeholder per implementation policy).

Chunks with missing or invalid `source_document_id` (sparse/legacy) are skipped for adjacency (neither trimmed nor used to trim a neighbor). Single-chunk documents and the last chunk in a document require no trim. If no exact suffix-of-A equals prefix-of-B in the window, no trim is performed.

**Pass 5 — Snippet-Group Collapse.**
Walk the trimmed chunk list in order and group consecutive chunks that share the same `(source_document_id, source)`:
- Chunks with missing/invalid `source_document_id` do not merge with neighbors; each forms its own single-chunk group.
- Different `source` values (e.g. `ltm` vs `daily`) never merge.

For each group, emit one entry with the same shape as a single chunk:
- `source`, `score`: from the first chunk in the group (all chunks in an expanded set share the same score).
- `text`: concatenation of all chunk texts in the group, joined with a single newline (`\n`); no extra spacing.
- `metadata`: from the first chunk in the group; MAY include a display-friendly range for `chunk_index` when the group has more than one chunk (e.g. `"199..201"`) so debug and logs show the span.

The resulting list of snippet-group entries replaces the per-chunk list as `kept_candidates` for all downstream consumers (prompt formatting, debug dumps, token counting). Prompt assembly emits one `Snippet N` header and one separator per entry; token counting uses the concatenated text once per group. The snippet-group list is injected as a single `Context:` system message before user input, subject to `RAG_CONTEXT_MAX_TOKENS`.

Invariants (global for FR-2.3-3.4.3):
- No chunk content is dropped except through identity-level dedup (pass 2) and exact-boundary overlap trim (pass 4).
- Group boundaries are determined only by consecutive same `(source_document_id, source)`.
- Deterministic for identical inputs and configuration.

#### FR-2.3-4 — Logging / Debug Visibility
When a pair is rolled off:

- Log to the backend console and file logs
- Include entries like:
  - `[DailyRAG] Rolled off pair → project=<id>`
  - `Prompt: <prompt text>`
  - `Response: <assistant text>`
  - `Tokens: <approx count>`

Ensure logs are readable for inspection and troubleshooting. Use the standard application logger (console/file levels configurable).

#### FR-2.3.5 — Environment Variables

- `CHAT_HISTORY_LIMIT_PAIRS=10` — number of prompt/response pairs kept in working memory.
- `DAILY_RAG_ENABLED=true` — global default toggle for Daily RAG; per-project toggle overrides.
- `BASE_TOP_K` — baseline retrieval size consumed by FR-2.3-3.1; `PER_SOURCE_K = ceil(BASE_TOP_K * retrieval_multiplier)` where `retrieval_multiplier` comes from `route_policy.json` (FR-2.3-3.3).
- `RAG_CONTEXT_MAX_TOKENS` — final prompt context token cap enforced during prompt assembly (downstream of FR-2.3-3.4.3).

All per-source K values, score thresholds, retained counts, and adjacency depths are controlled by `route_policy.json` (FR-2.3-3.3) and not by environment variables.

#### FR-2.3.6 — UI Integration
In the Manage Project modal display:

- “Active Pairs” count (deque length)
- “Daily RAG size” and “Tokens indexed” for daily (mirroring main stats rendering)
- Per-project toggle: “Keep Daily History” (maps to `daily_rag_enabled`, default true)

### Lifecycle
`daily.json` (and its companion `daily.txt`, per FR-2.7.1) are the persistent Daily artifacts; they persist across days until consumed/reset during the 3.0 sleep cycle. The Daily FAISS index is an in-memory cache with the lifetime of the server process, warmed lazily per project on first project-scoped request and rebuildable from `daily.json` at any time (see FR-2.3.2).

Sleep cycle logic will:

- Read and prune Daily memory via `daily.json` / `daily.txt`.
- Merge summarized chunks into `index.faiss`.
- Reset Daily persistent artifacts for the next run and clear the in-memory Daily FAISS cache for the merged project.

### Acceptance Criteria

- Oldest chat pair removed from memory and DB when limit exceeded.
- Rolled-off pair embedded and appended to the in-memory Daily FAISS cache; metadata appended to `daily.json` under `daily.lock`.
- Debug log clearly shows prompt + response text.
- Retrieval MUST execute the unified pipeline defined in FR-2.3-3; Daily and LTM candidates are produced by a single canonical entry point (FR-2.3-3.1), globally sorted by raw similarity (FR-2.3-3.2), pruned per `route_policy.json` (FR-2.3-3.3), and rehydrated/deduplicated/collapsed into snippet groups (FR-2.3-3.4).
- Identity-level deduplication at FR-2.3-3.4.3 (pass 2) is the only deduplication stage; no similarity-threshold or source-preference dedup is performed.
- Corruption / `EMBEDDING_MODEL`-change rebuilds of the in-memory Daily FAISS cache are handled cleanly with logging; `daily.json` is never deleted on model change (it is re-embedded in place).
- System operates with incremental in-memory adds; persistence writes are limited to `daily.json` (and `daily.txt` per FR-2.7.1), serialized via `daily.lock`.


Version 2.3.1 — RAG Query Builder + Router (Topic-Aware Retrieval)

Purpose
Add an intelligent pre-RAG “builder” stage that rewrites the user message into high-quality retrieval queries and decides whether retrieval should occur at all.
The builder also extracts semantic topics and entities to enable metadata-aware search using the #topics, #decisions, and #open_questions fields in pruned RAG data.
This reduces wasted RAG lookups, increases precision, and lays the groundwork for true semantic routing.

Functional Requirements

FR-2.3.1.1 — Mini Model Router + Query Builder
• Introduce a lightweight LLM call (builder_llm) before retrieval.
• Input: 3–4 sentence summary of all in‑memory pairs (not rolled off) + current user turn.
• Output (JSON): route, rag, standalone, paraphrases, hyde, entities, topics, reason, confidence.
• Example schema:
{ "route":"CHITCHAT|DIRECT|PROCEDURAL|EXPLORATORY|SYNTHESIS|OTHER", "rag":true, "standalone":"", "paraphrases":[], "hyde":"", "entities":[], "topics":[], "reason":"", "confidence":0.0 }
• Use `BUILDER_MODEL` over the same OpenAI channel as chat; no extra latency/budget constraints beyond `BUILDER_MAX_TOKENS`.

FR-2.3.1.2 — Routing Logic
• If rag=false or route="CHITCHAT", skip retrieval and reply directly via chat model (still include in‑memory history).
• Else embed standalone + 2–3 paraphrases + 1 HYDE and run topic‑aware RAG lookup.
• If `confidence < BUILDER_CONFIDENCE_MIN`, perform conservative retrieval (standalone only; skip paraphrases/HYDE).
• If the builder fails/times out/returns invalid JSON: log a warning and skip RAG entirely (answer directly).

FR-2.3.1.3 — Topic and Entity Extraction
• Builder emits topics and entities.
• Sidecar metadata for main RAG: store per‑chunk metadata in `memory/{project}/faiss/meta_topics.json`, keyed by FAISS docstore ID (no full re‑index now). Merge sidecar with existing metadata during retrieval for downstream consumers (e.g. tagging, dream). Topic/entity values MUST NOT be used to bias retrieval scoring or ordering (see FR-2.3-3.2).

FR-2.3.1.6 — Prompt Template (for Builder)
System: “You are a fast query builder and router for RAG. Return strict JSON. No prose.”
User: “Recent summary: {history} Turn: {user_text}”
Rules:
• If small-talk/joke/meta → route=CHITCHAT, rag=false.
• Else choose domain route and return concise rewritten query set plus topics/entities.

FR-2.3.1.8 — Environment Variables
BUILDER_MODEL=gpt-4o-mini
BUILDER_CONFIDENCE_MIN=0.75
BUILDER_MAX_TOKENS=512
BUILDER_CACHE=True

FR-2.3.1.9 — Logging / Debug Visibility
• Log builder JSON into the existing app log (no separate file), including timestamp, route, rag, confidence, topics, and trimmed standalone; tag lines clearly (module logger/type="builder").
• Optionally display route and confidence in chat UI for debug.

FR-2.3.1.10 — Concurrency and Locking
• Use a single `faiss.lock` for FAISS and sidecar metadata reads/writes under `memory/{project}/faiss/`; keep locks short‑lived.

FR-2.3.1.11 — Builder Cache
• If `BUILDER_CACHE=True`, cache builder JSON in memory per process with TTL ≈ 10 minutes and max ≈ 500 entries; key by `(project_id, history_summary, user_turn)`; no disk persistence.

Acceptance Criteria

• Builder invoked on every turn and returns valid JSON.
• Non-RAG turns bypass retrieval entirely.
• RAG turns use rewritten queries and topic/entity expansion via the unified pipeline in FR-2.3-3.
• Retrieved candidates are globally sorted by raw cosine similarity (FR-2.3-3.2); no topic/decision/question score boosts are applied.
• Performance target: ≤ 800 ms avg builder latency.

## Version 2.4 — Expanded Logging & Trace Flags

### Purpose
Improve observability and debugging by ensuring every major pipeline step (input, builder, retrieval, response, roll-off) is logged with clear, consistent tags.  
This replaces the previously planned Langfuse integration with a lightweight, built-in structured logging approach.

### Functional Requirements

#### FR-2.4.1 — Structured Log Format
Continue using the existing global logger, but standardize all messages to a common tagged format:

```
[timestamp] [level] [module] [TAG] message
```

Example:
```
2025-10-29 09:42:13 INFO app.core.chat [PROMPT] project=Continuum msg_id=153 text="How does RAG merge daily?"
```

#### FR-2.4.2 — Mandatory Log Points
Every chat request must include the following tagged log entries:
- **[PROMPT]** – user input received by `/chat`
- **[BUILDER]** – query-builder output (route, rag flag, confidence)
- **[RETRIEVAL]** – RAG query details (hit count, avg similarity)
- **[RESPONSE]** – model output summary (token count, short preview)
- **[ROLLOFF]** – when a pair is embedded into the in-memory Daily FAISS cache
- **[ERROR]** – any exception during request processing

#### FR-2.4.3 — Optional Context Data
Each log entry should include:
- `project_id`
- `message_id`
- `route`
- `rag_used`
- short preview of text (≤ 200 chars)

This makes it easy to trace specific projects, conversations, and decisions.

#### FR-2.4.4 — Log Destination and Rotation
- Keep default console + file handlers.  
- Add rotation policy: `logs/syx.log`, 10 MB × 5 files.  

#### FR-2.4.5 — Verification Checklist
- Each chat request produces a full `[PROMPT] → [BUILDER] → [RETRIEVAL] → [RESPONSE]` chain in the logs.
- Roll-off events show the complete prompt/response pair content.
- No sensitive or overly long text (>200 chars) is logged.
- Average latency impact of logging < 10 ms per request.

### Acceptance Criteria
- Logs clearly trace every request lifecycle from prompt to response.  
- Each log entry includes a standardized `[TAG]` identifier.  
- Developers can quickly grep for stages like `[RETRIEVAL]` or `[ROLLOFF]`.  
- No external tracing tools required; system is fully observable through native logs.  
- Old Langfuse references removed; same logger reused for all instrumentation.


## Version 2.5 — Route-Aware Retrieval

### Purpose
Adjust retrieval behavior based on the semantic route (`CHITCHAT | DIRECT | PROCEDURAL | EXPLORATORY | SYNTHESIS | OTHER`) identified by the query builder (FR-2.3.1.1). The route selects a row of `route_policy.json`, which configures per-source retrieval K, retained-candidate cap, and adjacency expansion for the unified pipeline in FR-2.3-3. Namespace-based routing, namespace boosting, and per-route score thresholds are removed; route behavior is expressed exclusively via `route_policy.json` and selection/expansion logic.

### Functional Requirements

#### FR-2.5.1 — Builder Output Utilization
Use the existing builder LLM output (FR-2.3.1.1) to extract the `route` and `rag` fields, e.g.:

```
{"route": "PROCEDURAL", "rag": true, "confidence": 0.91}
```

If `rag=false` or the selected `route_policy.json` row has `retrieval_multiplier = 0` (e.g. `CHITCHAT`), retrieval is skipped entirely and the chat model answers directly using in-memory history only.

#### FR-2.5.2 — Route Policy Configuration
Route-specific retrieval configuration is held in `backend/app/config/route_policy.json`. Canonical schema, routes, and defaults are defined in FR-2.3-3.3. `route_policy.json` is the authoritative per-route configuration source for:
- `retrieval_multiplier` (per-source K via `ceil(BASE_TOP_K * retrieval_multiplier)`; consumed by FR-2.3-3.1)
- `max_keep` (initial retained-candidate cap; consumed by FR-2.3-3.3)
- `expansion.max_before` / `expansion.max_after` (adjacency depth; consumed by FR-2.3-3.4.2)

`meta_namespaces.json` is deprecated and MUST NOT be used; namespace-based routing is removed.

#### FR-2.5.5 — Logging Integration
Add a `[ROUTE]` log event before retrieval and a `[RETRIEVAL]` log event after retrieval, e.g.:

```
[ROUTE] route=PROCEDURAL retrieval_multiplier=1.5 max_keep=16 expansion={"max_before":1,"max_after":3}
[RETRIEVAL] route=PROCEDURAL hits=24 kept=16 avg_similarity=0.78
```

Logged fields MUST reflect values resolved from `route_policy.json` and the FR-2.3-3 pipeline (no `namespaces` field).

#### FR-2.5.6 — Fallback Behavior
If the builder returns an unknown route, routing MUST fall back to the `OTHER` row of `route_policy.json`. A missing or invalid `route_policy.json` at startup is a fail-fast condition (no per-request fallbacks; see FR-2.3-3.3).

### Acceptance Criteria
- Builder-identified routes map deterministically to `route_policy.json` rows; runtime retrieval K, retained counts, and adjacency depth match the selected row.
- CHITCHAT and `rag=false` turns bypass retrieval entirely.
- Logging clearly displays the resolved route and applied policy values.
- Unknown routes fall back to `OTHER`; missing/invalid `route_policy.json` fails fast at startup.
- No breaking changes to the existing RAG pipeline beyond removal of namespace-based routing and namespace boosting.


## Version 2.6 — Project Personality & System Prompt Profiles

### Purpose
Enable each project to define its own persistent **system prompt** and **LLM personality**, so interactions, retrieval bias, and memory tone adapt automatically per project. This gives each project a distinct “voice” and cognitive style before entering the Sleep Cycle.

### Functional Requirements

#### FR-2.6.1 — Per-Project System Prompt File
Create a text file for each project containing its base system prompt.

- File path: `memory/{project}/system_prompt.txt`
- Loaded automatically at project startup or when the user switches projects.
- Automatically inserted as the first system message for every `/chat` request.
- Editable from the UI (“Edit Project Prompt” button).
- If missing or empty, fall back to the default prompt file referenced by `DEFAULT_SYSTEM_PROMPT_PATH`.

Env:
- `DEFAULT_SYSTEM_PROMPT_PATH` (e.g., `app/config/defaults/system_prompt.txt`)
- `DEFAULT_PERSONALITY_PROMPT_PATH` (e.g., `app/config/defaults/personality.json`)
  - Values are written by the Makefile to `.env` and read by the backend.

Example content:
```
You are Syx-AI, a reflective assistant that consolidates knowledge during nightly sleep.
Focus on pruning redundant information and clarifying reasoning.
```

#### FR-2.6.2 — Personality Profile
Add a companion JSON file to capture tone, verbosity, and stylistic preferences.

- File path: `memory/{project}/personality.json`
- Example schema:
  ```json
  {
    "tone": "analytical",
    "verbosity": "concise",
    "format": "markdown",
    "creativity": 0.4,
    "domain_focus": ["AI", "neuroscience"]
  }
  ```
- Loaded and cached at runtime.
- Accessible via `GET /projects/{id}/personality`
- Editable via `PATCH /projects/{id}/personality`
- When changed, updates persist immediately to disk.
- Normalization and mapping:
  - `tone`, `verbosity`, `format` are normalized to lowercase.
  - `creativity` is a float 0.0–1.0 and maps directly to model temperature (passthrough) when supported by the selected model.
  - `domain_focus` is preserved as provided and used as phrasing hints (no retrieval bias in 2.6).
- Caching: prompt and personality are cached per project and invalidated on `PATCH`/`PUT` so the next `/chat` uses new values without restart.
- System project (Continuum) is editable for both prompt and personality.

#### FR-2.6.3 — Prompt Injection Layer
Integrate both the system prompt and personality profile into model calls.

- Load `system_prompt.txt` as the first system message.
- Apply `personality.json` to adjust:
  - temperature
  - max tokens
  - or inject phrasing hints (e.g., “Respond concisely in Markdown.”)
- Message ordering (final):
  1) `system` → project system prompt
  2) `assistant` → "personality hint" derived from `personality.json`
  3) `system` → merged RAG context (when retrieval is used)
  4) `user` → current user message

Notes:
- Some models reject non-default temperatures. The system detects this once per model and thereafter skips the temperature override for that model, silently using the default.
- Model override on `/chat` is validated against `settings.available_models`; invalid models return HTTP 400.

Example message structure:
```python
messages = [
    {"role": "system", "content": project.system_prompt},
    {"role": "assistant", "content": format_personality_hint(project.personality)},
    {"role": "user", "content": user_input}
]
```

#### FR-2.6.4 — Personality Manager UI
Add a new panel in the React frontend to edit per-project personality and system prompt.

- Tab or modal labeled **“Personality”**
- Fields:
  - System Prompt (multiline textarea)
  - Tone (dropdown: analytical, creative, friendly, formal)
  - Verbosity (dropdown: concise, balanced, detailed)
  - Creativity (slider 0–1)
  - Domain Focus (tag input)
- Save button → calls `PATCH /projects/{id}/personality` and `PUT /projects/{id}/system_prompt`
- Optional “Live Preview” showing a short simulated reply using current tone settings.

Example layout (using shadcn/ui):
```tsx
<Card>
  <CardHeader>
    <CardTitle>Project Personality</CardTitle>
    <CardDescription>Edit how this project thinks and speaks.</CardDescription>
  </CardHeader>
  <CardContent>
    <Textarea label="System Prompt" value={prompt} onChange={...} />
    <Select label="Tone" options={["analytical","friendly","creative","formal"]} />
    <Select label="Verbosity" options={["concise","balanced","detailed"]} />
    <Slider label="Creativity" min={0} max={1} step={0.05} />
    <TagInput label="Domain Focus" />
  </CardContent>
  <CardFooter>
    <Button onClick={saveChanges}>Save</Button>
  </CardFooter>
</Card>
```

#### FR-2.6.5 — Logging and Verification
- Log personality and system prompt load events:
  ```
  [PROJECT] Loaded system_prompt=system_prompt.txt personality=personality.json
  ```
- If missing files, log fallback:
  ```
  [PROJECT] Using default system prompt and personality
  ```
- Confirm new settings apply to the next chat message (no restart required).
- Additional debug (optional but recommended for verification):
  - Default paths, existence, and byte sizes on startup:
    - `Default system_prompt path=… exists=… size_bytes=…`
    - `Default personality path=… exists=… size_bytes=…`
  - On load/save per project:
    - `Loaded project system_prompt path=… bytes=…`
    - `Loaded project personality path=… keys=[…]`
    - `Saved project system_prompt path=… bytes=…`
  - On each `/chat` turn (trimmed):
    - `[PROMPT] base_sys_bytes=… rag_sys_bytes=… hint_bytes=… base_sys_preview="…"`
    - `[PROMPT] sending messages roles=[…] lens=[…]`

### Acceptance Criteria
- Each project loads and applies its unique system prompt and personality automatically.
- Edits persist and affect subsequent chat sessions immediately.
- Default fallback works cleanly if project-specific files don’t exist.
- Personality Manager UI can view, edit, and save personality and prompt files.
- Log entries verify proper load and fallback behavior.



## Version 2.7 — Cleanup & Sleep Prep

### Purpose
Finalize the 2.x foundation by polishing UI behavior and adding infrastructure needed for the upcoming 3.0 Sleep Cycle. This version adds a daily text export, a global sleep lock (to safely pause interactions), and a user-facing **Remember / Forget** toggle that controls whether a chat pair is persisted to daily memory.

### Functional Requirements

#### FR-2.7.1 — Daily Text Snapshot
Ensure each project maintains a single plain‑text mirror of its daily context for deterministic nightly consolidation (FR-3.2.3) and human review. Name retained historically; pruning no longer occurs at sleep time (see DELTA-A.5).

- File path: `memory/{project}/daily.txt` (one file per project; no date‑based rotation)
- Source of truth & flow:
  - Working chat history is persisted in the database (`ChatMessage`) per project.
  - When a user→assistant pair rolls off the working set, and the assistant’s `forget` flag is false, the pair is:
    - Appended to `daily.txt` as a text block
    - Added to the in-memory Daily FAISS cache (see FR-2.3.2; the legacy on-disk directory `memory/{project}/daily_faiss/` is deprecated and not written)
    - Recorded in `daily.json` metadata for backfill and stats
  - Rolled‑off DB rows for that pair are deleted.
- Generated automatically:
  - On each roll‑off: append the pruned pair as text.
  - On sleep initiation (`POST /sleep/start`) if `daily.txt` is missing: backfill from `daily.json`.
- Each entry block includes:
  ```
  [timestamp] [route: <namespace>]
  prompt: <user text>
  response: <assistant text>
  ```
- The daily text block MAY include tag metadata lines (e.g., `#topics/#intent/#type`) for rolled-off pairs when available.
- Purpose:
  - Human‑readable mirror of Daily memory (the Daily FAISS index itself is an in-memory cache per FR-2.3.2; `daily.json` is the persistent metadata store).
  - Input source for deterministic nightly consolidation (FR-3.2.3).
- Backfill policy on `/sleep/start`:
  - If `daily.json` has entries but `daily.txt` is missing, backfill each entry as a block in the above format and log a warning.
- Remember/Forget policy:
  - Pairs where the assistant message has `forget=true` are not written to `daily.txt`, `daily.json`, or the daily FAISS index.

#### FR-2.7.2 — Global Sleep Lock
Prevent user interactions during the sleep cycle.

- Implement lock flag:
  - File‑based: `runtime/sleep.lock`
  - In‑memory: `core.state.is_sleeping`
- While active:
  - All writes (POST/PUT/PATCH/DELETE) return HTTP **423 (Locked)** with message: `"System is sleeping. Try again later."`
  - Reads (GET) remain allowed.
  - Frontend shows overlay modal: “Syx is sleeping — consolidating memory. Please wait…”
  - No roll‑off or daily.txt writes occur while sleeping; submissions fail with 423.
- Status: `GET /sleep/status` → `{ sleeping: true|false, since: <ISO8601>, lock_path: "..." }`
- Startup behavior: if `runtime/sleep.lock` exists, start with `is_sleeping=true` and log a Warning.
- On wake: remove `sleep.lock` and set `is_sleeping = False`.
- Log entries:
  ```
  [SLEEP] Lock engaged at <time>
  [SLEEP] Lock released at <time>
  ```

#### FR-2.7.3 — Sleep Cycle Stub Endpoint
Add a placeholder endpoint to initiate and log the sleep cycle.

- `POST /sleep/start`
- Behavior:
  - Engage sleep lock (global; all projects).
  - Log start and completion messages.
  - Generate or update `daily.txt` for each project; perform backfill if needed (see FR‑2.7.1).
  - Return JSON: `{ "status": "sleep cycle initiated" }` (project is not required; applies globally).
  - No summarization yet (implemented in 3.0).

#### FR-2.7.4 — “Remember / Forget” Toggle
Add a toggle control at the top of each assistant response bubble that determines whether that chat pair will be persisted to the daily memory.

- Component: small toggle, left‑justified above each assistant response.
  - Left (default): **Remember** — pair will be embedded and rolled into daily RAG.
  - Right: **Forget** — pair is skipped during roll‑off.
- Visual:
  - Use `Toggle` from `shadcn/ui` (or equivalent).
  - Label aligned right: “Forget”; when active, style in muted red.
- Behavior:
  - Persist state in chat record metadata (`ChatMessage.forget: true|false`, default `false`).
  - Roll‑off logic checks this flag before embedding:
    ```python
    if not pair.get("forget", False):
        embed_to_daily(pair)
    else:
        logger.info("[ROLLOFF] Skipped pair (forget flag set).")
    ```
  - UI reload reflects stored state.
- API:
  - `PATCH /projects/{id}/chats/{assistant_msg_id}` with body `{ "forget": true|false }` to update the flag.
  - GET `/projects/{id}/chats` includes `forget` for assistant messages.
- Logging:
  ```
  [FORGET] Pair <id> skipped from daily memory.
  ```

#### FR-2.7.5 — UI & UX Enhancements
Polish interface consistency and readability.

- Enable Markdown and code‑block rendering for assistant messages:
  - Support fenced code (```python) and inline code (`example`).
  - Use `react-markdown` + `rehype-highlight` with a GitHub‑style theme.
- Ensure layouts and spacing are consistent across chat, memory, and personality tabs.

#### FR-2.7.6 — Code & Log Cleanup
- Normalize logger names and message styles (standard `[TAG]` syntax).
- Add/standardize tags: `[SLEEP]`, `[FORGET]`, `[DAILYTXT]` (daily text writes).
- Remove deprecated references (e.g., `preferred_namespace`).
- Verify old log files rotate correctly and remove any stale lock files on startup.

#### FR-2.7.7 — “Keep” Toggle and Daily Tag
Add a second toggle next to the existing Forget control to carry a “keep” flag through to daily history.

- UI:
  - Add a “Keep” checkbox next to the “Forget” checkbox (same row, a small horizontal gap; unchecked by default).
  - Render adjacent to the Forget control for each assistant message.
  - State persists and reflects when the chat reloads.

- Behavior:
  - The Keep flag is metadata only; it does not change roll-off behavior.
  - Forget takes precedence: if `forget=true`, the pair is not written to daily memory regardless of Keep.
  - If the pair is persisted (i.e., not forgotten and daily history is enabled), include the Keep flag in the `daily.txt` header line.

- Persistence:
  - Store per-assistant message as `ChatMessage.keep: bool` (default `false`), similar to `ChatMessage.namespace` and `ChatMessage.forget`.
  - Include `keep` in `daily.json` metadata entries written on roll-off for backfill and stats.

- daily.txt format:
  - Extend the header to include the keep flag alongside the namespace/route tag.
  - Example format:
    ```
    [timestamp] [route: <namespace>] [keep: true|false]
    prompt: <user text>
    response: <assistant text>
    ```
    - Projects already emitting `[namespace: <ns>]` may continue doing so; the Keep tag is appended similarly, e.g. `[namespace: other] [keep: true]`.
  - Each pair entry block is delimited by:
    - `=== BEGIN DAILY PAIR ===`
    - `=== END DAILY PAIR ===`

- API:
  - Update `GET /projects/{id}/chats` to include `keep` for assistant messages.
  - Extend `PATCH /projects/{id}/chats/{assistant_msg_id}` to accept `{ "keep": true|false }` (in addition to `forget`) and persist to `ChatMessage.keep`.

- Roll-off integration:
  - On roll-off, read `keep` and `namespace` from the assistant message and:
    - Write `[keep: true|false]` in `daily.txt` header.
    - Persist `keep` in `daily.json` for that entry.
  - If `forget=true`, skip writing to `daily.txt`, `daily.json`, and the daily FAISS index.

- Backfill:
  - When `POST /sleep/start` performs backfill (if `daily.txt` missing), include `[keep: true|false]` in reconstructed headers using the `daily.json` metadata (default to `false` if missing).

### Acceptance Criteria
- `daily.txt` is generated/updated automatically and mirrors the Daily memory represented by `daily.json` and the in-memory Daily FAISS cache (FR-2.3.2).
- “Forget” toggles correctly prevent a chat pair from being embedded or written to daily memory.
- System enters “sleeping” state when `/sleep/start` is called:
  - API returns **423 (Locked)** during the cycle.
  - UI overlay displayed until lock is released.
- Logs show clean sleep engagement/release timestamps.
- Markdown/code rendering works across chat messages.
- No blocking issues or schema changes introduced.


## Version 2.8 — Default Global RAG File

### Purpose
Ensure every new project starts with a consistent baseline of Syx system knowledge, even if the user never uploads any files.  
This version simplifies the earlier design by copying a shared **DEFAULT_RAG.txt** into each project’s uploads directory on creation and triggering a RAG rebuild automatically.

### Functional Requirements

#### FR-2.8.1 — Default RAG Source File
- Shared baseline file path:
  ```
  backend/app/config/defaults/DEFAULT_RAG.txt
  ```

#### FR-2.8.2 — Project Initialization Behavior
During project creation:
1. Create required folders:
   ```
   memory/{project}/uploads/
   ```
2. Copy the default baseline file:
   ```python
   shutil.copy("backend/app/config/defaults/DEFAULT_RAG.txt",
               f"memory/{project}/uploads/DEFAULT_RAG.txt")
   ```
3. Log initialization:
   ```
   [INIT] Added default RAG file to memory/{project}/uploads/
   ```

#### FR-2.8.3 — Automatic RAG Rebuild
After copying the default file:
- Automatically trigger a RAG rebuild (or “embed all uploads” process) to ensure the default file is indexed immediately, even if the user never uploads additional content.
- Example:
  ```python
  rebuild_rag(project_id)
  ```
- Log confirmation:
  ```
  [INIT] RAG rebuilt for project continuum (includes DEFAULT_RAG.txt)
  ```

#### FR-2.8.4 — Maintenance and Visibility
- The default file appears in the project’s **uploads directory** and can be viewed, edited, or replaced like any user file.
- If the project is rebuilt or reindexed, the default file is re-embedded automatically.
- No special handling (e.g., `system=true`) is required — the file name identifies it as part of the baseline.
- Missing default file:
  - Log a warning but do **not** block project creation.
  ```
  [WARN] DEFAULT_RAG.txt not found; project created without baseline knowledge.
  ```

### Acceptance Criteria
- Each new project automatically includes `DEFAULT_RAG.txt` in `uploads/`.
- RAG rebuild runs immediately after creation, ensuring the default file is embedded.
- Default file visible in the uploads list and re-embeds on rebuild.
- Logs confirm default file copy and rebuild actions.
- Missing default file logs a warning but does not cause failure.

**End of Version 2.x Series — Ready for 3.0 Sleep Cycle.**

# Version 3 — Sleep Cycle and Memory Consolidation

## Overview
Version 3 introduces **autonomous long-term memory consolidation** through a nightly **Sleep Cycle** that prunes, summarizes, and rebuilds each project’s RAG automatically.
This version transforms Syx from a reactive chat system into one that maintains knowledge over time, preparing the foundation for **Version 4 — Dreaming**.

---

## Version 3.1 — Sleep Scheduler and Lock Framework

### Overview
Version 3.1 implements the foundational scheduling and locking mechanism that controls the Sleep Cycle.  
This version focuses purely on automation, concurrency safety, and lifecycle logging — no summarization or RAG rebuilding yet.

---

### Purpose
Provide a stable framework for triggering and managing the Sleep Cycle automatically or manually, ensuring that all chat and upload actions are paused while the system performs maintenance.

### Functional Requirements

#### FR-3.1.1 — Global Sleep Lock
- On scheduler trigger or manual `/sleep/start`, create `runtime/sleep.lock`.
- While lock exists, all non-GET endpoints return `HTTP 423 (Locked)` (strict write block).
- Remove the lock after completion.
- If a lock already exists at start, log `[SLEEP] Already running, skipping.`

#### FR-3.1.2 — Internal Scheduler
- Integrate **APScheduler** (BackgroundScheduler).
- Configuration:
  - `ENABLE_SCHEDULER=True`
  - `SLEEP_CYCLE_HOUR=3` (default 3 AM)
- Scheduler invokes the same internal background runner used by the `/sleep/start` endpoint.
- If the system is already sleeping when the scheduler fires, log `[SLEEP] Already running, skipping.` and do nothing (no catch-up runs).
- Manual endpoint behavior:
  - `POST /sleep/start` starts the background runner and returns immediately with `200`.
  - If already sleeping, it returns `423` with `{ "error": "System is sleeping. Try again later." }`.

#### FR-3.1.3 — Background Thread Execution
- When triggered, spawn a background thread to simulate the sleep operation.
  - Log `[SLEEP] Thread started`.
  - First, flush all active chat pairs from the database into `daily.txt` for each project with `daily_rag_enabled=true`:
    - Pair consecutive `user` → `assistant` messages in chronological order; skip orphaned messages (delete them).
    - Respect flags: if the assistant message has `forget=true`, skip writing that pair; otherwise append the pair to `daily.txt` (text-only format, including `[route: <namespace>]` and `[keep: true|false]` headers).
    - After appending, delete both `ChatMessage` rows for that pair from the DB and clear the in-memory deque for the project to prevent duplication on later roll-off.
    - Log `[SLEEP][FLUSH] Flushed {N} pairs to daily.txt for project={id}` and a summary of deleted message counts; log a `[FORGET]` line for skipped pairs.
  - Perform the existing V2.x daily backfill behavior (for each project: if `daily.txt` is missing and `daily.json` exists, write `daily.txt` from metadata). Log count in `[SLEEP] Completed (updated_projects=N)`.
  - Sleep for ~60 seconds to simulate the maintenance window (testing aid).
  - Log `[SLEEP] Completed`.
- On any exception, log `[SLEEP][ERROR]` and release the lock.

#### FR-3.1.4 — Logging
- Mandatory log sequence for every run:
  `[SLEEP] Lock engaged → [SLEEP] Thread started → [SLEEP][FLUSH] … → [SLEEP] Completed → [SLEEP] Lock released`.

---

### Acceptance Criteria
- Scheduler fires automatically at the configured local hour and can be triggered manually via `/sleep/start`.
- Lock file is created and removed correctly; all non-GET endpoints return `HTTP 423` during the lock window (≈60s).
- Logs show the complete `[SLEEP]` sequence from start to finish, including the updated_projects count in the Completed message when backfill runs.
- Daily backfill (only if `daily.txt` is missing and `daily.json` exists) executes inside the sleep window; no summarization or RAG rebuilds occur in 3.1.


## Version 3.2 — Daily Consolidation Pipeline (Deterministic)

### Overview
Version 3.2 performs nightly consolidation of daily memory for each project with a non-empty `daily.txt`. Consolidation is **deterministic** and **prompt-less**: no LLM pruning or formatting passes are performed at sleep time. Semantic enrichment (topics/intent/type/semantic_handle/questions) already happened at pair-roll-off via the tagger (FR-3.4.2) and was persisted into `daily.txt`, `daily.json`, and the in-memory Daily FAISS cache; sleep only rolls those enriched artifacts forward.

The deterministic consolidation writes `sleep_summary.txt`, which is the input to FR-3.3 (per-cycle merge + RAG rebuild).

---

### Purpose
Convert each project's tag-enriched `daily.txt` into a per-cycle `sleep_summary.txt` artifact using a single deterministic pass. Rationale: removing LLM prompts from sleep consolidation eliminates nightly maintenance token cost while preserving retrieval quality, because all semantic enrichment already lives in the per-pair tags produced at ingest time (see DELTA-A.5).

### Functional Requirements

#### FR-3.2.1 — Project Scan
- During the sleep thread (after the global sleep lock is engaged), iterate through all `memory/{project}/` directories.
- If `daily.txt` exists and is non-empty → process it.
- Else, log `[SLEEP] Skipped project (no daily.txt) project={id}` and continue.

#### FR-3.2.3 — Deterministic Consolidation Stage
- Read `daily.txt` verbatim.
- Append an `=== END DAILY MEMORY: MM/DD/YYYY ===` closing tag in memory only (do not persist back to `daily.txt`; see FR-3.2.6).
- Normalize line endings to `\n`.
- Write the resulting text as-is to `memory/{project}/sleep_summary.txt`.
- No LLM calls, no content transformation, no reordering, no pruning, no `[Open Questions]` appendix (open-question candidates flow through the separate `open_questions.jsonl` stream; see FR-3.4.6).
- Log `[SLEEP][FORMAT] Deterministic summary complete project={id}`.

#### FR-3.2.4 — Cleanup and Archival
- `sleep_summary.txt` is the input to FR-3.3. Cleanup/removal of `sleep_summary.txt`, `daily.txt`, `daily.json`, and other per-project cycle artifacts is owned by FR-3.3.5 after a successful per-cycle merge + RAG rebuild.
- No intermediate `pruned.txt` artifact is produced under deterministic consolidation.

#### FR-3.2.5 — Logging
- Mandatory log chain per project:
  `[SLEEP] Lock engaged → [SLEEP][FORMAT] → [SLEEP][MERGE] … → [SLEEP][CLEANUP] → [SLEEP] Lock released`.
- On exceptions, log `[SLEEP][ERROR] project={id}` and continue to the next project.

---

#### FR-3.2.6 — Daily File BEGIN/END Tags
- When `daily.txt` is first created for a project, write a file header line:
  ```
  === BEGIN DAILY MEMORY: MM/DD/YYYY ===
  ```
  (Local date; followed by a blank line.)
- During deterministic consolidation (FR-3.2.3), append a closing tag ONLY to the in‑memory content written to `sleep_summary.txt` (do not persist back to `daily.txt`):
  ```
  === END DAILY MEMORY: MM/DD/YYYY ===
  ```
  (Local date; surrounded by blank lines.)
- The BEGIN/END tags bracket the daily memory window for the per-cycle artifact without altering the on‑disk daily file beyond the first‑write header.

### Acceptance Criteria
- Each project with a non-empty `daily.txt` produces `sleep_summary.txt` deterministically (no LLM calls).
- No `pruned.txt` or `[Open Questions]` appendix is produced in V3.2 or later.
- Skipped projects (missing/empty `daily.txt`) are logged clearly and do not block the sleep cycle.
- Lock and thread behavior remain identical to 3.1.
- Logs show a single `[SLEEP][FORMAT]` entry per processed project (no `[PRUNE]` entries; those are removed).
- `sleep_summary.txt` is preserved for FR-3.3 (merge + RAG rebuild); its removal is owned by FR-3.3.5 after successful consolidation.


## Version 3.3 — RAG Rebuild and Verification (Per-Cycle Artifacts)

### Overview
Version 3.3 completes the Sleep Cycle by writing per-cycle artifacts from Sleep and Dream into the project's uploads tree and rebuilding the FAISS index once per cycle. There is no cumulative `sleep_summary_all.txt`; each sleep/dream cycle produces its own timestamped file so the RAG index treats every cycle as an independent, verifiable upload.

### Purpose
Roll the freshly-produced `sleep_summary.txt` (FR-3.2.3) and, when present, `dream_summary.txt` (FR-4.x) into per-cycle upload artifacts and rebuild the project's long-term memory index.

### Functional Requirements

#### FR-3.3.1 — Per-Cycle Merge Trigger
- Executed within the same sleep thread, after Dream completes (Dream runs between FR-3.2.3 and FR-3.3; see Version 4.1 and `backend/app/sleep/cycle.py`).
- For each processed project, confirm that `sleep_summary.txt` exists and contains content beyond boundary tags alone.
- If the content (excluding `=== BEGIN/END DAILY MEMORY ===` lines) is empty, log `[SLEEP][MERGE] Skipped (empty) project={id}` and continue.
- Log `[SLEEP][MERGE] Initiating RAG update for {project}`.

#### FR-3.3.2 — Per-Cycle Upload Artifacts
For each project processed in the current sleep cycle, write per-cycle timestamped artifacts under the project's uploads tree and guard the merge with a per-project lock:

- Timestamp: filesystem-safe local time, format `YYYY-MM-DDTHH-MM-SS` (no `:`). Referred to below as `{cycle_ts}`.
- Sleep artifact (always written when `sleep_summary.txt` has content beyond boundary tags):
  - Path: `memory/{project}/uploads/sleep/sleep_{cycle_ts}.txt`
  - Content: verbatim copy of `sleep_summary.txt` (includes `=== BEGIN/END DAILY MEMORY ===` tags).
- Dream artifact (written only when `dream_summary.txt` is present and non-empty; see FR-4.x):
  - Path: `memory/{project}/uploads/dream/dream_{cycle_ts}.txt`
  - Content: verbatim copy of `dream_summary.txt`.
- Collision policy: if a target path already exists (extremely unlikely in a sub-second window), append `_{time_ns}` to the filename rather than clobber.
- Per-project merge lock: `memory/{project}/state/merge.lock` (covers the upload writes + rebuild). The legacy lock path `memory/{project}/merge.lock` MAY exist from earlier versions and MUST be migrated into `state/` on first use (best-effort `os.replace`; absence or migration failure is logged but does not abort the merge).
- No cumulative `sleep_summary_all.txt` is written or maintained; the previous append-all behavior is obsolete.
- Log: `[SLEEP][MERGE] Wrote uploads/sleep/sleep_{cycle_ts}.txt` (and, when applicable, `[SLEEP][DREAM_SUMMARY] Wrote uploads/dream/dream_{cycle_ts}.txt`).

#### FR-3.3.3 — Single RAG Rebuild Per Cycle
- After all per-cycle artifacts for a project have been written (sleep always; dream optional), call the shared upload-path rebuild function exactly once per project per cycle:
  ```python
  rebuild_faiss_index(project_id)
  ```
- Use the same rebuild routine invoked by the file-upload route; the rebuild indexes all files currently in `memory/{project}/uploads/**` (each per-cycle artifact is a distinct input document).
- Rebuild is synchronous and waits for completion before proceeding.
- Log `[MERGE] RAG rebuild complete for {project}`.

#### FR-3.3.4 — Optional Verification
- Controlled by env `VERIFY_RAG` (default: true). When enabled, after rebuild run a lightweight verification (e.g. `load_faiss_index(project_id)`) confirming the project's FAISS index is loadable.
- Log `[VERIFY] OK {project}` on success, `[VERIFY][ERROR] {project}` on failure.

#### FR-3.3.5 — Cleanup
Cleanup runs only after all of (artifact write + rebuild + verify-if-enabled) succeed for a project. On success:

- Remove `memory/{project}/sleep_summary.txt` (per-cycle intermediate; its content is now in `uploads/sleep/sleep_{cycle_ts}.txt`).
- Remove `memory/{project}/dream_summary.txt` when a dream artifact was written for this cycle.
- Clear Daily memory for the project (transitioning the day's content into main RAG):
  - Under `daily.lock`, remove `daily.json` and `daily.txt`.
  - Clear the in-memory Daily FAISS cache for this project (see FR-2.3.2).
- Append-only ingest artifacts (e.g., `open_questions.jsonl` from FR-3.4.6) follow their own lifecycle policy and are NOT deleted by FR-3.3.5.
- On failure at any step, leave per-project artifacts in place so the next cycle can retry; log the failure via the appropriate `[SLEEP]…[ERROR]` tag. Do not delete `sleep_summary.txt`, `dream_summary.txt`, `daily.json`, or `daily.txt` in that case.
- Log `[SLEEP][CLEANUP] Removed individual summary for {project}` (and related per-artifact cleanup logs).

#### FR-3.3.6 — Logging
Required sequence for each processed project (optional segments in brackets):

```
[SLEEP][MERGE] Initiating RAG update for {project}
[SLEEP][MERGE] Wrote uploads/sleep/sleep_{cycle_ts}.txt
[[SLEEP][DREAM_SUMMARY] Wrote uploads/dream/dream_{cycle_ts}.txt]
[MERGE] RAG rebuild complete for {project}
[[VERIFY] OK {project}]
[SLEEP][CLEANUP] …
```

---

### Acceptance Criteria
- After each sleep cycle, a per-cycle `uploads/sleep/sleep_{cycle_ts}.txt` exists for every processed project with non-empty daily content.
- When Dream produced content for the cycle, a matching `uploads/dream/dream_{cycle_ts}.txt` exists and shares the same `{cycle_ts}`.
- No `uploads/sleep_summary_all.txt` is created or maintained.
- The project's FAISS index rebuilds exactly once per cycle, after both writes complete.
- Optional verification passes when `VERIFY_RAG=true`.
- On full success, `sleep_summary.txt`, `dream_summary.txt` (when applicable), `daily.json`, and `daily.txt` are removed; the in-memory Daily FAISS cache is cleared for the project.
- On failure, the per-project artifacts are preserved for retry; append-only ingest artifacts (`open_questions.jsonl`) are never deleted by FR-3.3.5.

Implementation Notes
- FR-3.3 runs per project immediately after Dream (between FR-3.2.3 and final cleanup) within the same sleep thread. If FR-3.2.3 fails for a project, FR-3.3 is skipped for that project and the cycle continues with the next project.
- `uploads/sleep/` and `uploads/dream/` accumulate per-cycle files until normal uploads-lifecycle operations remove or rotate them; the design intentionally treats each nightly cycle as a distinct indexed document.


## Version 3.4 — Rolling Context Tagger

### Overview
Extend the daytime “Awake Phase” to semantically tag each chat pair as it rolls off the active context buffer.  
Tags are embedded into the daily vector text for improved retrieval; `daily.txt` may include the same tag lines.

---

### Purpose
Automate lightweight tagging of prompt/response pairs in real time using the model defined by `BUILDER_MODEL`.  
The tags enrich the text stored in `daily_faiss`, improving daily retrieval quality immediately.

### Functional Requirements

#### FR-3.4.1 — Trigger
- When the deque exceeds `CHAT_HISTORY_LIMIT_PAIRS`, the oldest complete pair is rolled off.  
- Before embedding into `daily_faiss`, run the tagger.

#### FR-3.4.2 — Tagging Prompt
For each rolled-off pair, call `BUILDER_MODEL` with a single strict-JSON prompt. Tagging input includes the current rolled-off pair plus a best-effort context snippet (`last_rolled_off_pair`) drawn from the most recent prior rolled-off pair for the project (see "Previous Rolled-Off Pair Context" below).

The tagger MUST return strict JSON only (no prose, no markdown fences) matching the following schema:

```json
{
  "topics": "",
  "intent": "",
  "type": "",
  "semantic_handle": "",
  "questions": [
    {
      "question": "<exact or naturally rewritten question>",
      "topic": "<topic title where the question originated>",
      "resolution": "<ignore | answer_local | answer_remote>"
    }
  ]
}
```

Field semantics:
- `topics` — comma-separated keywords describing subject matter (3–7 topics maximum).
- `intent` — user's intent in the exchange (brief).
- `type` — coarse category (e.g. technical, design, story, system).
- `semantic_handle` — a short, human-readable handle for the pair suitable for later navigation/analytics.
- `questions` — pair-local open-question candidates extracted from the exchange. See FR-3.4.6 for the downstream append-only stream contract. Each entry:
  - `question`: the question text (exact or naturally rewritten).
  - `topic`: the topic title where the question originated.
  - `resolution`: one of `ignore | answer_local | answer_remote`. `remind_user` is NOT a valid resolution value (removed per DELTA-A.5.1.4).

Contract rules:
- All keys in the schema MUST be present in every response.
- Unknown string values MUST be represented as `""` (empty string). The tagger MUST NOT emit `null`.
- `questions` MUST be an array; use `[]` when no candidates are extracted. Preferring zero questions over weak questions is intentional.
- Question extraction is pair-local: the tagger MUST NOT require full-memory/global resolution to decide whether to emit a candidate. Cross-turn consolidation and final open/answered status are handled downstream (see FR-4.1.1).
- Questions MUST NOT be emitted from user-prompt text alone; they are extracted from the assistant-side of the exchange or from genuinely unresolved, durable implicit questions surfaced by the pair.

Constraints:
- Use `BUILDER_MODEL` over the same channel as chat; enforce a small token budget and low/deterministic temperature.
- Timeout budget is small; on timeout/error/invalid JSON, see Fail‑Safe (FR-3.4.4).

##### Previous Rolled-Off Pair Context (`last_rolled_off_pair`)

- **Intent:** Provide a stable, best-effort semantic context snippet for tagging by supplying the most recent prior rolled-off pair to the tagging prompt.
- **State:**
  - The system maintains an in-memory, per-project value `last_rolled_off_pair` representing the most recent rolled-off pair with `forget=false`.
  - `last_rolled_off_pair` is ephemeral and MUST NOT be persisted as a first-class memory object.
- **Resolution precedence (for each rolled-off pair):**
  1. The in-memory `last_rolled_off_pair`, if present for the project.
  2. A best-effort fallback loaded from the most recent non-forgotten entry in `daily.json` for the project, using the canonical stored pair text (not embedding-augmented text).
  3. `None` if neither source is available.
- **Tagging and memory input:**
  - Before tagging and daily-memory persistence, assistant text SHOULD pass through the configured response pruner. The pruned assistant text is the canonical assistant text for daily memory, Dream memory, and downstream RAG artifacts.
  - When `last_rolled_off_pair` is available, prepend it to the tagging-prompt input before the current rolled-off pair.
  - When unavailable, emit a debug log and tagging proceeds with the current rolled-off pair alone (best-effort).
  - Any structured side outputs emitted by tagging at ingest time — such as question candidates consumed by downstream ingest-artifact streams — are derived from this same tagging-input contract.
- **Forget handling:** If the rolled-off pair has `forget=true`, the system:
  - Does not write the pair to daily memory.
  - Does not update `last_rolled_off_pair`.
  - Preserves the existing `last_rolled_off_pair` value for future roll-offs.
- **Update rule:**
  - `last_rolled_off_pair` is updated only when the rolled-off pair is actually persisted to daily memory (daily history is enabled for the project and the append operation reports success).
  - After a successful persist of a `forget=false` pair, set `last_rolled_off_pair = current_pair_text`, where `current_pair_text` is the canonical rolled-off pair text as used for daily memory storage (user + pruned assistant).
  - The `daily.txt` write is best-effort; the daily-memory append is the sole trigger for updating `last_rolled_off_pair`.
- **Multi-pair prune order:** If multiple pairs roll off sequentially during a single pruning operation, the rules above apply in order; each roll-off MAY reference the immediately preceding rolled-off pair processed in the same operation.
- **Reset / Invalidation:** `last_rolled_off_pair` is cleared for a project when:
  - Daily memory is explicitly reset for that project.
  - The sleep-cycle flush step clears active in-memory chat state for that project.
  - The project is deleted.
- **Restart semantics:**
  - On process restart, `last_rolled_off_pair` is empty.
  - When required and missing, the system MAY hydrate `last_rolled_off_pair` from `daily.json` as a best-effort fallback.
  - Absence of `last_rolled_off_pair` MUST NOT block roll-off processing or tagging.
- **Invariants:**
  - `last_rolled_off_pair` follows semantic roll-off order, not conversational order.
  - `last_rolled_off_pair` is ephemeral and is never persisted as an independent memory entry.
  - `last_rolled_off_pair` is used exclusively to improve tagging quality.

#### FR-3.4.3 — Integration
The tagger returns a single JSON object (FR-3.4.2). The integration step derives downstream artifacts from that JSON:

- Derive the `#topics / #intent / #type / #semantic_handle` tag lines from the JSON and prepend them to the text embedded into the in-memory Daily FAISS cache (FR-2.3.2) for the rolled-off pair:
  ```
  #topics: …
  #intent: …
  #type: …
  #semantic_handle: …
  User: …
  Assistant: …
  ```
  Empty-string fields MAY be omitted from the emitted tag-line block.
- Include the same tag lines in `daily.txt` for the rolled-off pair (as metadata lines, not part of the user/assistant message text).
- Persist structured tag fields in `daily.json` for analytics/backfill as:
  `tags_meta: { topics, intent, type, semantic_handle }`.
- Append every extracted question candidate (zero or more) as a structured record to the per-project append-only stream `memory/{project}/open_questions.jsonl` per FR-3.4.6.
- Stored text in daily artifacts (Daily FAISS vector, `daily.txt`, `daily.json`) consists solely of the current rolled-off pair plus tag metadata; `last_rolled_off_pair` (per FR-3.4.2) serves exclusively as tagging-prompt context and MUST NOT be stored in daily artifacts.

#### FR-3.4.4 — Fail‑Safe
- On timeout/error/invalid JSON, log `[TAGGER][WARN] …` and embed the original pair text unmodified (no tags). No question candidates are appended to `open_questions.jsonl` when the tagger output is invalid.

#### FR-3.4.5 — Logging
- On success, log `[TAGGER] topics=…, intent=…, type=…, semantic_handle=…, questions=<count>` (truncate long string fields in logs for brevity).

#### FR-3.4.6 — Open Questions Append-Only Stream
Purpose: make pair-local question candidates a first-class, auditable ingest artifact consumed by the Dream question pipeline (FR-4.1.1). Replaces the legacy `[Open Questions]` appendix inside `sleep_summary.txt` (removed in DELTA-A.5; see FR-3.2.3 and FR-4.1.1).

- Path: `memory/{project}/open_questions.jsonl` (one project-scoped file).
- Format: newline-delimited JSON (one record per line). Each record is produced per extracted question candidate (not per pair).
- Record shape:
  ```json
  {
    "project_id": "<string>",
    "timestamp": "<ISO-8601 local time>",
    "pair_id": "<opaque id of the rolled-off pair>",
    "question": "<string>",
    "topic": "<string>",
    "resolution": "ignore | answer_local | answer_remote",
    "route": "<builder route at pair-time, optional>",
    "semantic_handle": "<tagger semantic_handle, optional>"
  }
  ```
- Stable provenance fields (`project_id`, `timestamp`, `pair_id`, `topic`, `resolution`) are REQUIRED so downstream consolidation is deterministic and auditable. `route` and `semantic_handle` are OPTIONAL and MAY be omitted when unavailable.
- Write policy:
  - Append-only. Records are never mutated or reordered. Lines are never deleted by tagging or by the Sleep cycle (FR-3.3.5 MUST NOT remove this file).
  - Writes are best-effort. If the write fails, tagging MUST log `[TAGGER][WARN] open_questions.jsonl write failed …` with project/pair identifiers and proceed without aborting daily-memory persistence.
  - A lightweight file lock (e.g. `memory/{project}/state/open_questions.lock`) MAY be used to serialize concurrent appends; the existing `daily.lock` MAY be reused if that keeps implementation simpler.
  - Empty `questions=[]` from the tagger MUST result in zero appended lines (no placeholder records).
- Consumers:
  - Dream (FR-4.1.1) reads this stream as its canonical question input, performs deterministic consolidation/status resolution, and forwards resolved questions to the Questions Agent (FR-4.1.2).
  - Other consumers (analytics, debugging) MAY read the file read-only.
- Lifecycle:
  - The file persists across sleep cycles; it is not truncated by Sleep. Long-running projects are expected to accumulate records; downstream consumers MUST be tolerant of large files and MAY implement their own archival/rotation outside the scope of this FR.

---

### Acceptance Criteria
- The tagger returns a single strict-JSON object per rolled-off pair matching the FR-3.4.2 schema (all keys present).
- ≥90% of Daily FAISS entries for rolled-off pairs include the derived tag lines (`#topics`, `#intent`, `#type`, optionally `#semantic_handle`).
- Zero extracted questions from the tagger result in zero new lines in `open_questions.jsonl`; every non-empty `questions[]` entry appears as exactly one line with required provenance fields (FR-3.4.6).
- `open_questions.jsonl` is never deleted or truncated by the Sleep cleanup step (FR-3.3.5).
- Tagger failure path embeds the original pair text unmodified AND skips the `open_questions.jsonl` append for that pair.
- Average tagging overhead < ~100 ms per rolled‑off pair.

---

### Benefits
- Daily vector store becomes semantically rich immediately (before sleep).
- RAG quality improves for same‑day queries.
- Sleep summarization remains clean and unchanged for `daily.txt` and 3.2/3.3 flows.

## Version 3.5 — Streaming Chat Responses

### Overview
Enable progressive, token-by-token streaming of assistant responses so users can read output as it is generated, without waiting for completion. The existing synchronous `/chat` endpoint remains unchanged.

---

### Purpose
Improve responsiveness and perceived latency during the “Awake Phase” by streaming model output to the UI while preserving current RAG, persistence, and locking semantics.

### Functional Requirements

#### FR-3.5.1 — Backend Streaming Endpoint
- Add a new endpoint:
  - `POST /chat/stream`
  - Request shape: same as `/chat` (`message`, `project_id`, optional `model`), JSON body.
  - Response: HTTP 200 with a streaming body; transport is newline-delimited chunks (text/plain) suitable for `fetch()` streaming in browsers.
- Behavior:
  - Load project system prompt, personality, and merged RAG context as in `/chat`.
  - Persist the user message to DB immediately on stream start.
  - Begin model generation with streaming enabled; flush partial text chunks as they arrive.
  - On completion, persist the full assistant message to DB and trigger normal roll-off if limits exceeded.
  - On error/mid-stream abort: close the stream; do not persist partial assistant content (or persist a short “[error] …” stub if feasible).
- Locking:
  - If the stream starts before the sleep lock engages, it continues until done.
  - If the lock is already active at start, return HTTP 423 (Locked).

#### FR-3.5.2 — Frontend Streaming Integration
- Add a streaming path in the UI (e.g., “Stream” mode):
  - Use `fetch('/chat/stream', { method: 'POST', body: JSON.stringify({...}) })`.
  - Read from `response.body.getReader()` and append incoming chunks to the active assistant bubble in real time.
  - On “done”, finalize the message and re-enable input.
  - On error, show an error toast and leave partial text in-place (or clear), per UX preference.
- Keep `/chat` (non-streaming) as the default fallback; allow a toggle in the UI to enable/disable streaming.

#### FR-3.5.3 — Chunk Format
- Transport: newline-delimited UTF-8 text chunks.
- Chunk types:
  - Data chunks: raw assistant text segments.
  - Control messages (optional): lines starting with `::event: done` to indicate completion or `::event: error` to indicate errors.
- The client must tolerate arbitrary chunk boundaries and merge in-order.

#### FR-3.5.4 — Logging
- Log sequence per request:
  - `[STREAM] Start project_id=… msg_id=…`
  - `[STREAM] Chunks_emitted=N bytes=M`
  - `[STREAM] Done` or `[STREAM][ERROR] …`
- Keep existing `[PROMPT]`, `[ROUTE]`, `[RETRIEVAL]` logs when applicable.

#### FR-3.5.5 — Limits and Timeouts
- Model timeout and stream timeout enforced (e.g., 60–120s default).
- Backpressure: flush at least every 50–100 ms while tokens are incoming.
- If the model or connection stalls beyond timeout, abort stream and log `[STREAM][ERROR] timeout`.

#### FR-3.5.6 — DB Persistence Semantics
- Persist user message at stream start.
- Persist assistant message only on successful completion with the full text.
- Roll-off logic runs exactly as in the synchronous flow, only after assistant persist.
- No incremental DB writes during the stream.

#### FR-3.5.7 — Sleep Lock Semantics
- Streams initiated before lock continue; new streaming or non-streaming POSTs during lock receive HTTP 423.
- GET endpoints continue to work during sleep.

#### FR-3.5.8 — Configuration
- Env flags (add to `.env` via Makefile):
  - `STREAMING_ENABLED=true`
  - `STREAM_FLUSH_MS=50` (flush cadence for chunks)
  - `STREAM_TIMEOUT_MS=60000` (overall stream timeout)
- If `STREAMING_ENABLED=false`, `/chat/stream` returns HTTP 503 with `{ "error": "Streaming disabled" }`.

---

### Acceptance Criteria
- Tokens appear progressively in the UI during generation (visible typing effect).
- On completion, the assistant message appears in DB and in `/projects/{id}/chats`.
- RAG context injection, system prompt, and personality are applied the same as `/chat`.
- Lock behavior: streams can continue across lock; new POSTs during lock get 423.
- Logs show `[STREAM]` entries for start, chunk counts, and completion or error.
- If streaming is disabled by env, the endpoint returns a clear 503 error.


# Version 4.0 Overview

## Dream Cycle High Level Description

Version 4.0 introduces the Dream Cycle as a new phase executed after the Sleep Cycle's deterministic consolidation (FR-3.2.3) and before the per-cycle merge + RAG rebuild (FR-3.3). Dreaming analyses the project's tag-enriched ingest artifacts — the per-project `open_questions.jsonl` stream (FR-3.4.6) for questions and `sleep_summary.txt` for daily-memory context — and produces structured insight outputs. Version 4.0 does not implement research or multi-agent reasoning. It establishes the conceptual boundaries for Dream, introduces the Dream Orchestrator, and prepares the system for extension in Version 4.1 and beyond.

Goals of Version 4.0:

* Define Dream as a post Sleep maintenance phase.
* Introduce the Dream Orchestrator as the execution space for nightly agents (synchronous execution model).
* Ensure Dream runs under controlled conditions.
* Establish `dream.json` as the unified nightly Dream output file produced by the Dream Writer.
* Provide the user GUI element Analyze Dreams when `dream.json` has content.

**Note on Refactoring:** The Dream Orchestrator was simplified to use synchronous execution within the Sleep cycle thread, removing the ThreadPoolExecutor. Dream agents are organized under `backend/app/core/agents/` with prompts in `backend/app/core/agents/prompts/`.

---

# Version 4.1 Requirements

## 4.1.1 Deterministic Open-Question Consolidation

Dream's question input is the per-project append-only stream `memory/{project}/open_questions.jsonl` (FR-3.4.6), produced at pair roll-off by the tagger (FR-3.4.2 / FR-3.4.3). There is no `[Open Questions]` appendix in `sleep_summary.txt` anymore, and there is no LLM-based extraction step inside Dream. Dream consumes the jsonl stream, performs deterministic consolidation/status resolution, and forwards the resulting question set to the downstream Questions Agent (FR-4.1.2).

### Input contract
- Source file: `memory/{project}/open_questions.jsonl` (append-only; schema per FR-3.4.6).
- Each line is parsed as JSON; malformed lines are logged at WARNING level and skipped (no retry).
- If the file is missing, empty, or contains zero valid records after parsing, Dream runs with zero questions (valid, non-error state).

### Deterministic consolidation pass
Dream performs a single pure-Python pass over the parsed records — no LLM call, no prompt:

1. **Filter** out any record with `resolution="ignore"`. These never reach the Questions Agent (per DELTA-A.5.1.4 narrowing).
2. **Project-scope check**: records whose `project_id` does not match the active project are dropped with a WARNING log (defensive; should not happen in normal ingest).
3. **Deduplication**: collapse records whose `(topic, normalized question text)` key is identical. Normalization is deterministic: lowercase, collapse whitespace, trim punctuation. Keep the most recent record (by `timestamp`) as the canonical entry; older duplicates are dropped.
4. **Validation**: require non-empty `question`, `topic`, and a `resolution` in `{answer_local, answer_remote}` after filtering. Records failing validation are logged at WARNING level and skipped.
5. **Ordering**: downstream ordering is deterministic and stable; records retain ingest order (earliest surviving `timestamp` first). Ordering MUST NOT be influenced by record count, RNG, or LLM output.

The consolidated output of this pass is an in-memory list `[{ question, topic, resolution, pair_id, timestamp, ... }, ...]` passed to FR-4.1.2.

### Dream Orchestrator integration
- Execution model:
  - Dream executes synchronously within the Sleep cycle thread (no ThreadPoolExecutor).
  - When `ENABLE_DREAM=false`, Dream is skipped entirely.
  - `MAX_WORKERS` is deprecated and unused.
- Submission timing:
  - For each project, after Sleep produces `sleep_summary.txt` (FR-3.2.3) and **before** the per-cycle merge/rebuild sequence (FR-3.3) runs for that project, call `dream(project_id)` synchronously and wait for completion. Sleep holds the maintenance lock until Dream (including all Dream agents) completes for that project.
- Inputs:
  - Dream loads `memory/{project}/open_questions.jsonl` itself. It does not read `sleep_summary.txt` for questions.
  - Dream MAY still load `sleep_summary.txt` for other pipeline stages (e.g., the Dream Context Builder enriches context from project memory), but NOT for question extraction.
- Lock/idempotency:
  - Sleep idempotency is preserved: if Sleep is already running, further triggers are skipped; Dream is never double-enqueued.
- No RAG writes:
  - Dream MUST NOT rebuild or modify any RAG index. RAG is read-only during Dream.
- Feature flags and model:
  - `ENABLE_DREAM` (default: true). When false, skip Dream entirely.
  - `AUTO_ACCEPT_DREAMS` (default: false). When true, Sleep auto-processes all pending `dream.json` items after Dream completes and before the per-cycle merge/rebuild sequence.
  - Dream agent LLMs are bound via the provider factory (see FR-003) using `DREAM_MODEL` / `DREAM_TEMPERATURE` / `DREAM_MAX_TOKENS`.
- Logging:
  - `[DREAM] Starting dreaming for project=<id>`
  - `[DREAM][QUESTIONS] input=<parsed> ignored=<count> duplicates=<count> invalid=<count> forwarded=<count>`
  - `[DREAM] Project <id> complete in duration=<seconds>s`
  - `[DREAM][WARN] …` for malformed jsonl lines or validation failures; `[DREAM][ERROR] …` for execution errors.
- GUI/status endpoint:
  - `GET /dream/status` returns `{ "has_dreams": <bool>, "count": <int> }` based on the current `dream.json` artifact.
- Lifecycle of `open_questions.jsonl`:
  - Dream does NOT truncate, rewrite, or delete `open_questions.jsonl`. FR-3.4.6 owns its lifecycle; Sleep cleanup (FR-3.3.5) MUST NOT delete it.

### FR-4.1.1.1 — Dream Debug Artifacts

When `GENERATE_DEBUG_FILES=true`, the Dream pipeline SHOULD write human-readable per-stage debug files into the project's Dream workspace directory so that deterministic decisions made in FR-4.1.1 (and downstream Dream agents) are auditable without re-running the pipeline.

- Directory: `memory/{project}/dream_work/` (create lazily; tolerate a pre-existing directory).
- File format: plain `.txt` with labeled sections. Files SHOULD use a consistent structure such as:
  ```
  [INPUT]
  <parsed input or upstream stage output>

  [DECISION]
  <counters, filters, or deterministic rules applied>

  [OUTPUT]
  <the artifact forwarded to the next stage>
  ```
- Suggested files (non-exhaustive; add as needed per agent):
  - `debug_open_questions_input.txt` — raw parsed `open_questions.jsonl` records consumed by FR-4.1.1.
  - `debug_open_questions_consolidated.txt` — post-consolidation list with filter/dedup/invalid counters.
  - `debug_<agent>_input.txt` / `debug_<agent>_output.txt` — per-agent inputs and outputs for downstream Dream agents (Questions Agent, Context Builder, Idea Agent, Dream Writer).
  - `debug/dreaming/{timestamp}_{purpose}_prompt_to_execute.txt` — exact Dream LLM API submission payload rendered as system/user prompt sections for every Dream agent call, including estimated prompt tokens and requested output cap.
  - `debug/dreaming/{timestamp}_{purpose}_response_usage.txt` — Dream LLM response text and provider-reported prompt/completion/total token usage for every successful Dream agent call.
- Writes MUST be best-effort: a debug-write failure MUST NOT abort Dream execution and MUST be logged at WARNING level.
- When `GENERATE_DEBUG_FILES` is false or unset, no files under `dream_work/` are created by Dream.
- This FR does not replace agent-specific debug artifacts (e.g., NFR-4.2.1.9 for the Idea Agent); it establishes the common directory, naming convention, and gating flag.

# Version 4.1.2 Requirements

## Open Questions Dream Agent (RAG Answer Generation)

Version 4.1.2 introduces the first functional Dream Agent. This agent processes the structured open questions extracted in Version 4.1.1 and generates answers by combining project RAG context with a single LLM prompt per question.

---

## Scope and Preconditions

* Version 4.1.1 is complete: Dream has performed deterministic consolidation of `memory/{project}/open_questions.jsonl` and produced the in-memory consolidated question list (per FR-4.1.1).
* The consolidated list contains only records with `resolution ∈ {answer_local, answer_remote}`; `ignore` records are already filtered at consolidation time.
* `remind_user` is not a valid resolution (removed in DELTA-A.5.1.4). Any legacy records bearing that value are treated as `ignore` and dropped during FR-4.1.1 consolidation.
* No GUI changes are implemented in 4.1.2.

---

## Dream LLM and Research Abstraction

* Dream must use the Dream-specific OpenAI Responses wrapper and must not depend on legacy generic LLM wrappers.
* Create `backend/app/core/dream_llm.py`:

  * Thin wrapper over the OpenAI Responses API.
  * Must expose a function such as `dream_llm_call(prompt: str, max_output_tokens: int) -> str`.
  * Uses environment variables:
    * `DREAM_MODEL` (default: `gpt-5.1`)
    * `DREAM_TEMPERATURE` (default: `1.0`)
    * `DREAM_MAX_TOKENS` (default: `32000`)
    * `DREAM_ENABLE_REMOTE_RESEARCH` (default: `true`)
    * `DREAM_REMOTE_CONTEXT_MAX_TOKENS` (default: `32000`, tokens; use tiktoken to count/trim)
* Create `backend/app/core/agents/prompts/questions_prompts.py`:

  * Contains pure functions for building Dream question-answering prompts.
  * Must expose:
    * `build_answer_question_prompt_local(question: str, topic: str, local_context: str) -> str`
    * `build_answer_question_prompt_remote(question: str, topic: str, local_context: str, remote_context: str) -> str`
  * Prompt must:
    * Use the literal headers:
      * `Question:`, `Topic:`, `Local Project Memory:`, and (when remote is used) `Remote Research:`
      * Include an “Answer requirements” section that instructs strict JSON output.
    * Require the model to return a single JSON object containing exactly one required field:
      * `"answer": "<string>"`
    * Allow optional fields (e.g., `citations`, `notes`, `confidence`) but Dream will only rely on `"answer"`.
* Create `backend/app/core/dream_research.py`:

  * Contains utility functions for token counting, trimming, and remote research.
  * Must expose: `count_tokens(text: str) -> int`, `trim_to_tokens(text: str, max_tokens: int) -> str`, `fetch_remote_research(question: str) -> str`.
  * Note: `run_open_question_pipeline` was moved to `backend/app/core/agents/questions_agent.py` as a private function `_run_open_question_pipeline`.
  * If `resolution="answer_local"`, fetch RAG context and run a single LLM answer prompt.
  * If `resolution="answer_remote"`, fetch RAG context and include optional remote research via the OpenAI web_search tool (enabled only when `DREAM_ENABLE_REMOTE_RESEARCH=true`).

---

## RAG Usage

* Dream must use `rag_manager.retrieve_context(...)` for all local memory retrieval.
* `retrieve_context` MUST execute the unified pipeline in FR-2.3-3 and MUST be called with:

  * `project_id` set to the active project.
  * `query` set to the question text.
  * Pipeline parameters resolved from the route policy configured for Dream (typically the `OTHER` route of `route_policy.json`) and the environment (`BASE_TOP_K`, `RAG_SNIPPET_MAX_TOKENS`, `RAG_CONTEXT_MAX_TOKENS`).
  * No namespace-based biasing, no per-call `route_namespaces`, no namespace boosts, and no similarity-threshold filter (all removed by FR-2.3-3; ranking is purely cosine-similarity-based per FR-2.3-3.2, bounded by `max_keep` per FR-2.3-3.3).
* RAG is read only during Dream.
* Dream must not rebuild or write any RAG data.

---

## Per Question Processing Pipeline

* For each `{ question, topic, resolution }` in the consolidated question list produced by FR-4.1.1:

  * If `resolution="answer_local"`:

    * Retrieve local RAG context.
    * Build a prompt via `build_answer_question_prompt(question, topic, local_context, remote_context="")`.
    * Call `dream_llm_call` once.
    * Parse strict JSON.
  * If `resolution="answer_remote"`:

    * Retrieve local RAG context.
    * Perform remote research using OpenAI web_search (only if `DREAM_ENABLE_REMOTE_RESEARCH=true`).
    * Build answer prompt including both contexts (local first, then remote).
    * Cap `remote_context` to `DREAM_REMOTE_CONTEXT_MAX_TOKENS` tokens (tiktoken). If web_search fails/empty, proceed with `remote_context=""` and log a warning (no retries in 4.1.2).
    * Call `dream_llm_call`.
    * Parse strict JSON.
  * If invalid JSON is returned:

    * Fallback to `{ "answer": "Dream agent failed to generate a valid answer." }`.
    * Log a warning and continue.
  * When trimming combined context to meet budgets, prefer local context; include remote context only with remaining budget. Log a warning showing token trims, e.g., `trimmed local=5000→4500 remote=5000→3500`.

---

## Output Format (Questions Data)

The Questions Agent MUST return an in-memory Python dictionary of the form:

```
{
  "questions": [
    { "question": "...", "topic": "...", "answer": "..." },
    ...
  ]
}
```

* The `questions` list MUST contain one entry per processed open question.
* The returned structure SHALL NOT be mutated by Dream downstream; it is treated as read-only input.
* Keys MUST be lowercase (`question`, `topic`, `answer`). No additional per-question fields (citations, confidence, etc.) are required in 4.1.2.
* If no valid entries exist, the Questions Agent SHALL return `{ "questions": [] }`.
* No persistent `questions.json` file is written in 4.1.2; all question results are kept in memory.
* When `GENERATE_DEBUG_FILES=true`, the system SHALL write:

  ```
  memory/{project_id}/debug_questions.txt
  ```

  containing a pretty-printed JSON dump of the returned questions dictionary.

---

## Execution Behavior

* Dream executes synchronously within the Sleep cycle thread (no ThreadPoolExecutor or threading).
* Sleep calls `dream(project_id)` directly for each project and waits for completion. Dream loads the consolidated open-question list from `memory/{project}/open_questions.jsonl` per FR-4.1.1; no summary text argument is passed.
* Inside `dream()`, the questions agent processes the consolidated list sequentially and returns an in-memory `questions_data` dictionary.
* Dream must treat RAG as read only.
* Dream must not read or write data belonging to other projects.
* The questions agent is implemented in `backend/app/core/agents/questions_agent.py` with the main entry point `run_questions_agent(project_id: str, questions: List[Dict[str, Any]]) -> Dict[str, Any]`, where `questions` is the output of FR-4.1.1 consolidation (each item has at minimum `question`, `topic`, and `resolution ∈ {answer_local, answer_remote}`).

---

## Logging and Error Handling

* Log per project:

  * `[DREAM] Starting dreaming for project=...`
  * `[DREAM][QUESTIONS] Start project=...`
  * `[DREAM][QUESTIONS] Completed project=... count=...`
  * `[DREAM] Project ... complete in duration=...s`
* Log per question (success):
  * `[DREAM][QUESTIONS] Q answered question="<trimmed 120>" preview="<answer[:250]>" used_remote_research=<true|false> tokens(local=X, remote=Y, combined=Z)`
* On invalid JSON:

  * `[DREAM][WARN] project=... question=... invalid answer JSON`
* On RAG retrieval failure:

  * `[DREAM][WARN] project=... question=... RAG retrieval failed; continuing with empty local context`
* Failures in one question must not stop processing of others.

---

## Memory Integration Constraints (4.1.2)

* Dream must not modify `sleep_summary.txt`.
* Dream must not modify or rebuild RAG.
* User review and long term memory integration begin in 4.2.
* `/dream/status` remains a stub returning `{ "has_dreams": false, "count": 0 }` in 4.1.2 (GUI integration in 4.2).


# Version 4.1.3 Overview

## Idea Layer Preparation

Version 4.1.3 begins the next phase of Dream development by introducing the infrastructure needed for autonomous idea generation. This release does not create new agents yet. Instead, it prepares a unified context block that all future Dream Agents will consume.

Goals of Version 4.1.3:

* Establish the Dream Context Block as a standard prelude for all Dream Agents.
* Retrieve user identity and project rules through RAG rather than static files.
* Generate a concise Project Context Summary from RAG using a lightweight summarizer prompt.
* Combine identity, system rules, project summary, Question Answering results, and daily memory into a single ordered input block.
* Keep all memory access read only and consistent.

---

# Version 4.1.3.1 Requirements

## Dream Context Block Injection

Version 4.1.3.1 introduces the Dream Context Builder. This component runs inside each Dream task before any agents execute. It does not modify RAG or generate ideas. Its job is to assemble a unified structured context string that subsequent Dream Agents will use as input.

---

## Scope and Preconditions

* Version 4.1.2 is complete and the Questions Agent returns an in-memory `questions_data` dictionary containing Question Answering results.
* RAG is already populated with:

  * default user profile codex
  * default project system rules
  * accumulated project memory
* sleep_summary.txt is fully formatted and present.
* No new agents are introduced in this version.

---

## Required Context Components

The Dream Context Builder must assemble the following five components for each project:

### 1. User Profile

The Dream Context Builder MUST assemble the User Profile component using the following precedence:

1. If `memory/{project_id}/user_profile_summary.txt` exists and is non‑empty, load that file and use its contents verbatim.
2. Otherwise, retrieve from RAG using `rag_manager.retrieve_context(...)` with a query such as:

   User Profile Codex

3. If RAG retrieval yields no usable content, fall back to loading the default user profile text file inside the project (`memory/{project_id}/default_profile.txt`) and log a warning.
4. If the fallback file is also missing or empty, substitute `(empty)` and log a warning.

### 2. Project System Prompt

Retrieved from RAG using a query such as:

Project system rules

This component contains the project specific system prompt or design rules. If RAG retrieval yields no usable content, Dream must fall back to loading `memory/{project}/system_prompt.txt`. If that file is missing or unreadable, substitute `(empty)`. In both fallback cases, log a warning and continue.

### 3. Project Context Summary

Dream generates a concise summary of the project using a lightweight RAG summarization prompt. Requirements:

* Retrieve relevant snippets using retrieve_context.
* Summarize with a Responses API call using a small summarizer prompt.
* Limit the text to a safe token budget suitable for Dream Agents.
* If empty, log a warning and continue.

### 4. Question Answering Results

Loaded from the existing questions.json produced in Version 4.1.2. Must be included exactly as written.

### 5. Daily Memory

Loaded from sleep_summary.txt. Must be included exactly as generated by the Sleep Cycle.

---

## Ordering Requirement

The Dream Context Block must be constructed in this exact order:

1. User Profile
2. Project System Prompt
3. Project Context Summary
4. Question Answering Results
5. Daily Memory

The final block is a single concatenated string.

---

## Implementation Requirements

* All RAG retrieval must use `rag_manager.retrieve_context` with queries such as `"User Profile Codex"` (for user profile) and `"Project system rules"` (for system prompt).
* For the User Profile component, Dream MUST first prefer `memory/{project_id}/user_profile_summary.txt` when present; if that file is missing or empty, it MUST fall back to RAG (`"User Profile Codex"`) and, if that yields no usable content, to `memory/{project_id}/default_profile.txt`, logging a warning in both fallback cases.
* The `default_profile.txt` file must be created at project creation and must match the default user codex format.
* Summaries must be generated using the OpenAI Responses API with the summarizer prompt defined in dream_prompts.build_project_summary_prompt.
* The summarizer must limit output via prompt instruction (for example, 400 words). No programmatic trimming is required in 4.1.3.1.
* The Dream Context Builder must construct and return a single concatenated text block in this exact order with section headers:

=== USER PROFILE ===
{text}

=== PROJECT SYSTEM PROMPT ===
{text}

=== PROJECT CONTEXT SUMMARY ===
{text}

=== QUESTION ANSWERS ===
{text}

=== DAILY MEMORY ===
{text}

* Dream Context Builder must consume the in-memory `questions_data` dictionary passed from `dream()` (output of `run_questions_agent`) and read `sleep_summary.txt` directly from disk, including placeholder blocks such as `(empty)` when data is missing.

* `build_dream_context(project_id: str, questions_data: dict) -> (str, str)` must be created in `backend/app/core/dream_context.py`, returning `(context_block, project_summary_text)`.

* The context block is built by calling `build_dream_context(project_id, questions_data)` from `dream.py` after the questions agent completes. The context is stored in a simple process‑local variable for the duration of the Dream task (no TTL, no cross‑run cache) and can be reused by later agents within the same task.

* No new persistent files are created by the Dream Context Builder in this version (debug files such as `debug_context.txt` are allowed).

* All errors inside the context builder must be caught. On failure, log an error and return a minimal context containing only the DAILY MEMORY section (derived from `sleep_summary.txt`).

* All RAG retrieval must use rag_manager.retrieve_context.

* All RAG calls are read only.

* Summaries use the OpenAI Responses API through the project's provider abstractions.

* Missing components are allowed but must produce warnings.

* The context block is stored in memory and passed to future agents when implemented.

* No `questions.json` file is written or modified in this version; questions are passed only in memory.

* No GUI changes are part of 4.1.3.1.

---

## Execution

* Constructed inside the Dream task (synchronous execution).
* No new threads are created.
* Dream executes synchronously per project within the Sleep cycle thread.
* Per project Dream remains serial (one project at a time).

---

## Logging Requirements

Dream must log the following:

* [DREAM][CONTEXT] Building context for project=<id>
* [DREAM][CONTEXT] Retrieved user profile
* [DREAM][CONTEXT] Retrieved system prompt
* [DREAM][CONTEXT] Generated project summary
* [DREAM][CONTEXT] Loaded Q and A results
* [DREAM][CONTEXT] Loaded daily memory
* [DREAM][CONTEXT] Combined context ready

Warnings:

* User profile missing from RAG. Using fallback file.
* Project system rules missing.
* Project summary empty.
* questions.json missing or empty.
* sleep_summary.txt missing or empty.

No errors are fatal in this version.

---

## Output of This Version

Version 4.1.3.1 does not create new files. Its output is an internal in memory string that becomes the input to future Dream Agents starting in 4.1.3.2.

Additionally, log per‑section token counts using tiktoken on the final inserted text:

* `[DREAM][CONTEXT] Retrieved user profile tokens=X`
* `[DREAM][CONTEXT] Retrieved system prompt tokens=Y`
* `[DREAM][CONTEXT] Generated project summary tokens=Z`
* `[DREAM][CONTEXT] Loaded Q and A results tokens=A`
* `[DREAM][CONTEXT] Loaded daily memory tokens=B`


## 4.1.3.2 Project RAG Enrichment

### Overview

The Dream Context Builder SHALL enrich the `dream_context` with relevant long-term project memory retrieved from the Project RAG Index. This step MUST occur before any Idea Agent or downstream agent is executed.

---

### 4.1.3.2.1 Topic Extraction from Sleep Summary

The system SHALL extract retrieval topics exclusively from `sleep_summary.txt`.

#### Required Extraction Elements

For each topic block of the form:

```
=== TOPIC: <Section Title> ===
#topics: topic1, topic2, topic3
```

the builder SHALL extract:

1. **Section Title**.
2. **Each individual topic** listed in the `#topics:` line (split by commas and trimmed).

#### Output of Extraction

A deduplicated list of topic queries including:

* Section titles
* Individual topic terms

#### Constraints

* Extraction MUST ignore malformed topic blocks.
* Empty `#topics` lines SHALL be skipped.

---

### 4.1.3.2.2 Topic-Based RAG Retrieval

The builder SHALL perform a RAG retrieval pass for each extracted topic.

#### Retrieval Rules

* Each topic SHALL be queried independently.
* Retrieval MUST use the unified pipeline (FR-2.3-3) via `rag_manager.retrieve_context(...)` over the main uploads index (which already includes per-cycle `uploads/sleep/sleep_{ts}.txt` and `uploads/dream/dream_{ts}.txt` artifacts; see FR-3.3.2).
  * Daily RAG (in-memory Daily FAISS cache) SHALL NOT participate in this enrichment step—current-day content is already present in the just-written `sleep_summary.txt` for this cycle.
* Per-topic retrieval MUST use the route policy configured for Dream (typically the `OTHER` route of `route_policy.json`) and existing environment settings (`BASE_TOP_K`, `RAG_SNIPPET_MAX_TOKENS`, `RAG_CONTEXT_MAX_TOKENS`). No new caps are introduced.
* No namespace/route biasing: do NOT pass `route_namespaces` or namespace boosts.
* No similarity-threshold filter is applied (removed by FR-2.3-3.2); ranking is purely cosine-similarity-based and bounded by `max_keep` per FR-2.3-3.3.

#### Returned Document Format

Each retrieved entry SHALL include:

* A content snippet (trimmed to `snippet_max_tokens` as per `retrieve_context`).
* Source metadata (filename/page where available).
* Similarity score (float).

#### Read-Only Requirement

The retrieval process MUST NOT modify long-term memory.

---

### 4.1.3.2.3 Construction of PROJECT RAG CONTEXT Section

The Dream Context Builder SHALL inject the RAG results into the `dream_context` under a new section header.

#### Section Header

```
=== PROJECT RAG CONTEXT ===
```

#### Entry Format

For each RAG hit:

```
Topic Query: <topic>
- Snippet: "<retrieved text>"
- Metadata: {source: "LTM", file: "<filename>", score: <float>}
```

#### Ordering Rules

* Entries MUST appear in the same order as topic queries were processed.
* Within a topic, entries with higher similarity SHOULD appear earlier.

#### Validation Rules

* If no RAG results are returned for any topic, the section SHALL contain:

  ```
  === PROJECT RAG CONTEXT ===
  (No relevant long-term memory found for today’s topics.)
  ```

---

### 4.1.3.2.4 Placement in Dream Context

The `=== PROJECT RAG CONTEXT ===` section SHALL be inserted **after** the existing five sections assembled by the Dream Context Builder:

1. USER PROFILE
2. PROJECT SYSTEM PROMPT
3. PROJECT CONTEXT SUMMARY
4. QUESTION ANSWERS
5. DAILY MEMORY
6. PROJECT RAG CONTEXT   ← new section

This ordering ensures:

1. The Idea Agent receives enriched context.
2. Any future Research Agent receives the same enriched context.
3. Future agents benefit automatically without additional wiring.

---

### 4.1.3.2.5 Debug File Support

If `GENERATE_DEBUG_FILES` is enabled:

* The extracted topic list SHALL be written to:
  * `memory/{project_id}/debug_rag_topics.txt`
* The raw RAG retrieval results SHALL be written to:
  * `memory/{project_id}/debug_rag_results.txt`

`debug_rag_topics.txt` and `debug_rag_results.txt` SHOULD use a human-readable text format, e.g., per-topic blocks with topic, snippet, score, and file.

---

### 4.1.3.2.6 Logging Requirements

The Dream Context Builder SHALL log the following INFO-level entries using the `[DREAM][CONTEXT]` tag:

* `[DREAM][CONTEXT] RAG enrichment extracted_topics=N`
* `[DREAM][CONTEXT] RAG enrichment retrieved_docs=M`

“No topics” or “no documents above threshold” are not considered warnings or errors.

---

### 4.1.3.2.7 Error Handling

The builder MUST catch and log all exceptions during retrieval.

If retrieval fails:

* The system SHALL continue dream processing with an empty PROJECT RAG CONTEXT section, logging a debug-level message such as:
  * `No relevant long-term memory found for today’s topics.`
* Downstream agents SHALL NOT fail due to missing RAG data.

If no topics are extracted from `sleep_summary.txt`:

* The builder SHALL still insert the `=== PROJECT RAG CONTEXT ===` header but MAY omit additional content beyond a brief notice.

---

### Output of This Step

The final `dream_context` string SHALL include a fully constructed:

```
=== PROJECT RAG CONTEXT ===
...
```

block, containing all retrieved items or an empty notice. This enriched context is passed directly to the Idea Agent and any future Dream Agents.


# 4.2 Idea Agent Requirements

## FR-4.2.1 Purpose
The Idea Agent SHALL analyze the daily `dream_context` and use an LLM prompt to generate structured Dream Entries. These entries represent open questions, insights, contradictions, and new topics derived from user interactions and the sleep summary.

## FR-4.2.2 Trigger
The Dream pipeline SHALL invoke the Idea Agent immediately after `dream_context` is successfully produced.

- Implementation: the Idea Agent entrypoint is `run_idea_agent(project_id: str, dream_context: str) -> Dict[str, Any>`, called from `dream()` after `build_dream_context(project_id)` returns a non‑`None` string.
- If `dream_context` is `None`, the Idea Agent SHALL NOT be invoked (effectively returning zero items for that project in this phase).

## FR-4.2.3 Inputs
The Idea Agent SHALL accept the following inputs:
- `project_id` (string)
- `dream_context` (string)

## FR-4.2.4 Prompt Construction
The Idea Agent SHALL construct its LLM prompt by calling:
`build_idea_prompt(dream_context: str)`
located in:
`backend/app/core/agents/prompts/idea_prompts.py`
The returned string SHALL constitute the full and final prompt passed to the LLM.

## FR-4.2.5 LLM Invocation
The Idea Agent SHALL invoke the LLM using:
`dream_llm_call(prompt: str, max_output_tokens: Optional[int])`
The Idea Agent SHALL:
- use only `dream_llm_call`
- pass `max_output_tokens=settings.dream_max_tokens` (backed by `DREAM_MAX_TOKENS`, default 32000) for all Idea Agent calls
- treat the returned value as raw JSON text produced by the model

## FR-4.2.6 Output Schema (LLM Generated)
The LLM SHALL return a single JSON object containing:

### Top level fields
- `date` (MM/DD/YYYY)
- `items` (list)

### Each item SHALL contain
- `id` (string)
- `agent` = "idea_agent"
- `timestamp` (ISO8601)
- `origin_text` (string)
- `origin_type` (open_question | insight | contradiction | new_topic)
- `assistant_response` (string)
- `context_link` (string)

### Each item SHALL include a metadata block
- `priority` (integer)
- `confidence` (float, conceptually 0.0–1.0 as defined in the prompt)
- `theme` (string)
- `recommended_research` (list of strings)

It SHALL only validate that the LLM-produced JSON conforms to this schema.
`recommended_research` entries are text-only and SHALL NOT trigger external research in this step.

## FR-4.2.7 JSON Parsing
The Idea Agent SHALL:

1. Parse the raw LLM output as JSON.
2. Validate presence of required top-level fields (`date`, `items`).
3. Validate that `items` is structurally usable:
   - If `items` is a list, use it as‑is.
   - If `items` is a dict, wrap it as `[items]`.
   - If `items` is missing or is not a list/dict (e.g., string/number), treat this as a validation failure and return `{ "date": <today>, "items": [] }`.
4. For the top‑level `date` field:
   - If present, pass it through as returned by the LLM (no strict format enforcement).
   - If missing or invalid, fall back to `date = <today>` in the final returned dictionary.
5. For each candidate item in `items`, validate that all required fields exist:
   - `id`, `agent`, `timestamp`, `origin_text`, `origin_type`, `assistant_response`, `context_link`.
   - `metadata` object containing `priority`, `confidence`, `theme`, and `recommended_research`.
6. Apply the following per‑field behaviors:
   - **Agent**: If `agent` is present but not equal to `"idea_agent"`, auto‑correct it to `"idea_agent"`.
   - **Origin type**: Validate that `origin_type` is one of: `open_question`, `insight`, `contradiction`, `new_topic`. Items with any other value SHALL be skipped.
   - **Priority**: Validate that `priority` exists and represents a positive integer (`>= 1`). If not, the item SHALL be skipped.
   - **Confidence**: Validate that `confidence` exists (the validator SHALL NOT reject items solely for being outside [0.0, 1.0], but the prompt defines 0.0–1.0 as the intended range).
   - **Metadata block**: If `metadata` is missing or is not a dict, the item SHALL be skipped.
   - **recommended_research**:
     - If the field is missing, the item SHALL be skipped.
     - If the field exists and is already a list, use it as‑is.
     - If the field exists but is not a list (e.g., string, dict, number), wrap/convert it into a one‑element list.
     - If the field exists but is effectively “empty” (e.g., empty string, empty dict), normalize it to an empty list `[]`.
   - **String fields** (`origin_text`, `assistant_response`, `context_link`, `theme`): The validator SHALL require that these keys exist; empty strings are allowed and SHALL be passed through.
7. Items that fail any of the above structural checks (missing required fields, invalid `origin_type`, unusable `metadata`, or missing `recommended_research`) SHALL be skipped; remaining items SHALL be preserved as returned by the LLM (subject to the auto‑corrections above).
8. If JSON parsing fails entirely, or if all items fail validation, the Idea Agent SHALL log an error or warning (per FR‑4.2.1.10) and return `{ "date": <today>, "items": [] }`.

All exceptions SHALL be logged but SHALL NOT escape the Dream pipeline.

## NFR-4.2.1.9 Debug File Generation
When `GENERATE_DEBUG_FILES=true`, the Idea Agent SHALL use the shared debug helper (the same pattern used by the Dream Context Builder) to write:
- `debug_idea_prompt.txt`
- `debug_idea_raw_response.txt`
into the project’s debug directory under `memory/{project_id}/`.

Debug writes SHALL NOT occur inline inside `idea_agent.py`.
When `GENERATE_DEBUG_FILES` is false or unset, no debug files SHALL be created.

## FR-4.2.10 Logging Requirements

### Info logs (with prefix `[DREAM][IDEA]`)
- Start of Idea Agent execution
- Number of Dream Entries returned

### Warning logs (no DREAM tags)
- Missing or empty `dream_context`
- Missing required fields in LLM output

### Error logs (no DREAM tags)
- JSON parsing failures
- Exceptions during LLM invocation or parsing

Warning and error logs SHALL NOT include DREAM tags.

## NFR-4.2.11 Architectural Note
The Idea Agent SHALL NOT perform external research.
It SHALL generate only `recommended_research` topics for downstream use by the Research Agent.


## FR-4.2.12 Output of This Version
The Idea Agent SHALL return a single Python dictionary produced by:
1. Parsing the raw JSON returned from `dream_llm_call`.
2. Validating and filtering entries through the manual field-by-field validation rules defined in FR-4.2.7.

The returned dictionary SHALL contain exactly the following fields:
- `date` (string in MM/DD/YYYY format)
- `items` (a Python list of validated Dream Entry dictionaries)

Invalid items SHALL be skipped. The final `items` list SHALL contain only entries that pass validation.

If all items fail validation, the Idea Agent SHALL return:
`{ "date": <today>, "items": [] }`

This output dictionary SHALL be passed directly to downstream components, including the Research Agent, without modification.
The Idea Agent SHALL return the parsed JSON object (Python dict) to the caller.
The Idea Agent SHALL NOT write persistent output files except via debug mechanisms.

# 4.3 Research Agent Requirements

The Research Agent performs factual enrichment for Dream Entries created by the Idea Agent.

It consumes the Idea Agent output as structured JSON, executes one research task per recommended topic, and returns a new JSON object containing all idea entries with appended research results.

The Research Agent SHALL NOT modify the idea entries themselves.
It only appends `"research": [...]` lists to each item.

Research output SHALL be plain text summaries, never JSON from the model.

All JSON structuring is done in Python inside `run_research_agent`.

## 4.3.1 Research Agent Overview

The Research Agent:

1. Receives:

   * `project_id`
   * the parsed idea agent JSON (`idea_data`)
   * `project_summary_text` from the Dream Context Builder

2. Iterates over all Dream Entries produced by the Idea Agent

3. For every recommended research topic:

   * Builds a research prompt using `build_research_prompt`
   * Executes the LLM call using the same OpenAI Responses configuration already used by `fetch_remote_research` in `dream_research.py` (no separate model/temperature/max‑tokens env block)
   * Parses the plain text result into a structured Research Entry

4. Appends all Research Entries to the idea entry under the `"research"` key

5. Returns the augmented JSON object

## 4.3.2 Function Signature (Implementation Requirement)

The Research Agent SHALL be implemented in:

backend/app/core/agents/research_agent.py

with the following function signature:

```
def run_research_agent(
    project_id: str,
    idea_data: dict,
    project_summary_text: str
) -> dict:
```

This function:

* SHALL perform zero file writes except for optional debug output.
* SHALL return the augmented Dream JSON structure to the caller (dream.py).

## 4.3.3 Input Contract

`run_research_agent` SHALL accept:

### A. project_id (string)

Used for logging and optional debug file output.

### B. idea_data (dict)

This is the parsed JSON from Idea Agent output:

```
{
  "date": "MM/DD/YYYY",
  "items": [ ... ]
}
```

Each Idea Entry contains:

* `id`
* `origin_text`
* `origin_type`
* `assistant_response`
* `context_link`
* `metadata` with:

  * `priority`
  * `theme`
  * `recommended_research` (a list)

### C. project_summary_text (string)

A short textual description of the project, included in research prompts to improve grounding.

## 4.3.4 Iteration Rules

For each entry in `idea_data["items"]`:

1. Extract fields:

   * `entry_id`
   * `origin_text`
   * `origin_type`
   * `assistant_response`
   * `theme`
   * `recommended_research`

2. If `recommended_research` is empty:

   * Set `entry["research"] = []`
   * Continue to the next entry

3. Otherwise:

   * For each research topic:

     * Build a prompt using:

       ```
       build_research_prompt(
           project_summary_text,
           origin_text,
           origin_type,
           assistant_response,
           research_topic,
           theme
       )
       ```

     * Execute the LLM call using the same underlying configuration as `fetch_remote_research` (Responses API, same model/temperature/token limits); no new `research_llm_call` wrapper is required.

     * Parse the LLM response (plain text only)

     * Convert the response into a Research Entry JSON dict

## 4.3.5 Research Agent Output Schema

Each research result SHALL be converted into:

```
{
  "entry_id": "<same as idea entry>",
  "agent": "researcher_agent",
  "timestamp": "<ISO-8601 now>",
  "research_topic": "<topic>",
  "research_summary": "<summary>",
  "metadata": {
      "related_theme": "<theme>"
  }
}
```

Rules:

* No confidence fields.
* Do not modify the Idea Agent fields.
* `metadata` contains only `related_theme`.

All research entries for an item SHALL be stored in:

```
item["research"] = [ ... ]
```

## 4.3.6 LLM Output Parsing Rules

LLM output MUST be plain text only.

Format:

```
<optional header line (ignored)>
<research summary>
```

Parsing procedure:

1. The first non-empty line MAY be a header, but the authoritative `research_topic` for the Research Entry SHALL always be the original string from `recommended_research` (per Idea Agent metadata), not the model’s header.
2. All remaining non-empty lines SHALL be joined to form `research_summary`.
3. If parsing fails:

   * log a warning
   * skip the research topic

## 4.3.7 Debug File Generation

If `GENERATE_DEBUG_FILES` is true:

* The system SHALL write:

```
memory/{project_id}/debug_research.txt
```

Contents:

```
{
  "date": "MM/DD/YYYY",
  "items": [
    ... all items with appended "research": [ ... ]
  ]
}
```

where the structure mirrors exactly the dictionary returned by `run_research_agent` for that project (pretty-printed JSON as plain text).

File semantics:

* `debug_research.txt` SHALL be overwritten on each Dream run (no append across nights).
* Multiple research entries for the same topic MAY appear in the items list; no deduplication is required.

## 4.3.8 Error Handling

* All exceptions SHALL be caught and logged.
* A failure on one research topic SHALL NOT block the rest.
* A failure on one entry SHALL NOT halt the dream cycle.
* If all topics for a given entry fail to parse or execute, that entry SHALL still receive `entry["research"] = []` and a lightweight failure marker such as `entry["research_failed"] = true` for observability.

## 4.3.9 Sequential Execution Requirement

Research SHALL run sequentially.

Parallelization MAY be added in a future higher-level orchestrator but MUST NOT appear here. Within a single `run_research_agent` invocation, all topics for a given project and night MUST execute one after another (no intra-project concurrency), though future orchestration MAY run different projects in parallel.

## 4.3.10 Output Contract

`run_research_agent` SHALL return:

```
{
  "date": "<same value from idea_data>",
  "items": [
      ... all items with appended "research": [ ... ]
  ]
}
```

Logging requirements:

* INFO‑level logs SHALL use the `[DREAM][RESEARCH]` prefix for high‑level lifecycle events (e.g., start/end, topic counts per project).
* For each built prompt, the agent SHALL emit a DEBUG‑level log containing the first ~250 characters of the prompt text (no additional DREAM tags required on this line).


# 4.4 Dream Writer Requirements

The Dream Writer is responsible for producing the final `dream.json` file that the GUI will read after the Dream Cycle completes.
It runs after the Research Agent and performs no reasoning, only merging and serialization.

---

## 4.4.1 Inputs

### FR-4.4.1.1 Input Parameters

The Dream Writer SHALL be invoked with the following parameters:

* `project_id: str`
* `project_summary_text: str`
* `dream_data: dict` (the full data structure returned by `run_research_agent`)

### FR-4.4.1.2 dream_data Contract

`dream_data` SHALL already contain:

* A top-level `date` field in `MM/DD/YYYY` format
* A top-level `items` array
* Each `items` entry MAY include a `research` sub-array if research was performed

The Dream Writer SHALL NOT modify, reorder, filter, or reinterpret any of the contents of `dream_data["items"]`.
If a valid `memory/{project_id}/dream.json` already exists because the user has not processed prior Dream output, the Dream Writer SHALL preserve those pending existing items and append the new `dream_data["items"]` after them.

### FR-4.4.1.3 project_summary_text

The Dream Writer SHALL insert the project summary at the top level of the final JSON output under the field:

```json
"project_summary": "..."
```

The value MUST be exactly the `project_summary_text` string passed into the function.

---

## 4.4.2 Output Specification

### FR-4.4.2.1 Output File Location

The Dream Writer SHALL create a file, or update an existing valid file by appending new items to its pending items:

```text
memory/{project_id}/dream.json
```

### FR-4.4.2.2 Output JSON Shape

The file SHALL contain a single JSON object with at least the following fields:

```json
{
  "date": "MM/DD/YYYY",
  "project_summary": "string",
  "items": [ ... ]
}
```

Where:

* `date` SHALL be copied from `dream_data["date"]` if present.

  * If `date` is missing, the Dream Writer MAY compute today’s date in `MM/DD/YYYY` format.
* `project_summary` SHALL contain `project_summary_text`.
* `items` SHALL be copied directly from `dream_data["items"]` (or an empty list if missing) when no valid prior `dream.json` exists.
* If a valid prior `dream.json` exists with an `items` array, `items` SHALL be the prior pending items followed by the new `dream_data["items"]`, preserving the relative order of both lists.

No additional top-level fields are required, but the Dream Writer SHALL preserve all other existing top-level keys in `dream_data` unchanged if they exist.

### FR-4.4.2.3 Human Readability

The Dream Writer SHALL write the JSON file in a human readable format:

* The JSON MUST be pretty-printed with indentation (2 or 4 spaces).
* The JSON MUST be encoded in UTF-8.
* Keys MUST NOT be sorted automatically; the natural key order from the constructed dict MAY be preserved.

### FR-4.4.2.4 No Additional Debug Files

The Dream Writer SHALL NOT write any additional debug files.
Only `dream.json` SHALL be produced at this stage.

---

## 4.4.3 Behavior and Logic

### FR-4.4.3.1 No Business Logic

The Dream Writer SHALL NOT:

* Generate or modify insights
* Generate or modify research
* Alter `origin_text`, `assistant_response`, or any `research_summary`
* Filter, reorder, or group items, except for appending newly produced items after still-pending items from an existing valid `dream.json`
* Perform any RAG operations
* Interact with STM or LTM

It is a pure I/O serialization step.

### FR-4.4.3.2 Error Handling

If an exception occurs while preparing or writing the file:

* The Dream Writer SHALL log the error using `logger.error`, including the exception text.
* The exception SHALL NOT be propagated to the caller; the function SHALL return after logging.

### FR-4.4.3.3 Logging

The Dream Writer SHALL produce the following log entries:

* After successful write (INFO level):

  ```text
  [DREAM] Dream output written successfully for project={project_id}
  ```

* On error: an `ERROR` level log including the exception message (no DREAM tag required).
* Any additional diagnostic messages MAY be logged at DEBUG or WARNING level without DREAM tags.

---

## 4.4.4 Dream Writer Function Definition

### FR-4.4.4.1 Prototype

The Dream Writer SHALL be implemented in `dream.py` as:

```python
def write_dream_output(project_id: str, dream_data: dict, project_summary_text: str) -> None:
```

### FR-4.4.4.2 Core Steps

The function SHALL:

1. Insert the project summary:

   ```python
   dream_data["project_summary"] = project_summary_text
   ```

2. Ensure `date` exists in `dream_data`.

   * If `"date"` is missing, compute today’s date in `MM/DD/YYYY` format using UTC time (`datetime.now(timezone.utc)`) and assign it.

3. Ensure `items` exists in `dream_data`.

   * If `"items"` is missing, assign an empty list: `dream_data["items"] = []`.

4. Serialize `dream_data` to JSON with indentation and write it to:

   ```text
   memory/{project_id}/dream.json
   ```

5. Log success or failure per FR-4.4.3.3 and FR-4.4.3.2.

---

## 4.4.5 Integration into dream.py

### FR-4.4.5.1 Ordering in Dream Pipeline

`write_dream_output` SHALL be called from `dream()` after:

1. `run_questions_agent(...)`
2. `run_idea_agent(...)`
3. `run_research_agent(...)`

And after `dream_data` and `project_summary_text` are both available.

### FR-4.4.5.2 No GUI or Memory Side Effects

The Dream Writer SHALL NOT:

* Read or modify any GUI state
* Apply Keep/Drop decisions
* Update any RAG indices
* Write long-term memory entries

Those concerns belong to downstream components (e.g., the Dream Review GUI and LTM update pipeline).

# 4.5 Analyze Dreams

FR-4.5 introduces a user-facing workflow for reviewing and curating nightly Dream output.  
It assumes that the Dream pipeline (FR-4.1.x–4.4) has produced a `memory/{project_id}/dream.json` file containing a top-level `"project_summary"` and `"items"` array.

---

## 4.5.1 GUI Reset and Project Summary Card After Sleep

### Scope

- Frontend-only behavior, triggered after the Sleep/Dream cycle completes.
- No changes to the Dream pipeline or RAG behavior are introduced in this sub-requirement.

### Functional Requirements

#### FR-4.5.1.1 Automatic GUI Refresh After Sleep Unlock

1. When the backend Sleep lock transitions from `sleeping=true` to `sleeping=false` as reported by `GET /sleep/status`, the GUI MUST:
   - Automatically refresh the current project’s:
     - Chat history (`GET /projects/{project_id}/chats`)
     - Files list (`GET /projects/{project_id}/files`)
     - Stats (`GET /projects/{project_id}/stats`)
     - Project metadata (`GET /projects/{project_id}`)
   - This refresh MUST occur without requiring the user to send a new prompt.
   - After refresh, the chat window MUST no longer show any chat pairs that were flushed to daily memory by the Sleep cycle.
2. Independently of Sleep timing, whenever the user selects a project in the main chat UI (initial load or project switch), the frontend MUST:
   - Refresh the selected project’s chat history and project metadata.
   - Attempt to load the project’s Dream output (see FR-4.5.1.2) so that a valid `dream.json` will surface the Project Summary card even if the user was not viewing that project when Sleep completed.

#### FR-4.5.1.2 Project Summary Card in Chat Window

1. After the post-Sleep refresh, the frontend MUST attempt to load the current project’s Dream output from `dream.json`.
   - Implementation note: this MAY be exposed via a backend endpoint such as:
     - `GET /projects/{project_id}/dream` → `{ "project_id": "...", "dream": { ... } }` or `{ "project_id": "...", "dream": null }`
     - The endpoint SHOULD read `memory/{project_id}/dream.json` and parse it as JSON, performing basic schema validation (e.g., top-level object, optional `date`, `project_summary` string, `items` list of objects).
2. If `dream.json` exists and contains a top-level `"project_summary"` string, the GUI MUST render a **Project Summary card** in the main chat window:
   - It MUST be visually distinct and **NOT** part of the normal chat `messages` list (i.e., it is not a user/assistant bubble and will not be rolled off as a chat message).
   - It MUST appear **above** the first chat pair in the scrollable chat area.
   - Styling requirements:
     - Background color: `#66b5ff`
     - Text color: black
     - The card MUST support multi-paragraph text (equivalent to CSS `white-space: pre-wrap`).
     - The card MUST include a small label or heading such as `Project Summary`.
   - Content:
     - Primary: `dream.project_summary` (the `"project_summary"` field from `dream.json`).
     - Fallback: if `"project_summary"` is missing or empty, the implementation MAY choose to omit the card or derive a fallback summary from the rest of `dream.json` (exact fallback behavior is implementation-defined and SHOULD be documented if used).
3. If no usable `dream.json` is available for the project, or the backend detects invalid JSON/schema when reading it, the Project Summary card MUST NOT be shown.
   - In this case, the frontend SHOULD display a small, non-blocking warning banner (e.g., “Dream summary unavailable for this project”) in the main chat view and MUST hide the Analyze Dreams button (see FR-4.5.1.3).

#### FR-4.5.1.3 “Analyze Dreams” Button Above the Prompt Box

1. When a valid `dream.json` is present for the current project (as determined in FR-4.5.1.2), the GUI MUST display an **Analyze Dreams** button in the main chat screen:
   - Placement: in the main chat view, **above the user prompt textarea** (e.g., between the chat history area and the input box).
   - Visibility:
     - The button MUST be visible only when `dream.json` exists and is readable for the current project.
     - If `dream.json` is missing, unreadable, or invalid, the button MUST be hidden.
2. Clicking the **Analyze Dreams** button MUST open a new dedicated Dream analysis UI:
   - For FR-4.5.1, this UI MUST be implemented as a modal dialog overlay that covers most of the main page (approximately 80–90% of the viewport in width and height) to provide enough space for reading Dream content.
   - The detailed layout and content of this modal are deferred to FR-4.5.2.
   - FR-4.5.1 only requires that:
     - The button reliably opens a container suitable for showing Dream content.
     - No Dream items are mutated, kept, or persisted as a result of simply opening this UI (no selection/submit behavior yet).
3. The Dream analysis UI introduced here MUST be considered read-only for FR-4.5.1; selection and “Keep”/submit workflows are defined in FR-4.5.2.

### Non-Goals (FR-4.5.1)

- FR-4.5.1 does **not** define:
  - How Dream items are curated or “Kept” for long-term memory.
  - How Dream outputs are written into daily FAISS or rolled into per-cycle `uploads/sleep/` and `uploads/dream/` artifacts (see FR-3.3.2).
  - Any changes to `dream.json` structure beyond the existing `"project_summary"` field.

## 4.5.2 Dream Items Layout

### Scope
Populate the Dream analysis modal with dream entries from `dream.json`, rendered as chat-style pairs plus optional research blocks. This version is read-only; no persistence or submit flows (see 4.5.3+).

### Data Source
- Use the already-loaded `dream.json` (via `/projects/{project_id}/dream`).
- Required fields per item:
  - `origin_text` (string) — displayed as “User/Agent”.
  - `assistant_response` (string) — displayed as “AI/Response”.
  - `research` (optional array of objects), each with:
    - `research_topic` (string)
    - `research_summary` (string)
- Items missing both `origin_text` and `assistant_response` SHOULD be skipped.

### Layout & Rendering
- Render each dream item as a vertical block with spacing between items (e.g., `space-y-4`).
- Within each item:
  1. **User/Agent block**: show `origin_text`.
     - Style: match main chat user bubble (light gray background, black text, rounded, padded). Optional small label “User/Agent”.
  2. **AI/Response block**: show `assistant_response`.
     - Style: same blue as Project Summary (`#66b5ff`), black text, rounded, padded. Optional small label “AI/Response”.
  3. **Research section** (only if `research` array non-empty):
     - For each research entry, render:
       ```
       [RESEARCH]
       Topic: {research_topic}
       {research_summary}
       ```
     - Styling: subtle border or light background; stacked with small vertical spacing.
  4. **Keep checkbox (UI-only placeholder)**:
     - Render an unchecked “Keep” checkbox at the bottom of each item (left-aligned).
     - No behavior or persistence in this version (no-op).
- The modal body remains scrollable (`flex-1 overflow-auto`); modal sizing from 4.5.1.3 is unchanged.

### Behavior
- Read-only: no edits, saves, or submits.
- If `items` is empty or missing, show a brief notice such as “No dream items available.”
- Do not alter chat streaming or the main chat UI.
- Analyze Dreams button visibility remains driven by the presence of `dream.json` (per 4.5.1.3).

### Non-Goals (Deferred)
- No “Keep/Submit” workflow (handled in 4.5.3+).
- No mutations to `dream.json`.
- No pagination, filters, or search in this iteration.

## 4.5.3 Dream Modal Controls (Close vs. Submit)
**Scope:** Modal control behavior for this iteration, adding an interactive Keep workflow and backend submission.

- The **Close** button MUST dismiss the Dream modal with no side effects or data mutations.
- The **Keep** checkbox for each Dream item MUST be interactive, default unchecked; user selection is the source of truth for submission (no preexisting keep flag is honored).
- The **Submit** button MUST:
  - Collect only items with `keep=true`.
  - Call a backend endpoint (e.g., `POST /projects/{project_id}/dream/keep`) with the kept items.
  - On success: show a success toast (“Dream items saved”), delete `dream.json` (handled by the backend), close the modal, and ensure the Analyze Dreams button disappears once `dream.json` is gone. The Project Summary card may remain until chat naturally clears it.
  - On failure: show an error toast (“Failed to save dream items”) with a brief reason if available; do not delete `dream.json`.
- Backend processing (summary):
  - For each kept item, run the same response pruner used by chat persistence before the tagger and memory persistence, tag the pruned pair (using existing tagger), and append the pruned pair to daily RAG via the existing roll-off primitives (`tag_pair`, `append_pair`).
  - Append kept pairs to `dream_summary.txt` using the daily.txt format; include pruned research content folded into the response text without adding a synthetic research-overview sentence.
  - Delete `dream.json` only if all kept items were successfully processed; otherwise log warnings and leave `dream.json` intact.
- Items without `keep=true` are ignored/dropped silently.

## 4.5.4 Dream Summary Per-Cycle Consolidation
**Scope:** Deterministic Sleep-pipeline step that folds the nightly Dream summary, when present, into the project's per-cycle upload artifacts alongside the sleep artifact.

- Trigger: run at the end of every Sleep cycle **only if** `memory/{project}/dream_summary.txt` exists and is non-empty; skip silently otherwise.
- Transform: deterministic pass-through. Read `dream_summary.txt`, normalize line endings to `\n`, and treat the content as-is (including any BEGIN/END tags embedded by upstream agents). No LLM prompts, no pruning, no formatting pass. This aligns with the promptless sleep posture established in DELTA-A.5.
- Write: produce a per-cycle artifact at `memory/{project}/uploads/dream/dream_{cycle_ts}.txt` with the same `{cycle_ts}` used for the sibling `uploads/sleep/sleep_{cycle_ts}.txt` (see FR-3.3.2). The file-lock, rebuild-once, and verify semantics are owned by FR-3.3.2 / FR-3.3.3 / FR-3.3.4; this step only contributes the dream artifact.
- Debug: when `GENERATE_DEBUG_FILES` is enabled, reuse `write_debug_file` to emit `debug_dream_summary.txt` (verbatim).
- Cleanup: `dream_summary.txt` is removed by FR-3.3.5 after the per-cycle merge + rebuild (and verify, if enabled) succeed. On failure, `dream_summary.txt` is preserved for the next cycle and the failure is logged.
- Non-goal: does not change the daily roll-off process; daily.txt / Daily FAISS cache behavior remains unchanged.

## 4.5.5 Auto-Accept Dream Processing
**Scope:** Optional Sleep-pipeline step that persists pending Dream entries without requiring the frontend Analyze Dreams flow.

- Trigger: after `dream(project_id)` completes and before FR-4.5.4 reads `dream_summary.txt`, run only when `AUTO_ACCEPT_DREAMS=true`.
- Input: process all valid items currently present in `memory/{project}/dream.json`, including older unprocessed items preserved across prior Dream runs.
- Processing:
  - Use a backend helper that can run without the frontend endpoint.
  - Apply the same remote-without-research filter used by manual Dream submission.
  - For each processable item, run the same response pruner used by chat persistence before the tagger and memory persistence, call the tagger with the pruned response, and append the pruned pair to Daily RAG using the existing `append_pair` path.
  - Tagger failure is non-fatal; persist the item without tags, matching manual Dream submission behavior.
  - Auto-accepted items MUST use `keep=false` even though manual Dream submission currently persists remembered items with `keep=true`.
  - Append accepted items to `dream_summary.txt` using the same Dream memory block format so the same Sleep cycle can fold them into `uploads/dream/dream_{cycle_ts}.txt`; research-backed responses MUST include pruned research blocks without adding a synthetic research-overview sentence.
  - Before deleting `dream.json`, preserve its `project_summary` in `memory/{project}/latest_dream_summary.txt` when present.
- Success cleanup:
  - If all processable items succeed, delete `dream.json`.
  - If filtering leaves zero processable items, log at DEBUG level and delete `dream.json`.
- UI fallback:
  - When `dream.json` is absent but `latest_dream_summary.txt` exists, `GET /projects/{project_id}/dream` SHALL return a summary-only Dream payload with an empty `items` array so the Project Summary card remains visible while Analyze Dreams remains hidden.
- Failure cleanup:
  - If any processable item fails to persist or post-processing fails, log a WARNING and rename `dream.json` beside the original file as `bad_dream_<timestamp>.json`.
  - Do not silently swallow auto-accept failures; Sleep may continue with partial status.


# 5 Instrumentation Overview
## Instrumentation High Level Description

Version 5.0 introduces **Instrumentation** as a first-class telemetry layer for Syx. Instrumentation collects structured, end to end metrics across the multi-module pipeline, including interactive chat turns and internal helper model calls. Its purpose is to generate defensible evidence for token usage and latency behavior over time, and to support profiling and optimization without changing core routing, retrieval, or memory logic.

Instrumentation is designed to run with minimal overhead, remain disabled by default, and avoid logging raw content unless explicitly enabled for research and evaluation.

Goals of Version 5.0:

* Provide a unified Instrumentation component accessible across modules, similar in usage style to the logger.
* Track tokens by type from day one, including main model tokens and mini model tokens.
* Track latency per invocation and per turn, including TTFB and TTLT for the main model.
* Record retrieval and context assembly counters needed to explain token spikes and to tune prompt budgeting.
* Persist results in a run folder with JSON and JSONL artifacts suitable for offline plotting and report generation.
* Default to metrics-only logging (hashes, lengths, counters) with an opt-in research mode for saving prompt and response artifacts.

**Note on Retrieval Embeddings:** Instrumentation does not track embedding token usage for retrieval. Retrieval cost is represented indirectly via what is retrieved and injected into the final prompt, and therefore appears in the main prompt token totals and prompt composition estimates.

## 5.1 Goals and Scope

### 5.1.1 Purpose
Add a unified `Instrumentation` component that works like the logger: all modules can contribute structured metrics for evaluation runs. The goal is to produce defensible data for token and latency charts comparing Syx to external baselines.

### 5.1.2 Primary Outputs
Instrumentation MUST enable generation of:
- Tokens per turn vs turn index
- Cumulative tokens processed vs turn index
- Latency per turn vs turn index (TTFB and TTLT)
- Optional stacked bar breakdown for Syx: main model vs mini model

### 5.1.3 In Scope
- Per run, per turn, and per invocation metrics capture
- Token totals by type from day one
- Latency capture (TTFB and TTLT) for Syx
- In memory collection with flush at end of run

### 5.1.4 Out of Scope
- ChatGPT website instrumentation (captured via separate tooling)
- Logging or storing retrieval embeddings usage
- Changing model behavior, routing behavior, or RAG logic
- Quality judging pipeline (judging JSONL is separate work; instrumentation only stores artifacts when enabled)
- Dream cycle instrumentation (temporarily out of scope for this phase)

---

## 5.2 Modes and Safety

### 5.2.1 Enable Flag
- Instrumentation MUST be disabled by default.
- When disabled, it MUST impose near-zero overhead and MUST NOT write any files.
- Enable flag: `INSTRUMENTATION_ENABLED=true|false`.
- `RUN_ID` MAY be provided via env. If set, it MUST override per-conversation run ids and force a single run id for all turns in the process.
- When `RUN_ID` is provided, the effective run id MUST be `RUN_ID_<timestamp>` so each process startup creates a new run folder.
- Timestamp format MUST match logger timestamp format: `%Y%m%d_%H%M%S`.

### 5.2.2 Metrics Mode vs Research Mode
Instrumentation MUST support two modes:
- Metrics mode (default when enabled): record counts, tokens, timings, and hashes only.
- Research mode (explicit opt-in): additionally persist prompt and response text artifacts to disk for offline judging.

### 5.2.3 Content Logging Rules
- Metrics mode MUST NOT store raw user prompts, assistant responses, retrieved text, or any other content-bearing strings.
- Research mode MAY store raw prompts/responses only as separate files referenced by ids in JSONL, not embedded inline in JSONL records.

### 5.2.4 Lifecycle and Segregation (Internal-Only)
- Instrumentation lifecycle is internal-only (no control endpoints required in this phase).
- Default run segregation is **one run per conversation**.
- If a request has no `conversation_id`, the system MUST auto-generate one and proceed.
- On clean shutdown (including Ctrl-C in dev), if instrumentation is enabled, the process MUST flush and finalize active run files.

---

## 5.3 Storage and File Formats

### 5.3.1 Run Folder Layout
When enabled, each run MUST write under:
- `runs/{run_id}/`

Deployment note:
- The `runs/` directory MUST be persisted outside ephemeral container layers (bind-mounted in Docker deployments), similar to logs/memory persistence expectations.

### 5.3.2 Canonical Files
At minimum, Instrumentation MUST produce:
- `run.json` (single JSON object)
- `turns.jsonl` (one JSON record per turn)

### 5.3.3 Flush Strategy
- Instrumentation MAY collect in memory and flush only at end of run.
- Instrumentation MUST flush when `end_run()` is called.
- Instrumentation SHOULD flush when the process exits cleanly, if feasible.
- In the current runtime assumptions (single worker), no cross-process file locking is required.

---

## 5.4 Core API (Python)

### 5.4.1 Minimal Lifecycle API
Implement the instrumentation API under:
- `backend/app/core/tracking/`

The primary implementation module SHOULD be:
- `backend/app/core/tracking/instrumentation.py`

It MUST expose at least the following lifecycle surface:

- `start_run(config: dict) -> str`
- `end_run(summary: dict | None = None) -> None`

- `start_turn(turn_id: int, user_meta: dict | None = None) -> None`
- `end_turn(output_meta: dict | None = None) -> None`

- `start_invocation(purpose: str, model: str, meta: dict | None = None) -> str`
- `end_invocation(invocation_id: str, usage: dict | None = None, timing: dict | None = None) -> None`

- `record_stage(name: str, data: dict) -> None`

Implementation pattern requirement:
- Use a strategy/facade pattern with a shared interface and two concrete implementations:
  - `NoopInstrumentation` (disabled mode; no-op methods)
  - `RealInstrumentation` (enabled mode; full metrics behavior)
- A single factory/bootstrap function MUST select one implementation at startup based on `INSTRUMENTATION_ENABLED`.
- Call sites in application code MUST call the instrumentation facade directly and MUST NOT require per-call `if instrumentation_enabled` branching.
- Disabled behavior and checks MUST be centralized inside the tracking module, not duplicated across chat/sleep/retrieval code paths.

### 5.4.2 Multi-Module Integration Requirement
All modules that can:
- call an LLM
- assemble the final prompt
- perform retrieval selection/expansion
- run sleep maintenance
MUST be able to call into the same Instrumentation instance.

Instrumentation SHOULD be passed via a shared context object or imported singleton, but the mechanism MUST be consistent across the codebase.

Tagger integration requirement:
- The tagger call (mini-model classification of user/assistant pair metadata) MUST be instrumented as an invocation.
- Tagger invocations MUST be emitted with `purpose="tagger"` and include reported or estimated token usage fields per 5.5.1.
- Tagger token usage MUST be attributed to the same interactive turn that produced the assistant response being tagged.

## 5.5 Token Accounting Requirements (Mandatory)

### 5.5.1 Invocation Token Fields
Every LLM call recorded as an invocation MUST log:
- `purpose` (enum string; see 5.5.3)
- `model`
- `prompt_tokens_reported` (int, if available)
- `completion_tokens_reported` (int, if available)
- `total_tokens_reported` (int, if available)
- `usage_is_estimate` (bool)
- `usage_source` (`provider` | `estimate` | `zero_fallback`)
- `usage_estimate_method` (string or null)

If reported usage is not available, estimates MAY be used, but `usage_is_estimate=true` MUST be set.

Streaming policy:
- For streaming calls, use provider-reported usage when available.
- If provider-reported usage is unavailable, compute estimates using `tiktoken` and set:
  - `usage_source="estimate"`
  - `usage_is_estimate=true`
  - `usage_estimate_method` to the method identifier used.
- If estimation fails, write zeros for usage fields and set:
  - `usage_source="zero_fallback"`
  - `usage_is_estimate=true`
  - `usage_estimate_method=null` (or method attempted, if known)
- Streaming invocation usage MAY be finalized in the stream completion/finalization path (for example `finally`) when usage is only available at stream end.
- If the client disconnects early and provider usage is unavailable, the system MUST still emit `end_invocation` using estimate-or-zero fallback and MUST NOT mark the turn invalid solely for missing provider usage.
- If the provider returns additional token categories (for example cached/reasoning token fields), implementations MAY persist those extras under invocation `meta` for diagnostics while still populating canonical `prompt/completion/total` fields.

Usage provenance consistency:
- `usage_source="provider"` MUST imply `usage_is_estimate=false`.
- `usage_source="estimate"` and `usage_source="zero_fallback"` MUST imply `usage_is_estimate=true`.

### 5.5.2 Turn Level Token Rollups
Each turn record MUST include:
- `main_total_tokens_reported`
- `mini_prompt_tokens_reported`
- `mini_completion_tokens_reported`
- `turn_total_tokens_reported` = `main_total_tokens_reported + mini_prompt_tokens_reported`

Rollup inclusion rule:
- `mini_prompt_tokens_reported` MUST include prompt tokens for all non-main interactive mini calls for that turn, including at minimum `router` and `tagger` invocations.
- `mini_completion_tokens_reported` MUST include completion tokens for all non-main interactive mini calls for that turn, including at minimum `router` and `tagger` invocations.
- If tagging occurs in post-response persistence for the same request path, its tokens still belong to that originating turn and MUST be included in that turn rollup.

### 5.5.3 Purpose Taxonomy (Token Types)
Invocations MUST use a stable `purpose` value from:
- `main`
- `router`
- `tagger`
- `retrieval_summarizer`
- `formatter`
- `guard`
- `sleep`
- `other`

A codebase MAY add additional values later, but MUST NOT rename or repurpose existing values.

Purpose classification rule:
- `purpose` MUST be determined by pipeline context (chat/router/sleep/etc.), not by model identity.  
  Example: a sleep-stage LLM call using the same underlying model as chat main is still classified as `sleep`.

### 5.5.4 Prompt Composition Estimates (For Tuning and Stacked Bars)
For the main model prompt, the turn record MUST include estimated token breakdown fields:
- `prompt_system_tokens_est`
- `prompt_history_tokens_est`
- `prompt_rag_tokens_est`
- `prompt_profile_tokens_est`
- `prompt_other_tokens_est`

These are estimates used for analysis. Reported token usage remains the authoritative total.

---

## 5.6 Latency Requirements (Mandatory)

### 5.6.1 Invocation Timing Fields
Each invocation record MUST include:
- `start_ts` (timestamp)
- `end_ts` (timestamp)
- `first_token_ts` (timestamp or null)
- Derived:
  - `timing.ttfb_ms`
  - `timing.ttlt_ms`

Timing normalization and fallback rules:
- `start_ts` and `end_ts` MUST use UTC ISO-8601 with timezone offset.
- For non-streaming invocations:
  - `first_token_ts` MUST be `null`.
  - `timing.ttfb_ms` MUST be `null`.
  - `timing.ttlt_ms` MUST represent end-to-end latency and SHOULD be computed from `end_ts - start_ts` when not provided.
- For streaming invocations:
  - `timing.ttfb_ms` SHOULD be measured at first token yield when available.
  - If no first token is yielded or measurable, `first_token_ts` and `timing.ttfb_ms` MUST be `null` and the system MUST emit a warning.
- `timing.ttlt_ms` MUST be integer milliseconds.
- `timing.ttfb_ms` MUST be integer milliseconds or `null`.
- If `timing.ttlt_ms` is missing, invalid, or negative, implementation MUST fallback to computing from timestamps (`end_ts - start_ts`) when possible; if still unavailable, force `0` and emit a warning.
- If `timing.ttfb_ms` is invalid or negative for a streaming invocation, force `null` and emit a warning.
- `timing` is the canonical location for invocation latency fields; top-level `ttfb_ms` and `ttlt_ms` MUST NOT be emitted.

### 5.6.2 Turn Latency Fields
Each turn record MUST include:
- `ttfb_ms_main`
- `ttlt_ms_main`

Streaming TTFB rule:
- For streaming chat, `ttfb_ms_main` MUST be measured at first token yielded to the client.

Optionally, the implementation MAY also record:
- `ttlt_ms_turn_total` (includes mini calls and retrieval)

Turn latency derivation rules:
- `ttfb_ms_main` MUST be copied from the `main` invocation `ttfb_ms` for the turn.
- `ttlt_ms_main` MUST be copied from the `main` invocation `ttlt_ms` for the turn.
- If `main` invocation is missing for a turn, the system MUST emit a warning and MUST skip writing the `end_turn` record.
- For non-streaming main invocations, `ttfb_ms_main` MUST be `null` and `ttlt_ms_main` SHOULD be populated when derivable.
- If latency is unknown due to error/corruption, the system MUST emit a warning and MUST skip writing the `end_turn` record.
- `ttlt_ms_turn_total` (when recorded) MUST span request-path completion from `start_turn` to `end_turn` and MUST NOT include deferred post-response async work.

---

## 5.7 Retrieval and Context Assembly Metrics (Minimum Required)

Each turn record MUST include enough fields to explain token growth or spikes:

- `route` (string)
- `rag_enabled` (bool)
- `retrieved_count` (int)
- `kept_count` (int)
- `expanded_unique_chunks_after_merge` (int)
- `final_context_tokens_est` (int)
- `final_context_clipped` (bool)

Field definitions and boundaries:
- `route` MUST record the builder route exactly as returned; if builder fails/unavailable, it MUST default to `OTHER`.
- `rag_enabled` indicates retrieval path enabled/attempted for the turn and MAY be `true` even when counts resolve to zero.
- `retrieved_count` MUST be the total candidate count produced by the canonical retrieval entry point (FR-2.3-3.1), summed across attempted sources, before selection.
- `kept_count` MUST be the retained candidate count after FR-2.3-3.3 selection (including adjacent-chunk effective-limit bonuses), before FR-2.3-3.4 expansion/dedup.
- `expanded_unique_chunks_after_merge` MUST be computed immediately after FR-2.3-3.4.3 pass 2 (chunk identity deduplication) as the unique `(source_document_id, chunk_index)` count.
- `final_context_tokens_est` MUST represent total final prompt context estimate actually sent to the main model (system + history + RAG + profile + other).
- `final_context_clipped` MUST be `true` only when clipping/truncation occurred due to context/token budget enforcement; otherwise `false`.
- `final_context_tokens_est` SHOULD equal the exact sum of:
  - `prompt_system_tokens_est`
  - `prompt_history_tokens_est`
  - `prompt_rag_tokens_est`
  - `prompt_profile_tokens_est`
  - `prompt_other_tokens_est`

Zero/null policy:
- For turns where RAG is disabled/skipped, required numeric fields in this section MUST be `0` (not `null`).
- On partial retrieval/source failures, retrieval remains best-effort and counts MUST reflect what was actually returned/retained.
- If `rag_enabled=false`, `rag_skip_reason` MUST be present and MUST be one of:
  - `disabled_by_route`
  - `budget_zero`
  - `retrieval_error`
  - `no_candidates`
- If `rag_enabled=true`, `rag_skip_reason` MUST be omitted.

Stage-event requirements for turns stream:
- `turns.jsonl` stage records MUST include top-level `run_id`, `turn_id`, `name`, and `data`.
- Stage names are allowlisted in v1:
  - `retrieval_selection_expansion`
  - `prompt_assembly`
- Unknown stage names MUST be warned and dropped (no write).
- Stage `data` MUST NOT duplicate top-level envelope keys (`run_id`, `turn_id`, `ts`, `event`).

---

## 5.9 Accounting Validation (Required)

At `end_turn()`, Instrumentation MUST compute validation checks in-memory before writing records.

Validation MUST include:
- The turn main totals match the `main` invocation totals.
- The mini totals match the sum of all non-main interactive invocations in that turn.
- The prompt composition estimate sum approximately matches `main_prompt_tokens_reported` within a configurable tolerance (if both are present).

Validation semantics:
- If required turn validations fail, the system MUST emit warnings and MUST skip writing the `end_turn` record.
- Validation failure details MUST be logged, not persisted as per-record error arrays in `turns.jsonl`.

Error representation:
- Per-record arrays such as `token_accounting_errors` and `schema_errors` are out of scope for `turns.jsonl` v1.
- Implementations MAY keep optional in-memory booleans for control flow, but SHOULD NOT persist turn error collections.
- Standardized codes:
  - `main_total_mismatch`
  - `mini_total_mismatch`
  - `multiple_main_invocations`
  - `missing_main_invocation`
  - `prompt_estimate_out_of_tolerance`
  - `prompt_usage_missing_skipped` (optional non-failing visibility code)

Main invocation validation:
- Each interactive turn MUST have exactly one `purpose="main"` invocation.
- If zero `main` invocations exist, validation MUST emit `missing_main_invocation`.
- If more than one `main` invocation exists, validation MUST emit `multiple_main_invocations` and MUST NOT silently pass by summing mains.

Mini invocation scope:
- Mini-total validation MUST include only interactive non-main invocations for the turn.
- Maintenance invocations MUST be excluded from mini validation (for example `sleep`, and `dream` if introduced later).

Prompt estimate tolerance:
- Prompt estimate validation MUST pass if either condition is true:
  - absolute delta <= `abs_tolerance_tokens`
  - relative delta <= `pct_tolerance`
- Default values:
  - `abs_tolerance_tokens = 25`
  - `pct_tolerance = 0.02` (2%)
- Both tolerance values MUST be configurable via settings/environment.

Prompt-usage missing/unreliable handling:
- If `main_prompt_tokens_reported` is missing or known unreliable (for example estimate/zero fallback), prompt-estimate validation SHOULD be marked skipped and SHOULD NOT fail token accounting by default.
- Implementations MAY emit non-failing visibility code `prompt_usage_missing_skipped`.

Turn record contract additions (v1):
- `start_turn` records MUST include top-level:
  - `ts`
  - `event="start_turn"`
  - `run_id`
  - `turn_id`
- `turn_id` MUST be monotonic within a run; duplicates/non-monotonic IDs MUST be warned and dropped.

- `end_turn` records MUST include top-level:
  - `ts`
  - `event="end_turn"`
  - `run_id`
  - `turn_id`
  - canonical turn metrics fields from 5.6.2/5.7

Turn rollup/provenance fields:
- `turn_total_tokens_reported` MUST equal:
  - `main_total_tokens_reported + mini_prompt_tokens_reported`
- `turn_usage_source` MUST use enum:
  - `provider` | `estimate` | `zero_fallback`
- `turn_usage_is_estimate` MUST be true whenever `turn_usage_source != "provider"`.
- Turn usage/provenance aggregation scope is only invocations where:
  - `invocation.turn_id == end_turn.turn_id`
  - `turn_id` is not null

Invocation reconciliation counters:
- `invocations_count_total`
- `main_invocations_count`
- `mini_invocations_count`
- Required invariant:
  - `invocations_count_total == main_invocations_count + mini_invocations_count`

Fields removed/restricted in `end_turn`:
- `rag_tokens_injected_est` MUST NOT be emitted in `turns.jsonl` v1.
- `output_meta` MUST NOT be emitted in `turns.jsonl` v1.
- If needed, response summary fields (for example `response_len`, `finish_reason`) SHOULD be top-level and non-duplicative.

---

## 5.10 Configuration Snapshot (Run Reproducibility)

`run.json` MUST capture an immutable startup `config_snapshot` for reproducibility.

Canonical top-level shape:
- `config_snapshot` is the only canonical startup configuration object.
- Top-level duplicate aliases such as `config` MUST NOT be emitted.

Snapshot immutability and runtime changes:
- `config_snapshot` MUST represent startup configuration only and MUST NOT be mutated mid-run.
- Runtime config changes (if any) MUST be logged as events (for example `config_change` stage events or a dedicated config events stream) rather than rewriting `config_snapshot`.
- Implementations MAY include an end-of-run summary field (for example `config_overrides_observed`) in addition to immutable startup snapshot data.

`config_snapshot` MUST include:

- `models_configured`:
  - configured defaults for main and mini-model paths at run start (for example main model, builder model, tagger model).
- `models_observed` (or equivalent):
  - per-purpose set of model IDs actually observed during the run from invocation records.
  - purpose keys MUST remain purpose-native (for example `router`, `main`, `tagger`, `sleep`) and MUST NOT be renamed to configured-model key names.
  - implementations MAY add an optional helper mapping (for example `models_configured_by_purpose`) for analysis convenience.

- `prompt_budgeting`:
  - `model_context_window_tokens`
  - `max_output_tokens_requested`
  - `max_output_tokens_effective`
  - `target_max_prompt_tokens`
  - `history_max_tokens`
  - `rag_max_tokens` (if enforced)
  - `profile_max_tokens` (if enforced)
  - `system_max_tokens` (if enforced)
  - `prompt_budgeting_known` (bool)
  - If a listed cap is not enforced in current code, implementations MAY write `null` or omit that specific field, but enforced caps MUST be present.
  - `prompt_budgeting_known=true` only when all key budgeting fields are populated with meaningful effective values.
  - If any key budget value is unknown/not captured, `prompt_budgeting_known=false` and unknown fields SHOULD be `null`.
  - If no clamp/adjustment exists in the code path, `max_output_tokens_effective` MUST equal `max_output_tokens_requested`.

- retrieval configuration split by scope:
  - `retrieval_static` for global/static settings (for example base K, chunk sizing, embedding model, similarity policy).
  - `route_policy` snapshot for route-derived behavior that affects retrieval/assembly (for example per-route multipliers, max_keep, expansion params).

- thresholds and deprecated settings policy:
  - Retrieval/selection thresholds MUST be recorded under active config sections only when enforced in the run's code path.
  - Settings present in config but not enforced SHOULD be captured under an explicitly non-enforced section (for example `deprecated_or_ignored`) to preserve evidence without implying active behavior.

- `maintenance`:
  - sleep enable/trigger/cadence settings used by the run (for example scheduler enablement and scheduler time).
  - operational maintenance flags that affect workload/outputs (for example `verify_rag`, `force_rag_rebuild_on_startup`, dream enablement).
  - reporting scope marker:
    - `reporting_scope` with enum value `"sleep_only"` in this phase.

- `instrumentation`:
  - instrumentation mode and enabled state.
  - validation parameters that affect accounting outcomes (for example `prompt_tol_abs_tokens`, `prompt_tol_pct`).

- reproducibility metadata:
  - `git_commit` (string SHA) is required in v1.
  - `git_dirty` (bool) is required in v1 and indicates uncommitted workspace changes at snapshot time.
  - if `git_dirty=true`, `git_commit` MUST still be recorded (MUST NOT be nulled).
  - optional metadata MAY include `python_version` and sanitized build/runtime identity fields.

---

## 5.11 Benchmark Evaluation Artifacts (Turn Capture)

To support repeatable quality-vs-cost comparisons across systems (for example Syx, ChatGPT, and additional baselines), instrumentation-adjacent benchmark artifacts SHALL be produced in structured JSONL form.

### 5.11.1 Primary Benchmark Turn Artifact

A benchmark turn artifact file SHALL be supported:
- `benchmark_results.jsonl`

Each record represents one evaluated turn/case candidate output.

Required fields (minimum):
- `case_id` (string; stable unique id for the benchmark case)
- `system` (string; for example `syx`, `chatgpt`, `baseline_x`)
- `model_id` (string)
- `timestamp` (UTC ISO timestamp string)
- `prompt_text` (string; exact prompt content used for that candidate)
- `response_text` (string; exact candidate output)

Turn/run linkage fields:
- `run_id` (string or null)
- `turn_id` (int or null)

Token/latency comparison fields:
- `main_total_tokens_reported` (int or null)
- `turn_total_tokens_reported` (int or null)
- `latency_ms` (int or null)

Alignment and completeness fields:
- `metrics_source` (string; for example `syx_instrumentation`, `html_extracted`)
- `completeness` (enum: `full` | `partial`)
- `missing_fields` (array of strings; MAY be empty)

### 5.11.2 Turn ID Alignment Rules

For records where `system="syx"`:
- `turn_id` MUST match the corresponding `turns.jsonl` turn id exactly.
- `run_id` MUST match the corresponding instrumentation run directory id.
- `turn_id`/`run_id` mismatches MUST be treated as alignment errors by benchmark tooling.

For external/manual sources (for example HTML-extracted ChatGPT turns):
- `turn_id` MAY be null when no native instrumentation turn id exists.
- Tooling SHOULD include an explicit alignment key (for example `aligned_turn_id` or equivalent) to map external turns to Syx benchmark turns.

### 5.11.3 Secondary Scoring Artifact

A second artifact SHOULD be used for judge/scorer outputs:
- `benchmark_scores.jsonl`

Recommended fields:
- `case_id`
- `scorer_model`
- rubric subscores (structured object)
- `overall_score`
- `rationale`
- optional judge metadata (for example prompt version, confidence, parsing status)

Separation rule:
- `benchmark_results.jsonl` stores candidate outputs and measured stats.
- `benchmark_scores.jsonl` stores evaluator judgments.
- Benchmark tooling MAY join on `case_id`.

### 5.11.4 Nullability and Partial Data Policy

Benchmark artifacts MUST permit partial metrics for non-instrumented sources:
- Unknown/unavailable numeric metrics MUST be null (not fabricated).
- Missing optional metrics MUST NOT block record creation.
- `missing_fields` SHOULD enumerate intentionally absent metrics for analysis transparency.

---

# Version 6 — Deterministic Response Pruning

## Purpose

Syx SHALL support deterministic, code-based pruning of low-information assistant-response text before text is used for storage, tagging, retrieval, benchmark export, or other memory-adjacent processing.

The v6 goal is to reduce assistant-response boilerplate and duplicate phrasing without using an LLM and without rewriting substantive content such as explanations, decisions, lists, code, structured metadata, requirements, or user-visible facts.

---

## 6.1 Scope

### 6.1.1 In Scope

- Deterministic pruning without LLM calls.
- Assistant-response text input.
- Leading pruning from the front of a response.
- Trailing pruning from a detected paragraph boundary to the end of a response.
- JSON-based pruning-rule configuration.
- Loading and merging multiple pruning-rule configuration files.
- Conservative normalization-based prefix matching.
- Markdown markup stripping for common non-code prose markup.
- Whitespace compaction with fenced-code preservation.
- Lightweight duplicate-sentence pruning based on sentence similarity.
- Runtime configuration that can enable or disable the whole pruning pipeline and each major pruning stage.
- Structured result metadata suitable for debugging and audit.
- Safe behavior by default.

### 6.1.2 Out of Scope

- LLM-assisted pruning.
- Arbitrary rewriting, summarization, or compression of retained text.
- Mid-response deletion except for duplicate-sentence removal by the explicit similarity stage.
- Regex-first pruning logic.
- Automatic corpus mining of new rules.
- Exact-match rule families separate from prefix rules.
- Semantic meaning comparison beyond lightweight duplicate-sentence detection.

---

## 6.2 Definitions

### 6.2.1 Response

The assistant-produced text to be evaluated for pruning.

### 6.2.2 Front Pruning

Removal of one or more leading sentence units from the beginning of a response.

### 6.2.3 End Pruning

Removal of a paragraph boundary and all following content from a detected trailing prune point to the end of a response.

### 6.2.4 Prefix Rule

A configured string that is compared against the normalized start of a candidate text unit.

### 6.2.5 Normalization

A deterministic transformation applied only for comparison unless a separate transformation stage explicitly modifies output text.

### 6.2.6 Cut Mode

A named pruning behavior that defines what unit is removed when a match is detected.

### 6.2.7 Similarity Scan

A lightweight deterministic stage that detects repeated or near-repeated sentences and drops later duplicate sentences while preserving protected sentences and fenced code blocks.

---

## 6.3 Functional Requirements

### 6.3.1 Core Behavior

- FR-6.3.1.1 The pruning module SHALL expose a primary function or service method equivalent to `prune_response()`.
- FR-6.3.1.2 The primary pruning API SHALL accept a response string as input.
- FR-6.3.1.3 The primary pruning API SHALL return both the pruned text and metadata describing what changed.
- FR-6.3.1.4 The pruning module SHALL perform deterministic rule-based pruning without requiring an LLM call.
- FR-6.3.1.5 The pruning module SHALL preserve the original response when no safe trim or transformation is detected.
- FR-6.3.1.6 The pruning module SHALL support load-once, prune-many usage through a stateful pruner object.
- FR-6.3.1.7 The pruning module SHALL be usable inline before tagging, memory persistence, benchmark export, or other response-processing steps.

### 6.3.2 Front Pruning

- FR-6.3.2.1 Front pruning SHALL use prefix-based matching.
- FR-6.3.2.2 Front pruning SHALL operate on sentence units.
- FR-6.3.2.3 The pruning module SHALL inspect the leading sentence unit for configured prefix matches.
- FR-6.3.2.4 If the normalized leading sentence begins with a configured normalized prefix, the pruning module SHALL remove that sentence.
- FR-6.3.2.5 The pruning module MAY continue removing additional leading sentence units while matches continue and safety limits are satisfied.
- FR-6.3.2.6 Front pruning SHALL stop at the first non-matching substantive sentence unit.
- FR-6.3.2.7 Front pruning SHALL respect a configurable maximum number of leading sentence units to trim.
- FR-6.3.2.8 Front pruning SHALL preserve the response if trimming would leave too little substantive content.

### 6.3.3 End Pruning

- FR-6.3.3.1 End pruning SHALL use prefix-based matching.
- FR-6.3.3.2 End pruning SHALL use the configured cut mode to determine the removable trailing region.
- FR-6.3.3.3 For `paragraph_to_end`, end pruning SHALL remove the matching paragraph and all following content to the end of the response.
- FR-6.3.3.4 End pruning SHALL compare normalized candidate paragraph starts against normalized configured prefixes.
- FR-6.3.3.5 End pruning SHALL trim trailing content only from a detected prune boundary to the end of the response.
- FR-6.3.3.6 End pruning SHALL preserve the response if no safe trailing prune boundary is found.
- FR-6.3.3.7 End pruning SHALL NOT prune trailing content when the candidate region appears substantive under configured safety rules.
- FR-6.3.3.8 End pruning SHOULD inspect only trailing candidate paragraphs rather than arbitrary middle paragraphs.

### 6.3.4 Markdown Cleanup

- FR-6.3.4.1 The pruning module SHALL support a markdown cleanup stage for common assistant-response markup.
- FR-6.3.4.2 Markdown cleanup SHALL remove common prose markup such as ATX heading markers, blockquote markers, bullet/list markers, links, images, inline code markers, emphasis, strong emphasis, and strikethrough markers.
- FR-6.3.4.3 Markdown cleanup SHALL preserve fenced code block contents.
- FR-6.3.4.4 Markdown cleanup SHALL preserve requirement-like numbered lines, Q/A numbered lines, and similar structured lines where removing numbering would alter meaning.
- FR-6.3.4.5 Markdown cleanup SHALL be independently disableable through runtime configuration.

### 6.3.5 Whitespace Cleanup

- FR-6.3.5.1 The pruning module SHALL support whitespace cleanup for retained output text.
- FR-6.3.5.2 Whitespace cleanup SHALL be configurable through a `whitespace_mode` setting.
- FR-6.3.5.3 Supported `whitespace_mode` values SHALL include `off`, `compact_prose`, and `preserve_code`.
- FR-6.3.5.4 In compaction modes, the pruning module SHALL collapse repeated spaces and tabs in prose.
- FR-6.3.5.5 In compaction modes, the pruning module SHALL collapse repeated blank prose lines.
- FR-6.3.5.6 Whitespace cleanup SHALL preserve fenced code block contents.
- FR-6.3.5.7 Whitespace cleanup SHALL be independently disableable through runtime configuration.

### 6.3.6 Duplicate-Sentence Similarity Scan

- FR-6.3.6.1 The pruning module SHALL support a lightweight duplicate-sentence scan.
- FR-6.3.6.2 The similarity scan SHALL split prose into sentence units and compare normalized sentences against previously retained normalized sentences.
- FR-6.3.6.3 The similarity scan SHALL drop later duplicate or near-duplicate sentences when the configured similarity threshold is met.
- FR-6.3.6.4 The similarity scan SHALL NOT perform broad semantic similarity or paraphrase reasoning.
- FR-6.3.6.5 The similarity scan SHALL preserve fenced code block contents.
- FR-6.3.6.6 The similarity scan SHALL preserve protected sentences that contain requirement IDs, numeric values, function-call-like text, snake_case identifiers, or dotted identifiers.
- FR-6.3.6.7 The similarity scan SHALL use a configurable integer `similarity_threshold`.
- FR-6.3.6.8 `similarity_threshold` SHALL be validated as an integer from `0` through `100`.
- FR-6.3.6.9 The similarity scan SHALL be independently disableable through runtime configuration.

### 6.3.7 Safety Behavior

- FR-6.3.7.1 The pruning module SHALL avoid pruning inside fenced code blocks.
- FR-6.3.7.2 The pruning module SHALL avoid trimming content that begins with code fences, headings, bullets, blockquotes, ordered lists, or structured metadata when that content appears substantive.
- FR-6.3.7.3 The pruning module SHALL preserve responses that are too short for safe pruning.
- FR-6.3.7.4 The pruning module SHALL provide guardrails to prevent returning an empty result unless explicitly allowed by a future documented requirement.
- FR-6.3.7.5 The default behavior SHALL be conservative and prefer false negatives over false positives.
- FR-6.3.7.6 Prefix matching SHALL use normalization-based comparison.
- FR-6.3.7.7 Normalization SHALL be deterministic and documented.
- FR-6.3.7.8 Normalization for matching SHALL NOT rewrite retained output text.
- FR-6.3.7.9 The pruning module SHALL preserve the original unmodified response text in output metadata.
- FR-6.3.7.10 The pruning module SHALL support Unicode-safe handling of apostrophe variants in the default normalizer.

---

## 6.4 Normalization Requirements

For all configured prefix comparisons, the pruning module SHALL normalize both candidate text units and configured prefix strings using the following steps in order:

- FR-6.4.1 Convert text to lowercase.
- FR-6.4.2 Replace curly apostrophes with straight apostrophes.
- FR-6.4.3 Trim leading and trailing whitespace.
- FR-6.4.4 Collapse repeated whitespace characters, including spaces, tabs, and newlines, into a single space.
- FR-6.4.5 Remove trailing `.`, `!`, or `?` characters occurring at the very end of the text.
- FR-6.4.6 Trim leading and trailing whitespace again.
- FR-6.4.7 Return the normalized result.
- FR-6.4.8 Apply the same normalization procedure to configured prefixes and candidate text units.

---

## 6.5 Configuration Requirements

### 6.5.1 Rule Configuration Ingestion

- FR-6.5.1.1 The pruning module SHALL support loading pruning rules from one or more JSON files.
- FR-6.5.1.2 The pruning module SHALL support loading pruning rules from in-memory objects.
- FR-6.5.1.3 The pruning module SHALL validate all loaded rule inputs against the supported schema before use.
- FR-6.5.1.4 The pruning module SHALL reject malformed rule configurations with clear errors.
- FR-6.5.1.5 A valid rule configuration MAY contain `front`, `end`, or both sections.
- FR-6.5.1.6 Rule loading MAY support stripping `_comment`-prefixed keys before validation.

### 6.5.2 Rule Configuration Schema

- FR-6.5.2.1 The `front` section SHALL support a `prefix` field and a `cut_mode` field.
- FR-6.5.2.2 The `end` section SHALL support a `prefix` field and a `cut_mode` field.
- FR-6.5.2.3 The `prefix` field SHALL contain a list of non-empty strings.
- FR-6.5.2.4 The `cut_mode` field SHALL contain a supported cut mode string.
- FR-6.5.2.5 The pruning module SHALL reject unsupported or invalid `cut_mode` values.
- FR-6.5.2.6 The pruning module SHALL reject rule entries that are not strings within `prefix` lists.
- FR-6.5.2.7 The pruning module SHALL deduplicate repeated prefix entries during load or merge.

### 6.5.3 Rule Merge Behavior

- FR-6.5.3.1 The pruning module SHALL support merging multiple valid rule configurations into one effective rule set.
- FR-6.5.3.2 The pruning module SHALL merge `prefix` lists by deduplicated union.
- FR-6.5.3.3 The pruning module SHALL preserve deterministic ordering of merged prefixes.
- FR-6.5.3.4 The pruning module SHALL require compatible `cut_mode` values for the same section across merged configurations.
- FR-6.5.3.5 The pruning module SHALL raise a validation error when merged configurations specify conflicting `cut_mode` values for the same section unless an explicit conflict policy is configured.
- FR-6.5.3.6 The pruning module SHALL expose the final merged effective rule set for inspection or export.

### 6.5.4 Runtime PrunerConfig

- FR-6.5.4.1 The pruning module SHALL expose runtime configuration through a `PrunerConfig` or equivalent model.
- FR-6.5.4.2 `PrunerConfig` SHALL include `max_response_size`.
- FR-6.5.4.3 `max_response_size` SHALL be validated as an integer greater than `0`.
- FR-6.5.4.4 `PrunerConfig` SHALL include `max_front_units`.
- FR-6.5.4.5 `max_front_units` SHALL be validated as an integer greater than `0`.
- FR-6.5.4.6 `PrunerConfig` SHALL include `similarity_threshold`.
- FR-6.5.4.7 `similarity_threshold` SHALL be validated as an integer from `0` through `100`.
- FR-6.5.4.8 `PrunerConfig` SHALL include `whitespace_mode`.
- FR-6.5.4.9 `whitespace_mode` SHALL be validated against supported values.
- FR-6.5.4.10 `PrunerConfig` SHALL include a `response_pruning` stage-toggle mapping or equivalent structured toggle model.
- FR-6.5.4.11 `response_pruning.enabled=false` SHALL disable all pruning and cleanup stages.
- FR-6.5.4.12 `response_pruning.front_enabled=false` SHALL disable front pruning while preserving other enabled stages.
- FR-6.5.4.13 `response_pruning.end_enabled=false` SHALL disable end pruning while preserving other enabled stages.
- FR-6.5.4.14 `response_pruning.markdown_enabled=false` SHALL disable markdown cleanup while preserving other enabled stages.
- FR-6.5.4.15 `response_pruning.whitespace_enabled=false` SHALL disable whitespace cleanup while preserving other enabled stages.
- FR-6.5.4.16 `response_pruning.similarity_enabled=false` SHALL disable duplicate-sentence similarity scanning while preserving other enabled stages.
- FR-6.5.4.17 Unknown `response_pruning` keys SHALL be rejected.
- FR-6.5.4.18 Non-boolean `response_pruning` values SHALL be rejected.
- FR-6.5.4.19 The default `response_pruning` configuration SHALL enable all supported stages unless overridden by deployment configuration.

---

## 6.6 Supported Cut Modes

- FR-6.6.1 The pruning module SHALL support `sentence` as the valid `front.cut_mode`.
- FR-6.6.2 The pruning module SHALL support `paragraph_to_end` as the valid `end.cut_mode`.
- FR-6.6.3 The pruning module SHALL reject unsupported cut modes during validation.

---

## 6.7 Output Requirements

- FR-6.7.1 The pruning module SHALL return the pruned response text.
- FR-6.7.2 The pruning module SHALL return whether any trimming or transformation occurred.
- FR-6.7.3 The pruning module SHALL return which boundary side was trimmed: `none`, `front`, `end`, or `both`.
- FR-6.7.4 The pruning module SHALL return enough metadata for debugging, including matched prefixes, removed front unit counts, removed end spans, and safety-block status.
- FR-6.7.5 The pruning module SHALL make the original response text available for auditability.
- FR-6.7.6 The pruning module SHALL expose whether pruning was blocked by a safety rule.
- FR-6.7.7 If markdown cleanup, whitespace cleanup, or similarity scanning changes output without front/end boundary trimming, the result SHALL still indicate that the output changed.

Suggested result structure:

```python
class PruneResult:
    original_text: str
    pruned_text: str
    changed: bool
    trimmed_front: bool
    trimmed_end: bool
    matched_front_prefixes: list[str]
    matched_end_prefixes: list[str]
    front_units_removed: int
    end_span_removed: tuple[int, int] | None
    blocked_by_safety: bool
```

---

## 6.8 Supported Rule Configuration Shape

```json
{
  "front": {
    "prefix": ["got it", "absolutely", "good catch"],
    "cut_mode": "sentence"
  },
  "end": {
    "prefix": ["if you want", "let me know", "would you like"],
    "cut_mode": "paragraph_to_end"
  }
}
```

Additional semantic constraints:

- `front.cut_mode` MUST be `sentence` if `front` is present.
- `end.cut_mode` MUST be `paragraph_to_end` if `end` is present.
- Prefix entries SHOULD be normalized for comparison, but original configured values MAY be retained for reporting.
- Duplicate prefixes SHOULD be removed in the effective merged rule set.
- Conflicting `cut_mode` values across merged files SHALL raise a validation error by default.

---

## 6.9 Suggested Runtime API Shape

```python
pruner = Pruner.from_file(
    "rules.json",
    config=PrunerConfig(
        max_response_size=50_000,
        max_front_units=3,
        similarity_threshold=90,
        whitespace_mode="compact_prose",
        response_pruning={
            "enabled": True,
            "front_enabled": True,
            "end_enabled": True,
            "markdown_enabled": True,
            "whitespace_enabled": True,
            "similarity_enabled": True,
        },
    ),
    strip_comment_keys=True,
)

result = pruner.prune(response_text)
```

For one-off calls:

```python
result = prune_response(response_text, rules=rules, config=config)
```

---

## 6.10 Non-Functional Requirements

- NFR-6.10.1 The pruning module SHALL be lightweight and fast enough for inline use before tagging or storage.
- NFR-6.10.2 The pruning module SHALL have no mandatory network dependency.
- NFR-6.10.3 The pruning module SHALL be easy to inspect and debug.
- NFR-6.10.4 The pruning module SHALL be deterministic and reproducible across runs for identical inputs, rules, and configuration.
- NFR-6.10.5 The pruning module SHALL include tests covering safe trims, no-trim cases, merge behavior, schema validation, stage toggles, markdown cleanup, whitespace cleanup, duplicate-sentence pruning, and false-positive protection.
- NFR-6.10.6 The default behavior SHALL favor preserving content over maximizing token reduction.
