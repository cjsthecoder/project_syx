"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from ..config import get_settings
from ..debug_utils import write_debug_file
from ..dream_llm import dream_llm_call
from .prompts.idea_prompts import build_idea_prompt

logger = logging.getLogger(__name__)


def _today_mmddyyyy() -> str:
    """Return today's date in MM/DD/YYYY format (UTC)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%m/%d/%Y")


def _normalize_recommended_research(value: Any) -> List[Any] | None:
    """
    Normalize recommended_research according to FR-4.2.1.7.

    Returns:
        - list value (possibly wrapped/normalized) on success
        - None if the field is considered unusable and the item should be skipped
    """
    # Missing handling is done by caller (skip item).
    # If already a list, use as-is.
    if isinstance(value, list):
        return value

    # Empty-ish values → normalize to empty list
    if value in ("", None) or (isinstance(value, dict) and not value):
        return []

    # Non-list but present (string/dict/number/etc.) → wrap into a one-element list
    return [value]


def run_idea_agent(project_id: str, dream_context: str) -> Dict[str, Any]:
    """
    Run the Idea Agent for a project.

    This function:
      - Builds the idea prompt from dream_context.
      - Invokes the Dream LLM via dream_llm_call.
      - Parses and validates the returned JSON per FR-4.2.1.

    Args:
        project_id: Project identifier
        dream_context: Fully constructed dream context string

    Returns:
        Dict with shape: { "date": "MM/DD/YYYY", "items": [ ...validated entries... ] }
    """
    settings = get_settings()
    logger.info("[DREAM][IDEA] Start project=%s", project_id)

    # Build prompt
    prompt = build_idea_prompt(dream_context)

    # Debug: write prompt if enabled
    write_debug_file(project_id, "debug_idea_prompt.txt", prompt)

    # Call Dream LLM
    try:
        raw = dream_llm_call(prompt, max_output_tokens=settings.dream_max_tokens)
    except Exception as e:  # Defensive, though dream_llm_call already catches
        logger.error("Idea Agent LLM invocation failed project=%s: %s", project_id, e, exc_info=True)
        return {"date": _today_mmddyyyy(), "items": []}

    # Debug: write raw response if enabled
    write_debug_file(project_id, "debug_idea_raw_response.txt", raw or "")

    # Parse JSON
    try:
        data = json.loads(raw or "{}")
    except Exception as e:
        logger.error("Idea Agent JSON parse failed project=%s: %s", project_id, e)
        return {"date": _today_mmddyyyy(), "items": []}

    # Top-level date handling
    date_val = data.get("date")
    if not isinstance(date_val, str) or not date_val.strip():
        date_str = _today_mmddyyyy()
    else:
        date_str = date_val

    # Top-level items handling
    items_raw = data.get("items")
    if isinstance(items_raw, list):
        candidates = items_raw
    elif isinstance(items_raw, dict):
        candidates = [items_raw]
    else:
        logger.warning("Idea Agent items invalid or missing project=%s; returning empty items.", project_id)
        return {"date": date_str, "items": []}

    validated: List[Dict[str, Any]] = []
    for idx, item in enumerate(candidates):
        if not isinstance(item, dict):
            logger.warning("Idea Agent skipping non-dict item index=%s project=%s", idx, project_id)
            continue

        # Required top-level fields
        required_fields = [
            "id",
            "agent",
            "timestamp",
            "origin_text",
            "origin_type",
            "assistant_response",
            "context_link",
        ]
        if any(k not in item for k in required_fields):
            logger.warning("Idea Agent skipping item missing required fields index=%s project=%s", idx, project_id)
            continue

        # Agent: auto-correct to "idea_agent"
        item["agent"] = "idea_agent"

        # origin_type enum validation
        origin_type = item.get("origin_type")
        if origin_type not in ("open_question", "insight", "contradiction", "new_topic"):
            logger.warning(
                "Idea Agent skipping item with invalid origin_type=%s index=%s project=%s",
                origin_type,
                idx,
                project_id,
            )
            continue

        # Metadata and nested fields
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            logger.warning("Idea Agent skipping item with missing/invalid metadata index=%s project=%s", idx, project_id)
            continue

        # Required metadata keys
        if any(k not in metadata for k in ("priority", "confidence", "theme", "recommended_research")):
            logger.warning(
                "Idea Agent skipping item with incomplete metadata index=%s project=%s", idx, project_id
            )
            continue

        # Priority: positive integer (>=1)
        priority_val = metadata.get("priority")
        try:
            priority_int = int(priority_val)
        except Exception:
            logger.warning(
                "Idea Agent skipping item with non-integer priority=%s index=%s project=%s",
                priority_val,
                idx,
                project_id,
            )
            continue
        if priority_int < 1:
            logger.warning(
                "Idea Agent skipping item with invalid priority=%s index=%s project=%s",
                priority_int,
                idx,
                project_id,
            )
            continue
        metadata["priority"] = priority_int

        # Confidence: must exist; range hints are in prompt, but we don't hard-enforce
        if "confidence" not in metadata:
            logger.warning(
                "Idea Agent skipping item with missing confidence index=%s project=%s", idx, project_id
            )
            continue

        # recommended_research normalization
        rec_raw = metadata.get("recommended_research", None)
        if rec_raw is None:
            logger.warning(
                "Idea Agent skipping item missing recommended_research index=%s project=%s", idx, project_id
            )
            continue
        rec_norm = _normalize_recommended_research(rec_raw)
        if rec_norm is None:
            logger.warning(
                "Idea Agent skipping item with unusable recommended_research index=%s project=%s",
                idx,
                project_id,
            )
            continue
        metadata["recommended_research"] = rec_norm

        # String fields must exist; emptiness is allowed
        for field in ("origin_text", "assistant_response", "context_link", "theme"):
            if field == "theme":
                # theme lives under metadata
                if field not in metadata:
                    logger.warning(
                        "Idea Agent skipping item missing theme in metadata index=%s project=%s",
                        idx,
                        project_id,
                    )
                    break
                # empty strings are allowed
            else:
                if field not in item:
                    logger.warning(
                        "Idea Agent skipping item missing field %s index=%s project=%s",
                        field,
                        idx,
                        project_id,
                    )
                    break
        else:
            # All checks passed; keep item
            validated.append(item)
            continue

        # If we broke out of the loop above, continue to next item
        continue

    if not validated:
        logger.info("[DREAM][IDEA] Completed project=%s count=0", project_id)
        return {"date": date_str, "items": []}

    logger.info("[DREAM][IDEA] Completed project=%s count=%s", project_id, len(validated))
    return {"date": date_str, "items": validated}


