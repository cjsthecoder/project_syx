"""
Helpers for project-level Dream summary card text.
"""

import logging
import os
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


def collect_research_topics(items: Iterable[Dict[str, Any]]) -> List[str]:
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
    if not isinstance(project_summary, str) or not project_summary.strip():
        return
    summary_path = os.path.join(base_dir, "latest_sleep_summary.txt")
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
