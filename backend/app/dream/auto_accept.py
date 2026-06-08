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
    snake_case_value,
)
from ..tagging.tagger import tag_pair
from ..utils.dream_summary import write_latest_sleep_summary
from ..utils.tokens import count_tokens
from .common import (
    dream_markdown_block,
    dream_memory_pairs_for_item,
    filter_remote_without_research_with_rows,
    format_tags_block,
    origin_memory_ids,
)

logger = logging.getLogger(__name__)


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


def _bad_dream_path(base_dir: str) -> str:
    """Build a unique timestamped path for quarantining a failed ``dream.json``.

    Args:
        base_dir: Project memory directory where the bad file is placed.

    Returns:
        A non-colliding ``bad_dream_*.json`` path within ``base_dir``.
    """
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    candidate = os.path.join(base_dir, f"bad_dream_{ts}.json")
    if not os.path.exists(candidate):
        return candidate
    return os.path.join(base_dir, f"bad_dream_{ts}_{time.time_ns()}.json")


def _rename_bad_dream(project_id: str, dream_path: str) -> Optional[str]:
    """Quarantine a failed ``dream.json`` by renaming it aside.

    Args:
        project_id: Project owning the dream file (used for logging).
        dream_path: Path to the ``dream.json`` to move aside.

    Returns:
        The new quarantine path on success, or ``None`` when the rename fails.
    """
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
    """Delete the project's ``dream.json`` after successful processing.

    Args:
        project_id: Project owning the dream file (used for logging).
        dream_path: Path to the ``dream.json`` to remove.

    Returns:
        True when the file is absent or removed; False when deletion fails.
    """
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


def _prepare_dream_summary_paths(base_dir: str, project_id: str) -> tuple[str, str]:
    """Resolve dream-summary paths, create the state dir, and migrate legacy locks.

    Args:
        base_dir: Project memory directory holding the dream artifacts.
        project_id: Project whose summary paths are prepared (for logging).

    Returns:
        Tuple of ``(summary_path, summary_lock_path)``. A legacy lock left in
        ``base_dir`` is best-effort moved under ``state/``.
    """
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
    return summary_path, summary_lock_path


def _tag_dream_pairs(project_id: str, to_process: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Expand and tag processable dream items into persistable memory pairs.

    Pass 1 of the auto-accept flow: each item is expanded into user/assistant
    pairs, the assistant side is pruned for the tagger, the pair is tagged
    (best-effort; a tagger failure persists without tags), and tags/embed text
    are precomputed. Empty pairs are skipped.

    Args:
        project_id: Project whose pairs are being tagged.
        to_process: Dream items that survived remote-without-research filtering.

    Returns:
        List of tagged-pair records carrying the source item, texts, token
        count, tagger metadata, and the embed text to persist.
    """
    tagged: List[Dict[str, Any]] = []
    previous_pair_text: Optional[str] = None
    for item in to_process:
        for pair in dream_memory_pairs_for_item(item):
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
            tags_block = format_tags_block(tags_meta)
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
    return tagged


def _persist_tagged_pairs(
    project_id: str,
    tagged: List[Dict[str, Any]],
    summary_path: str,
    summary_lock_path: str,
) -> tuple[int, List[str]]:
    """Persist tagged dream pairs to the daily store and dream summary markdown.

    Pass 2 of the auto-accept flow: for each tagged record a stable memory id is
    generated, the pair is appended to the daily store with ``keep=False`` Dream
    metadata, and a markdown block is appended to the dream summary under a lock.
    Each record is persisted independently; a failure is recorded and does not
    abort the remaining records.

    Args:
        project_id: Project whose pairs are persisted.
        tagged: Tagged-pair records produced by :func:`_tag_dream_pairs`.
        summary_path: Path to the dream summary markdown file.
        summary_lock_path: Lock guarding concurrent summary writes.

    Returns:
        Tuple of ``(accepted_count, failures)`` where ``failures`` holds
        ``"<item_id>: <error>"`` strings for records that failed to persist.
    """
    accepted = 0
    failures: List[str] = []
    for rec in tagged:
        item = rec["item"]
        try:
            ts_local = time.strftime("%m-%d-%Y_%H:%M:%S", time.localtime())
            accepted_item_id = str(item.get("id") or "").strip() or None
            dream_output_type = snake_case_value(item.get("origin_type") or item.get("source_resolution")) or None
            origin_ids = origin_memory_ids(item)
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
                origin_memory_ids=origin_ids,
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
                origin_memory_ids=origin_ids,
            )
            if not ok:
                raise RuntimeError("append_pair returned false")
            block = dream_markdown_block(
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
            accepted += 1
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
    return accepted, failures


def auto_accept_dreams(project_id: str) -> DreamAutoAcceptResult:
    """Process every pending ``dream.json`` item as remembered Dream memory during Sleep.

    Mirrors the manual Dream Remember persistence path, except auto-accepted
    entries are stored with ``keep=False`` and the helper runs independently of
    the UI. Each processable item is expanded into memory pairs, tagged, appended
    to the daily store and the dream summary markdown, and the daily cache is
    rebuilt. A malformed or unprocessable ``dream.json`` is quarantined; a clean
    run deletes it. Errors are accumulated on the result rather than raised.

    Args:
        project_id: Project whose pending ``dream.json`` is processed.

    Returns:
        A :class:`DreamAutoAcceptResult` with processed/accepted/failed counts,
        filtering stats, and any quarantine path or error messages.
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
    to_process, dropped_rows = filter_remote_without_research_with_rows(entries)
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

    summary_path, summary_lock_path = _prepare_dream_summary_paths(base_dir, project_id)

    tagged = _tag_dream_pairs(project_id, to_process)
    accepted, failures = _persist_tagged_pairs(project_id, tagged, summary_path, summary_lock_path)
    result.accepted = accepted

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
