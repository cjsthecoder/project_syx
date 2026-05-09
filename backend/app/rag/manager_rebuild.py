"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import faiss  # type: ignore
import numpy as np  # type: ignore
from sqlmodel import select

from ..core.config import get_settings, get_active_embedding_model
from ..core.database import get_session
from ..core.db_models import File as FileRow
from ..embedding.batching import iter_token_batches
from ..embedding.factory import get_embedding_client
from ..utils.tokens import count_tokens as _count_tokens, trim_to_tokens as _trim_to_tokens
from ..utils.debug_utils import write_debug_file
from .chunk_utils import split_text_simple
from .syx_memory_artifact import parse_syx_entries
from .manager_index_io import (
    LTM_DOCSTORE_NAME,
    LTM_INDEX_FILE_NAME,
    LTM_INDEX_TO_ID_NAME,
    atomic_write_json,
    clear_dir_contents,
    normalize_rows,
    uploads_relative_doc_id,
    write_ltm_manifest_and_adjacency,
)

logger = logging.getLogger(__name__)

def is_rate_limit_error_message(err: Exception) -> bool:
    msg = str(err or "").lower()
    return ("rate limit" in msg) or ("too many requests" in msg) or ("429" in msg) or ("rate_limit_exceeded" in msg)


def read_file_text(path: str, *, artifact_path: str | None = None) -> List[Tuple[str, dict]]:
    """Return list of (text, metadata) chunks at file-level (before splitting)."""
    name = os.path.basename(path)
    _, ext = os.path.splitext(name)
    ext = ext.lower()
    if ext in {".txt", ".md"}:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        parsed = parse_syx_entries(content, artifact_path=artifact_path)
        for warning in parsed.warnings:
            logger.warning("RAG: Syx boundary parse warning path=%s detail=%s", path, warning)
        if parsed.structural_warnings:
            logger.warning(
                "RAG: malformed Syx boundary markers; falling back to whole-file indexing path=%s warnings=%s",
                path,
                parsed.structural_warnings,
            )
            return [(content, {"filename": name})]
        if parsed.entries:
            out: List[Tuple[str, dict]] = []
            for entry in parsed.entries:
                md = dict(entry.metadata)
                md.update(
                    {
                        "filename": name,
                        "memory_id": entry.memory_id,
                        "entry_start_line": entry.start_line,
                        "entry_end_line": entry.end_line,
                        "doc_id": f"{artifact_path or name}::memory_id={entry.memory_id}",
                        "source_document_id": f"{artifact_path or name}::memory_id={entry.memory_id}",
                    }
                )
                out.append((entry.text, md))
            return out
        return [(content, {"filename": name})]
    return []


def count_tokens(text: str) -> int:
    return int(_count_tokens(text))


def trim_to_tokens(text: str, max_tokens: int) -> str:
    return _trim_to_tokens(text, max_tokens)


def ltm_docstore_item_id(metadata: dict) -> str:
    did = str((metadata or {}).get("doc_id") or "")
    seq = int((metadata or {}).get("chunk_seq") or 0)
    return f"{did}::chunk={seq}"


