"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Shared helpers for persisting dream items as Dream memory.

These pure helpers are used by both the manual Dream Remember path
(``api/projects.py``) and the Sleep-cycle auto-accept path (``dream/auto_accept.py``)
to parse dream items, expand them into memory pairs, filter remote items that
lack research, format tagger metadata, and render memory-artifact markdown
blocks. They contain no module-specific logging prefixes or persistence side
effects so both callers can share identical behavior.
"""
import logging
from typing import Any, Dict, List, Optional

from ..rag.syx_memory_artifact import (
    render_memory_entry,
    snake_case_value,
    topics_to_list,
)

logger = logging.getLogger(__name__)


def origin_memory_ids(item: Dict[str, Any]) -> List[str]:
    """Collect de-duplicated origin/memory ids from an item and its metadata.

    Gathers ids from the item's top-level keys and nested ``metadata`` block
    (single and list forms), preserving first-seen order.

    Args:
        item: Dream item whose top-level and ``metadata`` id fields are scanned.

    Returns:
        Ordered, de-duplicated list of non-empty origin/memory id strings.
    """
    values: List[str] = []
    for key in ("origin_memory_id", "memory_id"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            values.append(val.strip())
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        val = metadata.get("origin_memory_id") or metadata.get("memory_id")
        if isinstance(val, str) and val.strip():
            values.append(val.strip())
        vals = metadata.get("origin_memory_ids")
        if isinstance(vals, list):
            values.extend(str(v).strip() for v in vals if str(v or "").strip())
    return list(dict.fromkeys(values))


def normalize_resolution(value: Any) -> str:
    """Normalize a dream source resolution to a known value, or empty string.

    Recognizes ``ignore``, ``answer_local``, and ``answer_remote``; any other
    value yields ``""``.

    Args:
        value: Raw source-resolution value (any type) to normalize.

    Returns:
        The lowercased recognized resolution, or ``""`` when unrecognized.
    """
    res = str(value or "").strip().lower()
    if res in {"ignore", "answer_local", "answer_remote"}:
        return res
    return ""


def valid_research_entries(item: Dict[str, Any]) -> List[Dict[str, str]]:
    """Return research entries that have both a non-empty topic and summary.

    Args:
        item: Dream item whose ``research`` list is filtered.

    Returns:
        List of ``{"research_topic", "research_summary"}`` dicts; entries missing
        either field are dropped.
    """
    out: List[Dict[str, str]] = []
    research_list = item.get("research") if isinstance(item.get("research"), list) else []
    for r in research_list:
        if not isinstance(r, dict):
            continue
        topic = str(r.get("research_topic") or "").strip()
        summary = str(r.get("research_summary") or "").strip()
        if not topic or not summary:
            continue
        out.append({"research_topic": topic, "research_summary": summary})
    return out


def dream_memory_pairs_for_item(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Expand a dream item into the user/assistant memory pairs to persist.

    ``answer_remote`` items yield one pair per valid research entry (topic as
    user text, summary as assistant text); other items yield a single pair from
    ``origin_text`` and ``assistant_response``.

    Args:
        item: Dream item to expand into persistable memory pairs.

    Returns:
        List of ``{"item", "user_text", "assistant_text"}`` dicts ready for
        tagging and persistence.
    """
    resolution = normalize_resolution(item.get("source_resolution"))
    if resolution == "answer_remote":
        pairs = []
        for r in valid_research_entries(item):
            pairs.append(
                {
                    "item": item,
                    "user_text": r["research_topic"],
                    "assistant_text": f"[RESEARCH]\n{r['research_summary']}".strip(),
                }
            )
        return pairs

    return [
        {
            "item": item,
            "user_text": str(item.get("origin_text") or "").strip(),
            "assistant_text": (str(item.get("assistant_response") or "").strip() or "(no summary)").strip(),
        }
    ]


