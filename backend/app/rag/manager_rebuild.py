"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Long-term memory FAISS index rebuild pipeline.

This module rebuilds a project's FAISS index from uploaded files, parsing Syx
entries, chunking, embedding in parallel batches, and persisting the index and metadata.
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
    """Return True when an exception message looks like a provider rate-limit error.

    Args:
        err: Exception whose stringified message is inspected.

    Returns:
        True when the message matches common rate-limit signatures (e.g.
        ``rate limit``, ``too many requests``, ``429``).
    """
    msg = str(err or "").lower()
    return ("rate limit" in msg) or ("too many requests" in msg) or ("429" in msg) or ("rate_limit_exceeded" in msg)


def read_file_text(path: str, *, artifact_path: str | None = None) -> List[Tuple[str, dict]]:
    """Read a supported file into file-level ``(text, metadata)`` regions.

    For ``.txt``/``.md`` files, parses bounded Syx entries: each well-formed entry
    becomes its own region carrying adjacency identity (``doc_id``/
    ``source_document_id``) keyed by memory id. Malformed boundary markers fall
    back to whole-file indexing, and unsupported extensions yield no regions.
    Splitting into chunks happens downstream.

    Args:
        path: Filesystem path to the uploaded file.
        artifact_path: Stable relative document id used to namespace per-entry
            ``doc_id``/``source_document_id``; defaults to the basename.

    Returns:
        A list of ``(text, metadata)`` tuples; empty for unsupported file types.
    """
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
    """Return the model token count for ``text``.

    Args:
        text: Text to measure.

    Returns:
        The token count as an integer.
    """
    return int(_count_tokens(text))


def trim_to_tokens(text: str, max_tokens: int) -> str:
    """Return ``text`` truncated to at most ``max_tokens`` tokens.

    Args:
        text: Text to truncate.
        max_tokens: Maximum number of tokens to retain.

    Returns:
        The (possibly truncated) text.
    """
    return _trim_to_tokens(text, max_tokens)


def ltm_docstore_item_id(metadata: dict) -> str:
    """Build the stable docstore key ``{doc_id}::chunk={chunk_seq}`` for a chunk.

    Args:
        metadata: Chunk metadata providing ``doc_id`` and ``chunk_seq`` (missing
            values default to empty/0).

    Returns:
        The docstore item id string.
    """
    did = str((metadata or {}).get("doc_id") or "")
    seq = int((metadata or {}).get("chunk_seq") or 0)
    return f"{did}::chunk={seq}"


def _collect_chunks_from_uploads(
    project_id: str,
    uploads_dir: str,
    settings: Any,
) -> Tuple[List[str], List[dict], Dict[str, int], Dict[str, int]]:
    """Walk a project's uploads directory and produce chunk texts and metadata.

    Parses every uploaded file into Syx regions, chunks each region, and builds
    aligned ``texts``/``metadatas`` along with per-file token sums and page
    counts used to backfill the database after a successful build.

    Args:
        project_id: Project whose uploads are being indexed (stamped into each
            chunk's metadata).
        uploads_dir: Absolute path to the project's uploads directory. A missing
            directory yields empty results.
        settings: Settings object providing ``chunk_size`` and ``chunk_overlap``.

    Returns:
        A tuple ``(texts, metadatas, file_token_sums, file_page_max)`` where
        ``texts`` and ``metadatas`` are index-aligned per chunk, ``file_token_sums``
        maps filename to total region token count, and ``file_page_max`` maps
        filename to its page count (currently always 1).
    """
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

    return texts, metadatas, file_token_sums, file_page_max


