Project Overview

Morpheus is a modular system that provides a web-based chat interface backed by a FastAPI server and LangChain for LLM integration.
Version 1 Goal: Establish a working chatbot with a GUI and stable backend interfaces that can be extended later with RAG, memory pruning, and multi-project support.

Core Functional Requirements
1. Chat Interface (FR-001)

Priority: High

Requirement: Provide a web-based chat UI for user ↔ AI interaction.

Frontend: Built in React with Shadcn/UI.

Features:

Message history displayed in chat bubbles.

Input box for sending messages.

Basic UI controls for triggering stubbed actions (query_rag, switch_project).

Success Criteria: User can hold a conversation with the chatbot via the web UI.

2. Chat Endpoint (FR-002)

Priority: High

Requirement: Backend endpoint for handling user messages.

Implementation: FastAPI /chat route.

Flow:

Receive message → Forward to LangChain LLM → Return response.

Validation: Must return a valid response for every valid request.

Success Criteria: End-to-end chat works (UI → FastAPI → LangChain → UI).

3. LangChain Integration (FR-003)

Priority: High

Requirement: Use LangChain as the abstraction layer for LLM providers.

Default Provider: OpenAI GPT-4o-mini.

Future Proofing: Should support Anthropic, LLaMA, etc. with minimal change.

Success Criteria: Responses are generated via LangChain ChatOpenAI interface.

4. Stubbed Feature Hooks (FR-004)

Priority: Medium

Requirement: Provide backend routes for future functionality.

Endpoints:

/query_rag → currently returns “RAG not implemented.”

/projects → list/switch projects (stub).

/sleep_cycle → trigger pruning job (stub).

Success Criteria: Stubs exist, return placeholder responses, and can be called from frontend buttons.

5. Project Awareness (FR-005)

Priority: Medium

Requirement: Define project-based separation of future memory indexes.

Implementation: Project ID included in requests (stub only in V1).

Success Criteria: API supports project context, even if unused in V1.

Technical Requirements
1. Backend (TR-001)

Priority: High

Framework: FastAPI with Uvicorn.

Endpoints: /chat, /query_rag, /projects, /sleep_cycle.

Response Format: JSON with {"response": "...text..."}.

Success Criteria: Stable backend routes with predictable JSON outputs.

2. Frontend (TR-002)

Priority: High

Framework: React + Shadcn/UI.

Features: Chat message list, input box, action buttons.

API Calls: Fetch from FastAPI endpoints.

Success Criteria: Chat UI responds to user input and displays backend replies.

3. LLM Provider (TR-003)

Priority: High

Interface: LangChain ChatOpenAI (default OpenAI).

Flexibility: Must support provider swap by config, not refactor.

Success Criteria: Swapping OpenAI → Anthropic requires minimal changes.

4. Configuration (TR-004)

Priority: High

Env Variables:

OPENAI_API_KEY (required).

MODEL_NAME (default: gpt-4o-mini).

Success Criteria: No API key leakage, flexible configuration.

5. Error Handling (TR-005)

Priority: Medium

Must handle API errors and invalid inputs gracefully.

Fallback: return error JSON with message instead of crashing.

Success Criteria: System never crashes on bad input or API errors.

Deployment Requirements
1. Virtual Environment Setup (DEP-000)

Priority: High

Requirement: Use Python virtual environment to isolate dependencies.

Instructions:

python -m venv venv
source venv/bin/activate   # macOS/Linux
venv\\Scripts\\activate    # Windows

Success Criteria: All Python dependencies installed inside venv without system pollution.

2. Installation (DEP-001)

Priority: High

Backend: pip install -r requirements.txt.

Frontend: npm install && npm run dev.

Success Criteria: System installs cleanly on macOS/Linux/Windows.

3. Platform Support (DEP-002)

Priority: Medium

Backend: Python 3.10+

Frontend: Node.js 18+

Success Criteria: Works across supported platforms.

Maintenance Requirements
1. Documentation (MAINT-001)

Priority: High

Requirements file (this document).

README with setup instructions.

Comments in code for major functions.

Success Criteria: Developer can set up and run system in <30 minutes.

Success Metrics

Chat Functionality: User can chat via UI and receive responses from OpenAI (via LangChain).

