"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Sleep Cycle API endpoint for Syx AGI Chatbot Framework.

This module provides memory pruning and cleanup functionality (stubbed).
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

# Set up module-level logger
logger = logging.getLogger(__name__)

from ..core.models import SleepCycleRequest, SleepCycleResponse, ErrorResponse
from ..core.memory import get_memory_manager, _prune_assistant_for_tagger
from ..core.state import engage_lock, release_lock, is_sleeping, since, lock_path
from ..core.database import get_session
from ..core.db_models import Project, ChatMessage
from sqlmodel import select
from ..rag.daily_store import append_pair, backfill_daily_md_from_meta, rebuild_daily_cache
from ..tagging.tagger import tag_pair as tag_pair_tagger
from ..dream import dream
from ..dream.auto_accept import auto_accept_dreams
import time
from ..utils.logging import RequestLogger
from ..utils.errors import handle_memory_error, log_error_context
import os
import json
import uuid
from datetime import datetime
from ..utils.tokens import count_tokens

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize logger
request_logger = RequestLogger("sleep")

from ..rag.manager import rebuild_faiss_index, load_faiss_index
from filelock import FileLock
from ..core.config import get_settings
from ..rag.daily_store import _project_daily_paths, clear_daily_cache
from ..rag.syx_memory_artifact import normalize_legacy_artifact_wrappers, replace_current_scope_for_ltm
from ..utils.debug_utils import write_debug_file
from .questions_consolidation import consolidate_open_questions_artifact
from .worker import start_sleep_cycle_runner
def _nl(s: str) -> str:
    """Normalize line endings to LF to avoid mixed terminators.

    Args:
        s: Text whose CRLF/CR line endings are converted to LF.

    Returns:
        Text with all line endings normalized to ``\\n``.
    """
    return s.replace("\r\n", "\n").replace("\r", "\n")


@dataclass
class _SleepCycleStats:
    """Mutable accumulator for a sleep-cycle run.

    Attributes:
        status: Overall run status (``success`` -> ``partial`` -> ``failed``).
        errors: Per-stage error tags collected during the run.
        projects_failed_count: Number of per-project stage failures.
        items_in: Active pairs considered for flushing.
        items_out: Active pairs successfully flushed to Daily memory.
        updated: Projects whose daily.md was backfilled.
        projects_processed: Projects that ran the summarization pipeline.
        skipped_no_daily: Projects skipped for an empty/missing daily.md.
    """

    status: str = "success"
    errors: List[str] = field(default_factory=list)
    projects_failed_count: int = 0
    items_in: int = 0
    items_out: int = 0
    updated: int = 0
    projects_processed: int = 0
    skipped_no_daily: int = 0


def _public_tags_meta(tags_meta: Any) -> Optional[Dict[str, Any]]:
    """Return tags metadata with private (underscore-prefixed) keys removed.

    Args:
        tags_meta: Tagger metadata dict (or any value).

    Returns:
        A new dict containing only public keys, or ``None`` when ``tags_meta``
        is not a dict.
    """
    if not isinstance(tags_meta, dict):
        return None
    return {key: value for key, value in dict(tags_meta).items() if not str(key).startswith("_")}


def _build_pair_tags_block(public_tags_meta: Optional[Dict[str, Any]]) -> str:
    """Build the ``#topics/#intent/#type`` header block prepended to embed text.

    Args:
        public_tags_meta: Public tags metadata (or ``None``).

    Returns:
        The trailing-newline-terminated tags block, or an empty string when no
        public metadata is available.
    """
    if not isinstance(public_tags_meta, dict):
        return ""
    topics = str(public_tags_meta.get("topics", "") or "")
    intent = str(public_tags_meta.get("intent", "") or "")
    tag_type = str(public_tags_meta.get("type", "") or "")
    semantic_handle = public_tags_meta.get("semantic_handle", None)
    lines = [f"#topics: {topics}", f"#intent: {intent}", f"#type: {tag_type}"]
    if semantic_handle is not None:
        lines.append(f"#semantic_handle: {str(semantic_handle)}")
    return "\n".join(lines) + "\n"


def _summary_content_only(sum_text: Optional[str]) -> str:
    """Strip ``===``-prefixed boundary lines from a summary, returning the body.

    Args:
        sum_text: Raw summary text (or ``None``).

    Returns:
        The stripped content with boundary marker lines removed.
    """
    return "\n".join(
        ln for ln in (sum_text or "").splitlines() if not ln.strip().startswith("===")
    ).strip()