def _prepare_embedding_batches(
    texts: List[str],
    metadatas: List[dict],
    *,
    max_tokens_per_request: int,
    model_name: str,
) -> List[Tuple[List[str], List[dict], int]]:
    """Pack chunk texts/metadata into token-budgeted embedding batches.

    Args:
        texts: Ordered chunk texts to embed.
        metadatas: Per-chunk metadata, index-aligned with ``texts``.
        max_tokens_per_request: Maximum estimated tokens allowed per batch.
        model_name: Embedding model id forwarded to the token estimator.

    Returns:
        A list of ``(batch_texts, batch_metas, est_tokens)`` tuples with
        defensively copied contents.

    Raises:
        RuntimeError: If batching produces a batch without metadata.
    """
    prepared_batches: List[Tuple[List[str], List[dict], int]] = []
    for batch_texts, batch_metas, est_tokens in iter_token_batches(
        texts,
        metadatas=metadatas,
        max_tokens_per_batch=max_tokens_per_request,
        model_name=model_name,
    ):
        if batch_metas is None:
            raise RuntimeError("RAG rebuild batching produced missing metadata.")
        prepared_batches.append((list(batch_texts), list(batch_metas), int(est_tokens)))
    return prepared_batches


def _embed_one_batch(
    batch_id: int,
    batch_texts: List[str],
    batch_metas: List[dict],
    est_tokens: int,
    *,
    llm: Any,
    model_name: str,
) -> Dict[str, Any]:
    """Embed one prepared batch and package the result for the index build.

    Args:
        batch_id: 1-based batch ordinal used to reassemble results in order.
        batch_texts: Chunk texts to embed.
        batch_metas: Per-chunk metadata aligned with ``batch_texts``.
        est_tokens: Estimated token count for the batch (telemetry only).
        llm: Embedding client exposing ``embed(texts, model=...)``.
        model_name: Embedding model id to embed with.

    Returns:
        A payload dict with the batch id, texts, metas, estimated tokens,
        resulting vectors, and elapsed seconds.
    """
    t0 = time.monotonic()
    res = llm.embed(list(batch_texts), model=model_name)
    dt = time.monotonic() - t0
    return {
        "batch_id": int(batch_id),
        "texts": list(batch_texts),
        "metas": list(batch_metas),
        "est_tokens": int(est_tokens),
        "vectors": list(res.vectors),
        "elapsed_s": float(dt),
    }


def _embed_batches_parallel(
    prepared_batches: List[Tuple[List[str], List[dict], int]],
    *,
    llm: Any,
    model_name: str,
    worker_count: int,
    project_id: str,
) -> Dict[int, Dict[str, Any]]:
    """Embed all prepared batches concurrently and collect results by batch id.

    Args:
        prepared_batches: Batches produced by ``_prepare_embedding_batches``.
        llm: Embedding client passed through to ``_embed_one_batch``.
        model_name: Embedding model id to embed with.
        worker_count: Number of parallel embedding workers.
        project_id: Project id used for log context.

    Returns:
        A mapping of 1-based batch id to its embedding payload.

    Raises:
        RuntimeError: If any embedding batch fails (rate-limit or otherwise).
    """
    batch_results: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=int(worker_count)) as pool:
        future_to_batch: Dict[Any, int] = {}
        for batch_id, (batch_texts, batch_metas, est_tokens) in enumerate(prepared_batches, start=1):
            fut = pool.submit(
                _embed_one_batch,
                batch_id,
                batch_texts,
                batch_metas,
                est_tokens,
                llm=llm,
                model_name=model_name,
            )
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
    return batch_results


def _assemble_index_from_results(
    prepared_batches: List[Tuple[List[str], List[dict], int]],
    batch_results: Dict[int, Dict[str, Any]],
    *,
    project_id: str,
    worker_count: int,
    max_req_tokens: int,
) -> Tuple["faiss.IndexFlatIP | None", "int | None", List[str], Dict[str, Dict[str, Any]]]:
    """Build the FAISS index and docstore from ordered embedding results.

    Iterates batches in submission order, normalizes each batch's vectors, and
    accumulates them into a single inner-product index alongside an index-to-id
    list and docstore keyed by stable chunk ids.

    Args:
        prepared_batches: The batches embedded (used only for count/log context).
        batch_results: Mapping of batch id to embedding payload.
        project_id: Project id used for log context.
        worker_count: Number of embedding workers (telemetry only).
        max_req_tokens: Per-request token budget (telemetry only).

    Returns:
        A tuple ``(index, index_dim, index_to_id, docstore)``. ``index`` and
        ``index_dim`` are ``None`` when no batch produced vectors.

    Raises:
        RuntimeError: If a batch result is missing or embedding dimensionality
            changes mid-build.
    """
    index: "faiss.IndexFlatIP | None" = None
    index_dim: int | None = None
    index_to_id: List[str] = []
    docstore: Dict[str, Dict[str, Any]] = {}

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

    return index, index_dim, index_to_id, docstore


