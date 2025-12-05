"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
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
from ..core.personality import (
    load_project_system_prompt,
    load_project_personality,
    save_project_system_prompt,
    save_project_personality,
    seed_project_defaults,
)
from ..core.database import get_session
from ..core.db_models import ChatMessage
from ..core.daily_rag import daily_stats
from ..core.rag_manager import rebuild_faiss_index
import shutil

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
                # V2.6: seed default prompt/personality files
                try:
                    seed_project_defaults(obj.id)
                except Exception as e:
                    logger.warning("[PROJECT] Failed to seed defaults for project %s: %s", obj.id, e, exc_info=True)
                _current_project = obj.id
                message = f"Created and switched to new project '{obj.name}'"
                # V2.8: Seed DEFAULT_RAG.txt and rebuild RAG
                try:
                    uploads_dir = os.path.join("memory", obj.id, "uploads")
                    os.makedirs(uploads_dir, exist_ok=True)
                    default_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "defaults", "DEFAULT_RAG.txt"))
                    default_dst = os.path.join(uploads_dir, "DEFAULT_RAG.txt")
                    if os.path.isfile(default_src):
                        if os.path.exists(default_dst):
                            logger.warning("[INIT] DEFAULT_RAG.txt already exists for project %s; skipping copy", obj.id)
                        else:
                            shutil.copy(default_src, default_dst)
                            logger.info("[INIT] Added default RAG file to %s", default_dst)
                    else:
                        logger.warning("[WARN] DEFAULT_RAG.txt not found; project %s created without baseline knowledge.", obj.id)
                    try:
                        rebuild_faiss_index(obj.id)
                        logger.info("[INIT] RAG rebuilt for project %s (includes DEFAULT_RAG.txt when present)", obj.id)
                    except Exception as re:
                        logger.warning("[INIT] RAG rebuild failed for project %s: %s", obj.id, re)
                except Exception as se:
                    logger.warning("[INIT] Failed seeding default RAG for project %s: %s", obj.id, se)
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
        if not request.project_name and (request.daily_rag_enabled is None):
            raise HTTPException(status_code=400, detail={"error": "No fields to update"})
        with get_session() as session:
            obj = session.get(Project, project_id)
            if not obj:
                raise HTTPException(status_code=404, detail={"error": "Project not found"})
            if obj.system:
                raise HTTPException(status_code=400, detail={"error": "Cannot modify system project"})
            if request.project_name:
                # unique name check
                exists = session.exec(select(Project).where(Project.name.ilike(request.project_name)).where(Project.id != project_id)).first()
                if exists:
                    raise HTTPException(status_code=409, detail={"error": "Project name already exists"})
                obj.name = request.project_name.strip()
                obj.description = request.project_name.strip() if obj.description is None else obj.description
            if request.daily_rag_enabled is not None:
                obj.daily_rag_enabled = bool(request.daily_rag_enabled)
            session.add(obj)
            session.commit()
            # capture values before session context exits to avoid DetachedInstanceError
            name_val = obj.name
            daily_val = obj.daily_rag_enabled
        return JSONResponse(status_code=200, content={"success": True, "response": "Updated", "project_id": project_id, "name": name_val, "daily_rag_enabled": daily_val})
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
                        except Exception as e:
                            logger.warning("[PROJECT] Failed removing file %s: %s", os.path.join(root, name), e)
                    for name in dirs:
                        try:
                            os.rmdir(os.path.join(root, name))
                        except Exception as e:
                            logger.warning("[PROJECT] Failed removing dir %s: %s", os.path.join(root, name), e)
                os.rmdir(base)
        except Exception as e:
            logger.warning("[PROJECT] Failed cleaning project directory %s: %s", base, e)
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
    # If missing/zero, recompute from stored working memory for this project (excludes any RAG system prompts)
    if not context_tokens:
        try:
            mm = get_memory_manager()
            history = mm.get_project_history(project_id) or []
            combined_text = "\n".join((m.get("content") or "") for m in history)
            if combined_text.strip():
                try:
                    import tiktoken  # type: ignore
                    enc = tiktoken.get_encoding("cl100k_base")
                    context_tokens = len(enc.encode(combined_text))
                except Exception:
                    # Fallback: rough estimate by whitespace tokens if encoder unavailable
                    context_tokens = len([w for w in combined_text.split() if w])
                # cache for future stats calls
                mm.set_last_context_tokens(project_id, int(context_tokens))
        except Exception:
            # On any failure, leave as zero
            pass
    # daily stats
    dstat = daily_stats(project_id)
    # active pairs from memory manager
    try:
        mm2 = get_memory_manager()
        active_pairs = mm2.get_active_pair_count(project_id)
    except Exception:
        active_pairs = 0
    return JSONResponse(status_code=200, content={
        "project_id": project_id,
        "storage_bytes": storage_bytes,
        "index_size_bytes": index_size,
        "tokens_indexed": tokens_indexed,
        "context_tokens": context_tokens,
        "file_count": file_count,
        "daily_index_size_bytes": dstat.get("daily_index_size_bytes", 0),
        "daily_tokens_indexed": dstat.get("daily_tokens_indexed", 0),
        "daily_vector_count": dstat.get("daily_vector_count", 0),
        "active_pairs": active_pairs,
    })


