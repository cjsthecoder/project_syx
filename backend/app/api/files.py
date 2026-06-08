"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
File upload endpoints: upload files to a project and store to disk.
"""
import os
import time
from typing import List
import logging

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

from ..core.config import get_settings
from ..rag.manager import rebuild_faiss_index, _read_file_text
from ..core.database import get_session
from ..core.db_models import File as FileRow
from ..utils.tokens import count_tokens


router = APIRouter()
logger = logging.getLogger(__name__)


def _bytes_to_mb(n: int) -> float:
    return n / (1024 * 1024)


def _compute_file_stats(path: str) -> tuple[int, int]:
    """Return ``(page_count, token_count)`` for the file at ``path``.

    Reads the file via the RAG text extractor, tracking the maximum page
    number seen and accumulating token counts across extracted segments.

    Args:
        path: Absolute path to the uploaded file to inspect.

    Returns:
        Tuple of ``(page_count, token_count)``; ``page_count`` is at least 1,
        and both default toward 1/0 when extraction fails.
    """
    page_count = 1
    total_tokens = 0
    try:
        for raw_text, meta in _read_file_text(path):
            if meta.get("page_number"):
                page_count = max(page_count, int(meta["page_number"]))
            total_tokens += int(count_tokens(raw_text or ""))
    except Exception as exc:
        logger.warning("files.compute_file_stats failed path=%s detail=%s", path, exc)
    return (page_count, total_tokens)


@router.post("/projects/{project_id}/files")
async def upload_files(project_id: str, files: List[UploadFile] = File(...)) -> JSONResponse:
    """Upload one or more files to a project and index them for RAG.

    Accepts only ``.txt`` and ``.md`` files (PDFs are unsupported in the
    current RAG path). Enforces per-file, per-batch, and per-project storage
    limits, rolling back any writes that would breach a limit. Persists a
    ``File`` row per saved file with computed page/token stats, then rebuilds
    the project's FAISS index.

    Args:
        project_id: Target project identifier.
        files: Multipart upload payload of one or more files.

    Returns:
        JSON describing each uploaded file, the rebuilt index directory,
        the index rebuild status, total file count, and total token count.

    Raises:
        HTTPException: 400 if a file type is unsupported or any size limit
            (per-file, batch, or storage) would be exceeded.
    """
    settings = get_settings()

    # PDFs are intentionally unsupported in the current RAG path.
    allowed_ext = {".txt", ".md"}
    upload_root = os.path.join(get_settings().memory_root, project_id, "uploads")
    os.makedirs(upload_root, exist_ok=True)

    saved = []
    total_written = 0
    for f in files:
        name = os.path.basename(f.filename or "")
        _, ext = os.path.splitext(name)
        if ext.lower() not in allowed_ext:
            raise HTTPException(status_code=400, detail={"error": f"Unsupported file type: {ext}"})

        target = os.path.join(upload_root, name)
        size = 0
        with open(target, "wb") as out:
            while True:
                chunk = await f.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                out.write(chunk)

        # Per-file limit
        if _bytes_to_mb(size) > settings.max_upload_mb:
            os.remove(target)
            raise HTTPException(status_code=400, detail={"error": f"File {name} exceeds max size {settings.max_upload_mb}MB"})

        total_written += size
        saved.append({"filename": name, "size_bytes": size, "content_type": f.content_type, "path": target})

    # Batch limit
    if _bytes_to_mb(total_written) > settings.max_batch_mb:
        # Roll back writes
        for s in saved:
            try:
                os.remove(s["path"])  # type: ignore
            except Exception as exc:
                logger.warning(
                    "files.upload rollback delete failed project_id=%s file=%s detail=%s",
                    project_id,
                    s.get("path"),
                    exc,
                )
        raise HTTPException(status_code=400, detail={"error": f"Batch exceeds max size {settings.max_batch_mb}MB"})

    # Storage limit per project (existing + new)
    existing_total = 0
    for root, _, filenames in os.walk(upload_root):
        for n in filenames:
            try:
                existing_total += os.path.getsize(os.path.join(root, n))
            except Exception as exc:
                logger.warning(
                    "files.upload size calc failed project_id=%s file=%s detail=%s",
                    project_id,
                    os.path.join(root, n),
                    exc,
                )
    if _bytes_to_mb(existing_total) > settings.storage_limit_mb:
        raise HTTPException(status_code=400, detail={"error": f"Project storage already exceeds limit {settings.storage_limit_mb}MB"})
    if _bytes_to_mb(existing_total + total_written) > settings.storage_limit_mb:
        # Roll back this batch
        for s in saved:
            try:
                os.remove(s["path"])  # type: ignore
            except Exception as exc:
                logger.warning(
                    "files.upload storage rollback delete failed project_id=%s file=%s detail=%s",
                    project_id,
                    s.get("path"),
                    exc,
                )
        raise HTTPException(status_code=400, detail={"error": f"Storage limit {settings.storage_limit_mb}MB would be exceeded"})

    # Record files in DB with stats
    uploaded = []
    total_tokens = 0
    with get_session() as session:
        for s in saved:
            page_count, token_count = _compute_file_stats(s["path"])  # type: ignore
            row = FileRow(
                project_id=project_id,
                filename=s["filename"],  # type: ignore
                size_bytes=s["size_bytes"],  # type: ignore
                content_type=s.get("content_type"),
                embedding_status="indexed",
                page_count=page_count,
                token_count=token_count,
            )
            session.add(row)
            uploaded.append({
                "filename": s["filename"],  # type: ignore
                "status": "ok",
                "size_bytes": s["size_bytes"],  # type: ignore
                "token_count": token_count,
            })
            total_tokens += token_count
        session.commit()

    # Rebuild FAISS index per upload policy
    try:
        index_dir = rebuild_faiss_index(project_id)
        rebuild_status = "completed"
    except Exception as e:
        index_dir = None
        rebuild_status = "failed"

    return JSONResponse(status_code=200, content={
        "project_id": project_id,
        "uploaded": uploaded,
        "index_dir": index_dir,
        "rebuild_status": rebuild_status,
        "total_files": len(uploaded),
        "total_tokens": total_tokens,
    })


@router.get("/projects/{project_id}/files")
async def list_files(project_id: str) -> JSONResponse:
    """List uploaded files for a project (DB view).

    Args:
        project_id: Project whose file rows to list.

    Returns:
        JSON with the project's files (id, filename, size, upload time,
        embedding status, page/token counts) plus aggregate ``storage_bytes``
        and ``token_count`` totals.
    """
    from sqlmodel import select
    with get_session() as session:
        rows = session.exec(select(FileRow).where(FileRow.project_id == project_id)).all()
        files = [
            {
                "id": r.id,
                "filename": r.filename,
                "size_bytes": r.size_bytes,
                "uploaded_at": r.created_at.isoformat() if r.created_at else None,
                "embedding_status": r.embedding_status,
                "page_count": r.page_count,
                "token_count": r.token_count,
            }
            for r in rows
        ]
        storage_bytes = sum(r.size_bytes for r in rows)
        token_count = sum(r.token_count for r in rows)
    return JSONResponse(status_code=200, content={
        "project_id": project_id,
        "files": files,
        "storage_bytes": storage_bytes,
        "token_count": token_count,
    })


@router.delete("/projects/{project_id}/files/{file_id}")
async def delete_file(project_id: str, file_id: int) -> JSONResponse:
    """Delete a file from the DB and disk, then rebuild the FAISS index.

    Args:
        project_id: Project that owns the file.
        file_id: Identifier of the ``File`` row to delete.

    Returns:
        JSON with the project id, index rebuild status, and rebuilt index
        directory (``None`` when the rebuild fails).

    Raises:
        HTTPException: 404 if the file does not exist or does not belong to the
            given project.
    """
    upload_root = os.path.join(get_settings().memory_root, project_id, "uploads")
    from sqlmodel import select
    with get_session() as session:
        row = session.get(FileRow, file_id)
        if not row or row.project_id != project_id:
            raise HTTPException(status_code=404, detail={"error": "File not found"})
        # Delete disk file
        try:
            path = os.path.join(upload_root, row.filename)
            if os.path.exists(path):
                os.remove(path)
        except Exception as exc:
            logger.warning(
                "files.delete failed removing disk file project_id=%s file_id=%s path=%s detail=%s",
                project_id,
                file_id,
                path,
                exc,
            )
        session.delete(row)
        session.commit()

    try:
        index_dir = rebuild_faiss_index(project_id)
        rebuild_status = "completed"
    except Exception:
        index_dir = None
        rebuild_status = "failed"

    return JSONResponse(status_code=200, content={
        "project_id": project_id,
        "rebuild_status": rebuild_status,
        "index_dir": index_dir,
    })


