"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Syx AGI Chatbot Framework - FastAPI Main Entry Point

This is the main FastAPI application that provides the backend API for the Syx chatbot.
It includes endpoints for chat, RAG queries, projects, and sleep cycle management.
"""

import logging
import os
import shutil
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager, redirect_stderr, redirect_stdout

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import select

from .agent_interface import router as agent_interface_router
from .api import chat
from .api import dream as dream_api
from .api import files as files_api
from .api import llm_models, projects, sleep
from .api.sleep import start_sleep_cycle_async

# Import our modules
from .core.config import active_llm_key_status, get_settings, validate_active_llm_key
from .core.database import get_session, init_db
from .core.db_models import Project
from .core.models import HealthResponse
from .core.personality import backfill_all_projects
from .core.route_policy import load_and_validate_route_policy
from .core.state import clear_stale_lock, init_from_disk, is_sleeping, release_lock
from .embedding.factory import get_embedding_client
from .llm_model.factory import get_llm_client, get_llm_client_mini
from .llm_model.registry import LLMModelRegistryError
from .rag.manager import rebuild_faiss_index
from .tracking import get_instrumentation, init_instrumentation
from .utils.logging import get_logger, setup_logging

# Setup logging (only once, check if already configured)
setup_logging()
logger = get_logger()  # Use single shared logger

# Get settings
settings = get_settings()
logger.info("Config: DB_PATH=%s", settings.db_path)

# route_policy.json is required; validate at startup (fail-fast).
try:
    load_and_validate_route_policy()
except Exception as e:  # pragma: no cover - import-time fail-fast guard
    logger.error("[CONFIG] route_policy.json validation failed: %s", e)
    raise


def _collect_git_metadata() -> tuple[str, bool]:
    """Collect the current git commit and dirty-tree flag (best-effort).

    Returns:
        A tuple ``(git_commit, git_dirty)``. Defaults to ``("unknown", False)``
        when git is unavailable or the commands fail.
    """
    git_commit = "unknown"
    git_dirty = False
    try:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if rev.returncode == 0:
            parsed = str(rev.stdout or "").strip()
            if parsed:
                git_commit = parsed
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if dirty.returncode == 0:
            git_dirty = bool(str(dirty.stdout or "").strip())
    except Exception as exc:
        logger.info("[TRACKING] Failed to collect git metadata: %s", exc)
    return git_commit, git_dirty


def _build_run_config(settings, route_policy, git_commit: str, git_dirty: bool) -> dict:
    """Build the instrumentation run-config snapshot for ``start_run``.

    Args:
        settings: Application settings providing model/retrieval/maintenance config.
        route_policy: Mapping of route name to its resolved policy object.
        git_commit: Current git commit hash (or ``"unknown"``).
        git_dirty: Whether the working tree has uncommitted changes.

    Returns:
        A dict with a single ``config_snapshot`` key capturing the effective
        startup configuration.
    """
    s = settings
    from .llm_model.registry import get_active_llm_models

    runtime_models = get_active_llm_models()
    route_policy_snapshot = {}
    for route_name, route_pol in route_policy.items():
        route_policy_snapshot[str(route_name)] = {
            "retrieval_multiplier": float(route_pol.retrieval_multiplier),
            "max_keep": int(route_pol.max_keep),
            "min_score": float(route_pol.min_score),
            "expansion": {
                "max_before": int(route_pol.expansion_max_before),
                "max_after": int(route_pol.expansion_max_after),
            },
        }
    return {
        "config_snapshot": {
            "models_configured": {
                "provider": runtime_models.provider_id,
                "main_model": runtime_models.main_model,
                "builder_model": runtime_models.builder_model,
                "tagger_model": runtime_models.tagger_model,
                "dream_model": runtime_models.dream_model,
            },
            "prompt_budgeting": {
                "model_context_window_tokens": None,
                "max_output_tokens_requested": int(s.model_max_tokens),
                "max_output_tokens_effective": int(s.model_max_tokens),
                "target_max_prompt_tokens": None,
                "history_max_tokens": None,
                "rag_max_tokens": None,
                "profile_max_tokens": None,
                "system_max_tokens": None,
                "prompt_budgeting_known": False,
            },
            "retrieval_static": {
                "base_top_k": int(s.base_top_k),
                "retrieval_multiplier_default": float(s.retrieval_multiplier),
                "embedding_model": str(s.embedding_model),
                "chunk_size": int(s.chunk_size),
                "chunk_overlap": int(s.chunk_overlap),
            },
            "route_policy": route_policy_snapshot,
            "maintenance": {
                "sleep_enabled": True,
                "enable_scheduler": bool(s.enable_scheduler),
                "sleep_cycle_hour": int(s.sleep_cycle_hour),
                "sleep_cycle_minute": int(s.sleep_cycle_minute),
                "verify_rag": bool(s.verify_rag),
                "force_rag_rebuild_on_startup": bool(s.force_rag_rebuild_on_startup),
                "dream_enabled": bool(s.enable_dream),
                "reporting_scope": "sleep_only",
            },
            "instrumentation": {
                "enabled": bool(s.instrumentation_enabled),
                "mode": str(s.instrumentation_mode),
                "run_id_override": s.instrumentation_run_id,
                "runs_dir": str(s.instrumentation_runs_dir),
                "validation": {
                    "prompt_tol_abs_tokens": int(s.instrumentation_prompt_tol_abs_tokens),
                    "prompt_tol_pct": float(s.instrumentation_prompt_tol_pct),
                },
            },
            "git_commit": str(git_commit),
            "git_dirty": bool(git_dirty),
            "python_version": str(sys.version.split()[0]),
        },
    }


def _ensure_default_project() -> None:
    """Ensure the non-deletable system project ``Main`` exists.

    The schema-only initial migration does not seed data, so the default
    ``Main`` project is created here at startup when absent. Idempotent: it is a
    no-op when a project named ``Main`` already exists. Downstream startup steps
    (default backfill, ``USER_PROFILE.txt`` seeding) then operate on it.
    """
    try:
        with get_session() as session:
            existing = session.exec(select(Project).where(Project.name.ilike("Main"))).first()
            if existing is not None:
                return
            project = Project(
                id=str(uuid.uuid4()),
                name="Main",
                description=(
                    "The continuous memory stream where all thoughts, ideas, and "
                    "context flow beyond individual projects."
                ),
                system=True,
            )
            session.add(project)
            session.commit()
            logger.info("[INIT] Seeded default system project 'Main' id=%s", project.id)
    except Exception as e:
        logger.warning("[INIT] Failed to ensure default 'Main' project: %s", e, exc_info=True)


def _init_factory_clients() -> None:
    """Eagerly construct the LLM and embedding factory clients at startup.

    LLM client failures are logged and tolerated. Embedding failures are
    re-raised (fatal) when the configured provider is ``sentence_transformers``,
    since the system cannot embed without it; otherwise they are logged and
    tolerated.
    """
    try:
        get_llm_client()
        get_llm_client_mini()
    except LLMModelRegistryError as exc:
        logger.error("[INIT] LLM model registry preflight failed: %s", exc, exc_info=True)
        raise
    except Exception as exc:
        logger.warning("[INIT] LLM factory startup initialization failed: %s", exc, exc_info=True)
    try:
        get_embedding_client()
    except Exception as exc:
        if str(get_settings().embedding_provider or "").strip().lower() == "sentence_transformers":
            logger.error(
                "[INIT] sentence_transformers embedding provider failed to initialize: %s",
                exc,
                exc_info=True,
            )
            raise
        logger.warning(
            "[INIT] Embedding factory startup initialization failed: %s", exc, exc_info=True
        )
    else:
        logger.info("[INIT] Factory clients initialized at startup")


def _init_instrumentation() -> None:
    """Initialize the instrumentation facade and start the process run if enabled.

    Failures are logged and swallowed so a tracking problem never blocks
    startup.
    """
    try:
        git_commit, git_dirty = _collect_git_metadata()
        instr = init_instrumentation(get_settings(), has_lifespan_hook=True)
        run_cfg = _build_run_config(
            get_settings(),
            load_and_validate_route_policy(),
            git_commit,
            git_dirty,
        )
        run_id = instr.start_run(config=run_cfg)
        if run_id:
            logger.info(
                "[TRACKING] Initialized run_id=%s mode=%s",
                run_id,
                get_settings().instrumentation_mode,
            )
    except Exception as e:
        logger.warning("[TRACKING] Failed to initialize instrumentation: %s", e, exc_info=True)


def _clear_startup_lock() -> None:
    """Clear any leftover sleep lock on startup to avoid a stuck sleep state."""
    try:
        release_lock()
        logger.info("[SLEEP] Cleared any existing lock on startup")
    except Exception as e:
        logger.warning("[SLEEP] Failed clearing startup lock: %s", e)


def _backfill_project_defaults() -> None:
    """Backfill system prompt and personality defaults for existing projects."""
    try:
        backfill_all_projects()
    except Exception as e:
        logger.warning("[PROJECT] Backfill defaults failed: %s", e, exc_info=True)


def _init_sleep_lock_from_disk() -> None:
    """Initialize the in-memory sleep lock from the on-disk lock if present."""
    try:
        init_from_disk()
    except Exception as e:
        logger.warning("[SLEEP] Failed to init lock from disk: %s", e, exc_info=True)


def _seed_main_user_profile() -> None:
    """Seed ``USER_PROFILE.txt`` for the Main project when present and missing.

    Copies the packaged default profile into Main's uploads directory and
    rebuilds its RAG index so the baseline knowledge is retrievable. All
    failures are logged and swallowed (best-effort seeding).
    """
    try:
        with get_session() as session:
            row = session.exec(select(Project).where(Project.name.ilike("Main"))).first()
        if row:
            pid = row.id
            uploads_dir = os.path.join(settings.memory_root, pid, "uploads")
            os.makedirs(uploads_dir, exist_ok=True)
            default_src = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "config", "defaults", "USER_PROFILE.txt")
            )
            default_dst = os.path.join(uploads_dir, "USER_PROFILE.txt")
            if os.path.isfile(default_src):
                if not os.path.exists(default_dst):
                    shutil.copy(default_src, default_dst)
                    logger.info("[INIT] Added user profile file to %s", default_dst)
                    try:
                        rebuild_faiss_index(pid)
                        logger.info(
                            "[INIT] RAG rebuilt for project %s (includes USER_PROFILE.txt)", pid
                        )
                    except Exception as re:
                        logger.warning("[INIT] RAG rebuild failed for project %s: %s", pid, re)
            else:
                logger.warning(
                    "[WARN] USER_PROFILE.txt not found; Main created without baseline knowledge."
                )
    except Exception as e:
        logger.warning("[INIT] Main seed failed: %s", e, exc_info=True)


def _startup_rag_rebuild_sweep() -> None:
    """Optionally rebuild every project's RAG index from uploads at startup.

    Controlled by ``FORCE_RAG_REBUILD_ON_STARTUP``; per-project rebuild failures
    are isolated and logged, and the whole sweep is best-effort.
    """
    try:
        if bool(get_settings().force_rag_rebuild_on_startup):
            with get_session() as session:
                project_ids = [p.id for p in session.exec(select(Project)).all()]

            logger.info(
                "[INIT] FORCE_RAG_REBUILD_ON_STARTUP enabled; rebuilding RAG for %s project(s).",
                len(project_ids),
            )
            for pid in project_ids:
                try:
                    rebuild_faiss_index(pid)
                    logger.info("[INIT] RAG rebuilt at startup for project %s", pid)
                except Exception as re:
                    logger.warning("[INIT] Startup RAG rebuild failed for project %s: %s", pid, re)
        else:
            logger.info("[INIT] FORCE_RAG_REBUILD_ON_STARTUP disabled; skipping full RAG rebuild.")
    except Exception as e:
        logger.warning("[INIT] Startup RAG rebuild sweep failed: %s", e, exc_info=True)


def _start_sleep_scheduler() -> None:
    """Start the daily background sleep-cycle scheduler when enabled.

    Failures are logged and swallowed so a scheduler problem never blocks
    startup.
    """
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


# Lifespan handler to manage startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown side effects.

    On startup this initializes the database, ensures the default ``Main``
    system project exists, eagerly constructs the LLM and embedding factory
    clients, starts the instrumentation run, clears any leftover sleep lock,
    backfills project defaults, seeds ``USER_PROFILE.txt`` for the Main project
    (rebuilding its RAG index), optionally rebuilds every project's RAG index,
    and starts the daily sleep scheduler. On shutdown it finalizes the
    instrumentation run.
    """
    logger.info("FastAPI startup")
    init_db()
    # Seed the default system project ('Main') when absent. The squashed,
    # schema-only initial migration no longer creates it as a data seed.
    _ensure_default_project()
    _init_factory_clients()
    _init_instrumentation()
    _clear_startup_lock()
    _backfill_project_defaults()
    _init_sleep_lock_from_disk()
    _seed_main_user_profile()
    _startup_rag_rebuild_sweep()
    _start_sleep_scheduler()
    try:
        yield
    finally:
        try:
            get_instrumentation().end_run(summary={"reason": "lifespan_shutdown"})
        except Exception as e:
            logger.warning(
                "[TRACKING] Failed to finalize instrumentation run: %s", e, exc_info=True
            )
        logger.info("FastAPI shutdown: cleaning up resources...")


