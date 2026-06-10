# Syx Memory Search Agent

Use `tools/syx_memory_search_skill.md` for Syx memory access.

## Task

1. Read `tools/syx_memory_search_skill.md`.
2. Build a retrieval query from the current chat history or from the explicit
   query supplied by the user.
3. Identify the Syx project name. If the name is unknown, or if a search returns
   `project_not_found`, call `GET /projects` on the local backend and use the
   human-readable name from the `project_names` map.
4. Execute the memory search through the approved wrapper described in that
   skill.
5. Summarize the returned memory results for the user.
6. Write the summary to `chat_summary.md`.

## Query Placeholder

Replace this placeholder with the query needed for the current conversation:

```text
<memory search query derived from chat history or user instructions>
```

## Output

Create or overwrite `chat_summary.md` with:

- query used
- project searched
- key memories or source handles returned
- concise summary
- open questions or uncertainty, if any
