# Syx

[![CI](https://github.com/cjsthecoder/project_syx/actions/workflows/ci.yml/badge.svg)](https://github.com/cjsthecoder/project_syx/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-0.1.0-blue)](https://github.com/cjsthecoder/project_syx/releases)
[![Python](https://img.shields.io/badge/python-3.13-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Experimental local AI memory system for long-running projects, RAG-backed chat, sleep-cycle consolidation, dream-cycle synthesis, and read-only coding-agent memory access.

> [!WARNING]
> Syx is a research prototype intended for local or trusted environments. It is not production-hardened. Do not expose it directly to the public internet or to untrusted users.
>
> Memory artifacts, uploaded files, chat history, logs, and agent query results may contain sensitive information.

## Background & Project Story

Syx started as an idea about AI memory and became a working local prototype through an AI-assisted engineering process. For the narrative path from concept to implementation, see [Project History](docs/background/Project_History.md). For how requirements, deltas, and AI coding agents were used to build it, see [AI-Assisted Engineering](docs/ai_assisted_engineering.md).

## What It Is

Syx is a modular AI chat and memory framework with a React web interface, a FastAPI backend, provider-selectable LLM and embedding factories, project-scoped file upload, FAISS-backed retrieval, and a memory lifecycle that moves from active chat context into durable project memory.

At a high level, Syx is built around:

- A web-based chat interface for project-aware conversations.
- Configurable LLM and embedding providers.
- Project-specific uploads and FAISS-backed retrieval.
- Daily memory that captures rolled-off chat context.
- Sleep cycles that consolidate memory into long-term artifacts.
- Experimental Dream cycles that synthesize unresolved questions and higher-level insights after Sleep.
- Markdown memory artifacts intended for human review, git diffing, and agent-readable context.
- A local read-only agent-memory interface for trusted tools that need project context.

## Why This Approach

Syx is opinionated. It is not meant to replace every RAG tool, vector database, note-taking system, or agent framework.

The core idea behind Syx is that long-running AI project memory needs more than a place to store embeddings. In my experience building and using this project, the most useful behavior came from preserving months of project-specific conversations, decisions, corrections, and abandoned paths, then making that history available again when needed.

That experience shaped the design. Syx treats memory as a lifecycle:

* active chat context
* rolled-off Daily memory
* durable markdown artifacts
* Sleep-cycle consolidation
* long-term RAG retrieval
* Dream-cycle synthesis
* agent-readable memory access

Other systems may focus on larger context windows, vector search, file-based note organization, summarization, agent orchestration, or chat UI. Those are all useful pieces. Syx is focused on testing a different idea: long-running project memory needs a lifecycle.

In my experience using long project chats, the power of accumulated context is real. But long context is not the same thing as durable memory. As a project grows, important decisions can be buried, old assumptions can linger, useful details compete with noise, and the model may not reliably know which parts of the history still matter.

Syx treats that as a memory lifecycle problem, not only a context-size problem. It explores how durable project memory can be captured, consolidated, searched, reviewed, and eventually maintained over time.

This is still a research prototype, and these are design opinions rather than claims that Syx is the only right approach. The goal is to make those ideas concrete enough to test.

## Mission

Syx explores AI memory as a lifecycle, not just a vector search problem.

The project is a local research prototype for long-running AI project memory: active context, daily memory rolloff, long-term retrieval, sleep-cycle consolidation, dream-cycle synthesis, markdown memory artifacts, and read-only memory access for coding agents.

The goal is not to claim that Syx is AGI or production-ready software. The goal is to test practical ideas about how AI systems can preserve, retrieve, consolidate, and refine context over time.

## Current Status

Syx is preparing for its initial open source release. It is an active software project and research framework, not a hosted product, production service, or finalized memory standard.

The repository currently includes the web app, backend API, project storage, upload/RAG flow, Daily memory, Sleep cycle, experimental Dream cycle, instrumentation support, Docker deployment, and automated backend/frontend tests.

## Quickstart

Use a local virtual environment to isolate Python dependencies.

```bash
# 1) Create venv (one time)
python3 -m venv venv

# 2) Activate it (each new shell)
source venv/bin/activate

# 3) Install backend dependencies
pip install -r requirements.txt

# 4) Install frontend dependencies
cd frontend && npm install && cd ..

# 5) Create or update local environment config
make setup-env

# 6) Add your OpenAI API key to .env
# OPENAI_API_KEY=your-openai-api-key-here

# 7) Build frontend and run the app
make build
make run
```

Open the app at `http://localhost:8000`.

API docs are available at `http://localhost:8000/api/docs`, and health checks are available at `http://localhost:8000/health`.

## Docker

Run Syx in a container with bind-mounted data and a mounted `.env` file. Secrets are not baked into the image.

```bash
# Prepare host directories for persistent data
make docker-setup

# Build and run
docker compose up -d
```

Data is stored on the host under `./data/memory`, `./data/db`, `./runtime/logs`, and `./runtime/runs`, so it survives container rebuilds and can be backed up separately.

## Configuration

Runtime defaults are defined in [`backend/app/core/config.py`](backend/app/core/config.py) through `Settings`. The `make setup-env` target mirrors those defaults when generating `.env`.

Start from [`.env.example`](.env.example), then set at least:

- `OPENAI_API_KEY`
- `LLM_PROVIDER`
- `MODEL_NAME`
- `LLM_MINI_MODEL`
- `BUILDER_MODEL`
- `TAGGER_MODEL`
- `DREAM_MODEL`
- `EMBEDDING_PROVIDER`
- `EMBEDDING_MODEL` or `SENTENCE_TRANSFORMERS_MODEL_ID`

For the full environment template, see [`.env.example`](.env.example). Runtime defaults are defined in [`backend/app/core/config.py`](backend/app/core/config.py).

## Core Concepts

- **Projects**: isolate chat history, uploaded files, memory artifacts, and retrieval indexes by project.
- **File Upload + RAG**: stores uploaded `.txt` and `.md` documents, chunks them, embeds them, and rebuilds a project FAISS index.
- **Daily Memory**: captures older chat turns as durable, human-readable project memory.
- **Sleep Cycle**: consolidates Daily memory into timestamped long-term artifacts and refreshes retrieval state.
- **Dream Cycle**: runs after Sleep to synthesize unresolved questions, research prompts, or higher-level insights.
- **Agent Memory Interface**: exposes local project memory search for trusted external agent tools.
- **AI-Assisted Engineering Process**: documents how requirements and deltas are used to keep AI-assisted implementation aligned with project intent.

## Architecture

Syx combines a Vite/React frontend with a FastAPI backend that serves both API routes and the built static frontend. The backend owns provider factories, project persistence, memory artifacts, RAG indexing, Sleep/Dream orchestration, instrumentation, and local agent-facing memory access.

See [`docs/architecture.md`](docs/architecture.md) for the full architecture guide.

## Documentation

Start with the onboarding and project docs:

- [`README.md`](README.md) — public landing page and quickstart.
- [`ROADMAP.md`](ROADMAP.md) — shipped scope, near-term work, later ideas, and non-goals.
- [`CHANGELOG.md`](CHANGELOG.md) — release history.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — local setup, testing, documentation, and PR expectations.
- [`SUPPORT.md`](SUPPORT.md) — questions, bug reports, feature requests, and support boundaries.
- [`SECURITY.md`](SECURITY.md) — vulnerability reporting and local/trusted-environment assumptions.
- [`docs/ai_assisted_engineering.md`](docs/ai_assisted_engineering.md) — how requirements and deltas guide AI-assisted development.

Architecture and memory-system guides:

- [`docs/architecture.md`](docs/architecture.md) — system architecture.
- [`docs/memory_lifecycle.md`](docs/memory_lifecycle.md) — chat, Daily memory, Sleep, Dream, and RAG artifact lifecycle.
- [`docs/sleep_cycle.md`](docs/sleep_cycle.md) — Sleep behavior, scheduling, locking, outputs, and verification.
- [`docs/dream_cycle.md`](docs/dream_cycle.md) — Dream behavior, generated outputs, and configuration.
- [`docs/agent_interface.md`](docs/agent_interface.md) — local agent-memory access.

Specification and testing references:

- [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) — consolidated as-built specification.
- [`docs/DELTAS.md`](docs/DELTAS.md) — active change layer for newer or superseding requirements.
- [`docs/COVERAGE.md`](docs/COVERAGE.md) — testing and coverage policy.

Background material:

- [`docs/background/Project_History.md`](docs/background/Project_History.md) — development history and original project essays.

## Repository Layout

```text
backend/app/              FastAPI backend, provider factories, memory, RAG, Sleep, Dream
frontend/                 React + Vite frontend
tests/                    Backend pytest suite
docs/                     Architecture, lifecycle, requirements, deltas, and public docs
tools/                    Local helper tools, including agent memory search tooling
data/                     Generated local database, memory, uploads, and FAISS data
runtime/                  Generated logs, run artifacts, and lock/state files
backend/app/static/       Built frontend assets served by FastAPI
```

Generated and local-only files should generally not be edited or committed:
`data/`, `runtime/`, `.env`, coverage outputs, debug artifacts, generated memory
artifacts with private content, and built static assets unless a release process
or maintainer explicitly requires them.

## Development

Run backend tests:

```bash
make test
```

Run frontend tests:

```bash
make test-frontend
```

Run the full CI-style check locally:

```bash
make ci
```

For coverage expectations and test-writing policy, see [`docs/COVERAGE.md`](docs/COVERAGE.md).

## Security

Syx is designed for local development and trusted local deployments. Do not commit `.env`, API keys, generated memory, runtime logs, or private project data.

See [`SECURITY.md`](SECURITY.md) for vulnerability reporting and current security assumptions.

## Contributing

Contributions should follow the repository setup, testing, documentation, and secret-handling rules.

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Support

See [`SUPPORT.md`](SUPPORT.md) for how to ask questions, report bugs, or request features.

## Roadmap

See [`ROADMAP.md`](ROADMAP.md) for shipped scope, near-term work, future ideas, and non-goals.

## License

MIT — see [`LICENSE`](LICENSE).
