"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
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
from ..tagging.tagger import tag_pair
from ..utils.dream_summary import write_latest_sleep_summary
from ..utils.tokens import count_tokens

logger = logging.getLogger(__name__)


@dataclass
class DreamAutoAcceptResult:
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


def _assistant_response_for_item(item: Dict[str, Any]) -> str:
    assistant_resp = str(item.get("assistant_response") or "").strip()
    resolution = _normalize_resolution(item.get("source_resolution"))
    research_entries = []
    for r in _valid_research_entries(item):
        topic = r["research_topic"]
        summary = r["research_summary"]
        research_entries.append(f"[RESEARCH]\nTopic: {topic}\n{summary}".strip())

    if resolution != "answer_remote":
        return (assistant_resp or "(no summary)").strip()

    return "\n\n".join(research_entries).strip() or (assistant_resp or "(no summary)").strip()


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

    summary_path = os.path.join(base_dir, "dream_summary.txt")
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
        origin_text = str(item.get("origin_text") or "").strip()
        assistant_resp_full = _assistant_response_for_item(item)
        assistant_text_for_memory = _prune_assistant_for_tagger(
            project_id=project_id,
            assistant_text=assistant_resp_full,
            settings=get_settings(),
        )
        pair_text = f"User: {origin_text}\nAssistant: {assistant_text_for_memory}"
        tokens = int(count_tokens(pair_text))
        tags_meta = None
        try:
            tags_meta = tag_pair(origin_text, assistant_text_for_memory, previous_pair_text=previous_pair_text, project_id=project_id)
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
                "origin_text": origin_text,
                "assistant_resp_full": assistant_text_for_memory,
                "pair_text": pair_text,
                "tokens": tokens,
                "tags_meta": tags_meta,
                "tags_block": tags_block,
                "embed_text": embed_text,
            }
        )
        previous_pair_text = pair_text

    begin_dream_pair = "=== BEGIN DREAM PAIR ==="
    end_dream_pair = "=== END DREAM PAIR ==="
    failures: List[str] = []
    for rec in tagged:
        item = rec["item"]
        try:
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
                write_daily_txt=False,
                update_cache=False,
            )
            if not ok:
                raise RuntimeError("append_pair returned false")
            ts_local = time.strftime("%m-%d-%Y_%H:%M:%S", time.localtime())
            block = (
                f"{begin_dream_pair}\n"
                f"#timestamp: {ts_local}\n"
                f"#route: other\n"
                f"#keep: false\n"
                f"{rec['tags_block']}"
                f"\n"
                f"--- USER (data-message-author-role: user) ---\n"
                f"{rec['origin_text']}\n"
                f"\n"
                f"*** ASSISTANT (data-message-author-role: assistant) ***\n"
                f"{rec['assistant_resp_full']}\n"
                f"\n"
                f"{end_dream_pair}\n"
                f"\n"
            )
            with FileLock(summary_lock_path):
                with open(summary_path, "a", encoding="utf-8", newline="\n") as sf:
                    need_begin = (not os.path.isfile(summary_path)) or os.path.getsize(summary_path) == 0
                    if need_begin:
                        begin_date = time.strftime("%m/%d/%Y", time.localtime())
                        sf.write(f"=== BEGIN DREAM MEMORY: {begin_date} ===\n\n")
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

    result.processed = len(to_process)
    if result.accepted > 0:
        try:
            rebuild_daily_cache(project_id, reason="dream_auto_accept")
        except Exception as exc:
            failures.append(f"rebuild_cache: {exc}")
            logger.warning("[DREAM][AUTO_ACCEPT] Rebuild daily cache failed project=%s detail=%s", project_id, exc)

    if failures or result.accepted != len(to_process):
        result.errors = failures
        result.failed = len(to_process) - result.accepted + (1 if any(err.startswith("rebuild_cache:") for err in failures) else 0)
        result.renamed_bad_path = _rename_bad_dream(project_id, dream_path)
        return result

    with FileLock(summary_lock_path):
        try:
            if os.path.isfile(summary_path):
                end_date = time.strftime("%m/%d/%Y", time.localtime())
                with open(summary_path, "a", encoding="utf-8", newline="\n") as sf:
                    sf.write(f"=== END DREAM MEMORY: {end_date} ===\n")
        except OSError as exc:
            result.errors.append(f"write_end_footer: {exc}")
            result.failed = 1
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
