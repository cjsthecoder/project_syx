# Morpheus

## Project Overview
Morpheus is a modular system that provides a web-based chat interface backed by a FastAPI server and LangChain for LLM integration.  

**Version 1 Goal:** Establish a working chatbot with a GUI and stable backend interfaces that can be extended later with RAG, memory pruning, and multi-project support.  
**Version 2 Goal:** Add persistent Project Management, File Upload + RAG initialization, and dynamic Model Selection.
**Version 3 Goal:** Implement autonomous long-term memory consolidation through a nightly Sleep Cycle that prunes, summarizes, and rebuilds each project’s RAG automatically. This release transforms Morpheus from a reactive chat system into one that learns and maintains knowledge over time, preparing the foundation for Dreaming (creative synthesis) in version 4.
**Version 4 Goal:** Introduce the Dream Cycle as a post Sleep reasoning phase capable of autonomously analyzing the nightly memory summary and generating structured insight outputs. Version 4 establishes the Dream Orchestrator, the Dream Agent framework, and the first Dream function: extracting all open questions into a unified artifact. This transforms Morpheus from a system that only consolidates memory into one that begins to interpret, organize, and act on unresolved knowledge gaps during nightly maintenance.

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
- **Flow:** Receive message → Forward to LangChain LLM → Return response.  
- **Validation:** Must return a valid response for every valid request.  
- **Success Criteria:** End-to-end chat works (UI → FastAPI → LangChain → UI).

---

#### 3. LangChain Integration (FR-003)
**Priority:** High  
- **Requirement:** Use LangChain as the abstraction layer for LLM providers.  
- **Default Provider:** OpenAI GPT-5.  
- **Future Proofing:** Should support Anthropic, LLaMA, etc. with minimal change.  
- **Success Criteria:** Responses are generated via LangChain `ChatOpenAI` interface.

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
- End-to-end chat works between UI and FastAPI via LangChain.
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

### Acceptance Criteria
- Backend exposes the required endpoints with consistent JSON shapes.
- Frontend renders core chat UI and successfully calls the API.
- Configuration is driven by `.env` without hardcoding secrets.
- A single FastAPI server serves both API and built frontend.

---

# Version 2 — Project Management and Model Selection

## Overview
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

Generate assistant response via LangChain → OpenAI.

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
{ "role": "user", "content": "What is LangChain?", "created_at": "2025-10-08T10:00:00Z" },
{ "role": "assistant", "content": "LangChain is a framework for LLM apps.", "created_at": "2025-10-08T10:00:01Z" }
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
Extend Morpheus’ working memory by continuously off-loading the oldest prompt/response pairs from the live chat buffer and database into a persistent daily RAG file.
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

#### FR-2.3.2 — Incremental Embedding → Daily FAISS
Append embeddings to a single FAISS file per project: `memory/{project_id}/daily.faiss`.

- Do not rebuild the index each time; use incremental adds
- Embed each rolled-off prompt/response pair as a single chunk (do not apply file `CHUNK_SIZE`/`CHUNK_OVERLAP`); use the same `EMBEDDING_MODEL`
- Maintain a companion metadata file `memory/{project_id}/daily.json` with one entry per embedded pair using this schema:
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
- Write strategy: persist after each add and use lightweight file locking to prevent concurrent write corruption
- Embedding model changes: if `EMBEDDING_MODEL` changes, drop `daily.faiss` and `daily.json` and start fresh (main index remains)
- Corruption recovery: if FAISS or metadata is corrupt, reset both and log an error
- Failure path: if embedding/index write fails, log error, drop the pair from memory, delete its two DB rows, and do not retry

#### FR-2.3-3 — Retrieval Flow
On every `/chat` call:

