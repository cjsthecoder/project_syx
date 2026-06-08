"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Helpers for project-level Dream summary card text.
"""

import logging
import os
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


def collect_research_topics(items: Iterable[Dict[str, Any]]) -> List[str]:
    """Collect distinct research topics from accepted dream items.

    Only topics with both a non-empty topic and summary are included, and
    duplicates are removed case-insensitively while preserving first-seen order.

    Args:
        items: Accepted dream items, each optionally carrying a "research" list.

    Returns:
        Ordered list of unique research topic strings.
    """
    topics: List[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        research_list = item.get("research") if isinstance(item.get("research"), list) else []
        for research in research_list:
            if not isinstance(research, dict):
                continue
            topic = str(research.get("research_topic") or "").strip()
            summary = str(research.get("research_summary") or "").strip()
            if not topic or not summary:
                continue
            key = topic.casefold()
            if key in seen:
                continue
            seen.add(key)
            topics.append(topic)
    return topics


def format_latest_sleep_summary(project_summary: str, accepted_items: Iterable[Dict[str, Any]]) -> str:
    """Build the dream summary card text from a project summary and research topics.

    Appends a "[RESEARCH]" block listing collected topics beneath the base
    summary; returns the research block alone when no base summary is present.

    Args:
        project_summary: Base project summary text.
        accepted_items: Accepted dream items used to derive research topics.

    Returns:
        The combined summary text.
    """
    base = str(project_summary or "").strip()
    topics = collect_research_topics(accepted_items)
    if not topics:
        return base
    research_block = "\n".join(["[RESEARCH]", *[f"Topic: {topic}\n" for topic in topics]])
    return f"{base}\n\n{research_block}" if base else research_block


def write_latest_sleep_summary(
    *,
    project_id: str,
    base_dir: str,
    project_summary: Optional[str],
    accepted_items: Iterable[Dict[str, Any]],
) -> None:
    """Write the latest dream summary card to ``latest_sleep_summary.md``.

    No-ops when the project summary is missing or blank. Write failures are
    logged as warnings and suppressed so summary persistence is best-effort.

    Args:
        project_id: Project identifier used for log context.
        base_dir: Directory in which the summary file is written.
        project_summary: Base project summary text; skipped when empty.
        accepted_items: Accepted dream items used to derive research topics.
    """
    if not isinstance(project_summary, str) or not project_summary.strip():
        return
    summary_path = os.path.join(base_dir, "latest_sleep_summary.md")
    body = format_latest_sleep_summary(project_summary, accepted_items).strip()
    try:
        with open(summary_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(body + "\n")
    except OSError as exc:
        logger.warning(
            "[DREAM][SUMMARY] Failed writing latest dream summary project=%s path=%s detail=%s",
            project_id,
            summary_path,
            exc,
            exc_info=True,
        )
