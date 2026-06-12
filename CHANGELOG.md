# Changelog

All notable changes to Syx will be documented in this file.

This project uses `CHANGELOG.md` for release-by-release summaries. Longer
narrative release notes can be added separately later if a release needs more
context than this format should carry.

## 0.1.0 - Initial Public Release - 2026-06-12

### Added

- React + Vite chat interface served by a FastAPI backend as a single local web
  app.
- Project-scoped chat, uploads, memory artifacts, SQLite persistence, and
  static frontend deployment from the backend.
- Provider-based LLM and embedding configuration through environment variables,
  including builder, tagger, chat, Dream, and embedding model settings.
- File upload and RAG flow for `.txt` and `.md` documents using FAISS
  indexes and project-scoped storage.
- Daily memory lifecycle for rolling older chat context into durable,
  human-readable project memory.
- Markdown-based generated memory artifacts for Daily, Sleep, and Dream memory,
  including Syx entry boundaries and metadata suitable for human review and
  agent-readable retrieval.
- Sleep cycle for flushing active chat pairs, consolidating Daily memory into
  per-cycle long-term artifacts, rebuilding FAISS, verifying indexes, cleaning
  staging artifacts, and managing a global sleep lock.
- Experimental Dream cycle for post-Sleep question handling, context building,
  idea generation, research synthesis, optional auto-accept, and Dream memory
  artifact generation.
- Local read-only agent memory search endpoint and CLI tooling for trusted
  coding-agent workflows.
- Instrumentation support for collecting structured timing, token, and pipeline
  metrics during chat and internal helper-model calls.
- Docker and Docker Compose support with bind-mounted data, runtime, and
  environment configuration.
- Automated backend and frontend test coverage, plus documented coverage policy
  for behavior-focused tests and deterministic background work.

### Security

- Documented local/trusted-environment assumptions, secret-handling
  expectations, generated-data sensitivity, and current agent-token limitations.
- Explicitly documented that Syx is not production-hardened and should not be
  exposed directly to the public internet or untrusted users.