def _persist_index_artifacts(
    *,
    project_id: str,
    faiss_dir: str,
    index: "faiss.IndexFlatIP",
    index_dim: int,
    index_to_id: List[str],
    docstore: Dict[str, Dict[str, Any]],
    settings: Any,
) -> None:
    """Write the FAISS index, id map, docstore, manifest, and adjacency sidecar.

    Args:
        project_id: Project whose artifacts are written.
        faiss_dir: Target FAISS directory.
        index: The populated FAISS index to persist.
        index_dim: Embedding dimensionality recorded in the manifest.
        index_to_id: Ordered docstore ids aligned with index positions.
        docstore: Mapping of docstore id to ``{text, metadata}``.
        settings: Settings providing ``chunk_size``/``chunk_overlap`` for the
            manifest.
    """
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


def _backfill_file_stats(
    project_id: str,
    file_token_sums: Dict[str, int],
    file_page_max: Dict[str, int],
) -> None:
    """Backfill per-file token/page counts and embedding status in the database.

    Best-effort: a database failure is logged and otherwise suppressed so a
    successful index build is not lost due to a stats backfill error.

    Args:
        project_id: Project whose file rows are updated.
        file_token_sums: Filename to total token count.
        file_page_max: Filename to page count.
    """
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


def rebuild_faiss_index(project_id: str) -> str:
    """Rebuild a project's FAISS index from scratch from its uploads directory.

    Clears the existing FAISS directory, parses and chunks every uploaded file,
    embeds the chunks in parallel batches, then persists the index, docstore,
    index-to-id map, manifest, and adjacency sidecar. Also backfills per-file
    token/page counts and embedding status in the database.

    Args:
        project_id: Project whose index is rebuilt from its uploads directory.

    Returns:
        The absolute path to the project's FAISS directory. When there are no
        chunks (or no resulting vectors), the directory is returned without a
        persisted index.

    Raises:
        RuntimeError: If batch metadata is missing, an embedding batch fails, a
            batch result is missing, or the embedding dimensionality changes
            mid-build.
    """
    settings = get_settings()
    active_embedding_model = get_active_embedding_model()
    memory_root = settings.memory_root
    uploads_dir = os.path.join(memory_root, project_id, "uploads")
    faiss_dir = os.path.join(memory_root, project_id, "faiss")
    os.makedirs(faiss_dir, exist_ok=True)

    # No legacy support: rebuild from scratch.
    clear_dir_contents(faiss_dir)

    texts, metadatas, file_token_sums, file_page_max = _collect_chunks_from_uploads(
        project_id, uploads_dir, settings
    )
    if not texts:
        return faiss_dir

    max_req_tokens = int(getattr(settings, "max_embed_tokens_per_request", 250_000))
    worker_count_raw = int(getattr(settings, "rag_embed_rebuild_workers", 1) or 1)
    worker_count = max(1, min(8, worker_count_raw))
    llm = get_embedding_client()

    prepared_batches = _prepare_embedding_batches(
        texts,
        metadatas,
        max_tokens_per_request=max_req_tokens,
        model_name=active_embedding_model,
    )

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

    batch_results = _embed_batches_parallel(
        prepared_batches,
        llm=llm,
        model_name=active_embedding_model,
        worker_count=worker_count,
        project_id=project_id,
    )

    index, index_dim, index_to_id, docstore = _assemble_index_from_results(
        prepared_batches,
        batch_results,
        project_id=project_id,
        worker_count=worker_count,
        max_req_tokens=max_req_tokens,
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

    _persist_index_artifacts(
        project_id=project_id,
        faiss_dir=faiss_dir,
        index=index,
        index_dim=index_dim,
        index_to_id=index_to_id,
        docstore=docstore,
        settings=settings,
    )
    _backfill_file_stats(project_id, file_token_sums, file_page_max)
    return faiss_dir
