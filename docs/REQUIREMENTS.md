# Morpheus

## Project Overview
Morpheus is a modular system that provides a web-based chat interface backed by a FastAPI server and LangChain for LLM integration.  

**Version 1 Goal:** Establish a working chatbot with a GUI and stable backend interfaces that can be extended later with RAG, memory pruning, and multi-project support.  
**Version 2 Goal:** Add persistent Project Management, File Upload + RAG initialization, and dynamic Model Selection.

---

## Core Functional Requirements

### 1. Chat Interface (FR-001)
**Priority:** High  
- **Requirement:** Provide a web-based chat UI for user ↔ AI interaction.  
- **Frontend:** Built in React with Shadcn/UI.  
- **Features:**
  - Message history displayed in chat bubbles.  
  - Input box for sending messages.  
  - Basic UI controls for triggering stubbed actions (`query_rag`, `switch_project`).  
- **Success Criteria:** User can hold a conversation with the chatbot via the web UI.

---

### 2. Chat Endpoint (FR-002)
**Priority:** High  
- **Requirement:** Backend endpoint for handling user messages.  
- **Implementation:** FastAPI `/chat` route.  
- **Flow:** Receive message → Forward to LangChain LLM → Return response.  
- **Validation:** Must return a valid response for every valid request.  
- **Success Criteria:** End-to-end chat works (UI → FastAPI → LangChain → UI).

---

### 3. LangChain Integration (FR-003)
**Priority:** High  
- **Requirement:** Use LangChain as the abstraction layer for LLM providers.  
- **Default Provider:** OpenAI GPT-5.  
- **Future Proofing:** Should support Anthropic, LLaMA, etc. with minimal change.  
- **Success Criteria:** Responses are generated via LangChain `ChatOpenAI` interface.

---

### 4. Stubbed Feature Hooks (FR-004)
**Priority:** Medium  
- **Requirement:** Provide backend routes for future functionality.  
- **Endpoints:**
  - `/query_rag` → currently returns “RAG not implemented.”  
  - `/projects` → list/switch projects (stub).  
  - `/sleep_cycle` → trigger pruning job (stub).  
- **Success Criteria:** Stubs exist, return placeholder responses, and can be called from frontend buttons.

---

### 5. Project Awareness (FR-005)
**Priority:** Medium  
- **Requirement:** Define project-based separation of future memory indexes.  
- **Implementation:** Project ID included in requests (stub only in V1).  
- **Success Criteria:** API supports project context, even if unused in V1.

---

## Technical Requirements

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
- **Interface:** LangChain `ChatOpenAI` (default OpenAI GPT-5).  
- **Flexibility:** Must support provider swap by config, not refactor.  
- **Success Criteria:** Swapping OpenAI → Anthropic requires minimal changes.

---

### 4. Configuration (TR-004)
**Priority:** High  
- **Env Variables:**
  - `OPENAI_API_KEY` (required)
  - `MODEL_NAME` (default: `gpt-5`)
  - `MODEL_TEMPERATURE` (default: `1.0`)
  - `MODEL_MAX_TOKENS` (default: `32000`)
  - `DB_PATH` (e.g., `backend/app/data/morpheus.db`)
  - `MAX_UPLOAD_MB` (per-file limit; default `10`)
  - `MAX_BATCH_MB` (per-request batch limit; default `50`)
  - `STORAGE_LIMIT_MB` (per-project storage cap; default `500`)
  - `EMBEDDING_MODEL` (default: `text-embedding-3-large`)
  - `CHUNK_SIZE` (default: `800`)
  - `CHUNK_OVERLAP` (default: `100`)
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

---

## Version 2 — Project Management and Model Selection

### Overview
Version 2 introduces persistent **Project Management**, **File Upload + RAG Initialization**, and a **Dynamic Model Selector**.  
These upgrades make Morpheus a multi-project, persistent knowledge system.

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
  2. Process synchronously and embed via LangChain.  
  3. Store vectors in FAISS index at `memory/{project_id}/faiss/`.  
- **Formats:** `.txt`, `.md`, `.pdf`.  
- **Success Criteria:** Uploaded content retrievable via future `/query_rag`.

- **Embedding & RAG Policy (V2):**
  - Embedding model: `text-embedding-3-large` (3072D)
  - Chunking: size `800`, overlap `100` using `RecursiveCharacterTextSplitter`
  - Metadata per chunk: `project_id`, `filename`, `page_number`, `chunk_id`, `timestamp`
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
- Threshold: only include snippets with similarity ≥ `RAG_SCORE_THRESHOLD`
- Injection: prepend a single system message with a "Context:" block containing concatenated snippets, separated clearly; cap the context block at `RAG_CONTEXT_MAX_TOKENS`
- If no snippet meets threshold, proceed without RAG
- Do not index chat transcripts in V2.1

Env controls:
- `RAG_ON_CHAT=true`
- `RAG_TOP_K=5`
- `RAG_SNIPPET_MAX_TOKENS=500`
- `RAG_CONTEXT_MAX_TOKENS=5000`
- `RAG_SCORE_THRESHOLD=0.75`

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
