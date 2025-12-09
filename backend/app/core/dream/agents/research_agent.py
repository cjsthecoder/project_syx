"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from ...config import get_settings
from app.utils.debug_utils import write_debug_file
from ..llm import dream_llm_call
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
) -> Dict[str, Any]:
    """
    Run the Research Agent for a project.

    This function:
      - Iterates Idea Agent entries and their recommended_research topics.
      - Builds a research prompt for each topic.
      - Invokes the Dream LLM with the same configuration used by fetch_remote_research.
      - Parses plain-text results into Research Entry dicts and appends them under "research".

    Args:
        project_id: Project identifier.
        idea_data: Parsed JSON from the Idea Agent: { "date": "...", "items": [ ... ] }.
        project_summary_text: Short textual description of the project from the Dream Context Builder.

    Returns:
        Augmented JSON object with the same top-level shape as idea_data, where each item
        may have an additional "research": [ ... ] list (and an optional "research_failed" flag).
    """
    settings = get_settings()
    logger.info("[DREAM][RESEARCH] Start project=%s", project_id)

    date_val = idea_data.get("date")
    if not isinstance(date_val, str) or not date_val.strip():
        # Keep contract: always return a date string; fall back to today's date if missing.
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

    for entry in items:
        if not isinstance(entry, dict):
            continue

        entry_id = entry.get("id")
        origin_text = entry.get("origin_text", "") or ""
        origin_type = entry.get("origin_type", "") or ""
        assistant_response = entry.get("assistant_response", "") or ""

        metadata = entry.get("metadata") or {}
        if not isinstance(metadata, dict):
            # Idea Agent should already have enforced this, but be defensive.
            entry["research"] = []
            entry["research_failed"] = True
            continue

        theme = metadata.get("theme", "") or ""
        recommended = metadata.get("recommended_research")

        # If no recommended research, attach empty research list and continue.
        if not recommended:
            entry["research"] = []
            continue

        # Normalize recommended_research to a list of raw elements.
        topics_list: List[Any]
        if isinstance(recommended, list):
            topics_list = recommended
        else:
            topics_list = [recommended]

        entry_research: List[Dict[str, Any]] = []
        entry_failures = 0

        for raw_topic in topics_list:
            # Treat each element as a raw string topic.
            topic = str(raw_topic).strip()
            if not topic:
                continue

            total_topics += 1

            # Build the research prompt.
            prompt = build_research_prompt(
                project_summary_text=project_summary_text or "",
                origin_text=origin_text,
                origin_type=origin_type,
                assistant_response=assistant_response,
                research_topic=topic,
                theme=theme,
            )

            # Debug log: only log the topic label, not the full prompt body.
            logger.debug("Research Agent prompt topic=%s", topic)

            # Call Dream LLM with same configuration as fetch_remote_research (dream_* settings).
            try:
                raw = dream_llm_call(prompt, max_output_tokens=settings.dream_max_tokens)
            except Exception as e:  # Defensive; dream_llm_call already catches
                logger.error(
                    "Research Agent LLM invocation failed project=%s topic=%s: %s",
                    project_id,
                    topic,
                    e,
                    exc_info=True,
                )
                entry_failures += 1
                continue

            raw_text = raw or ""

            # Parse plain-text output according to FR-4.3.6.
            lines = [ln.strip() for ln in raw_text.splitlines()]
            non_empty = [ln for ln in lines if ln]
            if not non_empty:
                logger.warning(
                    "Research Agent empty output project=%s topic=%s; skipping topic.",
                    project_id,
                    topic,
                )
                entry_failures += 1
                continue

            # First non-empty line may be a header; authoritative research_topic remains the original.
            header = non_empty[0]
            summary_lines = non_empty[1:] or []
            summary = "\n".join(summary_lines).strip()

            # If no summary body was produced, treat parsing as failed.
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

        # Attach research results to the entry.
        entry["research"] = entry_research

        # If all topics for this entry failed, mark a lightweight failure flag.
        if topics_list and not entry_research:
            entry["research_failed"] = True

    # Build final result dict, mirroring the (possibly augmented) Idea Agent output.
    result: Dict[str, Any] = {"date": date_str, "items": items}

    # Write debug_research.txt if enabled (formatted JSON as plain text).
    try:
        debug_payload = json.dumps(result, ensure_ascii=False, indent=2)
        write_debug_file(project_id, "debug_research.txt", debug_payload)
    except Exception as de:
        logger.warning("Research Agent failed to write debug_research.txt project=%s: %s", project_id, de)

    logger.info(
        "[DREAM][RESEARCH] Completed project=%s items=%s topics=%s",
        project_id,
        len(items),
        total_topics,
    )

    # Return augmented structure (same top-level date, mutated items list).
    return result



