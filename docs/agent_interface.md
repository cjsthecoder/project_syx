# Agent Memory Interface

Syx includes a local agent-memory search interface so trusted external tools can query project memory without running the normal chat response pipeline.

This interface is intended for local development and trusted local agent workflows. It is not a public API and is not production-hardened. Read `SECURITY.md` before exposing any Syx endpoint outside a trusted environment.

## What It Does

The agent memory interface provides a read-only search endpoint:

```text
POST /agent/memory/search
```

The endpoint:

- Resolves a human-readable `project_name` to the internal `project_id`.
- Uses the provided `category` to select existing retrieval policy behavior.
- Searches Daily memory and long-term project memory through the RAG pipeline.
- Returns structured JSON snippets.
- Expands bounded Syx memory entries to fuller entry text when possible.
- Writes local debug artifacts for troubleshooting when debug output is enabled.

The endpoint does **not**:

- Generate an assistant answer.
- Stream chat output.
- Run the normal chat route-classification prompt.
- Persist chat messages.
- Write memory.
- Trigger Sleep or Dream.
- Rebuild indexes.
- Delete or mutate project artifacts.

## Current Status

The current public interface is read-only search.

Write-back is not part of the current public endpoint. `docs/DELTAS.md` describes future work for controlled agent memory add/write-back, but this document describes the interface that exists now.

## Endpoint Request

Send JSON to:

```text
POST http://127.0.0.1:8000/agent/memory/search
```

Request body:

```json
{
  "project_name": "Main",
  "query": "Find implementation guidance for agent memory search.",
  "category": "SYNTHESIS",
  "model": "optional-model-name",
  "agent_token": "local-token"
}
```

Fields:

- `project_name` is required. It is the human-readable project name, not the project UUID.
- `query` is required. It is the retrieval query text.
- `category` is optional and defaults to `OTHER`.
- `model` is optional. It is echoed for compatibility/debugging and does not select retrieval behavior.
- `agent_token` is required by the request contract.

The endpoint accepts `project_name` because external agents usually know the project by name. Matching is trimmed and case-insensitive.

## Categories

`category` selects the existing retrieval policy. It does not run a classifier.

Supported categories:

- `DIRECT` for narrow factual lookup.
- `PROCEDURAL` for implementation, configuration, setup, or execution guidance.
- `EXPLORATORY` for investigation, comparison, or broad discovery.
- `SYNTHESIS` for architecture, design tradeoffs, planning, and idea evolution.
- `OTHER` as a fallback.

Missing, invalid, or unsupported categories fall back to `OTHER`. `CHITCHAT` is not retrieval-eligible and also falls back to `OTHER`.

For broad project-memory searches, start with `SYNTHESIS`.

## Successful Response

A successful response returns `200 OK` and a structured JSON body:

```json
{
  "project_name": "Main",
  "project_id": "004208b5-ebc1-4747-92d5-fb10d2687440",
  "category": "SYNTHESIS",
  "query": "Find implementation guidance for agent memory search.",
  "snippet_count": 2,
  "bounded_result_count": 1,
  "unbounded_result_count": 1,
  "snippets": [
    {
      "snippet_number": 1,
      "source": "ltm",
      "cos": 0.6662,
      "score": 0.8331,
      "file": "sleep_2026-06-10T15-42-05.md",
      "source_document_id": "sleep/sleep_2026-06-10T15-42-05.md::memory_id=mem_...",
      "chunk_index_start": 0,
      "chunk_index_end": 2,
      "chunk_index_range": "0..2",
      "memory_id": "mem_...",
      "entry_type": "daily",
      "source_scope": "daily",
      "current_scope": "sleep",
      "semantic_handle": "agent memory search implementation",
      "topics": ["agent memory", "retrieval", "Syx"],
      "artifact_path": "sleep/sleep_2026-06-10T15-42-05.md",
      "result_mode": "bounded_entry",
      "entry_expansion_status": "expanded",
      "entry_expansion_method": "syx_boundary",
      "text": "Retrieved memory text..."
    }
  ]
}
```

When no snippets match, the endpoint still returns `200 OK`:

```json
{
  "project_name": "Main",
  "project_id": "004208b5-ebc1-4747-92d5-fb10d2687440",
  "category": "SYNTHESIS",
  "query": "Find implementation guidance for agent memory search.",
  "snippet_count": 0,
  "bounded_result_count": 0,
  "unbounded_result_count": 0,
  "snippets": []
}
```

## Snippet Fields

Important snippet fields include:

- `snippet_number` — 1-based result position.
- `source` — retrieval source bucket, such as Daily or long-term memory.
- `cos` — raw cosine/inner-product score when available.
- `score` — normalized similarity score in `[0, 1]` when available.
- `file` — source filename.
- `source_document_id` — stable source-document identity.
- `chunk_index_start`, `chunk_index_end`, `chunk_index_range`, `chunk_indexes` — chunk provenance.
- `memory_id` — stable Syx memory entry id when available.
- `entry_type` — memory entry type when available.
- `source_agent` — authoring agent when available.
- `source_scope` and `current_scope` — lifecycle scope metadata.
- `semantic_handle` — short phrase naming the entry.
- `topics` — topic tags attached to the memory entry.
- `artifact_path` — backing artifact path when available.
- `result_mode` — `bounded_entry` or `unbounded_chunk_group`.
- `entry_expansion_status` — expansion result such as `expanded`, `expanded_truncated`, `fallback`, or `failed`.
- `text` — retrieved snippet body returned to the caller.