@router.get("/projects/{project_id}")
async def get_project_detail(project_id: str) -> JSONResponse:
    try:
        with get_session() as session:
            obj = session.get(Project, project_id)
            if not obj:
                raise HTTPException(status_code=404, detail={"error": "Project not found"})
            return JSONResponse(status_code=200, content={
                "project": {
                    "id": obj.id,
                    "name": obj.name,
                    "description": obj.description,
                    "created_at": obj.created_at.isoformat(),
                    "updated_at": obj.updated_at.isoformat(),
                    "system": obj.system,
                    "daily_rag_enabled": obj.daily_rag_enabled,
                }
            })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get project detail {project_id}: {e}")
        return JSONResponse(status_code=500, content={"error": "Failed to retrieve project"})


@router.get("/projects/{project_id}/chats")
async def get_project_chats(project_id: str) -> JSONResponse:
    """Return the most recent N messages for the project in chronological order."""
    try:
        mm = get_memory_manager()
        messages = mm.get_project_history(project_id)
        # Normalize datetime to ISO strings for JSON response
        normalized = [
            {
                "id": m.get("id"),
                "role": m.get("role"),
                "content": m.get("content"),
                "created_at": (m.get("created_at").isoformat() if hasattr(m.get("created_at"), "isoformat") else m.get("created_at")),
                "forget": (bool(m.get("forget")) if m.get("role") == "assistant" else None),
                "keep": (bool(m.get("keep")) if m.get("role") == "assistant" else None),
            }
            for m in messages
        ]
        return JSONResponse(status_code=200, content={
            "project_id": project_id,
            "messages": normalized,
        })
    except Exception as e:
        logger.error("Failed to get chats for project %s: %s", project_id, e, exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to retrieve chats", "detail": str(e)})


@router.patch("/projects/{project_id}/chats/{assistant_msg_id}")
async def set_chat_forget(project_id: str, assistant_msg_id: int, payload: dict) -> JSONResponse:
    """Set the forget and/or keep flags for an assistant message (pair-level control)."""
    try:
        forget_val_present = "forget" in (payload or {})
        keep_val_present = "keep" in (payload or {})
        if not forget_val_present and not keep_val_present:
            return JSONResponse(status_code=400, content={"error": "No updatable fields in payload"})
        forget_val = bool((payload or {}).get("forget", False)) if forget_val_present else None
        keep_val = bool((payload or {}).get("keep", False)) if keep_val_present else None
        with get_session() as session:
            row = session.get(ChatMessage, assistant_msg_id)
            if not row or row.project_id != project_id or row.role != "assistant":
                return JSONResponse(status_code=404, content={"error": "Assistant message not found"})
            if forget_val_present:
                row.forget = bool(forget_val)  # type: ignore[attr-defined]
            if keep_val_present:
                setattr(row, "keep", bool(keep_val))
            session.add(row)
            session.commit()
        # Also update in-memory deque if present
        try:
            mm = get_memory_manager()
            dq = mm.project_deques.get(project_id)
            if dq:
                for m in dq:
                    if m.get("id") == assistant_msg_id and m.get("role") == "assistant":
                        if forget_val_present:
                            m["forget"] = bool(forget_val)
                        if keep_val_present:
                            m["keep"] = bool(keep_val)
                        break
        except Exception:
            pass
        return JSONResponse(
            status_code=200,
            content={
                "project_id": project_id,
                "assistant_msg_id": assistant_msg_id,
                **({"forget": bool(forget_val)} if forget_val_present else {}),
                **({"keep": bool(keep_val)} if keep_val_present else {}),
            }
        )
    except Exception as e:
        logger.error("Failed to update forget flag project_id=%s assistant_msg_id=%s: %s", project_id, str(assistant_msg_id), e, exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/projects/{project_id}/personality")
async def get_project_personality(project_id: str) -> JSONResponse:
    """Return the project's personality JSON and current system prompt."""
    try:
        p = load_project_personality(project_id)
        sp = load_project_system_prompt(project_id)
        try:
            logger.debug(
                "[PROJECT] personality_get project_id=%s sp_bytes=%s tone=%s verbosity=%s format=%s",
                project_id,
                len((sp or "").encode("utf-8")),
                p.get("tone"),
                p.get("verbosity"),
                p.get("format"),
            )
        except Exception:
            pass
        return JSONResponse(status_code=200, content={
            "project_id": project_id,
            "personality": p,
            "system_prompt": sp,
            "system_prompt_bytes": len((sp or "").encode("utf-8")),
        })
    except Exception as e:
        logger.error(f"Failed to load personality for project {project_id}: {e}")
        return JSONResponse(status_code=500, content={"error": "Failed to load personality"})


@router.patch("/projects/{project_id}/personality")
async def patch_project_personality(project_id: str, payload: dict) -> JSONResponse:
    """Update the project's personality JSON. Normalizes and persists immediately."""
    try:
        current = load_project_personality(project_id)
        current.update(payload or {})
        saved = save_project_personality(project_id, current)
        return JSONResponse(status_code=200, content={
            "project_id": project_id,
            "personality": saved,
        })
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"error": str(ve)})
    except Exception as e:
        logger.error(f"Failed to save personality for project {project_id}: {e}")
        return JSONResponse(status_code=500, content={"error": "Failed to save personality"})


@router.put("/projects/{project_id}/system_prompt")
async def put_project_system_prompt(project_id: str, payload: dict) -> JSONResponse:
    """Replace the project's system prompt text with provided content."""
    try:
        content = str((payload or {}).get("content", ""))
        save_project_system_prompt(project_id, content)
        return JSONResponse(status_code=200, content={
            "project_id": project_id,
            "content": content,
            "bytes": len(content.encode("utf-8")),
        })
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"error": str(ve)})
    except Exception as e:
        logger.error(f"Failed to save system prompt for project {project_id}: {e}")
        return JSONResponse(status_code=500, content={"error": "Failed to save system prompt"})
