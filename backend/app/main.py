"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Morpheus AGI Chatbot Framework - FastAPI Main Entry Point

This is the main FastAPI application that provides the backend API for the Morpheus chatbot.
It includes endpoints for chat, RAG queries, projects, and sleep cycle management.
"""

from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional
import os
import logging

# Set up module-level logger
logger = logging.getLogger(__name__)

# Import our modules
from .core.config import get_settings, validate_openai_key
from .core.models import HealthResponse
from .api import chat, rag, projects, sleep
from .api import dream as dream_api
from .api import files as files_api
from .api import llm_models
from .utils.logging import setup_logging, get_logger
from .core.database import init_db
from .core.state import init_from_disk, is_sleeping
from .core.personality import backfill_all_projects
from .core.database import get_session
from .core.db_models import Project
from .core.rag_manager import rebuild_faiss_index
import shutil
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from .api.sleep import start_sleep_cycle_async, is_sleeping

# Setup logging (only once, check if already configured)
setup_logging()
logger = get_logger()  # Use single shared logger

# Get settings
settings = get_settings()
logger.info("Config: DB_PATH=%s", settings.db_path)

# Lifespan handler to manage startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI startup")
    init_db()
    # Clear any leftover lock on startup to avoid stuck sleep state
    try:
        from .core.state import release_lock
        release_lock()
        logger.info("[SLEEP] Cleared any existing lock on startup")
    except Exception as e:
        logger.warning("[SLEEP] Failed clearing startup lock: %s", e)
    # V2.6: Backfill system prompt and personality defaults for existing projects
    try:
        backfill_all_projects()
    except Exception as e:
        logger.warning("[PROJECT] Backfill defaults failed: %s", e, exc_info=True)
    # V2.7: Initialize sleep lock from disk if present
    try:
        init_from_disk()
    except Exception as e:
        logger.warning("[SLEEP] Failed to init lock from disk: %s", e, exc_info=True)
    # V2.8: Seed DEFAULT_RAG for Continuum if present and missing
    try:
        from sqlmodel import select
        with get_session() as session:
            row = session.exec(select(Project).where(Project.name.ilike("Continuum"))).first()
        if row:
            pid = row.id
            uploads_dir = os.path.join("memory", pid, "uploads")
            os.makedirs(uploads_dir, exist_ok=True)
            default_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "config", "defaults", "DEFAULT_RAG.txt"))
            default_dst = os.path.join(uploads_dir, "DEFAULT_RAG.txt")
            if os.path.isfile(default_src):
                if not os.path.exists(default_dst):
                    shutil.copy(default_src, default_dst)
                    logger.info("[INIT] Added default RAG file to %s", default_dst)
                    try:
                        rebuild_faiss_index(pid)
                        logger.info("[INIT] RAG rebuilt for project %s (includes DEFAULT_RAG.txt)", pid)
                    except Exception as re:
                        logger.warning("[INIT] RAG rebuild failed for project %s: %s", pid, re)
            else:
                logger.warning("[WARN] DEFAULT_RAG.txt not found; Continuum created without baseline knowledge.")
    except Exception as e:
        logger.warning("[INIT] Continuum seed failed: %s", e, exc_info=True)
    # V3.1: Start daily scheduler if enabled
    try:
        if get_settings().enable_scheduler:
            sched = BackgroundScheduler(timezone=None)
            hour = int(get_settings().sleep_cycle_hour)
            minute = int(get_settings().sleep_cycle_minute)
            sched.add_job(
                lambda: (_schedule_entrypoint()),
                trigger=CronTrigger(hour=hour, minute=minute),
                id="sleep_cycle_job",
                replace_existing=True,
                misfire_grace_time=6 * 60 * 60,
                coalesce=True,
            )
            sched.start()
            logger.info("[SCHED] Sleep scheduler started (hour=%s, minute=%s)", hour, minute)
    except Exception as e:
        logger.warning("[SCHED] Failed to start scheduler: %s", e, exc_info=True)
    try:
        yield
    finally:
        logger.info("FastAPI shutdown: cleaning up resources...")

# Initialize FastAPI app with lifespan
app = FastAPI(
    title="Morpheus AGI Chatbot API",
    description="Backend API for the Morpheus chatbot framework",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan
)

# Add CORS middleware for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(chat.router, tags=["chat"])
app.include_router(rag.router, tags=["rag"])
app.include_router(projects.router, tags=["projects"])
app.include_router(sleep.router, tags=["sleep"])
app.include_router(files_api.router, tags=["files"])
app.include_router(llm_models.router, tags=["models"])
app.include_router(dream_api.router, tags=["dream"])

# V2.7: Write-blocking middleware during sleep
from fastapi.responses import JSONResponse
from .core.state import clear_stale_lock

@app.middleware("http")
async def sleep_guard(request, call_next):
    try:
        if is_sleeping() and request.method.upper() != "GET":
            return JSONResponse(status_code=423, content={"error": "System is sleeping. Try again later."})
    except Exception:
        pass
    return await call_next(request)

def _schedule_entrypoint():
    try:
        # Clear stale lock if present (older than default window)
        try:
            cleared = clear_stale_lock()
            if cleared:
                logger.info("[SLEEP] Cleared stale lock before scheduled run")
        except Exception:
            pass
        if not is_sleeping():
            start_sleep_cycle_async()
        else:
            logger.info("[SLEEP] Already running, skipping.")
    except Exception as e:
        logger.warning("[SCHED] Schedule entrypoint failed: %s", e, exc_info=True)

# Mount static files (React build output)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Health check endpoints
@app.get("/")
async def root():
    """Root endpoint - serves React app or API info."""
    # Check if static files exist (React build)
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    index_file = os.path.join(static_dir, "index.html")
    
    if os.path.exists(index_file):
        # Serve React app
        return FileResponse(index_file)
    else:
        # Return API info if no React build
        return {
            "message": "Morpheus AGI Chatbot API is running",
            "frontend": "Not built - run 'make build' to build React app",
            "docs": "/api/docs"
        }

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Detailed health check with dependency status."""
    try:
        # Check OpenAI API key
        api_key_status = "configured" if validate_openai_key() else "missing"
        
        # Check LLM health
        from .core.llm import get_llm_health
        llm_health = get_llm_health()
        
        dependencies = {
            "openai": api_key_status,
            "langchain": llm_health["status"]
        }
        
        return HealthResponse(
            status="healthy" if api_key_status == "configured" else "degraded",
            dependencies=dependencies
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return HealthResponse(
            status="unhealthy",
            dependencies={"error": str(e)}
        )

# Catch-all route for React Router (SPA support)
@app.get("/{full_path:path}")
async def serve_react_app(full_path: str):
    """Serve React app for all non-API routes."""
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    index_file = os.path.join(static_dir, "index.html")
    
    # If it's an API route, let FastAPI handle it
    if full_path.startswith("api/") or full_path.startswith("docs") or full_path.startswith("redoc"):
        raise HTTPException(status_code=404, detail="API endpoint not found")
    
    # Serve React app for all other routes
    if os.path.exists(index_file):
        return FileResponse(index_file)
    else:
        return {
            "error": "Frontend not built",
            "message": "Run 'make build' to build the React frontend",
            "path": full_path
        }

if __name__ == "__main__":
    import uvicorn
    
    # Validate configuration
    if not validate_openai_key():
        logger.warning("OpenAI API key not configured. Set OPENAI_API_KEY environment variable.")
        logger.info("You can still run the server, but chat functionality will not work.")
    
    # Get configuration from settings
    host = settings.host
    port = settings.port
    reload = settings.reload
    
    logger.info(f"Starting Morpheus API server on {host}:{port}")
    logger.info(f"API Documentation: http://{host}:{port}/api/docs")
    logger.info(f"Health Check: http://{host}:{port}/health")
    
    # Restore stdout/stderr redirection so uvicorn and other libs flow through our logger
    import sys
    from contextlib import redirect_stdout, redirect_stderr

    class LoggingRedirect:
        def __init__(self, logger, level):
            self.logger = logger
            self.level = level
            self.buffer = ""

        def write(self, text):
            if text.strip():
                self.logger.log(self.level, text.strip())

        def flush(self):
            pass

    stdout_redirect = LoggingRedirect(logger, logging.INFO)
    stderr_redirect = LoggingRedirect(logger, logging.WARNING)

    # Match uvicorn log level to our LOG_LEVEL
    uvicorn_level = "debug" if get_settings().log_level.upper() == "DEBUG" else "info"

    try:
        if get_settings().log_level.upper() == "DEBUG":
            # In DEBUG, do not redirect so DEBUG logs print directly to console
            uvicorn.run(
                app,
                host=host,
                port=port,
                reload=False,
                log_level=uvicorn_level,
                access_log=False,
                use_colors=False,
                log_config=None
            )
        else:
            with redirect_stdout(stdout_redirect), redirect_stderr(stderr_redirect):
                uvicorn.run(
                    app,
                    host=host,
                    port=port,
                    reload=False,
                    log_level=uvicorn_level,
                    access_log=False,
                    use_colors=False,
                    log_config=None
                )
    except KeyboardInterrupt:
        logger.info("Received Ctrl-C (KeyboardInterrupt). Shutting down gracefully...")
    finally:
        # Flush and close logging handlers to ensure clean shutdown
        root_logger = logging.getLogger()
        for handler in list(root_logger.handlers):
            try:
                handler.flush()
            except Exception:
                pass
            try:
                if hasattr(handler, "close"):
                    handler.close()
            except Exception:
                pass
