# Roadmap

This roadmap describes the public direction for Syx at the time of the initial open source release. It is intentionally high level. Priorities may change as the project is tested by real usage, contributor feedback, and new research questions.

For how Syx uses [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) and [`docs/DELTAS.md`](docs/DELTAS.md) during AI-assisted development, see [`docs/ai_assisted_engineering.md`](docs/ai_assisted_engineering.md).

## Shipped Scope

The initial public release includes the core local Syx prototype:

* React + Vite chat UI served by a FastAPI backend.
* Project-scoped chat, uploads, memory artifacts, SQLite state, and FAISS indexes.
* Configurable LLM, helper-model, tagger, Dream, and embedding settings through `.env`.
* File upload and RAG indexing for `.txt` and `.md` documents.
* Daily memory for rolling older chat context into durable project memory.
* Markdown-based generated memory artifacts for Daily, Sleep, and Dream memory.
* Syx memory entry boundaries and metadata for agent-readable retrieval.
* Sleep cycle for flushing active chat, consolidating Daily memory, rebuilding long-term RAG, and cleaning staging artifacts.
* Experimental Dream cycle for post-Sleep questions, context building, idea generation, research synthesis, and optional memory acceptance.
* Local read-only agent memory search endpoint and CLI tooling.
* Instrumentation support for timing, token, and pipeline metrics.
* Docker and Docker Compose support for local containerized runs.
* Backend and frontend tests, coverage guidance, linting, formatting, and pre-commit configuration.

## Near-Term Work

These are the most likely next areas after the initial open source release:

* Optional Syx-format context pack installer that creates a local `Syx_Development` project, imports curated sanitized Syx project memory, builds RAG, and demonstrates project onboarding through Syx itself.
* Add additional LLM and embedding model options to the provider factory layer.
* Add support for more RAG file types.
* Improve ingestion processing, including metadata extraction, tagging, preprocessing, and file preparation.
* Explore drag-and-drop file support in the prompt window, similar to the ChatGPT web interface.
* Improve Dream review flows so generated Dream items are easier to inspect, accept, reject, and understand.
* Continue hardening generated markdown memory artifacts, entry boundaries, and full-entry expansion behavior.
* Improve local agent memory tooling around `POST /agent/memory/search` and the CLI wrapper.
* Tighten setup, Docker, and troubleshooting docs based on first-user feedback.
* Fix issues reported by users if the project receives outside use or feedback.

These items are near-term directions, not guaranteed release commitments.

## Active Delta Direction

Syx began as a chat memory system. The original goal was to preserve long-running project context across conversations, roll older chat turns into durable memory, consolidate that memory through Sleep, and make it searchable through RAG.

The current Delta-A work started by standardizing the memory artifact format. Generated memory artifacts now use markdown, stable source-neutral memory IDs, explicit Syx entry boundaries, structured metadata, and boundary-aware RAG indexing. That work makes memory entries more durable, inspectable, and usable by both humans and external tools.

While Syx was being built, coding agents became much more important in the broader AI tooling ecosystem. That shifted part of Delta-A toward agent-facing memory access. The first agent-facing step is implemented: Syx can expose project memory through a local read-only agent search endpoint and CLI bridge. This allows tools outside the application to retrieve prior project context without writing to memory or modifying project state.

The next agent-facing step would be controlled write-back, where an external agent could add implementation notes, decisions, test results, or open questions into Syx memory. Looking at that more closely made the underlying problem clearer: once agents can write, update, strengthen, weaken, summarize, or delete memory, the system is no longer only a RAG problem. It becomes a memory-identity, lifecycle, and relationship-management problem.

That likely points toward reshaping the backend memory model so memory entries have a stronger database-backed source of truth. Semantic search would still matter, but it would become one retrieval view over memory rather than the only structure. A database-backed memory layer could support both:

* graph-style relationships between memories, decisions, artifacts, agents, and projects
* semantic retrieval through RAG indexes built from the same memory records
* access tracking that strengthens memories when they are repeatedly useful
* age, disuse, or supersession signals that weaken memories over time
* decay workflows that summarize, archive, or eventually delete low-value memory

This direction fits the original Syx idea: memory should have a lifecycle. Retrieval should not only find memory. Over time, retrieval and usage should help shape which memories remain detailed, which memories are summarized, and which memories are allowed to fade.

Because of that, controlled agent write-back and MCP service work are deferred until the backend memory model is ready to support provenance, review, rollback, relationship tracking, access/decay signals, and safer mutation.

In the long term, once that foundation exists, Syx can return to the agent interface and MCP direction with a stronger memory substrate underneath it.

## Later Ideas

These are possible future directions, not promises:

* Database-backed memory records that can support both graph-style relationships and semantic RAG retrieval.
* Memory strengthening and weakening signals based on access, usefulness, age, supersession, and review.
* Decay workflows that summarize, archive, or eventually delete low-value memories over time.
* Controlled external agent memory write-back with provenance, review, rollback, and lifecycle controls.
* MCP integration for local agent memory search and controlled memory writes.
* Public onboarding context packs or curated project-memory snapshots for developers and AI coding assistants.
* Better UI surfaces for memory inspection, Sleep results, Dream results, and retrieval provenance.
* More provider options for LLMs, embeddings, local models, and remote research.
* Improved import/export and backup workflows for project memory.
* Optional memory maintenance tools for pruning, archiving, or rotating older artifacts.
* Richer instrumentation dashboards or analysis tools for token usage, latency, retrieval quality, and model-call behavior.
* More examples and guides for local research workflows.

## Non-Goals For The First Public Release

Syx is not currently trying to be:

* A hosted product or managed service.
* A production-hardened public internet application.
* A multi-tenant platform with authentication, authorization, billing, or user administration.
* A general-purpose vector database.
* A replacement for source control, issue tracking, or documentation.
* A claim of AGI or a finished memory standard.
* A system that guarantees private or regulated-data handling without additional review and controls.
* A public write-back memory API for untrusted agents.

## How To Read This Roadmap

If you want to contribute, start with [`CONTRIBUTING.md`](CONTRIBUTING.md), [`docs/COVERAGE.md`](docs/COVERAGE.md), [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md), and [`docs/DELTAS.md`](docs/DELTAS.md).

For behavior changes that overlap existing requirements, discuss the direction before implementation. Significant changes should either update the consolidated requirements or add a new active delta that explains the change and what older behavior it supersedes.
