#!/usr/bin/env python3
"""
Copyright (c) 2025-2026 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Import ChatGPT HTML exports into Syx markdown memory artifacts.

Behavior:
- Accept an input path that may be one HTML file or a directory.
- For directory mode, process only top-level .html/.htm files.
- Extract and pair USER/ASSISTANT turns.
- Prune assistant responses through the configured light response pruner.
- Tag each pair via backend.app.tagging.tagger.tag_pair() unless tagger=false.
- Write one markdown memory artifact per input HTML file.
- Append one JSON object per successful file to statistics.jsonl.
"""

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional


logger = logging.getLogger("import_chat_html_to_markdown_memory")


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _repo_root_from_this_file() -> Path:
    return Path(__file__).resolve().parent.parent


def _ensure_import_paths() -> None:
    repo_root = _repo_root_from_this_file()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def _require_dependencies() -> tuple[Any, Any]:
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Missing dependency 'bs4'. Install backend dependencies before running this tool."
        ) from exc
    try:
        import tiktoken  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Missing dependency 'tiktoken'. Install backend dependencies before running this tool."
        ) from exc
    return BeautifulSoup, tiktoken


def _require_tagger() -> Any:
    try:
        from backend.app.tagging.tagger import tag_pair  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Failed importing backend.app.tagging.tagger.tag_pair. "
            "Run from repository context with backend dependencies configured."
        ) from exc
    return tag_pair


def _require_pruner() -> tuple[Any, Any]:
    try:
        from backend.app.core.config import get_settings  # type: ignore
        from backend.app.core.memory import _prune_assistant_for_tagger  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Failed importing light response pruner helper. "
            "Run from repository context with backend dependencies configured."
        ) from exc
    return _prune_assistant_for_tagger, get_settings


def _require_markdown_helpers() -> tuple[Any, Any, Any, Any]:
    try:
        from backend.app.rag.syx_memory_artifact import (  # type: ignore
            generate_memory_id,
            render_artifact_header,
            render_memory_entry,
            topics_to_list,
        )
    except Exception as exc:
        raise RuntimeError(
            "Failed importing Syx markdown memory helpers. "
            "Run from repository context with backend dependencies configured."
        ) from exc
    return generate_memory_id, render_artifact_header, render_memory_entry, topics_to_list