def _delete_pair_rows(pid: str, user_id: Any, assistant_id: Any) -> bool:
    """Delete a user/assistant chat-message pair from the database.

    Args:
        pid: Project id (for log context).
        user_id: User message row id.
        assistant_id: Assistant message row id.

    Returns:
        True when the deletion committed, False when it failed (logged).
    """
    try:
        with get_session() as session:
            urow = session.get(ChatMessage, user_id)
            arow = session.get(ChatMessage, assistant_id)
            if urow:
                session.delete(urow)
            if arow:
                session.delete(arow)
            session.commit()
        return True
    except Exception as de:
        logger.warning("[SLEEP][FLUSH] DB delete failed project=%s: %s", pid, de)
        return False


def _prepare_pair_for_daily(u: Any, a: Any, pid: str, previous_pair_text: Optional[str]):
    """Build the Daily-memory payload for one user/assistant pair.

    Resolves tagger metadata (from stored ``tags_meta_json`` or by tagging),
    applies assistant pruning, and assembles the embed text (tags block + pair).

    Args:
        u: User message row.
        a: Assistant message row.
        pid: Project id.
        previous_pair_text: Prior pair text passed to the tagger for continuity.

    Returns:
        A tuple ``(pair_text, embed_text, public_tags_meta, namespace, keep,
        created_at_iso)``.
    """
    user_text = getattr(u, "content", "") or ""
    asst_text = getattr(a, "content", "") or ""
    tags_meta = None
    tags_meta_json = getattr(a, "tags_meta_json", None)
    if isinstance(tags_meta_json, str) and (tags_meta_json or "").strip():
        try:
            parsed = json.loads(tags_meta_json)
            if isinstance(parsed, dict):
                tags_meta = parsed
        except json.JSONDecodeError as exc:
            logger.warning(
                "[SLEEP][FLUSH] Failed parsing tags_meta_json project=%s assistant_id=%s detail=%s",
                pid,
                getattr(a, "id", None),
                exc,
            )
            tags_meta = None
    pruned_from_meta = None
    if isinstance(tags_meta, dict):
        pruned_candidate = tags_meta.get("_pruned_assistant_text")
        if isinstance(pruned_candidate, str) and pruned_candidate.strip():
            pruned_from_meta = pruned_candidate
    asst_text_for_memory = (
        pruned_from_meta
        if isinstance(pruned_from_meta, str) and pruned_from_meta.strip()
        else _prune_assistant_for_tagger(
            project_id=pid,
            assistant_text=asst_text,
            settings=get_settings(),
        )
    )
    if asst_text_for_memory != asst_text and isinstance(tags_meta, dict):
        tags_meta = {**tags_meta, "_pruned_assistant_text": asst_text_for_memory}
    if tags_meta is None:
        tags_meta = tag_pair_tagger(
            user_text,
            asst_text_for_memory,
            previous_pair_text=previous_pair_text,
            project_id=pid,
        )
        if asst_text_for_memory != asst_text and isinstance(tags_meta, dict):
            tags_meta = {**tags_meta, "_pruned_assistant_text": asst_text_for_memory}
    created_at = getattr(u, "created_at", None) or getattr(a, "created_at", None)
    created_at_iso = (
        created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        if created_at and hasattr(created_at, "strftime")
        else None
    )
    ns = (getattr(a, "namespace", None) or "other")
    ns = ns.lower() if isinstance(ns, str) else "other"
    keep = bool(getattr(a, "keep", False))
    public_tags_meta = _public_tags_meta(tags_meta)
    pair_text = f"User: {user_text}\nAssistant: {asst_text_for_memory}"
    tags_block = _build_pair_tags_block(public_tags_meta)
    embed_text = (tags_block + pair_text) if tags_block else pair_text
    return pair_text, embed_text, public_tags_meta, ns, keep, created_at_iso