def rebuild_faiss_index(project_id: str) -> str:
    """Rebuild FAISS index for a project from uploads directory."""
    settings = get_settings()
    active_embedding_model = get_active_embedding_model()
    memory_root = settings.memory_root
    uploads_dir = os.path.join(memory_root, project_id, "uploads")
    faiss_dir = os.path.join(memory_root, project_id, "faiss")
    os.makedirs(faiss_dir, exist_ok=True)

    # No legacy support: rebuild from scratch.
    clear_dir_contents(faiss_dir)

    files: List[str] = []
    if os.path.isdir(uploads_dir):
        for root, _, names in os.walk(uploads_dir):
            for name in names:
                files.append(os.path.join(root, name))

    texts: List[str] = []
    metadatas: List[dict] = []
    file_token_sums: Dict[str, int] = {}
    file_page_max: Dict[str, int] = {}

    now_iso = datetime.now(timezone.utc).isoformat()
    for file_path in files:
        doc_id = uploads_relative_doc_id(uploads_dir, file_path)
        for raw_text, meta in read_file_text(file_path, artifact_path=doc_id):
            fname = meta.get("filename") or os.path.basename(file_path)
            file_token_sums[fname] = file_token_sums.get(fname, 0) + count_tokens(raw_text)
            file_page_max[fname] = 1
            region_doc_id = str(meta.get("doc_id") or doc_id)
            source_document_id = str(meta.get("source_document_id") or region_doc_id)
            for i, chunk in enumerate(
                split_text_simple(
                    raw_text,
                    chunk_size=int(settings.chunk_size),
                    chunk_overlap=int(settings.chunk_overlap),
                )
            ):
                texts.append(chunk)
                metadatas.append(
                    {
                        "project_id": project_id,
                        "filename": fname,
                        "page_number": None,
                        "doc_id": region_doc_id,
                        "source_document_id": source_document_id,
                        "chunk_seq": int(i),
                        "chunk_index": int(i),
                        "chunk_id": int(i),
                        "timestamp": now_iso,
                        **{
                            key: value
                            for key, value in dict(meta or {}).items()
                            if key not in {"filename", "doc_id", "source_document_id"}
                        },
                    }
                )

    if not texts:
        return faiss_dir

    max_req_tokens = int(getattr(settings, "max_embed_tokens_per_request", 250_000))
    worker_count_raw = int(getattr(settings, "rag_embed_rebuild_workers", 1) or 1)
    worker_count = max(1, min(8, worker_count_raw))
    llm = get_embedding_client()

    index: faiss.IndexFlatIP | None = None
    index_dim: int | None = None
    index_to_id: List[str] = []
    docstore: Dict[str, Dict[str, Any]] = {}
    prepared_batches: List[Tuple[List[str], List[dict], int]] = []
    for batch_texts, batch_metas, est_tokens in iter_token_batches(
        texts,
        metadatas=metadatas,
        max_tokens_per_batch=max_req_tokens,
        model_name=active_embedding_model,
    ):
        if batch_metas is None:
            raise RuntimeError("RAG rebuild batching produced missing metadata.")
        prepared_batches.append((list(batch_texts), list(batch_metas), int(est_tokens)))

    logger.info(
        "RAG: rebuild embedding start project=%s batches=%s workers=%s max_req_tokens=%s",
        project_id,
        int(len(prepared_batches)),
        int(worker_count),
        int(max_req_tokens),
    )
    embed_start_ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    embed_stage_t0 = time.monotonic()
    write_debug_file(
        project_id,
        f"rag/rebuild/{embed_start_ts}_embedding_start.txt",
        (
            f"# timestamp: {embed_start_ts}\n"
            f"# project_id: {project_id}\n"
            f"# stage: embedding_start\n"
            f"# embedding_model: {active_embedding_model}\n"
            f"# total_batches: {int(len(prepared_batches))}\n"
            f"# workers: {int(worker_count)}\n"
            f"# max_embed_tokens_per_request: {int(max_req_tokens)}\n"
        ),
    )

    def _embed_batch(
        batch_id: int,
        batch_texts: List[str],
        batch_metas: List[dict],
        est_tokens: int,
    ) -> Dict[str, Any]:
        t0 = time.monotonic()
        res = llm.embed(list(batch_texts), model=active_embedding_model)
        dt = time.monotonic() - t0
        return {
            "batch_id": int(batch_id),
            "texts": list(batch_texts),
            "metas": list(batch_metas),
            "est_tokens": int(est_tokens),
            "vectors": list(res.vectors),
            "elapsed_s": float(dt),
        }

    batch_results: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=int(worker_count)) as pool:
        future_to_batch: Dict[Any, int] = {}
        for batch_id, (batch_texts, batch_metas, est_tokens) in enumerate(prepared_batches, start=1):
            fut = pool.submit(_embed_batch, batch_id, batch_texts, batch_metas, est_tokens)
            future_to_batch[fut] = int(batch_id)
        for fut in as_completed(future_to_batch):
            batch_id = int(future_to_batch[fut])
            try:
                payload = fut.result()
            except Exception as exc:
                if is_rate_limit_error_message(exc):
                    logger.warning(
                        "RAG: parallel embed batch throttled project=%s batch=%s workers=%s err=%s",
                        project_id,
                        int(batch_id),
                        int(worker_count),
                        exc,
                    )
                else:
                    logger.error(
                        "RAG: parallel embed batch failed project=%s batch=%s workers=%s err=%s",
                        project_id,
                        int(batch_id),
                        int(worker_count),
                        exc,
                        exc_info=True,
                    )
                raise RuntimeError(
                    f"RAG rebuild failed during embedding batch={batch_id} workers={worker_count}: {exc}"
                ) from exc
            batch_results[int(batch_id)] = payload

    for batch_id in range(1, len(prepared_batches) + 1):
        payload = batch_results.get(int(batch_id))
        if not isinstance(payload, dict):
            raise RuntimeError(f"RAG rebuild missing embedding result for batch={batch_id}")
        batch_texts = payload.get("texts") if isinstance(payload.get("texts"), list) else []
        batch_metas = payload.get("metas") if isinstance(payload.get("metas"), list) else []
        est_tokens = int(payload.get("est_tokens") or 0)
        elapsed_s = float(payload.get("elapsed_s") or 0.0)
        vecs = payload.get("vectors") if isinstance(payload.get("vectors"), list) else []
        if not vecs:
            logger.warning("RAG: embed returned empty vectors project=%s batch=%s", project_id, int(batch_id))
            continue
        mat = normalize_rows(np.array(vecs, dtype="float32"))
        if index is None:
            index_dim = int(mat.shape[1])
            index = faiss.IndexFlatIP(int(index_dim))
        if mat.shape[1] != int(index_dim or 0):
            raise RuntimeError(f"Embedding dim changed mid-build: {mat.shape[1]} vs {index_dim}")

        for txt, md in zip(list(batch_texts), list(batch_metas)):
            item_id = ltm_docstore_item_id(md)
            index_to_id.append(item_id)
            docstore[item_id] = {"text": str(txt or ""), "metadata": dict(md or {})}
        index.add(mat)

        logger.debug(
            "RAG: embedded batch=%s/%s texts=%s est_tokens=%s elapsed_s=%.2f workers=%s max_req_tokens=%s",
            int(batch_id),
            int(len(prepared_batches)),
            int(len(batch_texts)),
            int(est_tokens),
            float(elapsed_s),
            int(worker_count),
            int(max_req_tokens),
        )

    embed_stage_elapsed_s = time.monotonic() - embed_stage_t0
    logger.info(
        "RAG: rebuild embedding complete project=%s batches=%s workers=%s total_embed_elapsed_s=%.2f",
        project_id,
        int(len(prepared_batches)),
        int(worker_count),
        float(embed_stage_elapsed_s),
    )

    if index is None or index_dim is None or int(index.ntotal) <= 0:
        return faiss_dir

    faiss.write_index(index, os.path.join(faiss_dir, LTM_INDEX_FILE_NAME))
    atomic_write_json(os.path.join(faiss_dir, LTM_INDEX_TO_ID_NAME), index_to_id)
    atomic_write_json(os.path.join(faiss_dir, LTM_DOCSTORE_NAME), docstore)

    try:
        ok = write_ltm_manifest_and_adjacency(
            project_id=project_id,
            faiss_dir=faiss_dir,
            index_dim=int(index_dim),
            chunk_size=int(settings.chunk_size),
            chunk_overlap=int(settings.chunk_overlap),
            docstore=docstore,
            index_to_id=index_to_id,
        )
        if not ok:
            logger.warning("RAG: failed to write adjacency index project=%s", project_id)
    except Exception as exc:
        logger.warning("RAG: exception writing adjacency index project=%s detail=%s", project_id, exc)

    try:
        with get_session() as session:
            for fname, tok_sum in file_token_sums.items():
                row = session.exec(
                    select(FileRow).where((FileRow.project_id == project_id) & (FileRow.filename == fname))
                ).first()
                if row:
                    row.token_count = int(tok_sum)
                    row.page_count = int(file_page_max.get(fname, row.page_count or 1))
                    row.embedding_status = "indexed"
                    session.add(row)
            session.commit()
    except Exception as exc:
        logger.warning(
            "RAG: failed backfilling file stats; operation=rebuild_faiss_index project_id=%s detail=%s",
            project_id,
            exc,
            exc_info=True,
        )
    return faiss_dir
