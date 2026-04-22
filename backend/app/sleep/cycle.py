"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Sleep Cycle API endpoint for Syx AGI Chatbot Framework.

This module provides memory pruning and cleanup functionality (stubbed).
"""

import logging
from typing import Optional, Any, Dict, List
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

# Set up module-level logger
logger = logging.getLogger(__name__)

from ..core.models import SleepCycleRequest, SleepCycleResponse, ErrorResponse
from ..core.memory import get_memory_manager
from ..core.state import engage_lock, release_lock, is_sleeping, since, lock_path
from ..core.database import get_session
from ..core.db_models import Project, ChatMessage
from sqlmodel import select
from ..rag.daily_store import backfill_daily_txt_from_meta, append_pair_text_only
from ..tagging.tagger import tag_pair as tag_pair_tagger
from ..dream import dream
import time
from ..utils.logging import RequestLogger
from ..utils.errors import handle_memory_error, log_error_context
import os
import json
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize logger
request_logger = RequestLogger("sleep")

from ..rag.manager import rebuild_faiss_index, load_faiss_index
from filelock import FileLock
from ..core.config import get_settings
from ..rag.daily_store import _project_daily_paths, clear_daily_cache
from ..utils.debug_utils import write_debug_file
from .questions_consolidation import consolidate_open_questions_artifact
from .worker import start_sleep_cycle_runner
def _nl(s: str) -> str:
    """Normalize line endings to LF to avoid mixed terminators."""
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _sleep_cycle_worker():
    start_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
    job_id = f"sleep_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    status = "success"
    errors = []
    projects_failed_count = 0
    items_in = 0
    items_out = 0
    updated = 0
    projects_processed = 0
    skipped_no_daily = 0
    try:
        engage_lock()
        logger.debug("[SLEEP] Lock engaged")
        logger.info("[SLEEP] Thread started t=%s job_id=%s", start_iso, job_id)
        # Flush active pairs from DB into daily.txt only (tagger + append_pair_text_only); only delete on success.
        try:
            from ..core.memory import get_memory_manager
            mem = get_memory_manager()
            settings = get_settings()
            pair_limit = int(getattr(settings, "chat_history_limit_pairs", 10) or 10)
            logger.info(
                "[SLEEP][FLUSH] Starting: flushing active pairs to daily.txt only (tagger + text-only append) per project (chat_history_limit_pairs=%s).",
                pair_limit,
            )
            with get_session() as session:
                projects = session.exec(select(Project)).all()
            for p in projects or []:
                pid = p.id
                if not bool(getattr(p, "daily_rag_enabled", True)):
                    continue
                try:
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
                            items_in += 1
                            if bool(getattr(a, "forget", False)):
                                # Delete both rows for forgotten pair (no daily append)
                                try:
                                    with get_session() as session:
                                        urow = session.get(ChatMessage, getattr(u, "id", None))
                                        arow = session.get(ChatMessage, getattr(a, "id", None))
                                        if urow:
                                            session.delete(urow)
                                        if arow:
                                            session.delete(arow)
                                        session.commit()
                                except Exception as de:
                                    logger.warning("[SLEEP][FLUSH] DB delete failed project=%s: %s", pid, de)
                                i += 2
                                continue
                            user_text = getattr(u, "content", "") or ""
                            asst_text = getattr(a, "content", "") or ""
                            tags_meta = None
                            tags_meta_json = getattr(a, "tags_meta_json", None)
                            if isinstance(tags_meta_json, str) and (tags_meta_json or "").strip():
                                try:
                                    parsed = json.loads(tags_meta_json)
                                    if isinstance(parsed, dict):
                                        tags_meta = parsed
                                except Exception:
                                    tags_meta = None
                            if tags_meta is None:
                                tags_meta = tag_pair_tagger(
                                    user_text,
                                    asst_text,
                                    previous_pair_text=previous_pair_text,
                                    project_id=pid,
                                )
                            created_at = getattr(u, "created_at", None) or getattr(a, "created_at", None)
                            created_at_iso = (
                                created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
                                if created_at and hasattr(created_at, "strftime")
                                else None
                            )
                            ns = (getattr(a, "namespace", None) or "other")
                            ns = ns.lower() if isinstance(ns, str) else "other"
                            keep = bool(getattr(a, "keep", False))
                            ok = append_pair_text_only(
                                pid,
                                user_text,
                                asst_text,
                                created_at_iso,
                                ns,
                                keep,
                                tags_meta=tags_meta,
                            )
                            if ok:
                                try:
                                    with get_session() as session:
                                        urow = session.get(ChatMessage, getattr(u, "id", None))
                                        arow = session.get(ChatMessage, getattr(a, "id", None))
                                        if urow:
                                            session.delete(urow)
                                        if arow:
                                            session.delete(arow)
                                        session.commit()
                                    flushed += 1
                                    items_out += 1
                                    previous_pair_text = f"User: {user_text}\nAssistant: {asst_text}"
                                except Exception as de:
                                    logger.warning("[SLEEP][FLUSH] DB delete failed project=%s: %s", pid, de)
                            else:
                                logger.warning(
                                    "[SLEEP][FLUSH] append_pair_text_only failed for project=%s user_id=%s assistant_id=%s; pair not deleted.",
                                    pid,
                                    getattr(u, "id", None),
                                    getattr(a, "id", None),
                                )
                            i += 2
                        else:
                            # Orphan/misaligned – delete the single row and continue
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
                    # Clear in-memory deque cache for this project to force reload
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
                        logger.info("[SLEEP][FLUSH] flushed_pairs=%s project=%s", flushed, pid)
                except Exception as fe:
                    projects_failed_count += 1
                    status = "partial"
                    errors.append(f"flush:{pid}")
                    logger.warning("[SLEEP][FLUSH][WARN] project=%s %s", pid, fe)
            logger.info("[SLEEP][FLUSH] Active pairs flush complete.")
        except Exception as e:
            status = "partial"
            errors.append("flush:global")
            logger.warning("[SLEEP][FLUSH][WARN] global flush step failed; operation=flush_pairs detail=%s", e)
        # Backfill daily.txt if missing (current behavior).
        try:
            with get_session() as session:
                rows = session.exec(select(Project)).all()
        except Exception:
            rows = []
        for p in rows or []:
            try:
                if backfill_daily_txt_from_meta(p.id):
                    updated += 1
            except Exception as e:
                projects_failed_count += 1
                status = "partial"
                errors.append(f"backfill:{p.id}")
                logger.warning("[SLEEP] Backfill failed for project=%s: %s", p.id, e)
        # Summarization pipeline (per project with non-empty daily.txt)
        for p in rows or []:
            pid = p.id
            base_dir = os.path.join(get_settings().memory_root, pid)
            try:
                consolidate_open_questions_artifact(pid)
            except Exception as qce:
                logger.warning("[SLEEP][QUESTIONS][WARN] project=%s: %s", pid, qce)
            daily_path = os.path.join(base_dir, "daily.txt")
            if not os.path.isfile(daily_path) or os.path.getsize(daily_path) == 0:
                skipped_no_daily += 1
                logger.info("[SLEEP] Skipped project (no daily.txt) project=%s", pid)
                continue
            projects_processed += 1
            try:
                with open(daily_path, "r", encoding="utf-8") as f:
                    daily_text = f.read()
                # Append END tag in-memory only (do not persist)
                end_tag_date = time.strftime("%m/%d/%Y", time.localtime())
                source_text = daily_text.rstrip() + f"\n\n=== END DAILY MEMORY: {end_tag_date} ===\n\n"
            except Exception as e:
                logger.warning("[SLEEP][ERROR] Failed reading daily.txt project=%s: %s", pid, e)
                continue
            # Deterministic consolidation: no sleep prompt calls.
            summary_path = os.path.join(base_dir, "sleep_summary.txt")
            try:
                final = _nl(source_text)
                with open(summary_path, "w", encoding="utf-8", newline="\n") as sf:
                    sf.write(_nl(final))
                logger.info("[SLEEP][FORMAT] Deterministic summary complete project=%s", pid)

                # Run Dream cycle (questions, context, idea agent) BEFORE merge/RAG rebuild
                try:
                    dream(pid)
                except Exception as de:
                    logger.error("[SLEEP][DREAM][ERROR] project=%s: %s", pid, de, exc_info=True)

                # Filesystem-safe timestamp for per-cycle upload artifacts (no ':' in name).
                cycle_ts = time.strftime("%Y-%m-%dT%H-%M-%S", time.localtime())
                sleep_upload_text: Optional[str] = None
                dream_upload_text: Optional[str] = None
                dream_summary_path = os.path.join(base_dir, "dream_summary.txt")

                # 3.3 Merge and RAG rebuild (uses the possibly cleaned sleep_summary.txt)
                try:
                    # Validate summary presence and non-empty (beyond just boundary tags)
                    if not os.path.isfile(summary_path) or os.path.getsize(summary_path) == 0:
                        logger.warning("[SLEEP][MERGE] Skipped project=%s (empty or missing sleep_summary.txt)", pid)
                        continue
                    with open(summary_path, "r", encoding="utf-8") as fsum:
                        sum_text = fsum.read()
                    content_only = "\n".join(
                        ln for ln in (sum_text or "").splitlines()
                        if not ln.strip().startswith("=== BEGIN DAILY MEMORY:")
                        and not ln.strip().startswith("=== END DAILY MEMORY:")
                    ).strip()
                    if len(content_only) == 0:
                        logger.warning("[SLEEP][MERGE] Skipped (empty) project=%s", pid)
                        continue
                    logger.info("[SLEEP][MERGE] Initiating RAG update for %s", pid)
                    # New behavior: do not append to uploads/sleep_summary_all.txt.
                    # Instead, write per-cycle artifacts into uploads/sleep/ and uploads/dream/
                    # and rebuild the index once after both writes.
                    sleep_upload_text = sum_text
                except Exception as me:
                    logger.error("[SLEEP][MERGE][ERROR] project=%s: %s", pid, me, exc_info=True)

                # 4.5.4 Dream summary post-sleep consolidation (deterministic pass-through)
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
                        dream_upload_text = formatted_dream
                except Exception as de:
                    logger.warning("[SLEEP][DREAM_SUMMARY][WARN] project=%s: %s", pid, de)

                # Write per-cycle artifacts and rebuild FAISS once (after both sleep + optional dream writes).
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
                                sleep_name = f"sleep_{cycle_ts}.txt"
                                sleep_path = os.path.join(sleep_dir, sleep_name)
                                if os.path.exists(sleep_path):
                                    # Extremely unlikely, but avoid clobbering if a file already exists.
                                    sleep_path = os.path.join(sleep_dir, f"sleep_{cycle_ts}_{time.time_ns()}.txt")
                                with open(sleep_path, "w", encoding="utf-8", newline="\n") as sf:
                                    sf.write(_nl(sleep_upload_text or ""))
                                logger.info("[SLEEP][MERGE] Wrote uploads/sleep/%s", os.path.basename(sleep_path))

                            if (dream_upload_text or "").strip():
                                dream_dir = os.path.join(uploads_dir, "dream")
                                os.makedirs(dream_dir, exist_ok=True)
                                dream_name = f"dream_{cycle_ts}.txt"
                                dream_path = os.path.join(dream_dir, dream_name)
                                if os.path.exists(dream_path):
                                    # Extremely unlikely, but avoid clobbering if a file already exists.
                                    dream_path = os.path.join(dream_dir, f"dream_{cycle_ts}_{time.time_ns()}.txt")
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

                            # Cleanup only if all succeeded
                            if ok:
                                try:
                                    # os.remove(summary_path)
                                    logger.info("[SLEEP][CLEANUP] Removed individual summary for %s", pid)
                                except Exception as ce:
                                    logger.warning("[SLEEP][CLEANUP] Failed removing summary for %s: %s", pid, ce)

                                # Remove dream_summary.txt only after successful consolidation into uploads/dream/
                                if (dream_upload_text or "").strip() and os.path.isfile(dream_summary_path):
                                    try:
                                        os.remove(dream_summary_path)
                                    except Exception as de:
                                        logger.warning(
                                            "[SLEEP][DREAM_SUMMARY] Failed removing dream_summary.txt for %s: %s",
                                            pid,
                                            de,
                                        )

                                # Clear in-memory daily cache and remove daily.json so daily memory moves into main RAG.
                                try:
                                    meta_path, lock_path, txt_path = _project_daily_paths(pid)
                                    with FileLock(lock_path):
                                        # remove daily.json
                                        if os.path.exists(meta_path):
                                            try:
                                                os.remove(meta_path)
                                            except Exception as exc:
                                                logger.warning(
                                                    "[SLEEP][CLEANUP] Failed removing daily.json for %s: %s",
                                                    pid,
                                                    exc,
                                                )
                                        # remove daily.txt
                                        if os.path.exists(txt_path):
                                            try:
                                                os.remove(txt_path)
                                                logger.info("[SLEEP][CLEANUP] Removed daily.txt for %s", pid)
                                            except Exception as te:
                                                logger.warning(
                                                    "[SLEEP][CLEANUP] Failed removing daily.txt for %s: %s", pid, te
                                                )
                                    try:
                                        clear_daily_cache(pid)
                                    except Exception as exc:
                                        logger.warning(
                                            "[SLEEP][MERGE] Failed clearing in-memory daily cache for %s: %s",
                                            pid,
                                            exc,
                                        )
                                    logger.info(
                                        "[SLEEP][MERGE] Cleared in-memory daily cache and removed daily.json for %s",
                                        pid,
                                    )
                                except Exception as de:
                                    logger.warning("[SLEEP][MERGE] Post-merge daily cleanup error for %s: %s", pid, de)
                except Exception as re:
                    projects_failed_count += 1
                    status = "partial"
                    errors.append(f"merge:{pid}")
                    logger.error("[SLEEP][MERGE][ERROR] project=%s: %s", pid, re, exc_info=True)
            except Exception as e:
                projects_failed_count += 1
                status = "partial"
                errors.append(f"format:{pid}")
                logger.error("[SLEEP][ERROR] Formatting failed project=%s: %s", pid, e, exc_info=True)
                continue
        logger.info(
            "[SLEEP] Completed (updated_projects=%s, projects_processed=%s, skipped_no_daily=%s)",
            updated,
            projects_processed,
            skipped_no_daily,
        )
    except Exception as e:
        status = "failed"
        errors.append("worker:fatal")
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
    """
    Trigger memory pruning and sleep cycle.
    
    This endpoint is stubbed for future scheduled cleanup implementation.
    Currently returns placeholder responses.
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
    """Start the sleep cycle in the background; returns immediately."""
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
    """Force release the global sleep lock."""
    try:
        release_lock()
        return JSONResponse(status_code=200, content={"status": "unlocked"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/sleep_cycle/status")
async def sleep_cycle_status() -> JSONResponse:
    """Get sleep cycle status and statistics."""
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
    """Get cleanup schedule information (stubbed)."""
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
    """Set cleanup schedule (stubbed)."""
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
    """Health check for sleep cycle functionality."""
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