def _flush_project_pairs(pid: str, pair_limit: int, stats: _SleepCycleStats) -> int:
    """Flush a single project's active chat pairs into indexed Daily memory.

    Iterates ordered chat messages, appending each well-formed user/assistant
    pair to Daily memory and deleting the source rows on success. Forgotten
    pairs are deleted without appending; orphan/misaligned rows are dropped.

    Args:
        pid: Project id whose active pairs are flushed.
        pair_limit: Maximum number of pairs to flush this cycle.
        stats: Run accumulator; ``items_in``/``items_out`` are updated here.

    Returns:
        The number of pairs successfully flushed to Daily memory.
    """
    with get_session() as session:
        msgs = session.exec(
            select(ChatMessage)
            .where(ChatMessage.project_id == pid)
            .order_by(ChatMessage.created_at.asc())
        ).all()
    i = 0
    flushed = 0
    n = len(msgs or [])
    previous_pair_text = None
    while i + 1 < n and flushed < pair_limit:
        u = msgs[i]
        a = msgs[i + 1]
        if (getattr(u, "role", "") == "user") and (getattr(a, "role", "") == "assistant"):
            stats.items_in += 1
            if bool(getattr(a, "forget", False)):
                # Delete both rows for forgotten pair (no daily append).
                _delete_pair_rows(pid, getattr(u, "id", None), getattr(a, "id", None))
                i += 2
                continue
            pair_text, embed_text, public_tags_meta, ns, keep, created_at_iso = _prepare_pair_for_daily(
                u, a, pid, previous_pair_text
            )
            ok = append_pair(
                pid,
                pair_text,
                int(getattr(u, "id", -1) or -1),
                int(getattr(a, "id", -2) or -2),
                int(count_tokens(pair_text)),
                namespace=ns,
                keep=keep,
                embed_override=embed_text,
                tags_meta=public_tags_meta,
                update_cache=False,
                created_at_iso_utc=created_at_iso,
            )
            if ok:
                if _delete_pair_rows(pid, getattr(u, "id", None), getattr(a, "id", None)):
                    flushed += 1
                    stats.items_out += 1
                    previous_pair_text = pair_text
            else:
                logger.warning(
                    "[SLEEP][FLUSH] Daily append failed for project=%s user_id=%s assistant_id=%s; pair not deleted.",
                    pid,
                    getattr(u, "id", None),
                    getattr(a, "id", None),
                )
            i += 2
        else:
            # Orphan/misaligned – delete the single row and continue.
            try:
                with get_session() as session:
                    row = session.get(ChatMessage, getattr(msgs[i], "id", None))
                    if row:
                        session.delete(row)
                        session.commit()
            except Exception as exc:
                logger.warning(
                    "[SLEEP][FLUSH] Failed deleting orphan row project=%s row_id=%s detail=%s",
                    pid,
                    getattr(msgs[i], "id", None),
                    exc,
                )
            i += 1
    return flushed


def _flush_active_pairs(stats: _SleepCycleStats) -> None:
    """Flush active chat pairs into Daily memory for every enabled project.

    Per-project failures are logged and downgrade status to ``partial`` without
    aborting the run; a global failure of the flush step is likewise contained.

    Args:
        stats: Run accumulator updated with flush counters and error tags.
    """
    try:
        mem = get_memory_manager()
        settings = get_settings()
        pair_limit = int(getattr(settings, "chat_history_limit_pairs", 10) or 10)
        logger.info(
            "[SLEEP][FLUSH] Starting: flushing active pairs to indexed Daily memory per project (chat_history_limit_pairs=%s).",
            pair_limit,
        )
        with get_session() as session:
            projects = session.exec(select(Project)).all()
        for p in projects or []:
            pid = p.id
            if not bool(getattr(p, "daily_rag_enabled", True)):
                continue
            try:
                flushed = _flush_project_pairs(pid, pair_limit, stats)
                # Clear in-memory deque cache for this project to force reload.
                try:
                    if pid in mem.project_deques:
                        mem.project_deques.pop(pid, None)
                    mem.last_context_tokens_per_project.pop(pid, None)
                except Exception as exc:
                    logger.warning(
                        "[SLEEP][FLUSH] Failed clearing in-memory caches project=%s detail=%s",
                        pid,
                        exc,
                    )
                if flushed:
                    if not rebuild_daily_cache(pid, reason="sleep_flush"):
                        stats.status = "partial"
                        stats.errors.append(f"daily_cache_rebuild:{pid}")
                        logger.warning(
                            "[SLEEP][FLUSH] Daily cache rebuild failed after flush project=%s flushed_pairs=%s",
                            pid,
                            flushed,
                        )
                    logger.info("[SLEEP][FLUSH] flushed_pairs=%s project=%s", flushed, pid)
            except Exception as fe:
                stats.projects_failed_count += 1
                stats.status = "partial"
                stats.errors.append(f"flush:{pid}")
                logger.warning("[SLEEP][FLUSH][WARN] project=%s %s", pid, fe)
        logger.info("[SLEEP][FLUSH] Active pairs flush complete.")
    except Exception as e:
        stats.status = "partial"
        stats.errors.append("flush:global")
        logger.warning("[SLEEP][FLUSH][WARN] global flush step failed; operation=flush_pairs detail=%s", e)


def _backfill_daily_md(rows: List[Any], stats: _SleepCycleStats) -> None:
    """Backfill daily.md from daily.json for each project (best-effort).

    Args:
        rows: Project rows to backfill.
        stats: Run accumulator updated with ``updated`` and error tags.
    """
    for p in rows or []:
        try:
            if backfill_daily_md_from_meta(p.id):
                stats.updated += 1
        except Exception as e:
            stats.projects_failed_count += 1
            stats.status = "partial"
            stats.errors.append(f"backfill:{p.id}")
            logger.warning("[SLEEP] Backfill failed for project=%s: %s", p.id, e)


