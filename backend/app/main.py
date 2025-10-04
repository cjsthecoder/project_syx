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
from .utils.logging import setup_logging, get_logger

# Setup logging (only once, check if already configured)
setup_logging()
logger = get_logger()  # Use single shared logger

# Get settings
settings = get_settings()

# Lifespan handler to manage startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI startup")
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
    
    # Suppress uvicorn's direct output by redirecting stdout/stderr temporarily
    import sys
    from contextlib import redirect_stdout, redirect_stderr
    
    class LoggingRedirect:
        def __init__(self, logger, level):
            self.logger = logger
            self.level = level
            self.buffer = ""
        
        def write(self, text):
            if text.strip():  # Only log non-empty lines
                self.logger.log(self.level, text.strip())
        
        def flush(self):
            pass
    
    # Redirect stdout and stderr to our logger
    stdout_redirect = LoggingRedirect(logger, logging.INFO)
    stderr_redirect = LoggingRedirect(logger, logging.WARNING)
    
    try:
        with redirect_stdout(stdout_redirect), redirect_stderr(stderr_redirect):
            uvicorn.run(
            app,
            host=host,
            port=port,
            reload=False,  # Disable reloader completely
                log_level="info",  # Capture WARNING messages from uvicorn
                access_log=False,  # Disable uvicorn access logs (we handle our own)
                use_colors=False,  # Use our custom formatter instead
                log_config=None  # Disable uvicorn's default logging config
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
