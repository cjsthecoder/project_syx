"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Projects API endpoint for Syx AGI Chatbot Framework.

This module provides project management functionality (stubbed).
"""

import logging
import json
import os
import time
from typing import Optional, List, Any, Dict
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
from ..core.memory import get_memory_manager, get_last_context_tokens, _prune_assistant_for_tagger
from ..tagging.tagger import tag_pair
from ..rag.daily_store import append_pair, daily_stats, rebuild_daily_cache, start_daily_cache_rebuild
from ..core.config import get_settings
from filelock import FileLock
from ..core.personality import (
    load_project_system_prompt,
    load_project_personality,
    save_project_system_prompt,
    save_project_personality,
    seed_project_defaults,
)
from ..core.database import get_session
from ..core.db_models import ChatMessage
from ..rag.manager import rebuild_faiss_index
from ..utils.debug_utils import write_debug_file
from ..utils.dream_summary import write_latest_sleep_summary
from ..utils.tokens import count_tokens
import shutil

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize logger
request_logger = RequestLogger("projects")

# Current project state (simple in-memory pointer)
_current_project = None


def _validate_dream_payload(data: Any) -> Optional[dict]:
    """Light validation of dream.json structure."""
    if not isinstance(data, dict):
        return None
    summary = data.get("project_summary")
    items = data.get("items")
    if summary is not None and not isinstance(summary, str):
        return None
    if items is not None and not isinstance(items, list):
        return None
    return {
        "project_summary": summary,
        "items": items or [],
    }


def _read_latest_sleep_summary(project_id: str) -> Optional[dict]:
    summary_path = os.path.join(get_settings().memory_root, project_id, "latest_sleep_summary.txt")
    try:
        if not os.path.isfile(summary_path):
            return None
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = f.read().strip()
        if not summary:
            return None
        return {"project_summary": summary, "items": []}
    except OSError as exc:
        logger.warning(
            "[PROJECT][DREAM] Failed reading latest dream summary project=%s path=%s detail=%s",
            project_id,
            summary_path,
            exc,
            exc_info=True,
        )
        return None


def _read_pending_dream_project_summary(project_id: str, dream_path: str) -> Optional[str]:
    try:
        if not os.path.isfile(dream_path):
            return None
        with open(dream_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "[PROJECT][DREAM] Failed reading pending dream summary project=%s path=%s detail=%s",
            project_id,
            dream_path,
            exc,
            exc_info=True,
        )
        return None
    if not isinstance(data, dict):
        return None
    summary = data.get("project_summary")
    return summary if isinstance(summary, str) and summary.strip() else None


def _normalize_resolution(value: Any) -> str:
    res = str(value or "").strip().lower()
    if res in {"ignore", "answer_local", "answer_remote"}:
        return res
    return ""


def _valid_research_entries(item: Dict[str, Any]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    research_list = item.get("research") if isinstance(item.get("research"), list) else []
    for r in research_list:
        if not isinstance(r, dict):
            continue
        topic = str(r.get("research_topic") or "").strip()
        summary = str(r.get("research_summary") or "").strip()
        if not topic or not summary:
            continue
        out.append({"research_topic": topic, "research_summary": summary})
    return out


def _dream_memory_pairs_for_item(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    resolution = _normalize_resolution(item.get("source_resolution"))
    if resolution == "answer_remote":
        pairs = []
        for r in _valid_research_entries(item):
            pairs.append(
                {
                    "item": item,
                    "user_text": r["research_topic"],
                    "assistant_text": f"[RESEARCH]\n{r['research_summary']}".strip(),
                }
            )
        return pairs

    return [
        {
            "item": item,
            "user_text": str(item.get("origin_text") or "").strip(),
            "assistant_text": (str(item.get("assistant_response") or "").strip() or "(no summary)").strip(),
        }
    ]


def _filter_remote_without_research(items: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
    kept: List[Dict[str, Any]] = []
    dropped = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        resolution = _normalize_resolution(it.get("source_resolution"))
        if resolution == "answer_remote" and not _valid_research_entries(it):
            dropped += 1
            continue
        kept.append(it)
    return kept, dropped


def _filter_remote_without_research_with_rows(
    items: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    kept: List[Dict[str, Any]] = []
    dropped_rows: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        resolution = _normalize_resolution(it.get("source_resolution"))
        if resolution != "answer_remote":
            kept.append(it)
            continue
        valid_research = _valid_research_entries(it)
        if valid_research:
            kept.append(it)
            continue
        dropped_rows.append(
            {
                "id": str(it.get("id") or ""),
                "origin_text": str(it.get("origin_text") or "").strip(),
                "source_resolution": resolution,
                "research_count": 0,
                "reason": "remote_without_research",
            }
        )
    return kept, dropped_rows


def _write_persist_filter_report(
    project_id: str,
    total_remembered: int,
    kept_after_filter: int,
    dropped_rows: List[Dict[str, Any]],
) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    body = (
        f"# timestamp: {ts}\n"
        f"# project_id: {project_id}\n"
        "\n"
        "====== INPUT ======\n"
        f"{json.dumps({'remembered_items': total_remembered}, ensure_ascii=False, indent=2)}\n\n"
        "====== DECISIONS ======\n"
        f"{json.dumps(dropped_rows, ensure_ascii=False, indent=2)}\n\n"
        "====== OUTPUT ======\n"
        f"{json.dumps({'kept_after_filter': kept_after_filter, 'dropped_count': len(dropped_rows)}, ensure_ascii=False, indent=2)}\n"
    )
    write_debug_file(project_id, "dreaming/persist_filter_report.txt", body)


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


@router.get("/projects/{project_id}/dream")
async def get_project_dream(project_id: str) -> JSONResponse:
    """Return dream.json content for a project, if present and well-formed."""
    request_logger.log_request(endpoint="/projects/{project_id}/dream", method="GET", user_id=project_id)
    dream_path = os.path.join(get_settings().memory_root, project_id, "dream.json")
    try:
        if not os.path.isfile(dream_path):
            return JSONResponse(status_code=200, content={"project_id": project_id, "dream": _read_latest_sleep_summary(project_id)})
        with open(dream_path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        if not raw:
            return JSONResponse(status_code=200, content={"project_id": project_id, "dream": _read_latest_sleep_summary(project_id)})
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return JSONResponse(status_code=200, content={"project_id": project_id, "dream": _read_latest_sleep_summary(project_id)})
        validated = _validate_dream_payload(data)
        if not validated:
            return JSONResponse(status_code=200, content={"project_id": project_id, "dream": _read_latest_sleep_summary(project_id)})
        filtered_items, dropped = _filter_remote_without_research(validated.get("items", []))
        validated["items"] = filtered_items
        if dropped:
            logger.info(
                "[PROJECT][DREAM] Filtered remote items without research project=%s dropped=%s",
                project_id,
                dropped,
            )
        return JSONResponse(status_code=200, content={"project_id": project_id, "dream": validated})
    except Exception as e:
        logger.warning("[PROJECT][DREAM] Failed reading dream for %s: %s", project_id, e, exc_info=True)
        return JSONResponse(status_code=500, content={"project_id": project_id, "error": "Failed to read dream.json"})


@router.post("/projects/{project_id}/dream/keep")
async def keep_dream_items(project_id: str, payload: Dict[str, Any]) -> JSONResponse:
    """
    Persist kept dream items by tagging and appending to daily RAG, appending to dream_summary.md,
    and deleting dream.json on full success.
    """
    try:
        items = payload.get("items", [])
        if not isinstance(items, list):
            return JSONResponse(status_code=400, content={"error": "items must be a list"})

        entries: List[Dict[str, Any]] = [it for it in items if isinstance(it, dict)]
        # Only tag and persist items where the user checked Remember
        to_process: List[Dict[str, Any]] = [it for it in entries if it.get("remember")]
        if not to_process:
            return JSONResponse(status_code=200, content={"project_id": project_id, "processed": 0, "kept": 0, "deleted_dream": False})

        total_remembered = len(to_process)
        to_process, dropped_rows = _filter_remote_without_research_with_rows(to_process)
        dropped_remote_no_research = len(dropped_rows)
        if dropped_remote_no_research:
            logger.info(
                "[PROJECT][DREAM][KEEP] Filtered remote items without research project=%s dropped=%s",
                project_id,
                dropped_remote_no_research,
            )
            try:
                _write_persist_filter_report(
                    project_id=project_id,
                    total_remembered=total_remembered,
                    kept_after_filter=len(to_process),
                    dropped_rows=dropped_rows,
                )
            except Exception as exc:
                logger.warning(
                    "[PROJECT][DREAM][KEEP] Failed writing persist_filter_report project=%s: %s",
                    project_id,
                    exc,
                    exc_info=exc,
                )
        if not to_process:
            return JSONResponse(
                status_code=200,
                content={
                    "project_id": project_id,
                    "processed": 0,
                    "kept": 0,
                    "deleted_dream": False,
                    "filtered_remote_without_research": dropped_remote_no_research,
                },
            )

        successes = 0
        failures = []

        # Prepare dream_summary.md append
        base_dir = os.path.join(get_settings().memory_root, project_id)
        os.makedirs(base_dir, exist_ok=True)
        summary_path = os.path.join(base_dir, "dream_summary.md")
        state_dir = os.path.join(base_dir, "state")
        os.makedirs(state_dir, exist_ok=True)
        summary_lock_path = os.path.join(state_dir, "dream_summary.lock")
        legacy_summary_lock_path = os.path.join(base_dir, "dream_summary.lock")
        if os.path.isfile(legacy_summary_lock_path) and not os.path.exists(summary_lock_path):
            try:
                os.replace(legacy_summary_lock_path, summary_lock_path)
            except OSError as exc:
                logger.warning("projects dream_summary lock migration failed project_id=%s detail=%s", project_id, exc)

        # Pass 1: expand remote research into per-topic pairs, then tag each pair independently.
        tagged: List[Dict[str, Any]] = []
        previous_pair_text: Optional[str] = None
        for it in to_process:
            for pair in _dream_memory_pairs_for_item(it):
                user_text = str(pair.get("user_text") or "").strip()
                assistant_resp_full = str(pair.get("assistant_text") or "").strip()
                if not user_text or not assistant_resp_full:
                    logger.warning(
                        "[PROJECT][DREAM][KEEP] Skipping empty memory pair project=%s item_id=%s",
                        project_id,
                        str(it.get("id") or ""),
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
                        "[PROJECT][DREAM][KEEP] Tagger failed; persisting without tags project=%s item_id=%s detail=%s",
                        project_id,
                        str(it.get("id") or ""),
                        exc,
                    )
                    tags_meta = None

                tags_block = ""
                try:
                    if isinstance(tags_meta, dict):
                        topics = str(tags_meta.get("topics", "") or "")
                        intent = str(tags_meta.get("intent", "") or "")
                        tag_type = str(tags_meta.get("type", "") or "")
                        semantic_handle = tags_meta.get("semantic_handle", None)
                        lines = [f"#topics: {topics}", f"#intent: {intent}", f"#type: {tag_type}"]
                        if semantic_handle is not None:
                            lines.append(f"#semantic_handle: {str(semantic_handle) if semantic_handle is not None else ''}")
                        tags_block = "\n".join(lines) + "\n"
                except Exception as exc:
                    logger.warning(
                        "[PROJECT][DREAM][KEEP] Failed formatting tags block project=%s item_id=%s detail=%s",
                        project_id,
                        str(it.get("id") or ""),
                        exc,
                    )
                    tags_block = ""

                embed_text = (tags_block + pair_text) if tags_block else pair_text
                tagged.append({
                    "it": it,
                    "user_text": user_text,
                    "assistant_resp_full": assistant_text_for_memory,
                    "pair_text": pair_text,
                    "tokens": tokens,
                    "tags_meta": tags_meta,
                    "tags_block": tags_block,
                    "embed_text": embed_text,
                })
                previous_pair_text = pair_text

        # Pass 2: append each to daily.json only (no cache update), write dream_summary blocks
        _BEGIN_DREAM_PAIR = "=== BEGIN DREAM PAIR ==="
        _END_DREAM_PAIR = "=== END DREAM PAIR ==="
        for rec in tagged:
            it = rec["it"]
            user_text = rec["user_text"]
            assistant_resp_full = rec["assistant_resp_full"]
            pair_text = rec["pair_text"]
            tokens = rec["tokens"]
            tags_meta = rec["tags_meta"]
            tags_block = rec["tags_block"]
            embed_text = rec["embed_text"]
            try:
                append_pair(
                    project_id,
                    pair_text,
                    -1,
                    -2,
                    int(tokens),
                    namespace="other",
                    keep=True,
                    embed_override=embed_text,
                    tags_meta=tags_meta,
                    write_daily_md=False,
                    update_cache=False,
                )
                ts_local = time.strftime("%m-%d-%Y_%H:%M:%S", time.localtime())
                keep_flag = bool(it.get("keep"))
                block = (
                    f"{_BEGIN_DREAM_PAIR}\n"
                    f"#timestamp: {ts_local}\n"
                    f"#route: other\n"
                    f"#keep: {str(keep_flag).lower()}\n"
                    f"{tags_block}"
                    f"\n"
                    f"--- USER (data-message-author-role: user) ---\n"
                    f"{user_text}\n"
                    f"\n"
                    f"*** ASSISTANT (data-message-author-role: assistant) ***\n"
                    f"{assistant_resp_full}\n"
                    f"\n"
                    f"{_END_DREAM_PAIR}\n"
                    f"\n"
                )
                with FileLock(summary_lock_path):
                    with open(summary_path, "a", encoding="utf-8", newline="\n") as sf:
                        need_begin = (not os.path.isfile(summary_path)) or os.path.getsize(summary_path) == 0
                        if need_begin:
                            begin_date = time.strftime("%m/%d/%Y", time.localtime())
                            sf.write(f"=== BEGIN DREAM MEMORY: {begin_date} ===\n\n")
                        sf.write(block)
                successes += 1
            except Exception as e:
                failures.append(str(e))

        # Rebuild in-memory daily RAG once after all pairs are in daily.json
        if successes > 0:
            try:
                rebuild_daily_cache(project_id, reason="dream_batch")
            except Exception as rb:
                logger.warning("[PROJECT][DREAM][KEEP] Rebuild daily cache failed project=%s: %s", project_id, rb)
                failures.append(f"rebuild_cache: {rb}")

        deleted = False
        dream_path = os.path.join(get_settings().memory_root, project_id, "dream.json")
        pending_project_summary = _read_pending_dream_project_summary(project_id, dream_path)
        if successes == len(tagged) and not failures:
            try:
                # Append END footer on successful completion before deleting dream.json
                with FileLock(summary_lock_path):
                    try:
                        if os.path.isfile(summary_path):
                            end_date = time.strftime("%m/%d/%Y", time.localtime())
                            with open(summary_path, "a", encoding="utf-8", newline="\n") as sf:
                                sf.write(f"=== END DREAM MEMORY: {end_date} ===\n")
                    except Exception as fe:
                        failures.append(f"write_end_footer: {fe}")
                if not failures:
                    write_latest_sleep_summary(
                        project_id=project_id,
                        base_dir=base_dir,
                        project_summary=pending_project_summary,
                        accepted_items=[rec["it"] for rec in tagged],
                    )
                if os.path.isfile(dream_path):
                    os.remove(dream_path)
                deleted = True
            except Exception as e:
                failures.append(f"delete_dream_json: {e}")

        status = 200 if not failures else 500
        return JSONResponse(
            status_code=status,
            content={
                "project_id": project_id,
                "processed": len(tagged),
                "kept": successes,
                "failed": len(failures),
                "deleted_dream": deleted,
                "filtered_remote_without_research": dropped_remote_no_research,
                "errors": failures if failures else None,
            },
        )
    except Exception as e:
        logger.error("[PROJECT][DREAM][KEEP] Failed for %s: %s", project_id, e, exc_info=True)
        return JSONResponse(status_code=500, content={"project_id": project_id, "error": "Failed to persist kept dream items"})


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
                # Seed default prompt/personality files
                try:
                    seed_project_defaults(obj.id)
                except Exception as e:
                    logger.warning("[PROJECT] Failed to seed defaults for project %s: %s", obj.id, e, exc_info=True)
                _current_project = obj.id
                message = f"Created and switched to new project '{obj.name}'"
                # Seed DEFAULT_RAG.txt and rebuild RAG
                try:
                    uploads_dir = os.path.join(get_settings().memory_root, obj.id, "uploads")
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
        base = os.path.join(get_settings().memory_root, project_id)
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
        # Clear ephemeral per-project memory state.
        try:
            mm = get_memory_manager()
            try:
                mm.project_deques.pop(project_id, None)
            except Exception as exc:
                logger.info("[PROJECT] Failed clearing project deque project_id=%s: %s", project_id, exc)
            try:
                mm.last_context_tokens_per_project.pop(project_id, None)
            except Exception as exc:
                logger.info(
                    "[PROJECT] Failed clearing last_rolled_off_pair project_id=%s: %s",
                    project_id,
                    exc,
                )
        except Exception as exc:
            logger.info("[PROJECT] Memory manager cleanup failed project_id=%s: %s", project_id, exc)
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
    # Lazily warm Daily in-memory cache on first project-scoped request.
    try:
        start_daily_cache_rebuild(project_id, reason="project_stats")
    except Exception as exc:
        logger.info("[PROJECT] Daily cache warm request failed project_id=%s op=project_stats detail=%s", project_id, exc)
    # storage and tokens from DB
    with get_session() as session:
        rows = session.exec(select(File).where(File.project_id == project_id)).all()
        storage_bytes = sum(r.size_bytes for r in rows)
        tokens_indexed = sum(r.token_count for r in rows)
        file_count = len(rows)
    # index size
    base = os.path.join(get_settings().memory_root, project_id, "faiss")
    index_size = 0
    if os.path.isdir(base):
        for root, _, files in os.walk(base):
            for n in files:
                try:
                    index_size += os.path.getsize(os.path.join(root, n))
                except Exception as exc:
                    logger.info(
                        "[PROJECT] Failed reading file size project_id=%s file=%s detail=%s",
                        project_id,
                        os.path.join(root, n),
                        exc,
                    )
    # context tokens from memory manager
    context_tokens = get_last_context_tokens(project_id)
    # If missing/zero, recompute from stored working memory for this project (excludes any RAG system prompts)
    if not context_tokens:
        try:
            mm = get_memory_manager()
            history = mm.get_project_history(project_id) or []
            combined_text = "\n".join((m.get("content") or "") for m in history)
            if combined_text.strip():
                context_tokens = int(count_tokens(combined_text))
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
        except Exception as exc:
            logger.warning(
                "[PROJECT] Failed updating in-memory chat flags project_id=%s assistant_msg_id=%s detail=%s",
                project_id,
                str(assistant_msg_id),
                exc,
            )
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
        except Exception as exc:
            logger.info("[PROJECT] personality_get debug log failed project_id=%s detail=%s", project_id, exc)
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