def _run_dream_and_auto_accept(pid: str, stats: _SleepCycleStats) -> None:
    """Run the Dream cycle and optional auto-accept for one project.

    Both stages are isolated: a Dream failure is logged and does not block
    auto-accept, and an auto-accept failure downgrades status to ``partial``.

    Args:
        pid: Project id.
        stats: Run accumulator updated on auto-accept failures.
    """
    try:
        dream(pid)
    except Exception as de:
        logger.error("[SLEEP][DREAM][ERROR] project=%s: %s", pid, de, exc_info=True)
    try:
        if bool(getattr(get_settings(), "auto_accept_dreams", False)):
            auto_result = auto_accept_dreams(pid)
            if auto_result.failed:
                stats.status = "partial"
                stats.errors.append(f"dream_auto_accept:{pid}")
                logger.warning(
                    "[SLEEP][DREAM][AUTO_ACCEPT][WARN] project=%s processed=%s accepted=%s failed=%s bad_path=%s errors=%s",
                    pid,
                    auto_result.processed,
                    auto_result.accepted,
                    auto_result.failed,
                    auto_result.renamed_bad_path,
                    auto_result.errors,
                )
            elif auto_result.processed or auto_result.filtered_remote_without_research:
                logger.info(
                    "[SLEEP][DREAM][AUTO_ACCEPT] project=%s processed=%s accepted=%s filtered=%s deleted_dream=%s",
                    pid,
                    auto_result.processed,
                    auto_result.accepted,
                    auto_result.filtered_remote_without_research,
                    auto_result.deleted_dream,
                )
    except Exception as de:
        stats.status = "partial"
        stats.errors.append(f"dream_auto_accept:{pid}")
        logger.warning("[SLEEP][DREAM][AUTO_ACCEPT][WARN] project=%s: %s", pid, de, exc_info=True)


def _post_merge_cleanup(
    pid: str,
    summary_path: str,
    dream_summary_path: str,
    has_dream_upload: bool,
) -> None:
    """Remove per-cycle summary artifacts and Daily caches after a good rebuild.

    Best-effort throughout: each removal is independently logged on failure so
    cleanup never aborts a successful merge.

    Args:
        pid: Project id.
        summary_path: Path to the consumed sleep_summary.md.
        dream_summary_path: Path to the consumed dream_summary.md.
        has_dream_upload: Whether a dream artifact was written this cycle.
    """
    try:
        os.remove(summary_path)
        logger.info("[SLEEP][CLEANUP] Removed individual summary for %s", pid)
    except Exception as ce:
        logger.warning("[SLEEP][CLEANUP] Failed removing summary for %s: %s", pid, ce)

    # Remove dream_summary.md only after successful consolidation into uploads/dream/.
    if has_dream_upload and os.path.isfile(dream_summary_path):
        try:
            os.remove(dream_summary_path)
        except Exception as de:
            logger.warning(
                "[SLEEP][DREAM_SUMMARY] Failed removing dream_summary.md for %s: %s",
                pid,
                de,
            )

    # Clear in-memory daily cache and remove daily.json so daily memory moves into main RAG.
    try:
        meta_path, lock_path, md_path = _project_daily_paths(pid)
        with FileLock(lock_path):
            if os.path.exists(meta_path):
                try:
                    os.remove(meta_path)
                except Exception as exc:
                    logger.warning("[SLEEP][CLEANUP] Failed removing daily.json for %s: %s", pid, exc)
            if os.path.exists(md_path):
                try:
                    os.remove(md_path)
                    logger.info("[SLEEP][CLEANUP] Removed daily.md for %s", pid)
                except Exception as te:
                    logger.warning("[SLEEP][CLEANUP] Failed removing daily.md for %s: %s", pid, te)
        try:
            clear_daily_cache(pid)
        except Exception as exc:
            logger.warning("[SLEEP][MERGE] Failed clearing in-memory daily cache for %s: %s", pid, exc)
        logger.info("[SLEEP][MERGE] Cleared in-memory daily cache and removed daily.json for %s", pid)
    except Exception as de:
        logger.warning("[SLEEP][MERGE] Post-merge daily cleanup error for %s: %s", pid, de)