def filter_remote_without_research(items: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
    """Drop ``answer_remote`` items that lack valid research entries.

    Args:
        items: Dream items to filter; non-dict entries are skipped.

    Returns:
        Tuple of ``(kept_items, dropped_count)``.
    """
    kept: List[Dict[str, Any]] = []
    dropped = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        resolution = normalize_resolution(it.get("source_resolution"))
        if resolution == "answer_remote" and not valid_research_entries(it):
            dropped += 1
            continue
        kept.append(it)
    return kept, dropped


def filter_remote_without_research_with_rows(
    items: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split items into kept and dropped, removing answer_remote items lacking research.

    Like :func:`filter_remote_without_research`, but instead of a count it
    returns detailed rows describing each dropped item for the persist-filter
    report.

    Args:
        items: Dream items to partition; non-dict entries are skipped.

    Returns:
        Tuple of ``(kept_items, dropped_rows)`` where each dropped row records
        the item id, origin text, resolution, research count, and drop reason.
    """
    kept: List[Dict[str, Any]] = []
    dropped_rows: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        resolution = normalize_resolution(it.get("source_resolution"))
        if resolution != "answer_remote":
            kept.append(it)
            continue
        valid_research = valid_research_entries(it)
        if valid_research:
            kept.append(it)
            continue
        dropped_rows.append(
            {
                "id": str(it.get("id") or ""),
                "origin_text": str(it.get("origin_text") or "").strip(),
                "source_resolution": resolution,
                "research_count": 0,
                "reason": "remote_without_research",
            }
        )
    return kept, dropped_rows


def format_tags_block(tags_meta: Optional[Dict[str, Any]]) -> str:
    """Render tagger metadata into a ``#topics/#intent/#type`` header block.

    Args:
        tags_meta: Tagger output dict; non-dict values yield an empty block.

    Returns:
        A trailing-newline-terminated tag block, or an empty string when no
        usable tags are present or formatting fails.
    """
    if not isinstance(tags_meta, dict):
        return ""
    try:
        topics = str(tags_meta.get("topics", "") or "")
        intent = str(tags_meta.get("intent", "") or "")
        tag_type = str(tags_meta.get("type", "") or "")
        semantic_handle = tags_meta.get("semantic_handle", None)
        lines = [f"#topics: {topics}", f"#intent: {intent}", f"#type: {tag_type}"]
        if semantic_handle is not None:
            lines.append(f"#semantic_handle: {str(semantic_handle) if semantic_handle is not None else ''}")
        return "\n".join(lines) + "\n"
    except Exception as exc:
        logger.warning("dream: failed formatting tags block detail=%s", exc)
        return ""


def dream_markdown_block(
    *,
    memory_id: str,
    timestamp: str,
    route: str,
    keep: bool,
    tags_meta: Optional[Dict[str, Any]],
    item: Dict[str, Any],
    user_text: str,
    assistant_text: str,
) -> str:
    """Render a single Dream memory entry as a markdown block with metadata.

    Assembles entry metadata (memory id, dream provenance, route, topics,
    semantic handle) and delegates to ``render_memory_entry`` to produce the
    persisted block.

    Args:
        memory_id: Stable identifier recorded in the entry metadata.
        timestamp: Local timestamp string for the entry.
        route: Retrieval route label stored in metadata.
        keep: Whether the entry is flagged as kept memory.
        tags_meta: Optional tagger output supplying topics and semantic handle;
            non-dict values are treated as empty.
        item: Source Dream item contributing id/type/origin metadata.
        user_text: User-side text of the persisted pair.
        assistant_text: Assistant-side text of the persisted pair.

    Returns:
        Rendered markdown memory entry string.
    """
    tags = tags_meta if isinstance(tags_meta, dict) else {}
    metadata: Dict[str, Any] = {
        "memory_id": memory_id,
        "entry_type": "dream_output",
        "source": "dream",
        "source_agent": "syx",
        "source_scope": "dream",
        "current_scope": "dream",
        "timestamp": timestamp,
        "route": route,
        "keep": bool(keep),
    }
    accepted_item_id = str(item.get("id") or "").strip()
    if accepted_item_id:
        metadata["accepted_item_id"] = accepted_item_id
    dream_output_type = snake_case_value(item.get("origin_type") or item.get("source_resolution"))
    if dream_output_type:
        metadata["dream_output_type"] = dream_output_type
    origin_ids = origin_memory_ids(item)
    if origin_ids:
        metadata["origin_memory_ids"] = origin_ids
    topics = topics_to_list(tags.get("topics"))
    if topics:
        metadata["topics"] = topics
    semantic_handle = tags.get("semantic_handle")
    if semantic_handle is not None and str(semantic_handle).strip():
        metadata["semantic_handle"] = str(semantic_handle).strip()
    return render_memory_entry(
        memory_id=memory_id,
        metadata=metadata,
        user_text=user_text,
        assistant_text=assistant_text,
    )