Stubbed Features: /query_rag, /projects, /sleep_cycle return placeholders without breaking.

Extensibility: Adding FAISS-based RAG in Version 2 requires no backend refactor, only filling in stub.

Future Enhancements

FAISS RAG Integration (Version 2).

Nightly pruning + sleep cycle (Version 3).

Multi-project memory management (Version 4).

Streaming responses in UI.

Cross-provider LLM swap (Anthropic, LLaMA, etc.).

Basic Structure to Follow

# Morpheus – REQUIREMENTS.md (Version 1)

## Project Overview

Morpheus is a modular system that provides a web-based chat interface backed by a FastAPI server and LangChain for LLM integration.
**Version 1 Goal**: Establish a working chatbot with a GUI and stable backend interfaces that can be extended later with RAG, memory pruning, and multi-project support.

---

## Core Functional Requirements

### 1. Chat Interface (FR-001)

**Priority: High**

* **Requirement**: Provide a web-based chat UI for user ↔ AI interaction.
* **Frontend**: Built in React with Shadcn/UI.
* **Features**:

  * Message history displayed in chat bubbles.
  * Input box for sending messages.
  * Basic UI controls for triggering stubbed actions (`query_rag`, `switch_project`).
* **Success Criteria**: User can hold a conversation with the chatbot via the web UI.

### 2. Chat Endpoint (FR-002)

**Priority: High**

* **Requirement**: Backend endpoint for handling user messages.
* **Implementation**: FastAPI `/chat` route.
* **Flow**:

  * Receive message → Forward to LangChain LLM → Return response.
* **Validation**: Must return a valid response for every valid request.
* **Success Criteria**: End-to-end chat works (UI → FastAPI → LangChain → UI).

### 3. LangChain Integration (FR-003)

**Priority: High**

* **Requirement**: Use LangChain as the abstraction layer for LLM providers.
* **Default Provider**: OpenAI GPT-5.
* **Future Proofing**: Should support Anthropic, LLaMA, etc. with minimal change.
* **Success Criteria**: Responses are generated via LangChain `ChatOpenAI` interface.

### 4. Stubbed Feature Hooks (FR-004)

**Priority: Medium**

* **Requirement**: Provide backend routes for future functionality.
* **Endpoints**:

  * `/query_rag` → currently returns “RAG not implemented.”
  * `/projects` → list/switch projects (stub).
  * `/sleep_cycle` → trigger pruning job (stub).
* **Success Criteria**: Stubs exist, return placeholder responses, and can be called from frontend buttons.

### 5. Project Awareness (FR-005)

**Priority: Medium**

* **Requirement**: Define project-based separation of future memory indexes.
* **Implementation**: Project ID included in requests (stub only in V1).
* **Success Criteria**: API supports project context, even if unused in V1.

---

## Technical Requirements

### 1. Backend (TR-001)

**Priority: High**

* **Framework**: FastAPI with Uvicorn.
* **Endpoints**: `/chat`, `/query_rag`, `/projects`, `/sleep_cycle`.
* **Response Format**: JSON with `{"response": "...text..."}`.
* **Success Criteria**: Stable backend routes with predictable JSON outputs.

### 2. Frontend (TR-002)

**Priority: High**

* **Framework**: React (built with Vite) + Shadcn/UI.
* **Build Tool**: Vite for fast build/dev times and clean setup.
* **UI Library**: Shadcn/UI installed manually via their CLI (modular, open source, no lock-in).
* **Features**: Chat message list, input box, action buttons.
* **API Calls**: Fetch from FastAPI endpoints.
* **Success Criteria**: Chat UI responds to user input and displays backend replies.

### 3. LLM Provider (TR-003)

**Priority: High**

* **Interface**: LangChain `ChatOpenAI` (default OpenAI GPT-5).
* **Flexibility**: Must support provider swap by config, not refactor.
* **Success Criteria**: Swapping OpenAI → Anthropic requires minimal changes.

### 4. Configuration (TR-004)

**Priority: High**

* **Env Variables**:

  * `OPENAI_API_KEY` (required).
  * `MODEL_NAME` (default: `gpt-5`).
* **Success Criteria**: No API key leakage, flexible configuration.