def _write_merge_artifacts_and_rebuild(
    pid: str,
    summary_path: str,
    dream_summary_path: str,
    cycle_ts: str,
    sleep_upload_text: Optional[str],
    dream_upload_text: Optional[str],
    stats: _SleepCycleStats,
) -> None:
    """Write per-cycle sleep/dream artifacts and rebuild the FAISS index once.

    Writes are serialized under the project's merge lock. After a verified
    rebuild, per-cycle summary artifacts and Daily caches are cleaned up. A
    failure downgrades status to ``partial`` and records a ``merge`` error tag.

    Args:
        pid: Project id.
        summary_path: Path to sleep_summary.md (removed on success).
        dream_summary_path: Path to dream_summary.md (removed on success).
        cycle_ts: Filesystem-safe timestamp for the artifact filenames.
        sleep_upload_text: Sleep artifact body (skipped when empty).
        dream_upload_text: Dream artifact body (skipped when empty).
        stats: Run accumulator updated on failure.
    """
    try:
        if (sleep_upload_text or "").strip() or (dream_upload_text or "").strip():
            uploads_dir = os.path.join(get_settings().memory_root, pid, "uploads")
            state_dir = os.path.join(get_settings().memory_root, pid, "state")
            os.makedirs(state_dir, exist_ok=True)
            merge_lock = os.path.join(state_dir, "merge.lock")
            legacy_merge_lock = os.path.join(get_settings().memory_root, pid, "merge.lock")
            if os.path.isfile(legacy_merge_lock) and not os.path.exists(merge_lock):
                try:
                    os.replace(legacy_merge_lock, merge_lock)
                except OSError as exc:
                    logger.warning("[SLEEP] merge lock migration failed project=%s detail=%s", pid, exc)
            with FileLock(merge_lock):
                os.makedirs(uploads_dir, exist_ok=True)

                if (sleep_upload_text or "").strip():
                    sleep_dir = os.path.join(uploads_dir, "sleep")
                    os.makedirs(sleep_dir, exist_ok=True)
                    sleep_name = f"sleep_{cycle_ts}.md"
                    sleep_path = os.path.join(sleep_dir, sleep_name)
                    if os.path.exists(sleep_path):
                        # Extremely unlikely, but avoid clobbering if a file already exists.
                        sleep_path = os.path.join(sleep_dir, f"sleep_{cycle_ts}_{time.time_ns()}.md")
                    with open(sleep_path, "w", encoding="utf-8", newline="\n") as sf:
                        sf.write(_nl(sleep_upload_text or ""))
                    logger.info("[SLEEP][MERGE] Wrote uploads/sleep/%s", os.path.basename(sleep_path))

                if (dream_upload_text or "").strip():
                    dream_dir = os.path.join(uploads_dir, "dream")
                    os.makedirs(dream_dir, exist_ok=True)
                    dream_name = f"dream_{cycle_ts}.md"
                    dream_path = os.path.join(dream_dir, dream_name)
                    if os.path.exists(dream_path):
                        # Extremely unlikely, but avoid clobbering if a file already exists.
                        dream_path = os.path.join(dream_dir, f"dream_{cycle_ts}_{time.time_ns()}.md")
                    with open(dream_path, "w", encoding="utf-8", newline="\n") as df:
                        df.write(_nl(dream_upload_text or ""))
                    logger.info("[SLEEP][DREAM_SUMMARY] Wrote uploads/dream/%s", os.path.basename(dream_path))

                rebuild_faiss_index(pid)
                logger.info("[MERGE] RAG rebuild complete for %s", pid)

                ok = True
                if get_settings().verify_rag:
                    ok = load_faiss_index(pid) is not None
                    if ok:
                        logger.info("[VERIFY] OK %s", pid)
                    else:
                        logger.error("[VERIFY][ERROR] %s", pid)

                # Cleanup only if all succeeded.
                if ok:
                    _post_merge_cleanup(
                        pid,
                        summary_path,
                        dream_summary_path,
                        bool((dream_upload_text or "").strip()),
                    )
    except Exception as re:
        stats.projects_failed_count += 1
        stats.status = "partial"
        stats.errors.append(f"merge:{pid}")
        logger.error("[SLEEP][MERGE][ERROR] project=%s: %s", pid, re, exc_info=True)


