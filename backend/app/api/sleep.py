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

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize logger
request_logger = RequestLogger("sleep")


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
    """Engage global sleep lock and update daily.txt for all projects (stub for 3.0)."""
    try:
        request_logger.log_request(endpoint="/sleep/start", method="POST")
        engage_lock()
        logger.info("[SLEEP] Lock engaged at %s", time.strftime("%H:%M", time.localtime()))
        # Update or backfill daily.txt for all projects
        try:
            with get_session() as session:
                rows = session.exec(select(Project)).all()
        except Exception:
            rows = []
        updated = 0
        for p in rows or []:
            try:
                if backfill_daily_txt_from_meta(p.id):
                    updated += 1
            except Exception:
                pass
        release_lock()
        logger.info("[SLEEP] Lock released at %s", time.strftime("%H:%M", time.localtime()))
        return JSONResponse(status_code=200, content={
            "status": "sleep cycle initiated",
            "updated_projects": updated,
        })
    except Exception as e:
        try:
            release_lock()
        except Exception:
            pass
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