- Retrieve K results from `daily.faiss` using `DAILY_RAG_K` and threshold `DAILY_RAG_SCORE_THRESHOLD`
- Retrieve K results from main project RAG using `RAG_TOP_K` and threshold `RAG_SCORE_THRESHOLD`
- Weight daily results by `DAILY_RAG_WEIGHT` (score' = score × weight) and merge by weighted score
- De-duplicate results according to env flags (see FR-2.3-5)
- Token budgeting: fill up to `DAILY_RAG_MAX_TOKENS` from daily first, then fill the remaining global `RAG_CONTEXT_MAX_TOKENS` from main
- Context assembly: label sections explicitly and order as:
  - Daily:
  - Main:
- Inject the combined Context block as a single system message before user input

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

- `CHAT_HISTORY_LIMIT_PAIRS=10` — number of prompt/response pairs kept in working memory
- `DAILY_RAG_ENABLED=true` — global default toggle; per-project toggle overrides
- `DAILY_RAG_K=3` — top-K from daily
- `DAILY_RAG_SCORE_THRESHOLD=0.70` — similarity threshold for daily
- `DAILY_RAG_MAX_TOKENS=2500` — max tokens contributed by daily layer
- `DAILY_RAG_WEIGHT=1.2` — weight multiplier applied to daily scores before merging
- Deduping controls:
  - `DEDUPE_EXACT=true` — remove exact-text duplicates
  - `DEDUPE_NEAR=true` — remove near-duplicates by similarity
  - `DEDUPE_SIMILARITY_THRESHOLD=0.98` — cosine threshold for near-duplicate detection
  - `DEDUPE_KEEP_DAILY=true` — when deduping, prefer keeping the daily hit

(Daily RAG values are tuned separately from main RAG for recall vs precision.)

#### FR-2.3.6 — UI Integration
In the Manage Project modal display:

- “Active Pairs” count (deque length)
- “Daily RAG size” and “Tokens indexed” for daily (mirroring main stats rendering)
- Per-project toggle: “Keep Daily History” (maps to `daily_rag_enabled`, default true)

### Lifecycle
`daily.faiss` persists across days until merged during 3.0 sleep cycle.

Sleep cycle logic will:

- Read and prune `daily.faiss`
- Merge summarized chunks into `index.faiss`
- Reset `daily.faiss` for the next run

### Acceptance Criteria

- Oldest chat pair removed from memory and DB when limit exceeded.
- Rolled-off pair embedded and appended to `daily.faiss`; metadata appended to `daily.json`.
- Debug log clearly shows prompt + response text.
- Retrieval includes results from both daily and main RAGs, with daily weighted per `DAILY_RAG_WEIGHT`.
- De-duplication applied per env settings.
- Corruption/model-change resets are handled cleanly with logging.
- System operates with incremental writes and file locking.


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
{ "route":"CHITCHAT|CODE|DOCS|OTHER", "rag":true, "standalone":"", "paraphrases":[], "hyde":"", "entities":[], "topics":[], "reason":"", "confidence":0.0 }
• Use `BUILDER_MODEL` over the same OpenAI channel as chat; no extra latency/budget constraints beyond `BUILDER_MAX_TOKENS`.

FR-2.3.1.2 — Routing Logic
• If rag=false or route="CHITCHAT", skip retrieval and reply directly via chat model (still include in‑memory history).
• Else embed standalone + 2–3 paraphrases + 1 HYDE and run topic‑aware RAG lookup.
• If `confidence < BUILDER_CONFIDENCE_MIN`, perform conservative retrieval (standalone only; skip paraphrases/HYDE).
• If the builder fails/times out/returns invalid JSON: log a warning and skip RAG entirely (answer directly).

FR-2.3.1.3 — Topic and Entity Extraction
• Builder emits topics and entities.
• Sidecar metadata for main RAG: store per‑chunk metadata in `memory/{project}/faiss/meta_topics.json`, keyed by FAISS docstore ID (no full re‑index now). Merge sidecar with existing metadata during retrieval/rerank.
• Biasing:
– Exact match boost if topic appears in sidecar (#topics).
– Partial/semantic boost via embedding similarity of topic terms (with in‑memory per‑project topic vector cache, LRU + TTL ~24h, max ~500 entries).

FR-2.3.1.4 — Metadata-Aware Reranking
• After cosine retrieval, adjust scores multiplicatively (topic → decision → open_question), then clamp to 1.0 before sorting/truncation.
• Then apply token budget.
• Optional ENV weights:
TOPIC_BOOST=1.10
DECISION_BOOST=1.05
QUESTION_BOOST=1.02

FR-2.3.1.5 — Query Expansion and Namespacing
• Route selects a preferred namespace (e.g., "jira", "code", "docs").
• Always search full corpus; strongly boost routed namespace (no hard filter).
• Maintain file→namespace sidecar `memory/{project}/faiss/meta_namespaces.json`; default namespace "other" for unmapped; include "other" when route unknown.
• Embed variants with optional prefix “query:”; include topic/entity terms for hybrid search.

FR-2.3.1.6 — Prompt Template (for Builder)
System: “You are a fast query builder and router for RAG. Return strict JSON. No prose.”
User: “Recent summary: {history} Turn: {user_text}”
Rules:
• If small-talk/joke/meta → route=CHITCHAT, rag=false.
• Else choose domain route and return concise rewritten query set plus topics/entities.

FR-2.3.1.7 — Retrieval Order and Context Assembly
• Daily results queried and filled first (up to DAILY_RAG_MAX_TOKENS).
• Main RAG fills remaining context budget (RAG_CONTEXT_MAX_TOKENS).
• Label sections clearly in prompt:
Context:
--- Daily:
<daily snippets>
--- Main:

<main snippets> • Deduplicate exact and near‑duplicates (cosine ≥ 0.98) after merging daily+main and before token budgeting.

FR-2.3.1.8 — Environment Variables
BUILDER_MODEL=gpt-4o-mini
BUILDER_CONFIDENCE_MIN=0.75
BUILDER_MAX_TOKENS=512
BUILDER_CACHE=True
TOPIC_BOOST=1.10
DECISION_BOOST=1.05
QUESTION_BOOST=1.02
DEDUPE_SIMILARITY_THRESHOLD=0.98

FR-2.3.1.9 — Logging / Debug Visibility
• Log builder JSON into the existing app log (no separate file), including timestamp, route, rag, confidence, topics, and trimmed standalone; tag lines clearly (module logger/type="builder").
• Log applied topic/decision/open_question boost values during reranking.
• Optionally display route and confidence in chat UI for debug.

FR-2.3.1.10 — Concurrency and Locking
• Use a single `faiss.lock` for FAISS and sidecar metadata reads/writes under `memory/{project}/faiss/`; keep locks short‑lived.

FR-2.3.1.11 — Builder Cache
• If `BUILDER_CACHE=True`, cache builder JSON in memory per process with TTL ≈ 10 minutes and max ≈ 500 entries; key by `(project_id, history_summary, user_turn)`; no disk persistence.

Acceptance Criteria

• Builder invoked on every turn and returns valid JSON.
• Non-RAG turns bypass retrieval entirely.
• RAG turns use rewritten queries and topic/entity expansion.
• Topic/decision/open_question boosts reflected in scores and logs; boosted scores clamped to 1.0.
• Context assembled as “Daily:” then “Main:”.
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
- **[ROLLOFF]** – when a pair is embedded into `daily.faiss`
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
- Add rotation policy: `logs/morpheus.log`, 10 MB × 5 files.  

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
Improve RAG precision and contextual relevance by adjusting retrieval behavior based on the semantic intent (“route”) identified by the query builder.
Each incoming message is classified as CODE, DOCS, OTHER, or CHITCHAT, and retrieval parameters (namespaces, thresholds, K-values) are tuned accordingly.

### Functional Requirements

#### FR-2.5.1 — Builder Output Utilization
Use the existing builder LLM output to extract route and rag flags:

```
{"route": "CODE", "rag": true, "confidence": 0.91}
```

If `rag=false` or `route="CHITCHAT"`, skip retrieval entirely.

#### FR-2.5.2 — Route Configuration Map
Create `/app/config/meta_namespaces.json` defining namespaces and retrieval parameters per route:

```
{
  "CODE": {
    "namespaces": ["code", "config", "api"],
    "rag_k": 8,
    "score_threshold": 0.70
  },
  "DOCS": {
    "namespaces": ["docs", "requirements", "notes"],
    "rag_k": 5,
    "score_threshold": 0.75
  },
  "OTHER": {
    "namespaces": ["general", "project"],
    "rag_k": 6,
    "score_threshold": 0.72
  },
  "CHITCHAT": {
    "namespaces": [],
    "rag_k": 0,
    "score_threshold": 0.0
  }
}
```

#### FR-2.5.3 — Retrieval Logic Update
Modify `rag_manager.retrieve_context()` to:
- Load the route configuration from `meta_namespaces.json`.
- Retrieve top-K results from both `daily.faiss` and `index.faiss` using the selected namespaces.
- Filter by `score_threshold`.
- Merge, rank by similarity, and return the top K items.

#### FR-2.5.4 — Namespace Boosting
When embeddings are stored, include metadata such as:

```
{"namespace": "docs", "source": "REQUIREMENTS.md"}
```

During retrieval, apply a small boost (e.g., `similarity *= 1.05`) if the namespace matches one of the configured route namespaces.

#### FR-2.5.5 — Logging Integration
Add a `[ROUTE]` log event before retrieval:

```
[ROUTE] route=CODE namespaces=['code','config','api'] k=8 threshold=0.70
```

and after retrieval:

```
[RETRIEVAL] route=CODE hits=12 used=8 avg_similarity=0.82
```

#### FR-2.5.6 — Fallback Behavior
If the builder route is unknown or the config file is missing, default to the “OTHER” route configuration.

### Acceptance Criteria
- CODE and DOCS queries retrieve from different namespaces with tuned thresholds.
- CHITCHAT messages bypass RAG retrieval.
- Logging clearly displays route and applied settings.
- Retrieval results align with route-specific context (e.g., code for technical prompts, docs for requirements).
- No breaking changes to the existing RAG pipeline or database schema.


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
You are Morpheus-AI, a reflective assistant that consolidates knowledge during nightly sleep.
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

#### FR-2.7.1 — Daily Text Snapshot for Pruning
Ensure each project maintains a single plain‑text mirror of its daily context for summarization and review.

- File path: `memory/{project}/daily.txt` (one file per project; no date‑based rotation)
- Source of truth & flow:
  - Working chat history is persisted in the database (`ChatMessage`) per project.
  - When a user→assistant pair rolls off the working set, and the assistant’s `forget` flag is false, the pair is:
    - Appended to `daily.txt` as a text block
    - Added to the daily FAISS index under `memory/{project}/daily_faiss/`
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
- Purpose:
  - Human‑readable backup of the daily FAISS index (`memory/{project}/daily_faiss/`).
  - Input source for future summarization and pruning logic.
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
  - Frontend shows overlay modal: “Morpheus is sleeping — consolidating memory. Please wait…”
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
- `daily.txt` is generated/updated automatically and mirrors `daily.faiss` content.
- “Forget” toggles correctly prevent a chat pair from being embedded or written to daily memory.
- System enters “sleeping” state when `/sleep/start` is called:
  - API returns **423 (Locked)** during the cycle.
  - UI overlay displayed until lock is released.
- Logs show clean sleep engagement/release timestamps.
- Markdown/code rendering works across chat messages.
- No blocking issues or schema changes introduced.


## Version 2.8 — Default Global RAG File

### Purpose
Ensure every new project starts with a consistent baseline of Morpheus system knowledge, even if the user never uploads any files.  
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
This version transforms Morpheus from a reactive chat system into one that maintains knowledge over time, preparing the foundation for **Version 4 — Dreaming**.

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
  - Perform the existing V2.x daily backfill behavior (for each project: if `daily.txt` is missing and `daily.json` exists, write `daily.txt` from metadata). Log count in `[SLEEP] Completed (updated_projects=N)`.
  - Sleep for ~60 seconds to simulate the maintenance window (testing aid).
  - Log `[SLEEP] Completed`.
- On any exception, log `[SLEEP][ERROR]` and release the lock.

#### FR-3.1.4 — Logging
- Mandatory log sequence for every run:
  `[SLEEP] Lock engaged → [SLEEP] Thread started → [SLEEP] Completed → [SLEEP] Lock released`.

---

### Acceptance Criteria
- Scheduler fires automatically at the configured local hour and can be triggered manually via `/sleep/start`.
- Lock file is created and removed correctly; all non-GET endpoints return `HTTP 423` during the lock window (≈60s).
- Logs show the complete `[SLEEP]` sequence from start to finish, including the updated_projects count in the Completed message when backfill runs.
- Daily backfill (only if `daily.txt` is missing and `daily.json` exists) executes inside the sleep window; no summarization or RAG rebuilds occur in 3.1.


## Version 3.2 — Daily Summarization Pipeline

### Overview
Version 3.2 extends the Sleep Cycle to perform nightly consolidation of daily memory.  
Each project with a valid `daily.txt` is pruned and reformatted into a structured summary file (`sleep_summary.txt`).  
This lays the groundwork for 3.3, which will rebuild the project RAG from these summaries.

---

### Purpose
Automate the transformation of each project's `daily.txt` into a structured long-term memory file using a two-step summarization process (Pruning → Formatting).

### Functional Requirements

#### FR-3.2.1 — Project Scan
- During the sleep thread (after lock engaged), iterate through all `memory/{project}/` directories.
- If `daily.txt` exists and is non-empty → process it.
- Else, log `[SLEEP] Skipped project (no daily.txt)`.

#### FR-3.2.2 — Pruning Stage
- Apply `generate_pruning_prompt(daily.txt)` using the LLM interface.
- Output `memory/{project}/pruned.txt`.
- Preserve all header lines, decisions, timestamps, and references.
- Log `[SLEEP][PRUNE] Completed project={id}` with size/line count.

#### FR-3.2.3 — Formatting Stage
- Apply `generate_formatting_prompt(pruned.txt)` to structure content into topic sections with metadata and appendices.
- Output `memory/{project}/sleep_summary.txt`.
- Log `[SLEEP][FORMAT] Completed project={id}`.

#### FR-3.2.4 — Cleanup and Archival
- Optionally remove intermediate files after verification (initially commented out for testing).

Example code block (commented):
```python
# import os
# try:
#     os.remove(f"memory/{project}/daily.txt")
#     os.remove(f"memory/{project}/pruned.txt")
#     logger.info(f"[SLEEP][CLEANUP] Removed daily.txt and pruned.txt for project {project}")
# except Exception as e:
#     logger.warning(f"[SLEEP][CLEANUP][ERROR] {e}")
```
- Keep `sleep_summary.txt` for verification and later RAG rebuild (3.3).
- Log `[SLEEP] Consolidation complete for {id}`.

#### FR-3.2.5 — Logging
- Mandatory log chain per project:
  `[SLEEP] Lock engaged → [SLEEP][PRUNE] → [SLEEP][FORMAT] → [SLEEP] Completed → [SLEEP] Lock released`.
- On exceptions, log `[SLEEP][ERROR] project={id}` and continue to next project.

---

#### FR-3.2.6 — Daily File BEGIN/END Tags
- When `daily.txt` is first created for a project, write a file header:
  ```
  === BEGIN DAILY MEMORY: MM/DD/YYYY ===
  ```
  (Local date; followed by a blank line.)
- Immediately before the pruning stage runs during the sleep cycle, append a closing tag ONLY to the in‑memory content sent to the LLM (do not persist back to `daily.txt`):
  ```
  === END DAILY MEMORY: MM/DD/YYYY ===
  ```
  (Local date; surrounded by blank lines.)
- The BEGIN/END tags bracket the daily memory window for clearer summarization context, without altering the on‑disk daily file beyond the first‑write header.

### Acceptance Criteria
- Each project with a `daily.txt` produces `pruned.txt` and `sleep_summary.txt`.
- Skipped projects are logged clearly.
- Lock and thread behavior remain identical to 3.1.
- Logs show `[PRUNE]` and `[FORMAT]` entries for each processed project.
- Cleanup code for `daily.txt` and `pruned.txt` is present but commented out until verified.
- No RAG rebuild yet — only summarization and cleanup verified.


## Version 3.3 — RAG Rebuild and Verification

### Overview
Version 3.3 completes the Sleep Cycle by merging the newly generated `sleep_summary.txt` from 3.2 directly into the project’s long-term memory and rebuilding the FAISS index immediately—no directory rescan required.

---

### Purpose
Finalize nightly memory consolidation by updating each project’s RAG index using the freshly formatted, tagged, and delimited `sleep_summary.txt`.

### Functional Requirements

#### FR-3.3.1 — Immediate Merge Trigger
- Executed directly after `sleep_summary.txt` is written during the same sleep thread.
- For each processed project, confirm that:
  - `sleep_summary.txt` exists.
  - File size > 0 bytes.
- Log `[SLEEP][MERGE] Initiating RAG update for {project}`.

#### FR-3.3.2 — Append to Long-Term Summary
- Append the existing, pre-delimited `sleep_summary.txt` to a persistent cumulative file:  
  `memory/{project}/uploads/sleep_summary_all.txt`
- Append the entire file verbatim (including `=== BEGIN/END DAILY MEMORY ===` tags).
- If the cumulative file does not exist, create it and write the new content. On first create only, prepend a single header line `#source: sleep_summary` and never duplicate it on later appends.
- Insert two newlines between appended summaries for readability.
- If the cumulative file already exists but is missing the `#source: sleep_summary` header, leave it as-is (do not retroactively modify).
- Guard appends with a per-project file lock: `memory/{project}/merge.lock` (covers append+rebuild for that project).
- Log `[SLEEP][MERGE] Appended summary to uploads/sleep_summary_all.txt`.

#### FR-3.3.3 — Trigger RAG Rebuild
- Immediately call:
  ```python
  rebuild_rag(project_id)
  ```
- Use the same function used by the file-upload route; rebuild the entire uploads index (full rebuild).
- Wait for completion (synchronous for prototype).
- Log `[MERGE] RAG rebuild complete for {project}`.

#### FR-3.3.4 — Optional Verification
- Controlled by env `VERIFY_RAG` (default: true). If enabled, run `verify_rag(project_id)` to confirm:
  - `index.faiss` and `index.json` exist and timestamps updated.
  - Vector count > 0.
- Log `[VERIFY] OK {project}` or `[VERIFY][ERROR]`.

#### FR-3.3.5 — Cleanup
- Delete `sleep_summary.txt` only when append + rebuild + (verify if enabled) all succeed.
- If append succeeds but rebuild fails, leave `sleep_summary_all.txt` as-is, keep `sleep_summary.txt` for retry next cycle, and log an error.
- If `sleep_summary.txt` is empty or contains only boundary tags, skip append/rebuild and log a warning (`[SLEEP][MERGE] Skipped (empty)`).
- Retain `sleep_summary_all.txt` in uploads for historical context.
- Log `[SLEEP][CLEANUP] Removed individual summary for {project}`.

#### FR-3.3.6 — Logging
Required sequence for each project:
```
[SLEEP][MERGE] Initiating RAG update
[SLEEP][MERGE] Appended summary
[MERGE] RAG rebuild complete
[VERIFY] OK
[SLEEP][CLEANUP]
```

---

### Acceptance Criteria
- After each sleep cycle, `sleep_summary.txt` is appended to `uploads/sleep_summary_all.txt`.
- The project’s FAISS index rebuilds immediately.
- Optional verification passes (when `VERIFY_RAG=true`).
- All actions occur within the same sleep cycle (no rescan).
- Log chain completes without errors.

Implementation Notes
- 3.3 runs per project immediately after 3.2 formatting within the same sleep thread. If 3.2 fails for a project, skip 3.3 for that project and continue others; log the skip.
- `sleep_summary_all.txt` may contain multiple BEGIN/END pairs over time; this is expected and desired (append verbatim without normalization).


## Version 3.4 — Rolling Context Tagger

### Overview
Extend the daytime “Awake Phase” to semantically tag each chat pair as it rolls off the active context buffer.  
Tags are embedded into the daily vector text for improved retrieval; `daily.txt` remains unchanged.

---

### Purpose
Automate lightweight tagging of prompt/response pairs in real time using the model defined by `BUILDER_MODEL`.  
The tags enrich the text stored in `daily_faiss`, improving daily retrieval quality immediately.

### Functional Requirements

#### FR-3.4.1 — Trigger
- When the deque exceeds `CHAT_HISTORY_LIMIT_PAIRS`, the oldest complete pair is rolled off.  
- Before embedding into `daily_faiss`, run the tagger.

#### FR-3.4.2 — Tagging Prompt
For each rolled-off pair (optionally including the previous pair for brief context), call `BUILDER_MODEL` with a short prompt targeting a compact response:

```
Classify this exchange for memory tagging.
Return 1-3 metadata lines only in this format:
#topics: <keywords>
#intent: <purpose>
#type: <category such as technical, design, story, system, etc.>
```

Constraints:
- Keep response minimal (≈ 3 short lines), fast (small tokens), and deterministic (temperature ~ 0).
- Timeout budget is small; if exceeded, skip tags (see Fail‑Safe).

#### FR-3.4.3 — Integration (Vectors Only)
- Do not modify `daily.txt` formatting. Keep the current V3.2 block format.
- Prepend the returned lines to the text that is embedded into `daily_faiss` only:
  ```
  #topics: …
  #intent: …
  #type: …
  User: …
  Assistant: …
  ```
- Optionally store the parsed fields in `daily.json` for analytics/backfill as:
  `tags_meta: { topics, intent, type }` (optional).

#### FR-3.4.4 — Fail‑Safe
- On timeout/error/invalid output, log `[TAGGER][WARN] …` and embed the original pair text unmodified (no tags).

#### FR-3.4.5 — Logging
- On success, log `[TAGGER] topics=…, intent=…, type=…` (truncate fields in logs for brevity).

---

### Acceptance Criteria
- >90% of daily_faiss vectors for rolled‑off pairs include the three tag lines.
- Daily retrieval quality measurably improves (qualitative check acceptable for V3).
- Tags survive the daily retrieval path (as they are part of the embedded text).
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

Version 4.0 introduces the Dream Cycle as a new phase executed after the Sleep Cycle. Dreaming is responsible for analyzing the consolidated memory artifact sleep_summary.txt and producing structured insight outputs. Version 4.0 does not implement research or multi agent reasoning. It establishes the conceptual boundaries for Dream, introduces the Dream Orchestrator, and prepares the system for extension in Version 4.1 and beyond.

Goals of Version 4.0:

* Define Dream as a post Sleep maintenance phase.
* Introduce the Dream Orchestrator as the execution space for nightly agents.
* Ensure Dream runs under controlled conditions without modifying sleep_summary.txt.
* Establish dream.txt as the unified nightly output file.
* Provide the user GUI element Analyze Dreams when dream.txt has content.

---

# Version 4.1 Requirements

## 4.1.1 JSON Extraction of Open Questions

* Sleep must generate a fully formatted sleep_summary.txt file that contains a final `[Open Questions]` appendix with a JSON object.
* The JSON object must include a field "questions" which is a list of objects, each containing:

  * question
  * topic
  * resolution
* The formatting prompt must filter out all questions with resolution set to "ignore" before returning the JSON.
* Dream Orchestrator Integration (4.1.1 scope):
  * Executor lifecycle:
    * Create a single ThreadPoolExecutor at backend startup only when `ENABLE_DREAM=true`.
    * Size is `MAX_WORKERS` (env), default 1. Reuse for all Dream tasks.
    * On FastAPI shutdown, drain and `shutdown(wait=True, cancel_futures=True)`.
  * Submission timing:
    * For each project, after Sleep finishes formatting and the RAG merge/cleanup sequence (3.3) completes for that project, submit the Dream task for that project and block on `future.result()` before proceeding. Sleep must hold the maintenance lock until all submitted Dream tasks for that project complete.
  * Inputs:
    * Pass `(project_id, sleep_summary_text)` to Dream. Sleep must write `sleep_summary.txt` to disk first, then submit the in‑memory string (no read‑back).
    * If the disk write fails, skip Dream for that project and log a warning.
  * Behavior in 4.1.1 (no persistence yet):
    * Run the Open Questions Agent against `sleep_summary_text`.
    * Do not write any Dream output files in 4.1.1 (no `dream_work/open_questions.json`, no `dream.txt`).
    * Log only a summary of the agent output: first 250 characters of the returned JSON string.
    * If the agent returns invalid JSON or an empty payload, treat as zero questions and log at WARNING level (no retries).
    * Implement `GET /dream/status` now, returning HTTP 200 with `{ "has_dreams": false, "count": 0 }` regardless of state in 4.1.1 (stub for UI integration). When `ENABLE_DREAM=false`, return the same stubbed payload.
    * Do not implement `GET /dream` in 4.1.1 (deferred).
  * Lock/idempotency:
    * Keep existing Sleep idempotency: if Sleep is already running, further triggers are skipped; Dream is never double‑enqueued.
  * No RAG retrieval in 4.1.1:
    * Dream must not perform RAG lookups in this version (added in later 4.x).
  * Logging:
    * `[DREAM] Start project=...`
    * `[DREAM] Completed project=... duration=...s`
    * `[DREAM] All agents complete for project=...`
    * `[DREAM][WARN] ...` for invalid/empty output; `[DREAM][ERROR] ...` for execution errors
    * Log only a 250‑char preview for large payloads.
* Feature flags and model:
  * `ENABLE_DREAM` (default: true). When false, do not create the executor and skip Dream entirely.
  * `MAX_WORKERS` (default: 1) controls executor size.
  * Agent LLM binding uses the OpenAI Responses API with `gpt-5.1` at `temperature=1.0`.
* Dream must not modify the RAG or sleep_summary.txt in Version 4.1.1.
* sleep_summary.txt must not be deleted until Dream has finished the extraction/logging step for that project.

# Version 4.1.2 Requirements

## Open Questions Dream Agent (RAG Answer Generation)

Version 4.1.2 introduces the first functional Dream Agent. This agent processes the structured open questions extracted in Version 4.1.1 and generates answers by combining project RAG context with a single LLM prompt per question.

---

## Scope and Preconditions

* Version 4.1.1 is complete and Dream already receives `(project_id, sleep_summary_text)` from Sleep.
* `sleep_summary.txt` contains a valid `[Open Questions]` JSON block with a `questions` list of `{ question, topic, resolution }` objects.
* Questions with `resolution="ignore"` have already been filtered out by Sleep formatting.
* No GUI changes are implemented in 4.1.2.

---

## Dream LLM and Research Abstraction

* Dream must not use the existing LangChain based `llm.py`.
* Create `backend/app/core/dream_llm.py`:

  * Thin wrapper over the OpenAI Responses API.
  * Must expose a function such as `dream_llm_call(prompt: str, max_output_tokens: int) -> str`.
  * Uses environment variables:
    * `DREAM_MODEL` (default: `gpt-5.1`)
    * `DREAM_TEMPERATURE` (default: `1.0`)
    * `DREAM_MAX_TOKENS` (default: `32000`)
    * `DREAM_ENABLE_REMOTE_RESEARCH` (default: `true`)
    * `DREAM_REMOTE_CONTEXT_MAX_TOKENS` (default: `32000`, tokens; use tiktoken to count/trim)
    * `DREAM_TOPIC_BOOST` (default: `1.5`)
* Create `backend/app/core/dream_prompts.py`:

  * Contains pure functions for building Dream prompts.
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

  * Contains higher level helpers using `dream_llm.py`, `dream_prompts.py`, and `rag_manager`.
  * Must expose: `run_open_question_pipeline(project_id: str, question: str, topic: str, resolution: str) -> Dict[str, Any]`.
  * If `resolution="remind_user"`, no LLM call is needed.
  * If `resolution="answer_local"`, fetch RAG context and run a single LLM answer prompt.
  * If `resolution="answer_remote"`, fetch RAG context and include optional remote research via the OpenAI web_search tool (enabled only when `DREAM_ENABLE_REMOTE_RESEARCH=true`).

---

## RAG Usage

* Dream must use `rag_manager.retrieve_context(...)` for all local memory retrieval.
* `retrieve_context` must be called with:

  * `project_id` set to the active project.
  * `query` set to the question text.
  * Other parameters set via existing RAG settings (reuse `rag_top_k`, `rag_snippet_max_tokens`, `rag_score_threshold`, `rag_context_max_tokens`).
  * Provide topic‑aware hints:
    * `route_namespaces=[topic]`
    * `namespace_boost=DREAM_TOPIC_BOOST` (default: 1.5)
* RAG is read only during Dream.
* Dream must not rebuild or write any RAG data.

---

## Per Question Processing Pipeline

* For each `{ question, topic, resolution }` in the Open Questions JSON:

  * If `resolution="remind_user"`:

    * Produce `{ "question": ..., "topic": ..., "answer": "User input required" }`.
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

## Output Format (dream.txt)

Dream must write `memory/{project}/dream.txt` containing:

```
[Open Questions]
{
  "questions": [
    { "question": "...", "topic": "...", "answer": "..." },
    ...
  ]
}
```

* The `questions` list must contain one entry per processed open question.
* Preserve original `question` and `topic` strings exactly.
* Include an `answer` field with the generated answer text.
* Keys must be lowercase (`question`, `topic`, `answer`). Do not include extra fields in `dream.txt` (citations, confidence, etc., are not written to this file in 4.1.2).
* If no valid entries exist, write an empty list:

```
[Open Questions]
{ "questions": [] }
```
* Overwrite `dream.txt` each run. Encoding: UTF‑8 with LF; newline‑terminated. Guard writes with a per‑project file lock (`memory/{project}/dream.lock`).

---

## Threading and Executor Behavior

* `MAX_WORKERS` controls the number of concurrent Dream tasks across projects.
* Sleep must submit at most one Dream task per project and block until completion.
* Inside a single Dream task, all questions are processed sequentially in 4.1.2.
* Dream tasks must treat RAG as read only.
* Dream tasks must not read or write data belonging to other projects.

---

## Logging and Error Handling

* Log per project:

  * `[DREAM] Start project=...`
  * `[DREAM] Completed project=... duration=...s count=...`
  * `[DREAM] All agents complete for project=...`
* Log per question (success):
  * `[DREAM] Q answered question="<trimmed 120>" preview="<answer[:250]>" used_remote_research=<true|false> tokens(local=X, remote=Y, combined=Z)`
* On invalid JSON:

  * `[DREAM][WARN] project=... question=... invalid answer JSON`
* On RAG retrieval failure:

  * `[DREAM][WARN] project=... question=... RAG retrieval failed; continuing with empty local context`
* Failures in one question must not stop processing of others.

---

## Memory Integration Constraints (4.1.2)

* Dream must not modify `sleep_summary.txt`.
* Dream must not modify or rebuild RAG.
* Dream must not write `dream_accepted.txt` or `dream_all.txt` in this version.
* User review and long term memory integration begin in 4.2.
* `/dream/status` remains a stub returning `{ "has_dreams": false, "count": 0 }` in 4.1.2 (GUI integration in 4.2).
