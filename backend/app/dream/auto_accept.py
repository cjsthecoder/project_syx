"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Auto-accept pending dream items as Dream memory during the Sleep cycle.

Reads each project's dream.json, tags and persists every processable item as a
kept=False Dream memory, renders the dream summary markdown, and rebuilds the
daily cache, mirroring the manual Dream Remember path independently of the UI.
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from filelock import FileLock

from ..core.config import get_settings
from ..core.memory import _prune_assistant_for_tagger
from ..rag.daily_store import append_pair, rebuild_daily_cache
from ..rag.syx_memory_artifact import (
    generate_memory_id,
    render_artifact_header,
    render_memory_entry,
    snake_case_value,
    topics_to_list,
)
from ..tagging.tagger import tag_pair
from ..utils.dream_summary import write_latest_sleep_summary
from ..utils.tokens import count_tokens

logger = logging.getLogger(__name__)


def _origin_memory_ids(item: Dict[str, Any]) -> List[str]:
    """Collect de-duplicated origin/memory ids from an item and its metadata."""
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


def _dream_markdown_block(
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
    origin_ids = _origin_memory_ids(item)
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


@dataclass
class DreamAutoAcceptResult:
    """Outcome counters and artifacts for a single auto-accept run."""

    processed: int = 0
    accepted: int = 0
    failed: int = 0
    deleted_dream: bool = False
    renamed_bad_path: Optional[str] = None
    filtered_remote_without_research: int = 0
    errors: List[str] = field(default_factory=list)


def _normalize_resolution(value: Any) -> str:
    res = str(value or "").strip().lower()
    if res in {"ignore", "answer_local", "answer_remote"}:
        return res
    return ""


def _valid_research_entries(item: Dict[str, Any]) -> List[Dict[str, str]]:
    """Return research entries that have both a non-empty topic and summary."""
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


def _filter_remote_without_research_with_rows(
    items: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split items into kept and dropped, removing answer_remote items lacking research.

    Returns:
        Tuple of (kept_items, dropped_rows) where dropped_rows describe each
        answer_remote item discarded for having no valid research entries.
    """
    kept: List[Dict[str, Any]] = []
    dropped_rows: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        resolution = _normalize_resolution(it.get("source_resolution"))
        if resolution != "answer_remote":
            kept.append(it)
            continue
        valid_research = _valid_research_entries(it)
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


def _bad_dream_path(base_dir: str) -> str:
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    candidate = os.path.join(base_dir, f"bad_dream_{ts}.json")
    if not os.path.exists(candidate):
        return candidate
    return os.path.join(base_dir, f"bad_dream_{ts}_{time.time_ns()}.json")


def _rename_bad_dream(project_id: str, dream_path: str) -> Optional[str]:
    bad_path = _bad_dream_path(os.path.dirname(dream_path))
    try:
        os.replace(dream_path, bad_path)
        logger.warning(
            "[DREAM][AUTO_ACCEPT] Renamed failed dream.json project=%s bad_path=%s",
            project_id,
            bad_path,
        )
        return bad_path
    except OSError as exc:
        logger.warning(
            "[DREAM][AUTO_ACCEPT] Failed renaming bad dream.json project=%s path=%s detail=%s",
            project_id,
            dream_path,
            exc,
            exc_info=True,
        )
        return None


def _delete_dream_file(project_id: str, dream_path: str) -> bool:
    try:
        if os.path.isfile(dream_path):
            os.remove(dream_path)
        return True
    except OSError as exc:
        logger.warning(
            "[DREAM][AUTO_ACCEPT] Failed deleting dream.json project=%s path=%s detail=%s",
            project_id,
            dream_path,
            exc,
            exc_info=True,
        )
        return False


def _format_tags_block(tags_meta: Optional[Dict[str, Any]]) -> str:
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
        logger.warning("[DREAM][AUTO_ACCEPT] Failed formatting tags block detail=%s", exc)
        return ""


def _memory_pairs_for_item(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Expand an item into the user/assistant memory pairs to persist.

    answer_remote items yield one pair per valid research entry; other items
    yield a single pair from origin_text and assistant_response.
    """
    resolution = _normalize_resolution(item.get("source_resolution"))
    if resolution == "answer_remote":
        pairs = []
        for r in _valid_research_entries(item):
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


def auto_accept_dreams(project_id: str) -> DreamAutoAcceptResult:
    """
    Process every pending dream.json item as remembered Dream memory during Sleep.

    This mirrors the manual Dream Remember persistence path, except auto-accepted
    entries are stored with keep=False and the helper runs independently of the UI.
    """
    result = DreamAutoAcceptResult()
    base_dir = os.path.join(get_settings().memory_root, project_id)
    dream_path = os.path.join(base_dir, "dream.json")
    if not os.path.isfile(dream_path):
        logger.debug("[DREAM][AUTO_ACCEPT] No dream.json to process project=%s", project_id)
        return result

    try:
        with open(dream_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        result.errors.append(f"read_dream_json: {exc}")
        result.renamed_bad_path = _rename_bad_dream(project_id, dream_path)
        result.failed = 1
        return result

    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        result.errors.append("invalid_dream_json_shape")
        result.renamed_bad_path = _rename_bad_dream(project_id, dream_path)
        result.failed = 1
        return result
    entries: List[Dict[str, Any]] = [it for it in data.get("items", []) if isinstance(it, dict)]
    to_process, dropped_rows = _filter_remote_without_research_with_rows(entries)
    result.filtered_remote_without_research = len(dropped_rows)

    if not to_process:
        logger.debug(
            "[DREAM][AUTO_ACCEPT] No processable dream items project=%s total_items=%s filtered_remote_without_research=%s",
            project_id,
            len(entries),
            result.filtered_remote_without_research,
        )
        write_latest_sleep_summary(
            project_id=project_id,
            base_dir=base_dir,
            project_summary=data.get("project_summary"),
            accepted_items=[],
        )
        result.deleted_dream = _delete_dream_file(project_id, dream_path)
        if not result.deleted_dream:
            result.failed = 1
            result.errors.append("delete_dream_json_failed")
        return result

    summary_path = os.path.join(base_dir, "dream_summary.md")
    state_dir = os.path.join(base_dir, "state")
    os.makedirs(state_dir, exist_ok=True)
    summary_lock_path = os.path.join(state_dir, "dream_summary.lock")
    legacy_summary_lock_path = os.path.join(base_dir, "dream_summary.lock")
    if os.path.isfile(legacy_summary_lock_path) and not os.path.exists(summary_lock_path):
        try:
            os.replace(legacy_summary_lock_path, summary_lock_path)
        except OSError as exc:
            logger.warning("dream auto-accept lock migration failed project_id=%s detail=%s", project_id, exc)

    tagged: List[Dict[str, Any]] = []
    previous_pair_text: Optional[str] = None
    for item in to_process:
        for pair in _memory_pairs_for_item(item):
            user_text = str(pair.get("user_text") or "").strip()
            assistant_resp_full = str(pair.get("assistant_text") or "").strip()
            if not user_text or not assistant_resp_full:
                logger.warning(
                    "[DREAM][AUTO_ACCEPT] Skipping empty memory pair project=%s item_id=%s",
                    project_id,
                    str(item.get("id") or ""),
                )
                continue
            assistant_text_for_memory = _prune_assistant_for_tagger(
                project_id=project_id,
                assistant_text=assistant_resp_full,
                settings=get_settings(),
            )
            pair_text = f"User: {user_text}\nAssistant: {assistant_text_for_memory}"
            tokens = int(count_tokens(pair_text))
            tags_meta = None
            try:
                tags_meta = tag_pair(user_text, assistant_text_for_memory, previous_pair_text=previous_pair_text, project_id=project_id)
            except Exception as exc:
                logger.warning(
                    "[DREAM][AUTO_ACCEPT] Tagger failed; persisting without tags project=%s item_id=%s detail=%s",
                    project_id,
                    str(item.get("id") or ""),
                    exc,
                )
            tags_block = _format_tags_block(tags_meta)
            embed_text = (tags_block + pair_text) if tags_block else pair_text
            tagged.append(
                {
                    "item": item,
                    "user_text": user_text,
                    "assistant_resp_full": assistant_text_for_memory,
                    "pair_text": pair_text,
                    "tokens": tokens,
                    "tags_meta": tags_meta,
                    "tags_block": tags_block,
                    "embed_text": embed_text,
                }
            )
            previous_pair_text = pair_text

    failures: List[str] = []
    for rec in tagged:
        item = rec["item"]
        try:
            ts_local = time.strftime("%m-%d-%Y_%H:%M:%S", time.localtime())
            accepted_item_id = str(item.get("id") or "").strip() or None
            dream_output_type = snake_case_value(item.get("origin_type") or item.get("source_resolution")) or None
            origin_memory_ids = _origin_memory_ids(item)
            semantic_handle = None
            if isinstance(rec["tags_meta"], dict) and rec["tags_meta"].get("semantic_handle") is not None:
                semantic_handle = str(rec["tags_meta"].get("semantic_handle") or "").strip() or None
            memory_id = generate_memory_id(
                project_id=project_id,
                timestamp=ts_local,
                source="dream",
                entry_type="dream_output",
                route="other",
                semantic_handle=semantic_handle,
                dream_output_type=dream_output_type,
                accepted_item_id=accepted_item_id,
                origin_memory_ids=origin_memory_ids,
                dream_content=rec["assistant_resp_full"],
            )
            ok = append_pair(
                project_id,
                rec["pair_text"],
                -1,
                -2,
                int(rec["tokens"]),
                namespace="other",
                keep=False,
                embed_override=rec["embed_text"],
                tags_meta=rec["tags_meta"],
                write_daily_md=False,
                update_cache=False,
                created_at_iso_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                memory_id=memory_id,
                entry_type="dream_output",
                source="dream",
                source_agent="syx",
                source_scope="dream",
                current_scope="dream",
                accepted_item_id=accepted_item_id,
                dream_output_type=dream_output_type,
                origin_memory_ids=origin_memory_ids,
            )
            if not ok:
                raise RuntimeError("append_pair returned false")
            block = _dream_markdown_block(
                memory_id=memory_id,
                timestamp=ts_local,
                route="other",
                keep=False,
                tags_meta=rec["tags_meta"],
                item=item,
                user_text=rec["user_text"],
                assistant_text=rec["assistant_resp_full"],
            )
            with FileLock(summary_lock_path):
                with open(summary_path, "a", encoding="utf-8", newline="\n") as sf:
                    need_begin = (not os.path.isfile(summary_path)) or os.path.getsize(summary_path) == 0
                    if need_begin:
                        memory_date = time.strftime("%m-%d-%Y", time.localtime())
                        sf.write(render_artifact_header(
                            artifact_type="dream_memory",
                            project_id=project_id,
                            memory_date=memory_date,
                        ))
                    sf.write(block)
            result.accepted += 1
        except Exception as exc:
            item_id = str(item.get("id") or "")
            failures.append(f"{item_id or 'unknown'}: {exc}")
            logger.warning(
                "[DREAM][AUTO_ACCEPT] Failed persisting dream item project=%s item_id=%s detail=%s",
                project_id,
                item_id,
                exc,
                exc_info=True,
            )

    result.processed = len(tagged)
    if result.accepted > 0:
        try:
            rebuild_daily_cache(project_id, reason="dream_auto_accept")
        except Exception as exc:
            failures.append(f"rebuild_cache: {exc}")
            logger.warning("[DREAM][AUTO_ACCEPT] Rebuild daily cache failed project=%s detail=%s", project_id, exc)

    if failures or result.accepted != len(tagged):
        result.errors = failures
        result.failed = len(tagged) - result.accepted + (1 if any(err.startswith("rebuild_cache:") for err in failures) else 0)
        result.renamed_bad_path = _rename_bad_dream(project_id, dream_path)
        return result

    write_latest_sleep_summary(
        project_id=project_id,
        base_dir=base_dir,
        project_summary=data.get("project_summary"),
        accepted_items=to_process,
    )

    result.deleted_dream = _delete_dream_file(project_id, dream_path)
    if not result.deleted_dream:
        result.failed = 1
        result.errors.append("delete_dream_json_failed")
        result.renamed_bad_path = _rename_bad_dream(project_id, dream_path)
    else:
        logger.info(
            "[DREAM][AUTO_ACCEPT] Processed dream.json project=%s accepted=%s filtered_remote_without_research=%s",
            project_id,
            result.accepted,
            result.filtered_remote_without_research,
        )
    return result
