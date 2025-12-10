"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone

from ..config import get_settings
from .agents.questions_agent import run_questions_agent
from .agents.idea_agent import run_idea_agent
from .agents.research_agent import run_research_agent
from .context import build_dream_context, _strip_open_questions_section

logger = logging.getLogger(__name__)


def write_dream_output(project_id: str, dream_data: dict, project_summary_text: str) -> None:
    """
    Write the final dream.json file for a project.

    This function performs no reasoning; it only serializes the Dream data structure
    returned by the Research Agent along with the project summary text.
    """
    try:
        def _capitalize_first_letter(text: str) -> str:
            """Capitalize the first non-whitespace character if it is a letter."""
            if not isinstance(text, str):
                return text
            leading_len = len(text) - len(text.lstrip())
            prefix = text[:leading_len]
            rest = text[leading_len:]
            if not rest:
                return text
            first = rest[0]
            if first.isalpha():
                rest = first.upper() + rest[1:]
            return prefix + rest

        # Insert/overwrite project summary at top level.
        dream_data["project_summary"] = project_summary_text

        # Ensure date exists (MM/DD/YYYY using UTC, matching Idea Agent convention).
        date_val = dream_data.get("date")
        if not isinstance(date_val, str) or not date_val.strip():
            today = datetime.now(timezone.utc).strftime("%m/%d/%Y")
            dream_data["date"] = today

        # Ensure items exists and is a list.
        items = dream_data.get("items")
        if not isinstance(items, list):
            items = []
        # Normalize origin_text capitalization for display.
        normalized_items = []
        for it in items:
            if isinstance(it, dict):
                # Only adjust origin_text; leave other fields untouched.
                if "origin_text" in it:
                    it = {**it, "origin_text": _capitalize_first_letter(it.get("origin_text"))}
            normalized_items.append(it)
        dream_data["items"] = normalized_items

        # Serialize to JSON and write to memory/{project_id}/dream.json.
        dream_path = os.path.join("memory", project_id, "dream.json")
        with open(dream_path, "w", encoding="utf-8", newline="\n") as df:
            json.dump(dream_data, df, ensure_ascii=False, indent=2)

        logger.info("[DREAM] Dream output written successfully for project=%s", project_id)
    except Exception as e:
        # Log error but do not propagate.
        logger.error("Dream Writer failed for project=%s: %s", project_id, e, exc_info=True)


def _strip_and_persist_sleep_summary(project_id: str, summary_text: str) -> None:
    """
    Strip the [Open Questions] section from the in-memory sleep summary and
    persist the cleaned text back to memory/{project_id}/sleep_summary.txt.

    This is a refactor of the inline logic in dream(); behavior is unchanged.
    """
    try:
        cleaned = _strip_open_questions_section(summary_text or "")
        base_dir = os.path.join("memory", project_id)
        os.makedirs(base_dir, exist_ok=True)
        summary_path = os.path.join(base_dir, "sleep_summary.txt")
        with open(summary_path, "w", encoding="utf-8", newline="\n") as sf:
            sf.write(cleaned)
        logger.info(
            "[DREAM] Stripped [Open Questions] section from sleep_summary.txt for project=%s",
            project_id,
        )
    except Exception as se:
        logger.warning(
            "project=%s failed to strip [Open Questions] from sleep_summary.txt: %s",
            project_id,
            se,
        )


def dream(project_id: str, summary_text: str) -> None:
    """
    Execute Dream cycle for a project after Sleep completes.

    This function processes questions and builds dream context synchronously.

    Args:
        project_id: Project identifier
        summary_text: The formatted sleep_summary.txt content (in-memory string)

    Returns:
        None (exceptions are logged but not raised)
    """
    try:
        settings = get_settings()
        if not settings.enable_dream:
            return
        t0 = time.monotonic()
        logger.info("[DREAM] Starting dreaming for project=%s", project_id)
        try:
            # Process questions synchronously and keep results in memory.
            questions_data = run_questions_agent(project_id, summary_text)

            # After extracting questions, strip the [Open Questions] section from the
            # on-disk sleep_summary.txt so that long-term summaries and RAG do not
            # contain the JSON appendix (questions are now represented in-memory via questions_data).
            _strip_and_persist_sleep_summary(project_id, summary_text)

            # Build dream context after questions are processed and sleep_summary.txt
            dream_context, project_summary_text = build_dream_context(project_id, questions_data)

            # Run Idea Agent on the constructed dream context.
            ideas = run_idea_agent(project_id, dream_context)

            # Run Research Agent on the Idea Agent output, using the project summary text.
            dream_data = run_research_agent(project_id, ideas, project_summary_text)

            # Serialize final Dream output to disk for downstream consumers (e.g., GUI).
            write_dream_output(project_id, dream_data, project_summary_text)

            # Currently, dream_data is kept in-memory for potential downstream use.
            _ = dream_data  # placeholder to avoid lints until consumed

            elapsed = time.monotonic() - t0
            logger.info("[DREAM] Project %s complete in duration=%.2fs", project_id, elapsed)
        except Exception as de:
            logger.error("project=%s %s", project_id, de, exc_info=True)
    except Exception:
        # Non-fatal; continue loop
        pass