def _run_project_summary_pipeline(p: Any, stats: _SleepCycleStats) -> None:
    """Run the per-project summarize/dream/merge/rebuild pipeline.

    Consolidates open questions, builds the deterministic sleep summary, runs the
    Dream cycle and optional auto-accept, then writes per-cycle artifacts and
    rebuilds the FAISS index. Projects without a non-empty daily.md are skipped.

    Args:
        p: Project row.
        stats: Run accumulator updated with per-project counters and error tags.
    """
    pid = p.id
    base_dir = os.path.join(get_settings().memory_root, pid)
    try:
        consolidate_open_questions_artifact(pid)
    except Exception as qce:
        logger.warning("[SLEEP][QUESTIONS][WARN] project=%s: %s", pid, qce)
    daily_path = os.path.join(base_dir, "daily.md")
    if not os.path.isfile(daily_path) or os.path.getsize(daily_path) == 0:
        stats.skipped_no_daily += 1
        logger.info("[SLEEP] Skipped project (no daily.md) project=%s", pid)
        return
    stats.projects_processed += 1
    try:
        with open(daily_path, "r", encoding="utf-8") as f:
            daily_text = f.read()
        memory_date = time.strftime("%m-%d-%Y", time.localtime())
        source_text = normalize_legacy_artifact_wrappers(
            daily_text,
            artifact_type="sleep_memory",
            project_id=pid,
            memory_date=memory_date,
        )
    except Exception as e:
        logger.warning("[SLEEP][ERROR] Failed reading daily.md project=%s: %s", pid, e)
        return
    # Deterministic consolidation: no sleep prompt calls.
    summary_path = os.path.join(base_dir, "sleep_summary.md")
    try:
        final = _nl(source_text)
        with open(summary_path, "w", encoding="utf-8", newline="\n") as sf:
            sf.write(_nl(final))
        logger.info("[SLEEP][FORMAT] Deterministic summary complete project=%s", pid)

        # Run Dream cycle (questions, context, idea agent) BEFORE merge/RAG rebuild.
        _run_dream_and_auto_accept(pid, stats)

        # Filesystem-safe timestamp for per-cycle upload artifacts (no ':' in name).
        cycle_ts = time.strftime("%Y-%m-%dT%H-%M-%S", time.localtime())
        sleep_upload_text: Optional[str] = None
        dream_upload_text: Optional[str] = None
        dream_summary_path = os.path.join(base_dir, "dream_summary.md")

        # 3.3 Merge and RAG rebuild (uses the possibly cleaned sleep_summary.md).
        try:
            # Validate summary presence and non-empty (beyond just boundary tags).
            if not os.path.isfile(summary_path) or os.path.getsize(summary_path) == 0:
                logger.warning("[SLEEP][MERGE] Skipped project=%s (empty or missing sleep_summary.md)", pid)
                return
            with open(summary_path, "r", encoding="utf-8") as fsum:
                sum_text = fsum.read()
            if len(_summary_content_only(sum_text)) == 0:
                logger.warning("[SLEEP][MERGE] Skipped (empty) project=%s", pid)
                return
            logger.info("[SLEEP][MERGE] Initiating RAG update for %s", pid)
            # New behavior: do not append to uploads/sleep_summary_all.txt.
            # Instead, write per-cycle artifacts into uploads/sleep/ and uploads/dream/
            # and rebuild the index once after both writes.
            sleep_upload_text = replace_current_scope_for_ltm(sum_text)
        except Exception as me:
            logger.error("[SLEEP][MERGE][ERROR] project=%s: %s", pid, me, exc_info=True)

        # 4.5.4 Dream summary post-sleep consolidation (deterministic pass-through).
        try:
            if os.path.isfile(dream_summary_path) and os.path.getsize(dream_summary_path) > 0:
                with open(dream_summary_path, "r", encoding="utf-8") as ds:
                    dream_raw = ds.read()
                formatted_dream = _nl(dream_raw)
                if get_settings().generate_debug_files:
                    try:
                        write_debug_file(pid, "debug_dream_summary.txt", formatted_dream)
                    except Exception:
                        logger.warning(
                            "[SLEEP][DREAM_SUMMARY] Failed writing debug file; operation=write_debug_file project_id=%s",
                            pid,
                        )
                dream_upload_text = replace_current_scope_for_ltm(formatted_dream)
        except Exception as de:
            logger.warning("[SLEEP][DREAM_SUMMARY][WARN] project=%s: %s", pid, de)

        # Write per-cycle artifacts and rebuild FAISS once (after both sleep + optional dream writes).
        _write_merge_artifacts_and_rebuild(
            pid,
            summary_path,
            dream_summary_path,
            cycle_ts,
            sleep_upload_text,
            dream_upload_text,
            stats,
        )
    except Exception as e:
        stats.projects_failed_count += 1
        stats.status = "partial"
        stats.errors.append(f"format:{pid}")
        logger.error("[SLEEP][ERROR] Formatting failed project=%s: %s", pid, e, exc_info=True)


def _sleep_cycle_worker():
    """Run the full sleep cycle for all projects under the global sleep lock.

    Orchestrates the end-to-end pipeline: flush active chat pairs into indexed
    daily memory, backfill daily markdown, consolidate open questions, build the
    deterministic sleep summary, run the Dream cycle and optional auto-accept,
    then merge per-cycle artifacts and rebuild the FAISS index. Per-project
    failures are logged and downgrade overall status to ``partial`` rather than
    aborting the run; the sleep lock is always released on exit.
    """
    start_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
    job_id = f"sleep_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    stats = _SleepCycleStats()
    try:
        engage_lock()
        logger.debug("[SLEEP] Lock engaged")
        logger.info("[SLEEP] Thread started t=%s job_id=%s", start_iso, job_id)
        # Flush active pairs from DB into Daily metadata and daily.md; rebuild the Daily cache before Dream.
        _flush_active_pairs(stats)
        # Backfill daily.md if missing from daily.json.
        try:
            with get_session() as session:
                rows = session.exec(select(Project)).all()
        except Exception:
            rows = []
        _backfill_daily_md(rows, stats)
        # Summarization pipeline (per project with non-empty daily.md).
        for p in rows or []:
            _run_project_summary_pipeline(p, stats)
        logger.info(
            "[SLEEP] Completed (updated_projects=%s, projects_processed=%s, skipped_no_daily=%s)",
            stats.updated,
            stats.projects_processed,
            stats.skipped_no_daily,
        )
    except Exception as e:
        stats.status = "failed"
        stats.errors.append("worker:fatal")
        logger.error("[SLEEP][ERROR] %s", e, exc_info=True)
    finally:
        try:
            release_lock()
            logger.debug("[SLEEP] Lock released")
        except Exception as e:
            logger.warning("[SLEEP] finalize failed; operation=release_lock detail=%s", e)