# Initialize FastAPI app with lifespan
app = FastAPI(
    title="Syx AGI Chatbot API",
    description="Backend API for the Syx chatbot framework",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
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
app.include_router(projects.router, tags=["projects"])
app.include_router(sleep.router, tags=["sleep"])
app.include_router(files_api.router, tags=["files"])
app.include_router(llm_models.router, tags=["models"])
app.include_router(dream_api.router, tags=["dream"])
app.include_router(agent_interface_router.router, tags=["agent-interface"])


# Write-blocking middleware during sleep
@app.middleware("http")
async def sleep_guard(request: Request, call_next):
    """Reject mutating requests with HTTP 423 while a sleep cycle is in progress.

    GET requests and a small recovery allowlist (sleep unlock, agent memory
    search) are always permitted so the system can be inspected and recovered.
    A failure to read the sleep state is logged and treated as not-sleeping so
    the request proceeds.

    Args:
        request: The incoming HTTP request.
        call_next: The downstream ASGI handler invoked when the request is
            allowed through.

    Returns:
        A 423 ``JSONResponse`` when blocked, otherwise the downstream response.
    """
    try:
        method = request.method.upper()
        path = request.url.path.rstrip("/") or "/"
        sleep_recovery_allowlist = {
            ("POST", "/sleep/unlock"),
            ("POST", "/agent/memory/search"),
        }
        if is_sleeping() and method != "GET" and (method, path) not in sleep_recovery_allowlist:
            return JSONResponse(
                status_code=423, content={"error": "System is sleeping. Try again later."}
            )
    except Exception as exc:
        logger.warning(
            "[SLEEP] sleep_guard state check failed; method=%s detail=%s", request.method, exc
        )
    return await call_next(request)


def _schedule_entrypoint():
    """Scheduler callback that launches the daily sleep cycle.

    Clears a stale lock if present, then starts an async sleep cycle unless one
    is already running. All failures are logged and swallowed so the scheduler
    thread is never broken by a single misfire.
    """
    try:
        # Clear stale lock if present (older than default window)
        try:
            cleared = clear_stale_lock()
            if cleared:
                logger.info("[SLEEP] Cleared stale lock before scheduled run")
        except Exception as exc:
            logger.info("[SLEEP] clear_stale_lock failed before scheduled run: %s", exc)
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
    """Serve the built React app, or API info when no build is present.

    Returns:
        A ``FileResponse`` for the SPA ``index.html`` when the static build
        exists; otherwise a JSON dict describing the API and build instructions.
    """
    # Check if static files exist (React build)
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    index_file = os.path.join(static_dir, "index.html")

    if os.path.exists(index_file):
        # Serve React app
        return FileResponse(index_file)
    else:
        # Return API info if no React build
        return {
            "message": "Syx AGI Chatbot API is running",
            "frontend": "Not built - run 'make build' to build React app",
            "docs": "/api/docs",
        }


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Report service health and downstream dependency status.

    Returns:
        A ``HealthResponse`` whose status is ``healthy`` when the API key is
        configured, ``degraded`` when it is missing, or ``unhealthy`` when the
        check itself raises.
    """
    try:
        key_status = active_llm_key_status()
        api_key_status = key_status["status"]

        # Check LLM health
        from .core.llm_service import get_llm_health

        llm_health = get_llm_health()

        dependencies = {
            key_status["dependency"]: api_key_status,
            "llm": llm_health["status"],
        }

        return HealthResponse(
            status="healthy" if api_key_status == "configured" else "degraded",
            dependencies=dependencies,
        )

    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return HealthResponse(status="unhealthy", dependencies={"error": str(e)})


# Catch-all route for React Router (SPA support)
@app.get("/{full_path:path}")
async def serve_react_app(full_path: str):
    """Serve the React SPA for all non-API routes (client-side routing support).

    Args:
        full_path: The unmatched request path captured by the catch-all route.

    Returns:
        A ``FileResponse`` for the SPA ``index.html`` when the build exists,
        otherwise a JSON dict explaining that the frontend is not built.

    Raises:
        HTTPException: 404 when the path targets an API/docs route, so FastAPI's
            own handlers take precedence.
    """
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    index_file = os.path.join(static_dir, "index.html")

    # If it's an API route, let FastAPI handle it
    if (
        full_path.startswith("api/")
        or full_path.startswith("docs")
        or full_path.startswith("redoc")
    ):
        raise HTTPException(status_code=404, detail="API endpoint not found")

    # Serve React app for all other routes
    if os.path.exists(index_file):
        return FileResponse(index_file)
    else:
        return {
            "error": "Frontend not built",
            "message": "Run 'make build' to build the React frontend",
            "path": full_path,
        }


class LoggingRedirect:
    """File-like adapter that forwards stdout/stderr writes to the logger."""

    def __init__(self, logger, level):
        """Configure the adapter to forward writes to a logger at one level.

        Args:
            logger: Logger that received writes are forwarded to.
            level: Logging level used for forwarded lines.
        """
        self.logger = logger
        self.level = level
        self.buffer = ""

    def write(self, text):
        """Forward a non-empty stdout/stderr write to the configured logger.

        Blank writes are dropped, and sentence-transformers/tqdm weight-loading
        progress is suppressed except for the completed line (demoted to INFO)
        so genuine warnings/errors retain their severity.

        Args:
            text: The text chunk written to the redirected stream.
        """
        line = (text or "").strip()
        if not line:
            return
        # sentence-transformers/tqdm prints weight-loading progress to stderr.
        # Keep only the completed progress line and demote it to INFO so stderr
        # redirection still preserves warning/error semantics for real failures.
        if "Loading weights:" in line:
            if "100%|" in line:
                self.logger.info(line)
            return
        self.logger.log(self.level, line)

    def flush(self):
        pass


def _flush_and_close_log_handlers() -> None:
    """Flush and close all root logger handlers for a clean shutdown.

    Per-handler flush/close failures are logged at INFO and tolerated so a
    single misbehaving handler cannot break shutdown.
    """
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        try:
            handler.flush()
        except Exception as exc:
            logger.info(
                "[SHUTDOWN] Failed to flush log handler %s: %s", type(handler).__name__, exc
            )
        try:
            if hasattr(handler, "close"):
                handler.close()
        except Exception as exc:
            logger.info(
                "[SHUTDOWN] Failed to close log handler %s: %s", type(handler).__name__, exc
            )


def run_server() -> None:
    """Launch the uvicorn server (the ``python -m app.main`` entry point).

    Validates the OpenAI key (warn-only), reads host/port from settings, and
    runs uvicorn. Outside DEBUG, stdout/stderr are redirected through the shared
    logger so third-party output keeps consistent formatting and severity. On
    Ctrl-C it shuts down gracefully, and log handlers are always flushed/closed.
    """
    import uvicorn

    # Validate configuration
    if not validate_active_llm_key():
        key_status = active_llm_key_status()
        logger.warning(
            "%s not configured for LLM_PROVIDER=%s. Set %s environment variable.",
            key_status["setting"],
            key_status["provider"],
            key_status["setting"],
        )
        logger.info("You can still run the server, but chat functionality will not work.")

    # Get configuration from settings
    host = settings.host
    port = settings.port

    logger.info(f"Starting Syx API server on {host}:{port}")
    logger.info(f"API Documentation: http://{host}:{port}/api/docs")
    logger.info(f"Health Check: http://{host}:{port}/health")

    # Restore stdout/stderr redirection so uvicorn and other libs flow through our logger
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
                log_config=None,
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
                    log_config=None,
                )
    except KeyboardInterrupt:  # pragma: no cover - OS interrupt signal
        logger.info("Received Ctrl-C (KeyboardInterrupt). Shutting down gracefully...")
    finally:
        _flush_and_close_log_handlers()


if __name__ == "__main__":  # pragma: no cover - process entry point
    run_server()