### 5. Error Handling (TR-005)

**Priority: Medium**

* Must handle API errors and invalid inputs gracefully.
* Fallback: return error JSON with message instead of crashing.
* **Success Criteria**: System never crashes on bad input or API errors.

### 6. Unified Deployment (TR-006)

**Priority: High**

* **Requirement**: Bundle React frontend into FastAPI for unified deployment.
* **Implementation**:
  * Build React app with `npm run build` (Vite)
  * Copy React's `dist/` output to FastAPI's `/static` folder
  * Configure FastAPI to serve static files and handle SPA routing
  * Single server deployment (FastAPI serves both frontend and backend)
  * Manual build process with make target for automation

* **Benefits**:
  * Simplified deployment (single server)
  * No CORS issues in production
  * Easier containerization and scaling
  * Single port for all services

* **Success Criteria**: 
  * FastAPI serves React app at root URL (`/`)
  * API endpoints accessible at direct paths (`/chat`, `/query_rag`, etc.)
  * React routing works with FastAPI catch-all route to `index.html`
  * Single command deployment (`python main.py`)

---

## Implementation Details

### Development Approach

* **Backend-First Implementation**: Start with FastAPI backend, then build React frontend
* **Production-Only Deployment**: No separate dev mode, unified FastAPI server
* **Core Functionality Focus**: Implement main features first, testing later
* **Environment Configuration**: Use `.env` template for configuration management

### Technical Stack Decisions

* **Frontend Framework**: React with Vite build tool
* **UI Library**: Shadcn/UI (installed via CLI for modularity)
* **API Structure**: Direct paths (`/chat`, `/query_rag`, `/projects`, `/sleep_cycle`)
* **Static File Serving**: FastAPI built-in with catch-all route in main.py
* **Build Process**: Manual with make targets for automation

### LangChain Integration

* **Implementation**: Full LangChain integration from start
* **API Key Management**: Environment variables (`OPENAI_API_KEY`)
* **Provider**: OpenAI GPT-4o-mini (default, configurable)
* **Configuration**: Environment-based with fallback defaults

### Build and Deployment

* **React Build**: `npm run build` (Vite) → `dist/` folder
* **Static Integration**: Copy `dist/` to FastAPI `static/` folder
* **Automation**: Make targets for build and deployment
* **Single Server**: FastAPI serves both API and React app

### Make Targets

* **`make install`**: Install all dependencies (Python + Node.js)
* **`make build`**: Build React app and copy to FastAPI static folder
* **`make run`**: Start the unified FastAPI server
* **`make clean`**: Clean build artifacts and dependencies

---

## Deployment Requirements

### 1. Virtual Environment Setup (DEP-000)

**Priority: High**

* **Requirement**: Use Python virtual environment to isolate dependencies.
* **Instructions**:

  ```bash
  python -m venv venv
  source venv/bin/activate   # macOS/Linux
  venv\\Scripts\\activate    # Windows
  ```
* **Success Criteria**: All Python dependencies installed inside venv without system pollution.

### 2. Installation (DEP-001)

**Priority: High**

* Backend: `pip install -r requirements.txt`.
* Frontend: `npm install && npm run dev`.
* **Success Criteria**: System installs cleanly on macOS/Linux/Windows.

### 3. Platform Support (DEP-002)

**Priority: Medium**

* **Backend**: Python 3.10+
* **Frontend**: Node.js 18+
* **Success Criteria**: Works across supported platforms.

---

## Maintenance Requirements

### 1. Documentation (MAINT-001)

**Priority: High**

* Requirements file (this document).
* README with setup instructions.
* Comments in code for major functions.
* **Success Criteria**: Developer can set up and run system in <30 minutes.

---

## Success Metrics

* **Chat Functionality**: User can chat via UI and receive responses from OpenAI GPT-5 (via LangChain).
* **Stubbed Features**: `/query_rag`, `/projects`, `/sleep_cycle` return placeholders without breaking.
* **Extensibility**: Adding FAISS-based RAG in Version 2 requires no backend refactor, only filling in stub.

---

## Future Enhancements