def start_sleep_cycle_async() -> bool:
    """Start sleep cycle in background if not already sleeping. Returns True if started."""
    return start_sleep_cycle_runner(_sleep_cycle_worker)

@router.post("/sleep_cycle", response_model=SleepCycleResponse)
async def sleep_cycle_endpoint(request: SleepCycleRequest) -> SleepCycleResponse:
    """Trigger memory pruning and the sleep cycle.

    This endpoint is stubbed for a future scheduled-cleanup implementation and
    currently returns placeholder cleanup statistics.

    Args:
        request: Sleep cycle request carrying the target ``project_id`` and the
            ``force_cleanup`` flag.

    Returns:
        A :class:`SleepCycleResponse` describing the (stubbed) cleanup outcome.

    Raises:
        HTTPException: Propagated from ``handle_memory_error`` when the underlying
            cleanup operation fails.
    """
    try:
        # Log the request
        request_logger.log_request(
            endpoint="/sleep_cycle",
            method="POST",
            user_id=request.project_id
        )
        
        # Get memory manager
        memory_manager = get_memory_manager()
        
        # Perform stubbed cleanup
        cleanup_stats = memory_manager.cleanup_old_memories(
            retention_days=30,  # Default retention
            conversation_id=request.project_id
        )
        
        # Create response (stubbed)
        response = SleepCycleResponse(
            response=f"Memory cleanup for project '{request.project_id or 'default'}' is not yet implemented. This feature will be available with scheduled pruning.",
            items_cleaned=cleanup_stats.get("items_cleaned", 0),
            memory_usage_before=cleanup_stats.get("memory_usage_before", "0MB"),
            memory_usage_after=cleanup_stats.get("memory_usage_after", "0MB")
        )
        
        # Log successful response
        request_logger.log_response(
            endpoint="/sleep_cycle",
            status_code=200,
            response_time=0.0,
            user_id=request.project_id
        )
        
        return response
        
    except Exception as e:
        # Log error
        request_logger.log_error(
            endpoint="/sleep_cycle",
            error=e,
            user_id=request.project_id
        )
        
        # Log error context
        log_error_context(
            error=e,
            context={
                "endpoint": "/sleep_cycle",
                "project_id": request.project_id,
                "force_cleanup": request.force_cleanup
            }
        )
        
        # Handle memory errors
        raise handle_memory_error(e)


