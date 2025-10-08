"""
Projects API endpoint for Morpheus AGI Chatbot Framework.

This module provides project management functionality (stubbed for Version 4).
"""

import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

# Set up module-level logger
logger = logging.getLogger(__name__)

from ..core.models import ProjectRequest, ProjectResponse, ErrorResponse
from ..core.database import get_session
from ..core.db_models import Project, File
from sqlmodel import select
from ..utils.logging import RequestLogger
from ..utils.errors import handle_project_error, log_error_context
import uuid
import os
from ..core.memory import get_memory_manager, get_last_context_tokens

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize logger
request_logger = RequestLogger("projects")

# Current project state (simple in-memory pointer)
_current_project = None


@router.get("/projects")
async def get_projects() -> JSONResponse:
    try:
        request_logger.log_request(endpoint="/projects", method="GET")
        with get_session() as session:
            rows = session.exec(select(Project).order_by(Project.created_at.desc())).all()
            available_projects = [p.id for p in rows]
            id_to_name = {}
            for p in rows:
                name = p.name or p.id
                # Normalize legacy pattern 'Project {id}' to just id
                if isinstance(name, str) and name.lower().startswith('project '):
                    tail = name[8:].strip()
                    if tail == p.id:
                        name = tail
                id_to_name[p.id] = name
            # Init default selection to Continuum by name
            global _current_project
            if _current_project is None:
                for p in rows:
                    if p.name.lower() == "continuum":
                        _current_project = p.id
                        break
                if _current_project is None and rows:
                    _current_project = rows[0].id
        request_logger.log_response(endpoint="/projects", status_code=200, response_time=0.0)
        return JSONResponse(status_code=200, content={
            "response": "OK",
            "current_project": _current_project,
            "available_projects": available_projects,
            "project_names": id_to_name,
        })
    except Exception as e:
        request_logger.log_error(endpoint="/projects", error=e)
        log_error_context(error=e, context={"endpoint": "/projects", "method": "GET"})
        raise handle_project_error(e)


@router.post("/projects")
async def create_or_switch_project(request: ProjectRequest) -> JSONResponse:
    try:
        request_logger.log_request(endpoint="/projects", method="POST", user_id=request.project_id)
        global _current_project
        with get_session() as session:
            if request.project_id:
                obj = session.get(Project, request.project_id)
                if obj:
                    _current_project = obj.id
                    message = f"Switched to project '{obj.name}'"
                else:
                    raise HTTPException(status_code=404, detail={"error": "Project not found"})
            else:
                # Create new project by name
                if not request.project_name:
                    raise HTTPException(status_code=400, detail={"error": "project_name required"})
                # Enforce case-insensitive unique name
                lower = request.project_name.strip().lower()
                exists = session.exec(select(Project).where(Project.name.ilike(request.project_name))).first()
                if exists:
                    raise HTTPException(status_code=409, detail={"error": "Project name already exists"})
                new_id = str(uuid.uuid4())
                obj = Project(id=new_id, name=request.project_name.strip(), description=request.project_name.strip(), system=False)
                session.add(obj)
                session.commit()
                _current_project = obj.id
                message = f"Created and switched to new project '{obj.name}'"
        with get_session() as session:
            rows = session.exec(select(Project)).all()
            available_projects = [p.id for p in rows]
            id_to_name = {}
            for p in rows:
                name = p.name or p.id
                if isinstance(name, str) and name.lower().startswith('project '):
                    tail = name[8:].strip()
                    if tail == p.id:
                        name = tail
                id_to_name[p.id] = name
        return JSONResponse(status_code=200, content={
            "success": True,
            "response": message,
            "current_project": _current_project,
            "available_projects": available_projects,
            "project_names": id_to_name,
        })
    except HTTPException:
        raise
    except Exception as e:
        request_logger.log_error(endpoint="/projects", error=e, user_id=request.project_id)
        log_error_context(error=e, context={"endpoint": "/projects", "method": "POST", "project_id": request.project_id, "project_name": request.project_name})
        raise handle_project_error(e)


@router.patch("/projects/{project_id}")
async def rename_project(project_id: str, request: ProjectRequest) -> JSONResponse:
    try:
        if not request.project_name:
            raise HTTPException(status_code=400, detail={"error": "project_name is required"})
        with get_session() as session:
            obj = session.get(Project, project_id)
            if not obj:
                raise HTTPException(status_code=404, detail={"error": "Project not found"})
            if obj.system:
                raise HTTPException(status_code=400, detail={"error": "Cannot modify system project"})
            # unique name check
            exists = session.exec(select(Project).where(Project.name.ilike(request.project_name)).where(Project.id != project_id)).first()
            if exists:
                raise HTTPException(status_code=409, detail={"error": "Project name already exists"})
            obj.name = request.project_name.strip()
            obj.description = request.project_name.strip() if obj.description is None else obj.description
            session.add(obj)
            session.commit()
        return JSONResponse(status_code=200, content={"success": True, "response": "Renamed", "project_id": project_id, "name": obj.name})
    except HTTPException:
        raise
    except Exception as e:
        raise handle_project_error(e)


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str) -> JSONResponse:
    try:
        with get_session() as session:
            obj = session.get(Project, project_id)
            if not obj:
                raise HTTPException(status_code=404, detail={"error": "Project not found"})
            if obj.system:
                raise HTTPException(status_code=400, detail={"error": "Cannot delete system project"})
            session.delete(obj)
            session.commit()
        # Delete disk directories
        base = os.path.join("memory", project_id)
        try:
            if os.path.isdir(base):
                for root, dirs, files in os.walk(base, topdown=False):
                    for name in files:
                        try:
                            os.remove(os.path.join(root, name))
                        except Exception:
                            pass
                    for name in dirs:
                        try:
                            os.rmdir(os.path.join(root, name))
                        except Exception:
                            pass
                os.rmdir(base)
        except Exception:
            pass
        # Reset current project to Continuum if needed
        global _current_project
        if _current_project == project_id:
            with get_session() as session:
                rows = session.exec(select(Project)).all()
                fallback = None
                for p in rows:
                    if p.name.lower() == "continuum":
                        fallback = p.id
                        break
                _current_project = fallback or (rows[0].id if rows else None)
        return JSONResponse(status_code=200, content={"message": "Project deleted", "project_id": project_id, "current_project": _current_project})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete project {project_id}: {str(e)}")
        return JSONResponse(status_code=500, content={"error": "Failed to delete project", "project_id": project_id, "details": str(e)})


@router.get("/projects/{project_id}/stats")
async def project_stats(project_id: str) -> JSONResponse:
    """Return storage_bytes, index_size_bytes, tokens_indexed, context_tokens, file_count."""
    # storage and tokens from DB
    with get_session() as session:
        rows = session.exec(select(File).where(File.project_id == project_id)).all()
        storage_bytes = sum(r.size_bytes for r in rows)
        tokens_indexed = sum(r.token_count for r in rows)
        file_count = len(rows)
    # index size
    base = os.path.join("memory", project_id, "faiss")
    index_size = 0
    if os.path.isdir(base):
        for root, _, files in os.walk(base):
            for n in files:
                try:
                    index_size += os.path.getsize(os.path.join(root, n))
                except Exception:
                    pass
    # context tokens from memory manager
    context_tokens = get_last_context_tokens(project_id)
    return JSONResponse(status_code=200, content={
        "project_id": project_id,
        "storage_bytes": storage_bytes,
        "index_size_bytes": index_size,
        "tokens_indexed": tokens_indexed,
        "context_tokens": context_tokens,
        "file_count": file_count,
    })
