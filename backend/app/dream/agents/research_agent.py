"""
Copyright (c) 2025-2026 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ...core.config import get_settings
from ...core.llm import generate_text_response
from app.utils.debug_utils import write_debug_file
from ..debug import safe_dream_purpose, write_dream_prompt_to_execute, write_dream_response_usage_debug
from ..research import count_tokens
from ..rag import retrieve_dream_context
from .prompts.research_prompts import build_research_prompt

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    now = datetime.now(timezone.utc)
    # Use full ISO format with Z suffix for consistency
    return now.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def run_research_agent(
    project_id: str,
    idea_data: Dict[str, Any],
    project_summary_text: str,
    debug_ts: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run the Research Agent for a project.

    This function:
      - Iterates Idea Agent entries and their recommended_research topics.
      - Builds a research prompt for each topic.
      - Invokes the Dream LLM with the same configuration used by fetch_remote_research.
      - Parses plain-text results into Research Entry dicts and appends them under "research".
    """
    settings = get_settings()
    logger.info("[DREAM][RESEARCH] Start project=%s", project_id)

    date_val = idea_data.get("date")
    if not isinstance(date_val, str) or not date_val.strip():
        today = datetime.now(timezone.utc).strftime("%m/%d/%Y")
        date_str = today
    else:
        date_str = date_val

    items = idea_data.get("items")
    if not isinstance(items, list):
        logger.warning(
            "Research Agent received invalid items (not a list) for project=%s; returning input unchanged.",
            project_id,
        )
        return {"date": date_str, "items": []}

    total_topics = 0
    skipped_non_remote = 0
    prompt_debug_rows: List[Dict[str, Any]] = []

    for entry in items:
        if not isinstance(entry, dict):
            continue

        entry_id = entry.get("id")
        origin_text = entry.get("origin_text", "") or ""
        origin_type = entry.get("origin_type", "") or ""
        assistant_response = entry.get("assistant_response", "") or ""
        source_resolution = str(entry.get("source_resolution") or "").strip().lower()

        metadata = entry.get("metadata") or {}
        if not isinstance(metadata, dict):
            entry["research"] = []
            entry["research_failed"] = True
            continue

        theme = metadata.get("theme", "") or ""
        recommended = metadata.get("recommended_research")

        # Only answer_remote entries are eligible for research enrichment.
        if source_resolution != "answer_remote":
            skipped_non_remote += 1
            entry["research"] = []
            continue

        if not recommended:
            entry["research"] = []
            continue

        topics_list: List[Any]
        if isinstance(recommended, list):
            topics_list = recommended
        else:
            topics_list = [recommended]

        entry_research: List[Dict[str, Any]] = []
        entry_failures = 0

        for raw_topic in topics_list:
            topic = str(raw_topic).strip()
            if not topic:
                continue

            total_topics += 1
            try:
                local_context_result = retrieve_dream_context(
                    project_id=project_id,
                    query=topic,
                    route="SYNTHESIS",
                )
                local_context_text = str(local_context_result.get("context_text") or "").strip()
            except Exception as exc:
                logger.warning(
                    "[DREAM][RESEARCH] Expanded local retrieval failed project=%s topic=%s detail=%s",
                    project_id,
                    topic,
                    exc,
                )
                local_context_text = ""

            prompt = build_research_prompt(
                project_summary_text=project_summary_text or "",
                local_context_text=local_context_text or "(empty)",
                origin_text=origin_text,
                origin_type=origin_type,
                assistant_response=assistant_response,
                research_topic=topic,
                theme=theme,
            )
            prompt_debug_rows.append(
                {
                    "entry_id": str(entry_id or ""),
                    "origin_text": str(origin_text or ""),
                    "research_topic": topic,
                    "local_context_tokens": int(count_tokens(local_context_text or "")),
                    "prompt": prompt,
                }
            )

            logger.debug("Research Agent prompt topic=%s", topic)

            purpose = "research_agent"
            max_tokens = int(settings.dream_max_tokens)
            model = str(settings.dream_model)
            write_dream_prompt_to_execute(
                project_id=project_id,
                prompt=prompt,
                purpose=purpose,
                model=model,
                max_output_tokens=max_tokens,
            )
            try:
                response = generate_text_response(
                    prompt,
                    override_model=model,
                    system_prompt=None,
                    temperature_override=float(settings.dream_temperature),
                    max_output_tokens=max_tokens,
                    purpose=f"dream:{safe_dream_purpose(purpose)}",
                )
                write_dream_response_usage_debug(
                    project_id=project_id,
                    response_text=response.text,
                    purpose=purpose,
                    model=model,
                    max_output_tokens=max_tokens,
                    usage=response.usage,
                )
                raw = response.text
            except Exception as exc:
                logger.error(
                    "Research Agent LLM invocation failed project=%s topic=%s: %s",
                    project_id,
                    topic,
                    exc,
                    exc_info=True,
                )
                raw = '{"answer": "Dream agent failed to generate a valid answer."}'

            raw_text = raw or ""

            # Preserve line structure so formatted bullets/sections render in UI.
            raw_lines = raw_text.splitlines()
            first_non_empty_idx = None
            for i, ln in enumerate(raw_lines):
                if str(ln).strip():
                    first_non_empty_idx = i
                    break
            if first_non_empty_idx is None:
                logger.warning(
                    "Research Agent empty output project=%s topic=%s; skipping topic.",
                    project_id,
                    topic,
                )
                entry_failures += 1
                continue

            header = str(raw_lines[first_non_empty_idx]).strip()
            summary_lines = raw_lines[first_non_empty_idx + 1 :] or []
            summary = "\n".join(summary_lines).strip()

            if not summary:
                logger.warning(
                    "Research Agent unable to parse summary body project=%s topic=%s header=%r",
                    project_id,
                    topic,
                    header,
                )
                entry_failures += 1
                continue

            research_entry: Dict[str, Any] = {
                "entry_id": entry_id,
                "agent": "researcher_agent",
                "timestamp": _utc_now_iso(),
                "research_topic": topic,
                "research_summary": summary,
                "metadata": {
                    "related_theme": theme,
                },
            }
            entry_research.append(research_entry)

        entry["research"] = entry_research

        if topics_list and not entry_research:
            entry["research_failed"] = True

    result: Dict[str, Any] = {"date": date_str, "items": items}

    try:
        debug_payload = json.dumps(result, ensure_ascii=False, indent=2)
        write_debug_file(project_id, "debug_research.txt", debug_payload)
    except Exception as de:
        logger.warning("Research Agent failed to write debug_research.txt project=%s: %s", project_id, de)
    try:
        if debug_ts:
            prompts_body = (
                f"# timestamp: {debug_ts}\n"
                f"# project_id: {project_id}\n"
                "\n"
                "====== INPUT ======\n"
                f"{json.dumps(prompt_debug_rows, ensure_ascii=False, indent=2)}\n"
            )
            write_debug_file(project_id, f"dreaming/{debug_ts}_research_prompts.txt", prompts_body)
    except Exception as de:
        logger.warning("Research Agent failed to write dreaming research prompts project=%s: %s", project_id, de)

    logger.info(
        "[DREAM][RESEARCH] Completed project=%s items=%s topics=%s skipped_non_remote=%s",
        project_id,
        len(items),
        total_topics,
        skipped_non_remote,
    )

    return result