Null fields are omitted from the serialized response.

## Error Responses

Missing `agent_token`:

```text
401 Unauthorized
```

```json
{
  "error": "unauthorized",
  "message": "Missing agent token."
}
```

Missing `project_name`:

```text
400 Bad Request
```

```json
{
  "error": "invalid_request",
  "message": "project_name is required."
}
```

Missing `query`:

```text
400 Bad Request
```

```json
{
  "error": "invalid_request",
  "message": "query is required."
}
```

Unknown project:

```text
404 Not Found
```

```json
{
  "error": "project_not_found",
  "message": "No project exists with the requested project_name.",
  "project_name": "Main"
}
```

Sleep lock active:

```text
423 Locked
```

```json
{
  "error": "memory_locked",
  "message": "Project memory is currently unavailable because sleep is running. Retry after sleep completes.",
  "project_id": "004208b5-ebc1-4747-92d5-fb10d2687440",
  "project_name": "Main",
  "retryable": true
}
```

Retrieval context parse failure:

```text
500 Internal Server Error
```

```json
{
  "error": "snippet_parse_failed",
  "message": "Agent memory search retrieved context but could not convert it to structured snippets.",
  "retryable": false
}
```

Unexpected failure:

```text
500 Internal Server Error
```

```json
{
  "error": "agent_memory_search_failed",
  "message": "Agent memory search failed."
}
```

## Token Requirement and Security Boundary

The request must include an `agent_token` field. This is part of the endpoint contract so current tools match the future secured interface.

Current limitation: token authorization is a local-development stub. The authorization boundary exists in `backend/app/security/agent_tokens.py`, but the current implementation authorizes requests instead of enforcing a real secret or project-level access policy.

Do not treat `local-token` or `SYX_AGENT_TOKEN` as production security.

The endpoint can return project memory, uploaded content, and generated memory artifacts. Use it only in trusted local environments.

## Tooling

Example local tools live under `tools/`:

- `tools/syx_memory_search.sh` — preferred shell wrapper.
- `tools/agent_memory_search.py` — Python CLI bridge for `POST /agent/memory/search`.
- `tools/config/syx.env` — local wrapper defaults, including `SYX_AGENT_TOKEN`.
- `tools/syx_memory_search_skill.md` — agent-facing usage guidance.

The wrapper defaults to:

```text
SYX_BASE_URL=http://127.0.0.1:8000
```

It expects `SYX_AGENT_TOKEN` to be set, either in the environment or through `tools/config/syx.env`.

## Shell Wrapper Usage

Start the Syx backend first:

```bash
make run
```

Then search memory:

```bash
tools/syx_memory_search.sh \
  --project-name "Main" \
  --query "Find implementation guidance for agent memory search. Context: DELTA-A.4 and DELTA-A.5." \
  --category "SYNTHESIS"
```

Short positional form:

```bash
tools/syx_memory_search.sh "Main" "Find prior decisions about Sleep and Dream" "SYNTHESIS"
```

Useful environment variables:

- `SYX_AGENT_TOKEN` — token sent to the backend; currently required but not strongly enforced.
- `SYX_BASE_URL` — backend base URL; defaults to `http://127.0.0.1:8000`.
- `SYX_REPO_DIR` — override repository root; normally not needed.
- `SYX_PYTHON` — override Python executable; normally not needed.

## Direct curl Usage

```bash
curl -s http://127.0.0.1:8000/agent/memory/search \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "Main",
    "query": "Find prior decisions about markdown memory artifacts.",
    "category": "SYNTHESIS",
    "agent_token": "local-token"
  }'
```

## Debug Artifacts

The backend writes paired debug files for endpoint calls under the project debug tree:

```text
data/memory/{project_id}/debug/agent_interface/
```

The Python CLI also writes local debug JSON under:

```text
tools/agent_interface/
```

These files may contain request queries, retrieved context, memory text, and response snippets. Do not commit them unless they are intentionally sanitized examples.

## Relationship to Normal Chat

Normal chat and agent memory search share retrieval machinery, but they have different endpoint responsibilities.

Normal chat:

- Builds prompts.
- Calls the configured chat model.
- Streams or returns an assistant response.
- Persists chat messages.
- Can roll older pairs into Daily memory.

Agent memory search:

- Accepts an explicit retrieval query.
- Uses the provided category as retrieval policy input.
- Returns structured snippets.
- Does not call the chat model to answer.
- Does not write memory.

## Future Direction

The current endpoint is the first local bridge for agent-readable Syx memory. Future work may add:

- Real token validation.
- Project-scoped token authorization.
- Authorization headers such as `Authorization: Bearer <token>`.
- Controlled agent memory write-back.
- MCP wrappers.

Until those features exist, treat the interface as trusted-local and read-only.
