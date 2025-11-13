"""
Sleep Cycle API endpoint for Morpheus AGI Chatbot Framework.

This module provides memory pruning and cleanup functionality (stubbed for Version 3).
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

# Set up module-level logger
logger = logging.getLogger(__name__)

from ..core.models import SleepCycleRequest, SleepCycleResponse, ErrorResponse
from ..core.memory import get_memory_manager
from ..core.state import engage_lock, release_lock, is_sleeping, since, lock_path
from ..core.database import get_session
from ..core.db_models import Project
from sqlmodel import select
from ..core.daily_rag import backfill_daily_txt_from_meta
import time
from ..utils.logging import RequestLogger
from ..utils.errors import handle_memory_error, log_error_context
import threading
import os
from ..core.state import release_lock
import re

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize logger
request_logger = RequestLogger("sleep")

# V3.1: unified sleep runner (background thread)
_runner_lock = threading.Lock()
_runner_thread: Optional[threading.Thread] = None
from ..core.sleep_prompts import generate_pruning_prompt, generate_formatting_prompt
from ..core.summarization import execute_prompt, execute_prompt_chunked, _count_tokens
from ..core.rag_manager import rebuild_faiss_index, load_faiss_index
from filelock import FileLock
from ..core.config import get_settings
from ..core.daily_rag import _project_daily_paths
def _nl(s: str) -> str:
    """Normalize line endings to LF to avoid mixed terminators."""
    return s.replace("\r\n", "\n").replace("\r", "\n")

def _sleep_cycle_worker():
    try:
        t0 = time.monotonic()
        start_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
        engage_lock()
        logger.info("[SLEEP] Lock engaged")
        logger.info("[SLEEP] Thread started t=%s", start_iso)
        # Backfill daily.txt if missing (current V2.x behavior)
        updated = 0
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
                logger.warning("[SLEEP] Backfill failed for project=%s: %s", p.id, e)
        # V3.2: Summarization pipeline (per project with non-empty daily.txt)
        projects_processed = 0
        pruned_count = 0
        formatted_count = 0
        skipped_no_daily = 0
        for p in rows or []:
            pid = p.id
            base_dir = os.path.join("memory", pid)
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
            # Pruning (chunked if needed)
            pruned_path = os.path.join(base_dir, "pruned.txt")
            try:
                max_tokens = 96000  # expanded chunk threshold to leverage 128k context
                if _count_tokens(source_text) > max_tokens:
                    pruned = execute_prompt_chunked(generate_pruning_prompt, source_text, max_tokens=max_tokens, overlap=200)
                else:
                    pruned = execute_prompt(generate_pruning_prompt(source_text))
                with open(pruned_path, "w", encoding="utf-8", newline="\n") as pf:
                    pf.write(_nl(pruned))
                pruned_count += 1
                try:
                    lines = len(pruned.splitlines())
                    size = len(pruned.encode("utf-8"))
                    logger.info("[SLEEP][PRUNE] Completed project=%s (bytes=%s, lines=%s)", pid, size, lines)
                except Exception:
                    logger.info("[SLEEP][PRUNE] Completed project=%s", pid)
            except Exception as e:
                logger.error("[SLEEP][ERROR] Pruning failed project=%s: %s", pid, e, exc_info=True)
                continue
            # Formatting (chunk-format if needed, then aggregate)
            summary_path = os.path.join(base_dir, "sleep_summary.txt")
            try:
                if _count_tokens(pruned) > max_tokens:
                    formatted_chunks = []
                    chunks = []
                    # reuse chunker from summarization by calling chunk_by_tokens indirectly via execute_prompt_chunked
                    # but we need chunks to aggregate appendices; simple split by sections to avoid nested calls
                    # fallback: re-chunk pruned by tokens
                    from ..core.summarization import chunk_by_tokens
                    chunks = chunk_by_tokens(pruned, max_tokens=max_tokens, overlap=200)
                    decisions = set()
                    openqs = set()
                    main_parts = []
                    for ch in chunks:
                        out = execute_prompt(generate_formatting_prompt(ch))
                        # crude split to extract appendices
                        part = out
                        decs = []
                        oqs = []
                        if "[Decisions Log]" in out:
                            part, tail = out.split("[Decisions Log]", 1)
                            decs_section = tail.split("[Open Questions]")[0] if "[Open Questions]" in tail else tail
                            decs = [ln.strip("- ").strip() for ln in decs_section.splitlines() if ln.strip() and not ln.strip().startswith("[")]
                            if "[Open Questions]" in tail:
                                oqs_section = tail.split("[Open Questions]", 1)[1]
                                oqs = [ln.strip("- ").strip() for ln in oqs_section.splitlines() if ln.strip() and not ln.strip().startswith("[")]
                        main_parts.append(part.strip())
                        for d in decs:
                            if d:
                                decisions.add(d)
                        for q in oqs:
                            if q:
                                openqs.add(q)
                    # Merge formatted chunks and normalize boundary tags (keep first BEGIN, last END)
                    main_body = "\n\n".join(mp for mp in main_parts if mp)
                    # Build appendices
                    appx = "\n\n[Decisions Log]\n"
                    for d in sorted(decisions):
                        appx += f"- {d}\n"
                    appx += "\n[Open Questions]\n"
                    for q in sorted(openqs):
                        appx += f"- {q}\n"
                    # Find first BEGIN and last END markers
                    lines = main_body.splitlines()
                    begin_line = None
                    end_line = None
                    end_idxs = []
                    for i, l in enumerate(lines):
                        s = l.strip()
                        if begin_line is None and s.startswith("=== BEGIN DAILY MEMORY:"):
                            begin_line = l.strip()
                        if s.startswith("=== END DAILY MEMORY:"):
                            end_idxs.append(i)
                    if end_idxs:
                        end_line = lines[end_idxs[-1]].strip()
                    # Remove all tag lines from the body
                    body_wo_tags = "\n".join(
                        l for l in lines
                        if not l.strip().startswith("=== BEGIN DAILY MEMORY:")
                        and not l.strip().startswith("=== END DAILY MEMORY:")
                    ).rstrip()
                    # Assemble final: first BEGIN, body, appendices, last END
                    final_parts = []
                    if begin_line:
                        final_parts.append(begin_line + "\n")
                    final_parts.append(body_wo_tags)
                    final_parts.append(appx.rstrip())
                    if end_line:
                        final_parts.append("\n" + end_line)
                    final = "\n\n".join(part for part in final_parts if part is not None)
                else:
                    final = execute_prompt(generate_formatting_prompt(pruned))
                with open(summary_path, "w", encoding="utf-8", newline="\n") as sf:
                    sf.write(_nl(final))
                formatted_count += 1
                logger.info("[SLEEP][FORMAT] Completed project=%s", pid)
                # 3.3 Merge and RAG rebuild
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
                    uploads_dir = os.path.join("memory", pid, "uploads")
                    os.makedirs(uploads_dir, exist_ok=True)
                    cumulative_path = os.path.join(uploads_dir, "sleep_summary_all.txt")
                    merge_lock = os.path.join("memory", pid, "merge.lock")
                    with FileLock(merge_lock):
                        # Create file with one-time header if missing
                        created = False
                        if not os.path.exists(cumulative_path):
                            with open(cumulative_path, "w", encoding="utf-8", newline="\n") as cf:
                                cf.write(_nl("#source: sleep_summary\n\n"))
                            created = True
                        # Append two newlines and then the entire summary verbatim
                        with open(cumulative_path, "a", encoding="utf-8", newline="\n") as cf:
                            cf.write("\n\n")
                            cf.write(_nl(sum_text))
                        logger.info("[SLEEP][MERGE] Appended summary to uploads/sleep_summary_all.txt (created=%s)", created)
                        # Rebuild full uploads index
                        rebuild_faiss_index(pid)
                        logger.info("[MERGE] RAG rebuild complete for %s", pid)
                        # Optional verification
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
                                os.remove(summary_path)
                                logger.info("[SLEEP][CLEANUP] Removed individual summary for %s", pid)
                            except Exception as ce:
                                logger.warning("[SLEEP][CLEANUP] Failed removing summary for %s: %s", pid, ce)
                            # Also remove pruned.txt and daily.txt per finalized cleanup policy
                            try:
                                if os.path.exists(pruned_path):
                                    os.remove(pruned_path)
                                logger.info("[SLEEP][CLEANUP] Removed pruned.txt for %s", pid)
                            except Exception as pe:
                                logger.warning("[SLEEP][CLEANUP] Failed removing pruned.txt for %s: %s", pid, pe)
                            # Clear daily_faiss and remove daily.json so daily memory moves into main RAG
                            try:
                                faiss_dir, meta_path, lock_path, txt_path = _project_daily_paths(pid)
                                with FileLock(lock_path):
                                    # clear daily_faiss files
                                    if os.path.isdir(faiss_dir):
                                        for n in os.listdir(faiss_dir):
                                            fp = os.path.join(faiss_dir, n)
                                            if os.path.isfile(fp):
                                                try:
                                                    os.remove(fp)
                                                except Exception:
                                                    pass
                                    # remove daily.json
                                    if os.path.exists(meta_path):
                                        try:
                                            os.remove(meta_path)
                                        except Exception:
                                            pass
                                    # remove daily.txt
                                    if os.path.exists(txt_path):
                                        try:
                                            os.remove(txt_path)
                                            logger.info("[SLEEP][CLEANUP] Removed daily.txt for %s", pid)
                                        except Exception as te:
                                            logger.warning("[SLEEP][CLEANUP] Failed removing daily.txt for %s: %s", pid, te)
                                logger.info("[SLEEP][MERGE] Cleared daily_faiss and removed daily.json for %s", pid)
                            except Exception as de:
                                logger.warning("[SLEEP][MERGE] Post-merge daily cleanup error for %s: %s", pid, de)
                except Exception as me:
                    logger.error("[SLEEP][MERGE][ERROR] project=%s: %s", pid, me, exc_info=True)
            except Exception as e:
                logger.error("[SLEEP][ERROR] Formatting failed project=%s: %s", pid, e, exc_info=True)
                continue
        logger.info("[SLEEP] Completed (updated_projects=%s, projects_processed=%s, pruned=%s, formatted=%s, skipped_no_daily=%s)",
                    updated, projects_processed, pruned_count, formatted_count, skipped_no_daily)
    except Exception as e:
        logger.error("[SLEEP][ERROR] %s", e, exc_info=True)
    finally:
        try:
            # Duration logging (even on errors)
            try:
                elapsed = time.monotonic() - t0  # type: ignore[name-defined]
                h = int(elapsed // 3600)
                m = int((elapsed % 3600) // 60)
                s = int(elapsed % 60)
                logger.info("[SLEEP] Duration elapsed=%.2fs (%02d:%02d:%02d) since=%s",
                            elapsed, h, m, s, start_iso)
            except Exception:
                pass
            release_lock()
            logger.info("[SLEEP] Lock released")
        except Exception:
            pass

def start_sleep_cycle_async() -> bool:
    """Start sleep cycle in background if not already sleeping. Returns True if started."""
    if is_sleeping():
        logger.info("[SLEEP] Already running, skipping.")
        return False
    global _runner_thread
    with _runner_lock:
        if is_sleeping():
            logger.info("[SLEEP] Already running, skipping.")
            return False
        t = threading.Thread(target=_sleep_cycle_worker, name="sleep-cycle", daemon=True)
        _runner_thread = t
        t.start()
        return True

@router.post("/sleep_cycle", response_model=SleepCycleResponse)
async def sleep_cycle_endpoint(request: SleepCycleRequest) -> SleepCycleResponse:
    """
    Trigger memory pruning and sleep cycle.
    
    This endpoint is stubbed for Version 3 implementation with scheduled cleanup.
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
            response=f"Memory cleanup for project '{request.project_id or 'default'}' is not yet implemented. This feature will be available in Version 3 with scheduled pruning.",
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
                "implementation": "Version 3 with scheduled cleanup"
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
    """Get cleanup schedule information (stubbed for V3)."""
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
                "implementation": "Version 3 with Celery and Redis"
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
    """Set cleanup schedule (stubbed for V3)."""
    try:
        # Log the request
        request_logger.log_request(
            endpoint="/sleep_cycle/schedule",
            method="POST"
        )
        
        # Stubbed schedule setting
        logger.info(f"Cleanup schedule setting requested (stub - will be implemented in V3)")
        
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
                "implementation": "Version 3 with Celery and Redis"
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
                "implementation": "Version 3 with scheduled cleanup"
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