def _parse_bool_flag(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean value for tagger: {value!r}. Use true or false.")


def _estimate_tokens(text: str, enc: Any) -> int:
    return len(enc.encode(str(text or "")))


def _read_html(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        raise RuntimeError(f"Failed reading HTML file '{path}': {exc}") from exc


@dataclass(frozen=True)
class ExtractionResult:
    messages: list[tuple[str, str]]
    diagnostics: dict[str, Any]


_PLACEHOLDER_ASSISTANT_TEXTS = {
    "stopped thinking",
    "stopped thinking edit",
}


def _normalize_extracted_text(text: str) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return "\n".join(lines).strip()


def _strip_chatgpt_turn_prefix(text: str, prefix: str) -> str:
    normalized = _normalize_extracted_text(text)
    if normalized.lower() == prefix.lower():
        return ""
    prefix_with_colon = f"{prefix}:"
    if normalized.lower().startswith(prefix_with_colon.lower()):
        return normalized[len(prefix_with_colon) :].strip()
    return normalized


def _is_placeholder_assistant_text(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    return normalized in _PLACEHOLDER_ASSISTANT_TEXTS


def _extract_role_tagged_messages(soup: Any) -> list[tuple[str, str]]:
    messages: list[tuple[str, str]] = []
    for div in soup.find_all("div", attrs={"data-message-author-role": True}):
        role = str(div.get("data-message-author-role") or "").upper().strip()
        if role not in {"USER", "ASSISTANT"}:
            continue
        text = _normalize_extracted_text(div.get_text("\n", strip=True))
        if text:
            messages.append((role, text))
    return messages


def _extract_conversation_turn_messages(soup: Any) -> tuple[list[tuple[str, str]], dict[str, int]]:
    messages: list[tuple[str, str]] = []
    stats = {
        "conversation_turns_total": 0,
        "conversation_turns_empty": 0,
        "conversation_turns_nonempty": 0,
        "conversation_turns_user": 0,
        "conversation_turns_assistant": 0,
        "conversation_turns_placeholder_assistant": 0,
        "conversation_turns_unclassified": 0,
    }

    for turn in soup.select('[data-testid^="conversation-turn"]'):
        stats["conversation_turns_total"] += 1
        full_text = _normalize_extracted_text(turn.get_text("\n", strip=True))
        if not full_text:
            stats["conversation_turns_empty"] += 1
            continue
        stats["conversation_turns_nonempty"] += 1

        role_nodes = turn.select("[data-message-author-role]")
        role = ""
        text = ""
        if len(role_nodes) == 1:
            role = str(role_nodes[0].get("data-message-author-role") or "").upper().strip()
            text = _normalize_extracted_text(role_nodes[0].get_text("\n", strip=True))
        elif full_text.lower().startswith("you said:"):
            role = "USER"
            text = _strip_chatgpt_turn_prefix(full_text, "You said")
        elif full_text.lower().startswith("chatgpt said:"):
            role = "ASSISTANT"
            text = _strip_chatgpt_turn_prefix(full_text, "ChatGPT said")
        elif turn.select('[aria-label="Your message actions"]'):
            role = "USER"
            text = _strip_chatgpt_turn_prefix(full_text, "You said")
        elif turn.select('[aria-label="Response actions"]'):
            role = "ASSISTANT"
            text = _strip_chatgpt_turn_prefix(full_text, "ChatGPT said")

        if role not in {"USER", "ASSISTANT"} or not text:
            stats["conversation_turns_unclassified"] += 1
            continue
        if role == "ASSISTANT" and _is_placeholder_assistant_text(text):
            stats["conversation_turns_placeholder_assistant"] += 1
            continue

        messages.append((role, text))
        if role == "USER":
            stats["conversation_turns_user"] += 1
        else:
            stats["conversation_turns_assistant"] += 1

    return messages, stats


def _role_counts(messages: list[tuple[str, str]]) -> dict[str, int]:
    return {
        "user": sum(1 for role, _text in messages if role == "USER"),
        "assistant": sum(1 for role, _text in messages if role == "ASSISTANT"),
    }


def _extract_messages_with_diagnostics(html_text: str, bs4_type: Any) -> ExtractionResult:
    soup = bs4_type(html_text, "html.parser")
    role_messages = _extract_role_tagged_messages(soup)
    turn_messages, turn_stats = _extract_conversation_turn_messages(soup)
    role_counts = _role_counts(role_messages)
    turn_counts = _role_counts(turn_messages)

    if len(turn_messages) > len(role_messages):
        extractor = "conversation_turn"
        messages = turn_messages
    else:
        extractor = "role_tagged"
        messages = role_messages

    diagnostics: dict[str, Any] = {
        "extractor": extractor,
        "role_tagged_messages_total": len(role_messages),
        "role_tagged_user_turns": role_counts["user"],
        "role_tagged_assistant_turns": role_counts["assistant"],
        "selected_messages_total": len(messages),
        "selected_user_turns": _role_counts(messages)["user"],
        "selected_assistant_turns": _role_counts(messages)["assistant"],
        **turn_stats,
    }
    if turn_messages and role_messages and len(turn_messages) != len(role_messages):
        diagnostics["alternate_extractor_messages_total"] = len(turn_messages)
        diagnostics["alternate_extractor_user_turns"] = turn_counts["user"]
        diagnostics["alternate_extractor_assistant_turns"] = turn_counts["assistant"]
    return ExtractionResult(messages=messages, diagnostics=diagnostics)


def _extract_messages(html_text: str, bs4_type: Any) -> list[tuple[str, str]]:
    return _extract_messages_with_diagnostics(html_text, bs4_type).messages


def _html_appears_incomplete_or_virtualized(diagnostics: dict[str, Any]) -> bool:
    empty_turns = int(diagnostics.get("conversation_turns_empty", 0))
    selected_users = int(diagnostics.get("selected_user_turns", 0))
    selected_assistants = int(diagnostics.get("selected_assistant_turns", 0))
    return empty_turns > 0 and selected_users > selected_assistants * 2


def _pair_turns(messages: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], dict[str, int]]:
    pairs: list[tuple[str, str]] = []
    stats = {
        "orphan_assistant": 0,
        "replaced_unanswered_user": 0,
        "trailing_unanswered_user": 0,
    }
    pending_user: Optional[str] = None

    for role, text in messages:
        if role == "USER":
            if pending_user is not None:
                stats["replaced_unanswered_user"] += 1
            pending_user = text
            continue
        if pending_user is None:
            stats["orphan_assistant"] += 1
            continue
        pairs.append((pending_user, text))
        pending_user = None

    if pending_user is not None:
        stats["trailing_unanswered_user"] += 1

    return pairs, stats


def _extract_dd_trace_ms(html_text: str) -> Optional[int]:
    match = re.search(r'<meta\s+name="dd-trace-time"\s+content="(\d+)"', html_text, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError as exc:
        logger.warning("Invalid dd-trace-time content '%s': %s", match.group(1), exc)
        return None


def _resolve_time_basis(html_text: str) -> tuple[datetime, str]:
    ms = _extract_dd_trace_ms(html_text)
    if ms is not None:
        try:
            return datetime.fromtimestamp(ms / 1000.0), "dd-trace-time"
        except (OSError, OverflowError, ValueError) as exc:
            logger.warning("Failed converting dd-trace-time=%s to datetime: %s", ms, exc)
    return datetime.now(), "now"


def _to_memory_date(dt_local: datetime) -> str:
    return dt_local.strftime("%m-%d-%Y")


def _to_pair_timestamp(dt_local: datetime, sequence: int) -> str:
    # Offset duplicate HTML-export timestamps while preserving Syx timestamp format.
    return (dt_local.replace(microsecond=0) + timedelta(seconds=max(0, sequence - 1))).strftime(
        "%m-%d-%Y_%H:%M:%S"
    )


def _normalize_tag_value(tag_data: Optional[dict[str, Any]], key: str) -> str:
    if not isinstance(tag_data, dict):
        return ""
    raw = tag_data.get(key, "")
    if raw is None:
        return ""
    return str(raw)


def _build_previous_pair_text(
    *,
    user_text: str,
    assistant_text: str,
    topics: str,
    intent: str,
    tag_type: str,
    semantic_handle: str,
) -> str:
    return (
        "#route: other\n"
        "#keep: false\n"
        f"#topics: {topics}\n"
        f"#intent: {intent}\n"
        f"#type: {tag_type}\n"
        f"#semantic_handle: {semantic_handle}\n\n"
        f"User: {user_text}\n"
        f"Assistant: {assistant_text}"
    )


def _is_html_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in {".html", ".htm"}


def _validate_input_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Input file does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"Input path is not a file: {path}")
    if not _is_html_file(path):
        raise ValueError(f"Unsupported input extension '{path.suffix.lower()}'. Expected .html/.htm")


def _ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError(f"Output path is not a directory: {path}")


def _destination_with_suffix(output_dir: Path, src_stem: str) -> Path:
    candidate = output_dir / f"{src_stem}.md"
    if not candidate.exists():
        return candidate
    idx = 1
    while True:
        candidate = output_dir / f"{src_stem}_{idx}.md"
        if not candidate.exists():
            return candidate
        idx += 1


def _metadata_for_pair(
    *,
    memory_id: str,
    project_id: str,
    source_file: str,
    timestamp: str,
    day_sequence: int,
    route: str,
    source: str,
    source_agent: str,
    source_scope: str,
    current_scope: str,
    tags: dict[str, Any],
    topics_to_list: Any,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "memory_id": memory_id,
        "entry_type": "chat_pair",
        "source": source,
        "source_agent": source_agent,
        "source_scope": source_scope,
        "current_scope": current_scope,
        "timestamp": timestamp,
        "route": route,
        "keep": False,
        "day_sequence": int(day_sequence),
        "source_file": source_file,
    }
    topics = topics_to_list(tags.get("topics"))
    if topics:
        metadata["topics"] = topics
    intent = tags.get("intent")
    if intent is not None:
        metadata["intent"] = str(intent)
    tag_type = tags.get("type")
    if tag_type is not None:
        metadata["type"] = str(tag_type)
    semantic_handle = tags.get("semantic_handle")
    if semantic_handle is not None and str(semantic_handle).strip():
        metadata["semantic_handle"] = str(semantic_handle).strip()
    return metadata


def _process_one_file(
    *,
    input_path: Path,
    out_dir: Path,
    project_id: str,
    route: str,
    artifact_type: str,
    source: str,
    source_agent: str,
    source_scope: str,
    current_scope: str,
    BeautifulSoup: Any,
    tag_pair: Optional[Any],
    prune_assistant_for_tagger: Any,
    settings: Any,
    encoding: Any,
    allow_partial_html: bool,
    generate_memory_id: Any,
    render_artifact_header: Any,
    render_memory_entry: Any,
    topics_to_list: Any,
) -> Path:
    html_text = _read_html(input_path)
    extraction = _extract_messages_with_diagnostics(html_text, BeautifulSoup)
    messages = extraction.messages
    if not messages:
        raise RuntimeError("No USER/ASSISTANT messages found in input HTML.")
    logger.info(
        "Extraction summary for %s: extractor=%s message_nodes=%s user_nodes=%s "
        "assistant_nodes=%s max_complete_pairs=%s conversation_turn_containers=%s empty_turns=%s "
        "placeholder_assistant_turns=%s",
        input_path.name,
        extraction.diagnostics.get("extractor"),
        extraction.diagnostics.get("selected_messages_total"),
        extraction.diagnostics.get("selected_user_turns"),
        extraction.diagnostics.get("selected_assistant_turns"),
        min(
            int(extraction.diagnostics.get("selected_user_turns", 0)),
            int(extraction.diagnostics.get("selected_assistant_turns", 0)),
        ),
        extraction.diagnostics.get("conversation_turns_total"),
        extraction.diagnostics.get("conversation_turns_empty"),
        extraction.diagnostics.get("conversation_turns_placeholder_assistant"),
    )
    if _html_appears_incomplete_or_virtualized(extraction.diagnostics):
        message = (
            "HTML appears incomplete or virtualized; "
            f"user_turns={extraction.diagnostics.get('selected_user_turns')} "
            f"assistant_turns={extraction.diagnostics.get('selected_assistant_turns')} "
            f"empty_turns={extraction.diagnostics.get('conversation_turns_empty')} "
            f"placeholder_assistant_turns="
            f"{extraction.diagnostics.get('conversation_turns_placeholder_assistant')}. "
            "A Syx chat_pair requires both a user turn and an assistant turn, so this file "
            f"can produce at most {extraction.diagnostics.get('selected_assistant_turns')} "
            "complete pairs. "
            "Re-save the chat after fully loading/rendering it, or rerun with "
            "--allow-partial-html to import only the turns present in this file."
        )
        if not allow_partial_html:
            raise RuntimeError(message)
        logger.warning("%s", message)

    pairs, pair_stats = _pair_turns(messages)
    if not pairs:
        raise RuntimeError("No valid USER->ASSISTANT pairs found after pairing.")

    file_dt_local, ts_source = _resolve_time_basis(html_text)
    memory_date = _to_memory_date(file_dt_local)
    out_md_path = _destination_with_suffix(out_dir, input_path.stem)
    stats_path = out_dir / "statistics.jsonl"

    blocks: list[str] = [
        render_artifact_header(
            artifact_type=artifact_type,
            project_id=project_id,
            memory_date=memory_date,
        )
    ]
    previous_pair_text: Optional[str] = None
    memory_ids: list[str] = []
    total_tokens_user_assistant = 0
    total_tokens_user = 0
    total_tokens_original_assistant = 0
    total_tokens_pruned_assistant = 0
    total_tokens_output = _estimate_tokens(blocks[0], encoding)
    pruned_pairs = 0

    for idx, (user_text, assistant_text) in enumerate(pairs, start=1):
        user_tokens = _estimate_tokens(user_text, encoding)
        original_assistant_tokens = _estimate_tokens(assistant_text, encoding)
        total_tokens_user += user_tokens
        total_tokens_original_assistant += original_assistant_tokens
        total_tokens_user_assistant += user_tokens + original_assistant_tokens
        assistant_text_for_memory = prune_assistant_for_tagger(
            project_id=project_id,
            assistant_text=assistant_text,
            settings=settings,
        )
        total_tokens_pruned_assistant += _estimate_tokens(assistant_text_for_memory, encoding)
        if assistant_text_for_memory != assistant_text:
            pruned_pairs += 1

        if tag_pair is not None:
            tags = tag_pair(
                user_text=user_text,
                assistant_text=assistant_text_for_memory,
                previous_pair_text=previous_pair_text,
                project_id=project_id,
            )
            if not isinstance(tags, dict):
                raise RuntimeError(
                    f"tag_pair failed for pair #{idx}. "
                    "Tagger requires valid backend configuration/API key."
                )
        else:
            tags = {}

        topics = _normalize_tag_value(tags, "topics")
        intent = _normalize_tag_value(tags, "intent")
        tag_type = _normalize_tag_value(tags, "type")
        semantic_handle = _normalize_tag_value(tags, "semantic_handle")
        pair_ts = _to_pair_timestamp(file_dt_local, idx)
        memory_id = generate_memory_id(
            project_id=project_id,
            timestamp=pair_ts,
            source=source,
            entry_type="chat_pair",
            user_text=user_text,
            assistant_text=assistant_text_for_memory,
            route=route,
            semantic_handle=semantic_handle or None,
        )
        memory_ids.append(memory_id)
        metadata = _metadata_for_pair(
            memory_id=memory_id,
            project_id=project_id,
            source_file=input_path.name,
            timestamp=pair_ts,
            day_sequence=idx,
            route=route,
            source=source,
            source_agent=source_agent,
            source_scope=source_scope,
            current_scope=current_scope,
            tags=tags,
            topics_to_list=topics_to_list,
        )
        block = render_memory_entry(
            memory_id=memory_id,
            metadata=metadata,
            user_text=user_text,
            assistant_text=assistant_text_for_memory,
        )
        blocks.append(block)
        total_tokens_output += _estimate_tokens(block, encoding)
        previous_pair_text = _build_previous_pair_text(
            user_text=user_text,
            assistant_text=assistant_text_for_memory,
            topics=topics,
            intent=intent,
            tag_type=tag_type,
            semantic_handle=semantic_handle,
        )

    output_text = "".join(blocks).rstrip() + "\n"
    try:
        out_md_path.write_text(output_text, encoding="utf-8", newline="\n")
    except Exception as exc:
        raise RuntimeError(f"Failed writing output markdown file '{out_md_path}': {exc}") from exc

    stats_record = {
        "ts": datetime.now().isoformat(),
        "filename_root": input_path.stem,
        "input_file": str(input_path),
        "output_file": str(out_md_path),
        "project_id": project_id,
        "output_format": "syx_markdown_memory",
        "artifact_type": artifact_type,
        "entry_type": "chat_pair",
        "source": source,
        "source_agent": source_agent,
        "source_scope": source_scope,
        "current_scope": current_scope,
        "route": route,
        "tagger_enabled": tag_pair is not None,
        "light_response_pruner_enabled": bool(getattr(settings, "response_pruning_enabled", True)),
        "pairs_total": len(pairs),
        "pruned_pairs": int(pruned_pairs),
        "tokens_user_assistant_total_est": int(total_tokens_user_assistant),
        "tokens_user_total_est": int(total_tokens_user),
        "tokens_original_assistant_total_est": int(total_tokens_original_assistant),
        "tokens_pruned_assistant_total_est": int(total_tokens_pruned_assistant),
        "tokens_user_pruned_assistant_total_est": int(total_tokens_user + total_tokens_pruned_assistant),
        "tokens_output_total_est": int(total_tokens_output),
        "timestamp_source": ts_source,
        "extraction_stats": extraction.diagnostics,
        "pairing_stats": pair_stats,
        "memory_ids": memory_ids,
    }
    try:
        with open(stats_path, "a", encoding="utf-8", newline="\n") as sf:
            sf.write(json.dumps(stats_record, ensure_ascii=False) + "\n")
    except Exception as exc:
        raise RuntimeError(f"Failed appending statistics JSONL '{stats_path}': {exc}") from exc

    logger.info("Processed file: %s", input_path.name)
    logger.info("Extractor: %s", extraction.diagnostics.get("extractor"))
    logger.info("Pairs written: %s", len(pairs))
    logger.info("Output markdown: %s", out_md_path)
    logger.info("Stats appended: %s", stats_path)
    return out_md_path


def run(
    input_path_raw: str,
    output_dir_raw: str,
    project_id: str,
    tagger: bool = True,
    *,
    route: str = "other",
    artifact_type: str = "daily_memory",
    source: str = "chat",
    source_agent: str = "syx",
    source_scope: str = "daily",
    current_scope: str = "ltm",
    allow_partial_html: bool = False,
) -> int:
    _setup_logging()
    _ensure_import_paths()

    input_path = Path(input_path_raw).resolve()
    out_dir = Path(output_dir_raw).resolve()
    _ensure_output_dir(out_dir)

    BeautifulSoup, tiktoken = _require_dependencies()
    tag_pair = _require_tagger() if tagger else None
    prune_assistant_for_tagger, get_settings = _require_pruner()
    settings = get_settings()
    generate_memory_id, render_artifact_header, render_memory_entry, topics_to_list = _require_markdown_helpers()
    encoding = tiktoken.get_encoding("cl100k_base")

    if not input_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")
    if not project_id.strip():
        raise ValueError("project_id is required")

    if input_path.is_file():
        _validate_input_file(input_path)
        files_to_process = [input_path]
    elif input_path.is_dir():
        files_to_process = [p.resolve() for p in input_path.iterdir() if _is_html_file(p)]
        if not files_to_process:
            raise RuntimeError(f"No .html/.htm files found in directory: {input_path}")
    else:
        raise ValueError(f"Input path is neither a file nor directory: {input_path}")

    processed_count = 0
    failed_count = 0
    for fpath in files_to_process:
        try:
            _process_one_file(
                input_path=fpath,
                out_dir=out_dir,
                project_id=project_id,
                route=route,
                artifact_type=artifact_type,
                source=source,
                source_agent=source_agent,
                source_scope=source_scope,
                current_scope=current_scope,
                BeautifulSoup=BeautifulSoup,
                tag_pair=tag_pair,
                prune_assistant_for_tagger=prune_assistant_for_tagger,
                settings=settings,
                encoding=encoding,
                allow_partial_html=allow_partial_html,
                generate_memory_id=generate_memory_id,
                render_artifact_header=render_artifact_header,
                render_memory_entry=render_memory_entry,
                topics_to_list=topics_to_list,
            )
            processed_count += 1
        except Exception as exc:
            failed_count += 1
            logger.warning("Failed processing file '%s': %s", fpath.name, exc)

    logger.info(
        "Run complete. processed=%s failed=%s input=%s output_dir=%s tagger=%s project_id=%s",
        processed_count,
        failed_count,
        input_path,
        out_dir,
        tagger,
        project_id,
    )
    return 0 if failed_count == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import ChatGPT HTML file(s) into Syx markdown memory artifacts."
    )
    parser.add_argument(
        "input_path",
        help="Path to one .html/.htm file or a directory of top-level .html/.htm files",
    )
    parser.add_argument("output_dir", help="Output directory for <input_root>.md and statistics.jsonl")
    parser.add_argument("--project-id", required=True, help="Syx project ID to store in memory metadata")
    parser.add_argument(
        "--tagger",
        default="true",
        help="Whether to run the tagger (true/false). Defaults to true.",
    )
    parser.add_argument("--route", default="other", help="Route metadata to assign to imported chat pairs")
    parser.add_argument(
        "--artifact-type",
        default="daily_memory",
        help="Top-level Syx artifact type for the markdown frontmatter",
    )
    parser.add_argument("--source", default="chat", help="Source metadata value")
    parser.add_argument("--source-agent", default="syx", help="Source agent metadata value")
    parser.add_argument("--source-scope", default="daily", help="Source scope metadata value")
    parser.add_argument("--current-scope", default="ltm", help="Current scope metadata value")
    parser.add_argument(
        "--allow-partial-html",
        action="store_true",
        help=(
            "Import even when the saved ChatGPT HTML appears incomplete or virtualized. "
            "By default, incomplete HTML fails before tagging/writing partial memory."
        ),
    )
    args = parser.parse_args()

    try:
        return run(
            args.input_path,
            args.output_dir,
            args.project_id,
            _parse_bool_flag(args.tagger),
            route=args.route,
            artifact_type=args.artifact_type,
            source=args.source,
            source_agent=args.source_agent,
            source_scope=args.source_scope,
            current_scope=args.current_scope,
            allow_partial_html=args.allow_partial_html,
        )
    except Exception as exc:
        logger.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