@router.get("/sleep/status")
async def sleep_status() -> JSONResponse:
    """Report whether a sleep cycle is active, its start time, and the lock path.

    Returns:
        A JSON response with ``sleeping``, ``since`` (UTC ISO timestamp or null),
        and ``lock_path``; a 500 response with an ``error`` field on failure.
    """
    try:
        return JSONResponse(status_code=200, content={
            "sleeping": bool(is_sleeping()),
            "since": (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since() or 0)) if is_sleeping() else None),
            "lock_path": lock_path(),
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/sleep/start")
async def sleep_start() -> JSONResponse:
    """Start the sleep cycle in the background; returns immediately.

    Returns:
        A 200 JSON response when the cycle is started, a 423 response when the
        system is already sleeping, or a 500 response with an ``error`` field on
        failure.
    """
    try:
        request_logger.log_request(endpoint="/sleep/start", method="POST")
        if is_sleeping():
            return JSONResponse(status_code=423, content={"error": "System is sleeping. Try again later."})
        started = start_sleep_cycle_async()
        if not started:
            return JSONResponse(status_code=423, content={"error": "System is sleeping. Try again later."})
        return JSONResponse(status_code=200, content={"status": "sleep cycle started"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/sleep/unlock")
async def sleep_force_unlock() -> JSONResponse:
    """Force release the global sleep lock.

    Returns:
        A 200 JSON response on success, or a 500 response with an ``error`` field
        on failure.
    """
    try:
        release_lock()
        return JSONResponse(status_code=200, content={"status": "unlocked"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/sleep_cycle/status")
async def sleep_cycle_status() -> JSONResponse:
    """Get sleep cycle status and statistics.

    Returns:
        A 200 JSON response with stub status and memory statistics, or a 500
        response with ``error`` details on failure.
    """
    try:
        memory_manager = get_memory_manager()
        stats = memory_manager.get_memory_stats()
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "stub",
                "service": "sleep_cycle",
                "memory_stats": stats,
                "implementation": "Scheduled cleanup implementation planned"
            }
        )
        
    except Exception as e:
        logger.error(f"Failed to get sleep cycle status: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "Failed to retrieve sleep cycle status",
                "details": str(e)
            }
        )


@router.post("/sleep_cycle/cleanup")
async def manual_cleanup(
    project_id: Optional[str] = None,
    retention_days: int = 30,
    force: bool = False
) -> JSONResponse:
    """
    Manually trigger memory cleanup.
    
    Args:
        project_id: Project to clean up
        retention_days: Number of days to retain
        force: Force cleanup even if not needed
        
    Returns:
        Cleanup results

    Raises:
        HTTPException: Propagated from ``handle_memory_error`` when the cleanup
            operation fails.
    """
    try:
        # Log the request
        request_logger.log_request(
            endpoint="/sleep_cycle/cleanup",
            method="POST",
            user_id=project_id
        )
        
        memory_manager = get_memory_manager()
        
        # Perform cleanup
        cleanup_stats = memory_manager.cleanup_old_memories(
            retention_days=retention_days,
            conversation_id=project_id
        )
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "stub",
                "project_id": project_id,
                "retention_days": retention_days,
                "force": force,
                "cleanup_stats": cleanup_stats,
                "message": "Manual cleanup not yet implemented"
            }
        )
        
    except Exception as e:
        request_logger.log_error(
            endpoint="/sleep_cycle/cleanup",
            error=e,
            user_id=project_id
        )
        
        raise handle_memory_error(e)


@router.get("/sleep_cycle/schedule")
async def get_cleanup_schedule() -> JSONResponse:
    """Get cleanup schedule information (stubbed).

    Returns:
        A 200 JSON response with the stubbed schedule, or a 500 response with
        ``error`` details on failure.
    """
    try:
        return JSONResponse(
            status_code=200,
            content={
                "status": "stub",
                "schedule": {
                    "enabled": False,
                    "frequency": "daily",
                    "time": "02:00",
                    "retention_days": 30
                },
                "implementation": "Planned with Celery and Redis"
            }
        )
        
    except Exception as e:
        logger.error(f"Failed to get cleanup schedule: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "Failed to retrieve cleanup schedule",
                "details": str(e)
            }
        )


@router.post("/sleep_cycle/schedule")
async def set_cleanup_schedule(
    enabled: bool = False,
    frequency: str = "daily",
    time: str = "02:00",
    retention_days: int = 30
) -> JSONResponse:
    """Set the cleanup schedule (stubbed).

    Args:
        enabled: Whether scheduled cleanup should be enabled.
        frequency: Cleanup cadence (e.g. ``daily``).
        time: Time-of-day to run cleanup, as ``HH:MM``.
        retention_days: Number of days of memory to retain.

    Returns:
        A 200 JSON response echoing the requested (stubbed) schedule.

    Raises:
        HTTPException: Propagated from ``handle_memory_error`` when handling fails.
    """
    try:
        # Log the request
        request_logger.log_request(
            endpoint="/sleep_cycle/schedule",
            method="POST"
        )
        
        # Stubbed schedule setting
        logger.info("Cleanup schedule setting requested (stub - not yet implemented)")
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "stub",
                "message": "Cleanup schedule not yet implemented",
                "requested_schedule": {
                    "enabled": enabled,
                    "frequency": frequency,
                    "time": time,
                    "retention_days": retention_days
                },
                "implementation": "Planned with Celery and Redis"
            }
        )
        
    except Exception as e:
        request_logger.log_error(
            endpoint="/sleep_cycle/schedule",
            error=e
        )
        
        raise handle_memory_error(e)


@router.get("/sleep_cycle/health")
async def sleep_cycle_health() -> JSONResponse:
    """Health check for sleep cycle functionality.

    Returns:
        A 200 JSON response with memory mode/features when healthy, or a 503
        response with an ``error`` field when the check fails.
    """
    try:
        memory_manager = get_memory_manager()
        stats = memory_manager.get_memory_stats()
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "stub",
                "service": "sleep_cycle",
                "memory_mode": stats["memory_mode"],
                "features": stats["features_available"],
                "implementation": "Scheduled cleanup implementation planned"
            }
        )
        
    except Exception as e:
        logger.error(f"Sleep cycle health check failed: {str(e)}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "service": "sleep_cycle",
                "error": str(e)
            }
        )
