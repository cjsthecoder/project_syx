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

#### FR-2.3-1 — Rolling Window by Pair Count
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

#### FR-2.3-2 — Incremental Embedding → Daily FAISS
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

#### FR-2.3-5 — Environment Variables

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

#### FR-2.3-6 — UI Integration
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

FR-2.3.1-1 — Mini Model Router + Query Builder
• Introduce a lightweight LLM call (builder_llm) before retrieval.
• Input: 3–4 sentence summary of all in‑memory pairs (not rolled off) + current user turn.
• Output (JSON): route, rag, standalone, paraphrases, hyde, entities, topics, reason, confidence.
• Example schema:
{ "route":"CHITCHAT|CODE|DOCS|OTHER", "rag":true, "standalone":"", "paraphrases":[], "hyde":"", "entities":[], "topics":[], "reason":"", "confidence":0.0 }
• Use `BUILDER_MODEL` over the same OpenAI channel as chat; no extra latency/budget constraints beyond `BUILDER_MAX_TOKENS`.

FR-2.3.1-2 — Routing Logic
• If rag=false or route="CHITCHAT", skip retrieval and reply directly via chat model (still include in‑memory history).
• Else embed standalone + 2–3 paraphrases + 1 HYDE and run topic‑aware RAG lookup.
• If `confidence < BUILDER_CONFIDENCE_MIN`, perform conservative retrieval (standalone only; skip paraphrases/HYDE).
• If the builder fails/times out/returns invalid JSON: log a warning and skip RAG entirely (answer directly).

FR-2.3.1-3 — Topic and Entity Extraction
• Builder emits topics and entities.
• Sidecar metadata for main RAG: store per‑chunk metadata in `memory/{project}/faiss/meta_topics.json`, keyed by FAISS docstore ID (no full re‑index now). Merge sidecar with existing metadata during retrieval/rerank.
• Biasing:
– Exact match boost if topic appears in sidecar (#topics).
– Partial/semantic boost via embedding similarity of topic terms (with in‑memory per‑project topic vector cache, LRU + TTL ~24h, max ~500 entries).

FR-2.3.1-4 — Metadata-Aware Reranking
• After cosine retrieval, adjust scores multiplicatively (topic → decision → open_question), then clamp to 1.0 before sorting/truncation.
• Then apply token budget.
• Optional ENV weights:
TOPIC_BOOST=1.10
DECISION_BOOST=1.05
QUESTION_BOOST=1.02

FR-2.3.1-5 — Query Expansion and Namespacing
• Route selects a preferred namespace (e.g., "jira", "code", "docs").
• Always search full corpus; strongly boost routed namespace (no hard filter).
• Maintain file→namespace sidecar `memory/{project}/faiss/meta_namespaces.json`; default namespace "other" for unmapped; include "other" when route unknown.
• Embed variants with optional prefix “query:”; include topic/entity terms for hybrid search.

FR-2.3.1-6 — Prompt Template (for Builder)
System: “You are a fast query builder and router for RAG. Return strict JSON. No prose.”
User: “Recent summary: {history} Turn: {user_text}”
Rules:
• If small-talk/joke/meta → route=CHITCHAT, rag=false.
• Else choose domain route and return concise rewritten query set plus topics/entities.

FR-2.3.1-7 — Retrieval Order and Context Assembly
• Daily results queried and filled first (up to DAILY_RAG_MAX_TOKENS).
• Main RAG fills remaining context budget (RAG_CONTEXT_MAX_TOKENS).
• Label sections clearly in prompt:
Context:
--- Daily:
<daily snippets>
--- Main:

<main snippets> • Deduplicate exact and near‑duplicates (cosine ≥ 0.98) after merging daily+main and before token budgeting.

FR-2.3.1-8 — Environment Variables
BUILDER_MODEL=gpt-4o-mini
BUILDER_CONFIDENCE_MIN=0.75
BUILDER_MAX_TOKENS=512
BUILDER_CACHE=True
TOPIC_BOOST=1.10
DECISION_BOOST=1.05
QUESTION_BOOST=1.02
DEDUPE_SIMILARITY_THRESHOLD=0.98

FR-2.3.1-9 — Logging / Debug Visibility
• Log builder JSON into the existing app log (no separate file), including timestamp, route, rag, confidence, topics, and trimmed standalone; tag lines clearly (module logger/type="builder").
• Log applied topic/decision/open_question boost values during reranking.
• Optionally display route and confidence in chat UI for debug.

FR-2.3.1-10 — Concurrency and Locking
• Use a single `faiss.lock` for FAISS and sidecar metadata reads/writes under `memory/{project}/faiss/`; keep locks short‑lived.

FR-2.3.1-11 — Builder Cache
• If `BUILDER_CACHE=True`, cache builder JSON in memory per process with TTL ≈ 10 minutes and max ≈ 500 entries; key by `(project_id, history_summary, user_turn)`; no disk persistence.

Acceptance Criteria

• Builder invoked on every turn and returns valid JSON.
• Non-RAG turns bypass retrieval entirely.
• RAG turns use rewritten queries and topic/entity expansion.
• Topic/decision/open_question boosts reflected in scores and logs; boosted scores clamped to 1.0.
• Context assembled as “Daily:” then “Main:”.
• Performance target: ≤ 800 ms avg builder latency.