1. **FAISS RAG Integration** (Version 2).
2. **Nightly pruning + sleep cycle** (Version 3).
3. **Multi-project memory management** (Version 4).
4. **Streaming responses in UI**.
5. **Cross-provider LLM swap (Anthropic, LLaMA, etc.)**.

---

## Basic Structure to Follow

```
morpheus/
│
├── backend/                # FastAPI + LangChain backend
│   ├── app/
│   │   ├── main.py         # FastAPI entry point with static serving
│   │   ├── api/            # API route definitions
│   │   │   ├── __init__.py
│   │   │   ├── chat.py      # /chat endpoint with LangChain integration
│   │   │   ├── rag.py       # /query_rag endpoint (stub for V2)
│   │   │   ├── projects.py  # /projects endpoint (stub for V4)
│   │   │   └── sleep.py     # /sleep_cycle endpoint (stub for V3)
│   │   ├── core/           # Core logic and abstractions
│   │   │   ├── __init__.py
│   │   │   ├── llm.py       # LangChain ChatOpenAI wrapper
│   │   │   ├── memory.py    # Placeholder for FAISS + future RAG
│   │   │   ├── config.py    # Environment variable config loader
│   │   │   └── models.py    # Pydantic models for requests/responses
│   │   ├── utils/          # Shared utilities
│   │   │   ├── __init__.py
│   │   │   ├── logging.py   # Logging configuration
│   │   │   └── errors.py    # Error handling utilities
│   │   └── static/         # React build output (served by FastAPI)
│   │       ├── index.html   # React app entry point
│   │       ├── assets/      # React static assets (JS, CSS, images)
│   │       └── ...          # Other React build files
│   ├── tests/              # Unit tests
│   │   ├── __init__.py
│   │   ├── test_main.py     # FastAPI endpoint tests
│   │   ├── test_llm.py      # LangChain integration tests
│   │   └── test_models.py   # Pydantic model tests
│   ├── requirements.txt    # Python dependencies
│   └── README.md
│
├── frontend/               # React + Shadcn/UI frontend (development)
│   ├── src/
│   │   ├── components/     # Reusable UI components
│   │   │   ├── ui/          # Shadcn/UI components
│   │   │   │   ├── button.tsx
│   │   │   │   ├── input.tsx
│   │   │   │   ├── card.tsx
│   │   │   │   └── ...
│   │   │   ├── ChatBox.tsx  # Main chat interface
│   │   │   ├── MessageBubble.tsx # Individual message display
│   │   │   └── ActionButtons.tsx # query_rag, projects, sleep_cycle buttons
│   │   ├── pages/          # Page-level containers
│   │   │   └── Chat.tsx     # Main chat page
│   │   ├── hooks/          # Custom React hooks
│   │   │   ├── useChatAPI.ts # Chat API integration
│   │   │   ├── useProjects.ts # Project management
│   │   │   └── useRAG.ts    # RAG query integration
│   │   ├── api/            # API client
│   │   │   ├── client.ts    # FastAPI client configuration
│   │   │   ├── chat.ts      # Chat API calls
│   │   │   ├── rag.ts       # RAG API calls
│   │   │   ├── projects.ts  # Projects API calls
│   │   │   └── sleep.ts     # Sleep cycle API calls
│   │   ├── types/          # TypeScript type definitions
│   │   │   └── api.ts       # API response types
│   │   ├── App.tsx          # Main React app component
│   │   └── main.tsx         # React app entry point
│   ├── public/             # Static assets
│   │   ├── index.html       # HTML template
│   │   └── favicon.ico      # Site favicon
│   ├── dist/               # Vite build output (copied to backend/static/)
│   ├── package.json        # NPM dependencies
│   ├── vite.config.ts      # Vite configuration
│   ├── tsconfig.json       # TypeScript configuration
│   ├── tailwind.config.js  # Tailwind CSS configuration (for Shadcn/UI)
│   └── README.md
│
├── docs/                   # Documentation
│   ├── REQUIREMENTS.md     # Requirements file (living doc)
│   └── ARCHITECTURE.md     # High-level design and diagrams
│
├── venv/                   # Python virtual environment (ignored in git)
├── .env                    # Environment variables template
├── .env.example            # Environment variables example
├── Makefile               # Build automation targets
├── .gitignore
└── README.md               # Project overview
```
