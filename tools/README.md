# Tools

Utility scripts for importing memory artifacts, preparing benchmarks, and maintaining repository files. Run examples from the repository root unless noted otherwise.

## `add_header.py`

Adds or normalizes the standard Syx copyright header across Python files and frontend TypeScript/JavaScript files. It skips common generated and dependency directories.

```bash
python3 tools/add_header.py
```

## `agent_memory_search.py`

Calls the local `POST /agent/memory/search` endpoint and prints the JSON response. It also writes a debug request/response JSON file under `tools/agent_interface/` by default.

```bash
SYX_AGENT_TOKEN="local-token" python3 tools/agent_memory_search.py \
  --project-name "Main" \
  --query "<retrieval objective>. Context: <project/topic/semantic handle>. Include: <known terms, requirement IDs, deltas, files, decisions, constraints>." \
  --category "SYNTHESIS" \
  --pretty
```

examples:
Implementation guidance, requirements, design decisions, constraints, and known pitfalls for agent memory search endpoint. Context: DELTA-A.4 external agent memory search.
Prior decisions and constraints about memory decay, pruning, sleep cycle, and reconsolidation. Context: research plan for memory reconsolidation neuroscience.
Find file locations, requirements, and behavior for full Syx memory entry expansion. Context: DELTA-A.5 bounded entry expansion agent memory.

## `build_benchmark_scores.py`

Builds per-turn average score CSV files from blind judge score JSONL files under a test run's `judging/` directory. It can process batch `A`, batch `B`, or both.

```bash
python3 tools/build_benchmark_scores.py \
  --test-run-dir backend/runs/test_run_20260514_103000 \
  --batch BOTH \
  --overall-source provided
```

## `build_judge_input.py`

Builds blind judging artifacts from a benchmark test run. It reads Syx benchmark output, web benchmark output, and the prompts JSON, then writes runbooks, judge mapping, and copy/paste judge prompts to `<test_run_dir>/judging/`.

```bash
python3 tools/build_judge_input.py \
  backend/runs/test_run_20260514_103000 \
  backend/runs/test_run_20260514_103000/prompts.json
```

## `build_turn_data.py`

Builds `benchmark_turns.csv` from a test run's Syx `turns.jsonl` and optional web `web_turns.jsonl`. The CSV compares token components per turn.

```bash
python3 tools/build_turn_data.py \
  --test-run-dir backend/runs/test_run_20260514_103000
```

## `concat_txt_files.py`

Concatenates top-level `.txt` and `.md` files from an input directory into `concatenated_Syx.txt` in the output directory. It does not recurse into subdirectories.

```bash
python3 tools/concat_txt_files.py \
  data/memory/ce667335-ae8e-41d7-b810-59627cd8d67a/uploads/imported_chats \
  data/memory/ce667335-ae8e-41d7-b810-59627cd8d67a/uploads/exported_chats
```

## `convert_legacy_txt_to_markdown_memory.py`

Converts legacy Syx `.txt` memory artifacts into modern `.md` memory artifacts without pruning. Recognized legacy Daily/Dream pair blocks are rendered with Syx memory boundaries, markdown headings, YAML metadata, and mapped `#topics` lists. Unrecognized leftover sections are preserved as raw bounded entries instead of being dropped. The original files are not modified.

```bash
python3 tools/convert_legacy_txt_to_markdown_memory.py \
  --dir data/memory/ce667335-ae8e-41d7-b810-59627cd8d67a/uploads/history \
  --output-dir data/memory/ce667335-ae8e-41d7-b810-59627cd8d67a/uploads/imported_chats \
  --project-id ce667335-ae8e-41d7-b810-59627cd8d67a
```

## `extract_chat.py`

Extracts USER/ASSISTANT pairs from one ChatGPT HTML export and writes benchmark-compatible JSONL artifacts into a test run directory. It writes `web_benchmark_results.jsonl` and synthetic `web_turns.jsonl`.

```bash
python3 tools/extract_chat.py \
  backend/runs/test_run_20260514_103000/prompts.json \
  exports/chat_export.html \
  backend/runs/test_run_20260514_103000
```

## `import_chat_html_to_daily.py`

Imports one ChatGPT HTML export, or all top-level `.html`/`.htm` files in a directory, into legacy daily-memory text format. By default it tags each USER/ASSISTANT pair with the current backend tagger and writes `<input_root>.txt`, plus `statistics.jsonl`; when multiple files are processed it also writes `concatenated_daily.txt`.

```bash
python3 tools/import_chat_html_to_daily.py \
  exports/chat_html \
  data/imported_daily \
  true
```

## `import_chat_html_to_markdown_memory.py`

Imports one ChatGPT HTML export, or all top-level `.html`/`.htm` files in a directory, into modern Syx markdown memory artifacts. This is the preferred importer for raw HTML chats that should become new-format memory files: it extracts USER/ASSISTANT pairs, prunes assistant responses with the configured light response pruner, runs the tagger by default, renders Syx memory boundaries and YAML metadata, writes one `<input_root>.md` file per HTML file, and appends per-file rows to `statistics.jsonl`.

```bash
python3 tools/import_chat_html_to_markdown_memory.py \
  exports/chat_html \
  data/memory/ce667335-ae8e-41d7-b810-59627cd8d67a/uploads/imported_chats \
  --project-id ce667335-ae8e-41d7-b810-59627cd8d67a \
  --tagger true
```

## `import_chat_txt_to_daily.py`

Copies pre-tagged top-level `.txt` daily-memory files into an output directory, appending suffixes when names collide. It writes per-file statistics to `statistics.jsonl` and creates `concatenated_daily.txt`.

```bash
python3 tools/import_chat_txt_to_daily.py \
  data/pretagged_chats \
  data/imported_daily
```

## `process_responses.py`

Processes top-level `.txt` chat logs and extracts opening and closing response boundary data from assistant blocks. It writes `front.jsonl` and `end.jsonl` into the same directory.

```bash
python3 tools/process_responses.py data/imported_daily
```

## `replace_morpheus_with_syx_txt.py`

Replaces every case-insensitive occurrence of `Morpheus` with `Syx` in top-level `.txt` files in a directory. Use `--dry-run` to inspect changes before writing.

```bash
python3 tools/replace_morpheus_with_syx_txt.py \
  data/imported_daily \
  --dry-run
```

## `tag_legacy_syx_boundaries.py`

Adds Syx memory boundary comments, memory IDs, markdown artifact headers, and entry headings to legacy Daily/Sleep/Dream pair artifacts. It can process one file or recurse through a directory for `.txt` and `.md` files.

```bash
python3 tools/tag_legacy_syx_boundaries.py \
  --dir data/memory/project-id \
  --in-place \
  --backup
```
