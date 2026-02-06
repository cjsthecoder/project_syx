"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
from __future__ import annotations
"""
RAG manager for building FAISS indices per project (V2).

Policy:
- Embedding model: text-embedding-3-large (configurable)
- Chunking: RecursiveCharacterTextSplitter(size=chunk_size, overlap=chunk_overlap)
- Metadata per chunk: project_id, filename, page_number (if pdf), chunk_id, timestamp
- Recreate FAISS index per upload (fresh build from uploads dir)
"""

import time
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any, Iterable, Set, cast
import json
import logging
import threading

import faiss  # type: ignore
import numpy as np  # type: ignore

from .config import get_settings, compute_per_source_k
from .embed_batching import iter_token_batches
import os
from .database import get_session
from .db_models import File as FileRow
from sqlmodel import select

logger = logging.getLogger(__name__)
from .retrieval_ordering import order_candidates_by_similarity_score
from ..utils.debug_utils import write_debug_file
from ..llm_model.llm_client import get_llm_client
from .vector_index import VectorEntry, VectorHit, VectorIndexInfo, VectorIndex

try:
    import tiktoken  # type: ignore
except Exception:
    tiktoken = None  # token counting optional until installed


_A441_SCHEMA_VERSION = "A.4.4.1"
_LTM_MANIFEST_NAME = "index_manifest.json"
_LTM_ADJACENCY_INDEX_NAME = "adjacency_index.json"
_LTM_DOCSTORE_NAME = "docstore.json"
_LTM_INDEX_TO_ID_NAME = "index_to_id.json"
_LTM_INDEX_FILE_NAME = "index.faiss"

_LTM_REBUILDING: Set[str] = set()
_LTM_REBUILD_LOCK = threading.Lock()


def _atomic_write_json(path: str, obj: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _safe_load_json(path: str) -> Optional[Any]:
    try:
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj
    except Exception:
        return None


def _uploads_relative_doc_id(uploads_dir: str, file_path: str) -> str:
    """Stable relative path identity under uploads/ (langchain-removal requirements)."""
    try:
        rel = os.path.relpath(file_path, uploads_dir)
    except Exception:
        rel = os.path.basename(file_path)
    return str(rel).replace(os.sep, "/")


def _ltm_doc_id(filename: Optional[str], page_number: Optional[Any]) -> Optional[str]:
    """
    DELTA-A.4.4.1: doc_id boundary rules.

    - Adjacency is within the same uploaded source document only (no cross-file).
    - PDFs are not supported in the langchain-removal implementation.
    """
    if not filename or not isinstance(filename, str):
        return None
    return filename


def _split_text_simple(text: str, *, chunk_size: int, chunk_overlap: int) -> List[str]:
    """Deterministic character splitter (boundaries may differ vs LangChain)."""
    t = text or ""
    if int(chunk_size) <= 0:
        return []
    ov = max(0, int(chunk_overlap))
    if ov >= int(chunk_size):
        ov = max(0, int(chunk_size) - 1)
    step = int(chunk_size) - ov
    out: List[str] = []
    i = 0
    n = len(t)
    while i < n:
        ch = t[i : i + int(chunk_size)]
        if ch and ch.strip():
            out.append(ch)
        i += step
    return out


def _normalize_rows(v: np.ndarray) -> np.ndarray:
    """Unit-normalize rows (safe for zero vectors)."""
    if v.size == 0:
        return v.astype("float32")
    v = v.astype("float32")
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return v / norms


def _cosine_to_01(cos: float) -> float:
    """Map cosine in [-1,1] to [0,1]."""
    try:
        c = float(cos)
    except Exception:
        return 0.0
    if c < -1.0:
        c = -1.0
    if c > 1.0:
        c = 1.0
    return (c + 1.0) / 2.0


def _clear_dir_contents(path: str) -> None:
    """Remove all files under directory (best-effort)."""
    try:
        if not os.path.isdir(path):
            return
        for root, _dirs, files in os.walk(path):
            for fn in files:
                try:
                    os.remove(os.path.join(root, fn))
                except Exception:
                    pass
    except Exception:
        pass


def _build_ltm_adjacency_lists(
    *, docstore: Dict[str, Dict[str, Any]], index_to_id: List[str]
) -> Optional[Dict[str, List[str]]]:
    """
    Build ordered adjacency list per doc_id:
      doc_id -> [item_id0, item_id1, ...]
    Validates chunk_seq is gap-free starting at 0 within each doc_id.
    """
    try:
        by_doc: Dict[str, List[Tuple[int, str]]] = {}
        for item_id in index_to_id:
            entry = docstore.get(item_id) or {}
            md = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
            doc_id = md.get("doc_id")
            seq = md.get("chunk_seq")
            if not isinstance(doc_id, str):
                continue
            try:
                si = int(seq)
            except Exception:
                continue
            by_doc.setdefault(doc_id, []).append((si, str(item_id)))

        out: Dict[str, List[str]] = {}
        for doc_id, pairs in by_doc.items():
            pairs = sorted(pairs, key=lambda p: p[0])
            if not pairs:
                continue
            seqs = [p[0] for p in pairs]
            if seqs[0] != 0 or seqs != list(range(0, len(seqs))):
                return None
            out[doc_id] = [p[1] for p in pairs]
        return out
    except Exception:
        return None


def _write_ltm_manifest_and_adjacency(
    *,
    project_id: str,
    faiss_dir: str,
    index_dim: int,
    chunk_size: int,
    chunk_overlap: int,
    docstore: Dict[str, Dict[str, Any]],
    index_to_id: List[str],
) -> bool:
    """
    Persist A.4.4.1 adjacency sidecar + manifest.
    If this fails, retrieval may still work, but adjacency is treated as unavailable.
    """
    try:
        adj_list = _build_ltm_adjacency_lists(docstore=docstore, index_to_id=index_to_id)
        if adj_list is None:
            return False

        adj_path = os.path.join(faiss_dir, _LTM_ADJACENCY_INDEX_NAME)
        _atomic_write_json(
            adj_path,
            {
                "schema_version": _A441_SCHEMA_VERSION,
                "project_id": project_id,
                "built_at": datetime.utcnow().isoformat(),
                "by_doc_id": adj_list,
            },
        )
        manifest_path = os.path.join(faiss_dir, _LTM_MANIFEST_NAME)
        _atomic_write_json(
            manifest_path,
            {
                "schema_version": _A441_SCHEMA_VERSION,
                "index_kind": "ltm",
                "project_id": project_id,
                "built_at": datetime.utcnow().isoformat(),
                "chunk_size": int(chunk_size),
                "chunk_overlap": int(chunk_overlap),
                "index_dim": int(index_dim),
                "score_mode": "cosine_ip_mapped_01",
                "index_file": _LTM_INDEX_FILE_NAME,
                "docstore_file": _LTM_DOCSTORE_NAME,
                "index_to_id_file": _LTM_INDEX_TO_ID_NAME,
                "adjacency_index": _LTM_ADJACENCY_INDEX_NAME,
            },
        )
        return True
    except Exception:
        return False


def _schedule_ltm_rebuild(project_id: str, reason: str) -> None:
    """Best-effort background rebuild (no in-request retry)."""
    try:
        with _LTM_REBUILD_LOCK:
            if project_id in _LTM_REBUILDING:
                return
            _LTM_REBUILDING.add(project_id)

        def _rebuild() -> None:
            try:
                rebuild_faiss_index(project_id)
            except Exception:
                pass
            finally:
                with _LTM_REBUILD_LOCK:
                    _LTM_REBUILDING.discard(project_id)

        threading.Thread(target=_rebuild, name=f"ltm-rebuild-{project_id[:8]}", daemon=True).start()
        logger.warning("RAG: scheduled LTM rebuild project=%s reason=%s", project_id, reason)
    except Exception:
        pass


def _read_file_text(path: str) -> List[Tuple[str, dict]]:
    """Return list of (text, metadata) chunks at file-level (before splitting)."""
    name = os.path.basename(path)
    _, ext = os.path.splitext(name)
    ext = ext.lower()
    if ext in {".txt", ".md"}:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        return [(content, {"filename": name})]
    else:
        return []


def _count_tokens(text: str) -> int:
    if not tiktoken:
        return len(text.split())
    try:
        enc = tiktoken.get_encoding("cl100k_base")
    except Exception:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def _trim_to_tokens(text: str, max_tokens: int) -> str:
    if not tiktoken:
        return text
    enc = tiktoken.get_encoding("cl100k_base")
    ids = enc.encode(text)
    if len(ids) <= max_tokens:
        return text
    ids = ids[:max_tokens]
    return enc.decode(ids)


def rebuild_faiss_index(project_id: str) -> str:
    """Rebuild FAISS index for a project from uploads directory (raw FAISS, no LangChain)."""
    settings = get_settings()
    uploads_dir = os.path.join("memory", project_id, "uploads")
    faiss_dir = os.path.join("memory", project_id, "faiss")
    os.makedirs(faiss_dir, exist_ok=True)

    # No legacy support: rebuild from scratch.
    _clear_dir_contents(faiss_dir)

    files: List[str] = []
    if os.path.isdir(uploads_dir):
        for root, _, names in os.walk(uploads_dir):
            for name in names:
                files.append(os.path.join(root, name))

    texts: List[str] = []
    metadatas: List[dict] = []
    # For per-file stats
    file_token_sums: Dict[str, int] = {}
    file_page_max: Dict[str, int] = {}

    now_iso = datetime.utcnow().isoformat()
    for f in files:
        doc_id = _uploads_relative_doc_id(uploads_dir, f)
        for raw_text, meta in _read_file_text(f):
            fname = meta.get("filename") or os.path.basename(f)
            file_token_sums[fname] = file_token_sums.get(fname, 0) + _count_tokens(raw_text)
            file_page_max[fname] = 1
            for i, chunk in enumerate(
                _split_text_simple(
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
                        "doc_id": doc_id,
                        "source_document_id": doc_id,
                        "chunk_seq": int(i),
                        "chunk_index": int(i),
                        "chunk_id": int(i),
                        "timestamp": now_iso,
                    }
                )

    if not texts:
        return faiss_dir

    max_req_tokens = int(getattr(settings, "max_embed_tokens_per_request", 250_000))
    llm = get_llm_client()

    index: Optional[faiss.IndexFlatIP] = None
    index_dim: Optional[int] = None
    index_to_id: List[str] = []
    docstore: Dict[str, Dict[str, Any]] = {}

    batch_idx = 0
    for batch_texts, batch_metas, est_tokens in iter_token_batches(
        texts,
        metadatas=metadatas,
        max_tokens_per_batch=max_req_tokens,
        model_name=settings.embedding_model,
    ):
        batch_idx += 1
        res = llm.embed(list(batch_texts), model=settings.embedding_model)
        vecs = res.vectors
        if not vecs:
            continue
        mat = _normalize_rows(np.array(vecs, dtype="float32"))
        if index is None:
            index_dim = int(mat.shape[1])
            index = faiss.IndexFlatIP(int(index_dim))
        if mat.shape[1] != int(index_dim or 0):
            raise RuntimeError(f"Embedding dim changed mid-build: {mat.shape[1]} vs {index_dim}")

        # Maintain strict alignment: row i -> index_to_id[i] -> docstore[id]
        for txt, md in zip(list(batch_texts), list(batch_metas)):
            did = str(md.get("doc_id") or "")
            seq = int(md.get("chunk_seq") or 0)
            item_id = f"{did}::chunk={seq}"
            index_to_id.append(item_id)
            docstore[item_id] = {"text": str(txt or ""), "metadata": dict(md or {})}
        index.add(mat)

        logger.debug(
            "RAG: embedded batch=%s texts=%s est_tokens=%s max_req_tokens=%s",
            int(batch_idx),
            int(len(batch_texts)),
            int(est_tokens),
            int(max_req_tokens),
        )

    if index is None or index_dim is None or int(index.ntotal) <= 0:
        return faiss_dir

    # Persist raw FAISS + sidecars under existing faiss/ layout.
    faiss.write_index(index, os.path.join(faiss_dir, _LTM_INDEX_FILE_NAME))
    _atomic_write_json(os.path.join(faiss_dir, _LTM_INDEX_TO_ID_NAME), index_to_id)
    _atomic_write_json(os.path.join(faiss_dir, _LTM_DOCSTORE_NAME), docstore)

    # A.4.4.1 adjacency + manifest (best-effort; does not block retrieval).
    try:
        ok = _write_ltm_manifest_and_adjacency(
            project_id=project_id,
            faiss_dir=faiss_dir,
            index_dim=int(index_dim),
            chunk_size=int(settings.chunk_size),
            chunk_overlap=int(settings.chunk_overlap),
            docstore=docstore,
            index_to_id=index_to_id,
        )
        if not ok:
            logger.warning("RAG: failed to write A.4.4.1 adjacency index project=%s", project_id)
    except Exception:
        logger.warning("RAG: exception writing A.4.4.1 adjacency index project=%s", project_id)

    # Backfill file token/page stats in DB
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
    except Exception:
        pass
    return faiss_dir


class LTMIndex:
    def __init__(
        self,
        *,
        index: faiss.IndexFlatIP,
        index_to_id: List[str],
        docstore: Dict[str, Dict[str, Any]],
        built_at: Optional[str],
        schema_version: Optional[str],
    ):
        self.index = index
        self.index_to_id = index_to_id
        self.docstore = docstore
        self._built_at = built_at
        self._schema_version = schema_version

    def size(self) -> int:
        return int(self.index.ntotal)

    def info(self) -> VectorIndexInfo:
        return VectorIndexInfo(
            index_kind="ltm",
            dim=int(self.index.d),
            score_mode="cosine_ip_mapped_01",
            built_at=self._built_at,
            schema_version=self._schema_version,
        )

    def get_by_id(self, item_id: str) -> Optional[VectorEntry]:
        try:
            entry = self.docstore.get(str(item_id))
            if not isinstance(entry, dict):
                return None
            txt = entry.get("text") if isinstance(entry.get("text"), str) else ""
            md = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
            return VectorEntry(text=txt or "", metadata=md)
        except Exception:
            return None

    def search_by_vector(self, qvec_norm: np.ndarray, *, k: int) -> List[VectorHit]:
        if int(self.index.ntotal) <= 0:
            return []
        q = np.array([qvec_norm], dtype="float32")
        D, I = self.index.search(q, k=int(k))
        out: List[VectorHit] = []
        for idx, ip in zip(I[0].tolist(), D[0].tolist()):
            if int(idx) < 0 or int(idx) >= len(self.index_to_id):
                continue
            item_id = self.index_to_id[int(idx)]
            ve = self.get_by_id(str(item_id))
            if ve is None:
                continue
            ipf = float(ip)
            score01 = _cosine_to_01(ipf)
            out.append(VectorHit(entry=ve, ip=ipf, score01=float(score01)))
        return out


def load_faiss_index(project_id: str) -> Optional[LTMIndex]:
    """Load raw FAISS index + docstore for project if exists and non-empty."""
    settings = get_settings()
    faiss_dir = os.path.join("memory", project_id, "faiss")
    if not os.path.isdir(faiss_dir):
        logger.debug(f"RAG: index directory missing for project '{project_id}' at {faiss_dir}")
        return None
    try:
        idx_path = os.path.join(faiss_dir, _LTM_INDEX_FILE_NAME)
        ids_path = os.path.join(faiss_dir, _LTM_INDEX_TO_ID_NAME)
        ds_path = os.path.join(faiss_dir, _LTM_DOCSTORE_NAME)
        if not os.path.isfile(idx_path) or not os.path.isfile(ids_path) or not os.path.isfile(ds_path):
            return None
        index = cast(faiss.IndexFlatIP, faiss.read_index(idx_path))
        ids_obj = _safe_load_json(ids_path)
        ds_obj = _safe_load_json(ds_path)
        if not isinstance(ids_obj, list) or not isinstance(ds_obj, dict) or int(index.ntotal) <= 0:
            return None
        index_to_id = [str(x) for x in ids_obj]
        docstore = cast(Dict[str, Dict[str, Any]], ds_obj)
        # DELTA-A.4.4.1: validate adjacency sidecar only when index claims A.4.4.1+
        try:
            manifest_path = os.path.join(faiss_dir, _LTM_MANIFEST_NAME)
            manifest = _safe_load_json(manifest_path)
            claims_a441 = bool(isinstance(manifest, dict) and manifest.get("schema_version") == _A441_SCHEMA_VERSION)
            if claims_a441:
                # Invalidate adjacency (trigger background rebuild) if chunking params changed since build.
                try:
                    built_cs = int(manifest.get("chunk_size")) if manifest.get("chunk_size") is not None else None
                    built_co = int(manifest.get("chunk_overlap")) if manifest.get("chunk_overlap") is not None else None
                except Exception:
                    built_cs, built_co = None, None
                if built_cs != int(settings.chunk_size) or built_co != int(settings.chunk_overlap):
                    _schedule_ltm_rebuild(project_id, reason="a441_chunk_params_mismatch")
                else:
                    adj_name = manifest.get("adjacency_index") or _LTM_ADJACENCY_INDEX_NAME
                    adj_path = os.path.join(faiss_dir, str(adj_name))
                    adj_obj = _safe_load_json(adj_path)
                    # If missing/invalid, rebuild (A.4.4.1+ only). Legacy absence is expected.
                    if not isinstance(adj_obj, dict) or adj_obj.get("schema_version") != _A441_SCHEMA_VERSION:
                        _schedule_ltm_rebuild(project_id, reason="a441_adjacency_missing_or_invalid")
        except Exception:
            # Best-effort only; never block retrieval.
            pass
        built_at = None
        schema_version = None
        try:
            manifest_path = os.path.join(faiss_dir, _LTM_MANIFEST_NAME)
            manifest = _safe_load_json(manifest_path)
            if isinstance(manifest, dict):
                built_at = manifest.get("built_at") if isinstance(manifest.get("built_at"), str) else None
                schema_version = manifest.get("schema_version") if isinstance(manifest.get("schema_version"), str) else None
        except Exception:
            pass
        logger.debug(f"RAG: loaded index for '{project_id}' with {int(index.ntotal)} vectors")
        return LTMIndex(
            index=index,
            index_to_id=index_to_id,
            docstore=docstore,
            built_at=built_at,
            schema_version=schema_version,
        )
    except Exception as e:
        logger.debug(f"RAG: failed to load index for '{project_id}': {e}")
        return None


def ltm_lookup_adjacent_docstore_ids(
    project_id: str,
    *,
    doc_id: str,
    chunk_seq: int,
) -> Dict[str, Optional[str]]:
    """
    DELTA-A.4.4.1: deterministic neighbor lookup for LTM chunks.

    Returns dict with keys: prev_docstore_id, next_docstore_id.
    If adjacency is unavailable (legacy index, missing/corrupt sidecar), returns None values.
    """
    faiss_dir = os.path.join("memory", project_id, "faiss")
    manifest = _safe_load_json(os.path.join(faiss_dir, _LTM_MANIFEST_NAME))
    claims_a441 = bool(isinstance(manifest, dict) and manifest.get("schema_version") == _A441_SCHEMA_VERSION)
    if not claims_a441:
        return {"prev_docstore_id": None, "next_docstore_id": None}

    adj_name = (manifest.get("adjacency_index") if isinstance(manifest, dict) else None) or _LTM_ADJACENCY_INDEX_NAME
    adj = _safe_load_json(os.path.join(faiss_dir, str(adj_name)))
    if not isinstance(adj, dict) or adj.get("schema_version") != _A441_SCHEMA_VERSION:
        # A.4.4.1+ but adjacency missing/invalid: degrade (no expansion) and schedule rebuild
        _schedule_ltm_rebuild(project_id, reason="a441_lookup_missing_or_invalid")
        return {"prev_docstore_id": None, "next_docstore_id": None}

    by_doc = adj.get("by_doc_id")
    if not isinstance(by_doc, dict):
        _schedule_ltm_rebuild(project_id, reason="a441_lookup_bad_shape")
        return {"prev_docstore_id": None, "next_docstore_id": None}

    seq_map = by_doc.get(doc_id)
    if not isinstance(seq_map, list):
        return {"prev_docstore_id": None, "next_docstore_id": None}

    i = int(chunk_seq)
    prev_id = seq_map[i - 1] if 0 <= (i - 1) < len(seq_map) else None
    next_id = seq_map[i + 1] if 0 <= (i + 1) < len(seq_map) else None
    return {
        "prev_docstore_id": str(prev_id) if isinstance(prev_id, str) else None,
        "next_docstore_id": str(next_id) if isinstance(next_id, str) else None,
    }


def ltm_fetch_chunk_by_docstore_id(project_id: str, docstore_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a stored LTM chunk by docstore_id.
    Returns {text, metadata} or None on failure.
    """
    vs = load_faiss_index(project_id)
    if not vs:
        return None
    try:
        entry = vs.docstore.get(str(docstore_id))
        if not isinstance(entry, dict):
            return None
        txt = entry.get("text") if isinstance(entry.get("text"), str) else ""
        md = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
        return {"text": txt or "", "metadata": md}
    except Exception:
        return None

def canonical_retrieve_candidates(
    project_id: str,
    query: str,
    *,
    sources: Optional[List[str]] = None,
    per_source_k_override: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    DELTA-A.4.1: Canonical retrieval entry point.

    - Computes the query embedding exactly once and reuses it across all sources queried.
    - No thresholding, no boosting, and no route-based eligibility pruning occurs here.
    Scores are normalized to cosine similarity in [0.0, 1.0].

    On error querying a source, trigger best-effort rebuild/repair (where applicable)
    and return an empty candidate set for that source for the current request (no retry).
    """
    settings = get_settings()
    per_source_k = (
        int(per_source_k_override)
        if per_source_k_override is not None
        else compute_per_source_k(settings.base_top_k, settings.retrieval_multiplier)
    )
    srcs = [s.lower() for s in (sources or ["daily", "ltm"]) if isinstance(s, str)]

    out: List[Dict[str, Any]] = []
    daily_count = 0
    ltm_count = 0

    # Allow callers to explicitly skip retrieval by passing k<=0.
    # This keeps the "0 means skip RAG" contract stable at the retrieval boundary.
    if int(per_source_k) <= 0:
        return []

    # Embed ONCE (shared query vector) via LLMClient boundary (plain-data; no vendor SDK outside llm_model)
    qvec: Optional[List[float]] = None
    try:
        qvec = get_llm_client().embed_query(query or "", model=settings.embedding_model)
    except Exception as e:
        logger.warning("RAG: failed to embed query for canonical retrieval project=%s: %s", project_id, e)
        return []
    qmat = _normalize_rows(np.array([qvec], dtype="float32"))

    # Daily
    if "daily" in srcs:
        try:
            from .daily_rag import get_daily_source, notify_daily_search_failure

            ds = get_daily_source(project_id)
            if ds is not None:
                try:
                    results = ds.vs.search_by_vector(qmat[0], k=int(per_source_k))
                except Exception as e:
                    logger.warning("RAG: Daily candidate search failed project=%s: %s", project_id, e)
                    notify_daily_search_failure(project_id, reason="canonical_daily_search_exception")
                    results = []
                for hit in results:
                    score01 = float(hit.score01)
                    md = hit.entry.metadata if isinstance(hit.entry.metadata, dict) else {}
                    eid = md.get("daily_entry_id")
                    entry = None
                    try:
                        if eid is not None:
                            entry = ds.meta_by_id.get(str(eid))
                    except Exception:
                        entry = None
                    # Authoritative from daily.json when available; otherwise best-effort from doc metadata.
                    if isinstance(entry, dict):
                        created_at = entry.get("created_at")
                        route = None
                        tags_meta = entry.get("tags_meta") if isinstance(entry.get("tags_meta"), dict) else None
                        topics = tags_meta.get("topics") if isinstance(tags_meta, dict) else None
                        intent = tags_meta.get("intent") if isinstance(tags_meta, dict) else None
                        tag_type = tags_meta.get("type") if isinstance(tags_meta, dict) else None
                        out.append(
                            {
                                "source": "daily",
                                "text": hit.entry.text or "",
                                "score": float(score01),
                                "metadata": {
                                    "id": str(eid) if eid is not None else None,
                                    "timestamp": created_at,
                                    "route": (str(route).lower() if isinstance(route, str) else route),
                                    "tags": entry.get("tags"),
                                    "topics": topics,
                                    "intent": intent,
                                    "type": tag_type,
                                    "tags_meta": tags_meta,
                                    "keep": entry.get("keep"),
                                    "day_sequence": entry.get("day_sequence"),
                                    "pair_ids": entry.get("pair_ids"),
                                    # DELTA-A.4.4.1 adjacency identity for Daily entries
                                    "doc_id": "daily",
                                    "chunk_seq": entry.get("day_sequence"),
                                    "source_document_id": "daily",
                                    "chunk_index": entry.get("day_sequence"),
                                },
                            }
                        )
                    else:
                        # Join-miss: return candidate with partial metadata (lossless recall).
                        out.append(
                            {
                                "source": "daily",
                                "text": hit.entry.text or "",
                                "score": float(score01),
                                "metadata": {
                                    "id": None,
                                    "timestamp": None,
                                    "route": None,
                                    "tags": None,
                                    "topics": None,
                                    "intent": None,
                                    "type": None,
                                    "tags_meta": None,
                                    "keep": None,
                                    "day_sequence": None,
                                    "pair_ids": None,
                                    "doc_id": "daily",
                                    "chunk_seq": md.get("chunk_seq") if isinstance(md, dict) else None,
                                    "source_document_id": "daily",
                                    "chunk_index": md.get("chunk_seq") if isinstance(md, dict) else None,
                                },
                            }
                        )
                daily_count = len(results)
        except Exception:
            # Daily source owns rebuild semantics; degrade gracefully.
            pass

    # LTM (main FAISS index)
    if "ltm" in srcs:
        def _ltm_search_by_vector() -> List[VectorHit]:
            """
            Source-owned LTM search wrapper (best-effort rebuild-on-error; no retry in-request).
            Canonical retrieval calls this but does not own rebuild semantics.
            """
            ltm = load_faiss_index(project_id)
            if not ltm:
                return []
            try:
                return ltm.search_by_vector(qmat[0], k=int(per_source_k))
            except Exception as e:
                try:
                    logger.warning("RAG: LTM candidate search failed project=%s; scheduling rebuild: %s", project_id, e)
                    _schedule_ltm_rebuild(project_id, reason="canonical_ltm_search_exception")
                except Exception:
                    pass
                return []

        results = _ltm_search_by_vector()
        for hit in results:
                md = hit.entry.metadata if isinstance(hit.entry.metadata, dict) else {}
                score01 = float(hit.score01)
                out.append(
                    {
                        "source": "ltm",
                        "text": hit.entry.text or "",
                        "score": float(score01),
                        "metadata": {
                            # Allow missing/absent metadata fields in A.4.1
                            "timestamp": md.get("timestamp"),
                            "route": None,
                            "tags": None,
                            "topics": None,
                            "intent": None,
                            "type": None,
                            "id": None,
                            "tags_meta": None,
                            "keep": None,
                            "day_sequence": None,
                            "pair_ids": None,
                            # Existing main index metadata retained for downstream use/telemetry
                            "filename": md.get("filename"),
                            "page_number": md.get("page_number"),
                            "chunk_id": md.get("chunk_id"),
                            # DELTA-A.4.4.1 adjacency identity
                            "doc_id": md.get("doc_id"),
                            "chunk_seq": md.get("chunk_seq"),
                            "source_document_id": md.get("doc_id"),
                            "chunk_index": md.get("chunk_seq"),
                        },
                    }
                )
        ltm_count = len(results)

    try:
        qprev = (query or "")[:120].replace("\n", " ")
        logger.debug(
            "[A.4.1][CANONICAL_RETRIEVE] project_id=%s sources=%s per_source_k=%s daily_candidates=%s ltm_candidates=%s query_preview=\"%s\"",
            project_id,
            srcs,
            int(per_source_k),
            int(daily_count),
            int(ltm_count),
            qprev,
        )
    except Exception:
        pass
    return out


def retrieve_context(
    project_id: str,
    query: str,
    score_threshold: float,
) -> Dict[str, Any]:
    """Retrieve top-k snippets and assemble a single Context: block string.

    Returns dict with keys:
      - context_text: combined context block prefixed with "Context:"
      - snippets: list of snippet strings (with headers)
      - tokens_used: approximate token count
      - hit_count: number of hits at/above threshold
      - hit_avg: average similarity of hits
      - hits: list of per-snippet metadata dicts
        (each with snippet, filename, page_number, score)
    """
    # DELTA-A.4.1: all retrieval passes through canonical entry point (LTM-only here; embed-once).
    # DELTA-A.4.2: order candidates by raw similarity score before selection and assembly.
    cands = canonical_retrieve_candidates(project_id, query, sources=["ltm"])
    ltm = [c for c in (cands or []) if (c.get("source") == "ltm")]
    ltm = order_candidates_by_similarity_score(ltm)
    if not ltm:
        logger.debug(f"RAG: no index available for project '{project_id}', skipping retrieval")
        return {"context_text": "", "snippets": [], "tokens_used": 0}

    logger.debug(f"RAG: query='{query[:120]}...' got {len(ltm)} results (pre-filter)")

    filtered: List[Tuple[str, dict, float]] = []
    details = []
    scored: List[Tuple[str, dict, float]] = []  # (content, meta, effective_cos)
    passed_cosines: List[float] = []
    for c in ltm:
        content = c.get("text") or ""
        meta = (c.get("metadata") or {}) if isinstance(c.get("metadata"), dict) else {}
        # Canonical score is raw cosine; downstream may apply namespace boost for selection.
        raw_cos = float(c.get("score") or 0.0)
        cos = raw_cos
        if cos >= score_threshold:
            filtered.append((content, meta, cos))
            passed_cosines.append(cos)
        scored.append((content, meta, cos))
        details.append(
            {
                "file": meta.get("filename"),
                "page": meta.get("page_number"),
                "cos": round(raw_cos, 3),
            }
        )
    logger.debug(f"RAG: filtered {len(filtered)} >= threshold {score_threshold}; details={details}")

    # Build context (no token caps in A.4.1/A.4.2; trimming/budgeting is deferred to A.4.3).
    tokens_used = 0
    pieces: List[str] = []
    for i, (content, meta, score) in enumerate(filtered):
        snippet_tokens = _count_tokens(content)
        header = f"Snippet {i+1} (score={score:.2f}, file={meta.get('filename')}, page={meta.get('page_number')})\n"
        pieces.append(header + content)
        tokens_used += snippet_tokens

    if not pieces:
        # Fallback: if nothing passed threshold, include the best-scoring snippet
        if scored:
            best = sorted(scored, key=lambda t: t[2], reverse=True)[0]
            content, meta, cos = best
            tokens_used = _count_tokens(content)
            header = f"Snippet 1 (fallback, score={cos:.2f}, file={meta.get('filename')}, page={meta.get('page_number')})\n"
            context_text = "Context:\n---\n" + header + content
            logger.debug("RAG: fallback applied - included top-scoring snippet despite threshold")
            hits = [
                {
                    "snippet": content,
                    "filename": meta.get("filename"),
                    "page_number": meta.get("page_number"),
                    "score": float(cos),
                }
            ]
            return {
                "context_text": context_text,
                "snippets": [header + content],
                "tokens_used": tokens_used,
                "hit_count": len(passed_cosines),
                "hit_avg": (sum(passed_cosines) / len(passed_cosines) if passed_cosines else 0.0),
                "hits": hits,
            }
        logger.debug("RAG: no snippets selected and no fallback available")
        return {
            "context_text": "",
            "snippets": [],
            "tokens_used": 0,
            "hit_count": len(passed_cosines),
            "hit_avg": (sum(passed_cosines) / len(passed_cosines) if passed_cosines else 0.0),
            "hits": [],
        }

    # Build hits metadata aligned with pieces
    hits = []
    for (content, meta, score) in filtered[: len(pieces)]:
        hits.append(
            {
                "snippet": content,
                "filename": meta.get("filename"),
                "page_number": meta.get("page_number"),
                "score": float(score),
            }
        )

    context_text = "Context:\n---\n" + "\n\n---\n".join(pieces)
    logger.debug(f"RAG: built context block tokens_used={tokens_used} snippets={len(pieces)}")
    return {
        "context_text": context_text,
        "snippets": pieces,
        "tokens_used": tokens_used,
        "hit_count": len(passed_cosines),
        "hit_avg": (sum(passed_cosines) / len(passed_cosines) if passed_cosines else 0.0),
        "hits": hits,
    }


def merge_daily_and_main(
    project_id: str,
    query: str,
    daily_enabled: bool,
    max_keep: int,
    per_source_k_override: Optional[int] = None,
) -> Dict[str, Any]:
    """Retrieve from daily and main, then apply A.4.3 positional truncation.

    DELTA-A.4.2: candidate ordering is by raw similarity score across all sources
    before selection/truncation/prompt assembly.

    DELTA-A.4.3: selection is positional/deterministic:
    - consume the globally ordered list from A.4.2
    - retain the first MAX_KEEP candidates
    - no reordering, skipping, thresholding, boosting, or dedupe occurs here
    """
    settings = get_settings()
    per_source_k = (
        int(per_source_k_override)
        if per_source_k_override is not None
        else compute_per_source_k(settings.base_top_k, settings.retrieval_multiplier)
    )
    if int(per_source_k) <= 0 or int(max_keep) <= 0:
        return {
            "context_text": "",
            "tokens_used": 0,
            "daily_texts": [],
            "main_texts": [],
            "main_hits": 0,
            "main_avg": 0.0,
            "daily_hits": 0,
            "daily_avg": 0.0,
            "total_hits": 0,
            "ordered_candidates": 0,
            "kept_candidates": 0,
        }
    logger.debug(
        "DailyRAG: starting merged retrieval project=%s per_source_k=%s daily_enabled=%s max_keep=%s",
        project_id,
        int(per_source_k),
        str(bool(daily_enabled)).lower(),
        int(max_keep),
    )
    # DELTA-A.4.1: retrieval via canonical entry point (raw candidates; no thresholding/boosting here).
    sources = ["ltm"] + (["daily"] if bool(daily_enabled) else [])
    cands = canonical_retrieve_candidates(project_id, query, sources=sources, per_source_k_override=per_source_k)
    # DELTA-A.4.2: global ordering by raw similarity score (stable; ties preserve pre-sort order).
    ordered = order_candidates_by_similarity_score(list(cands or []))

    # DELTA-A.4.3: positional truncation only.
    kept_candidates = list(ordered[: int(max_keep)]) if ordered else []

    # Debug dumps (human-readable .txt) for A.4.2 ordering and A.4.3 selection.
    try:
        if project_id:
            ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
            qprev = (query or "")[:240].replace("\n", " ")

            def _fmt_list(title: str, items: List[Dict[str, Any]]) -> str:
                lines = [
                    f"# timestamp: {ts}",
                    f"# project_id: {project_id}",
                    f"# query_preview: {qprev}",
                    f"# per_source_k: {int(per_source_k)}",
                    f"# max_keep: {int(max_keep)}",
                    f"# daily_enabled: {str(bool(daily_enabled)).lower()}",
                    "",
                    f"====== {title} ======",
                    "",
                ]
                for rank, c in enumerate(items, start=1):
                    md = c.get("metadata") if isinstance(c.get("metadata"), dict) else {}
                    src = c.get("source")
                    score = c.get("score")
                    doc_id = md.get("source_document_id") or md.get("doc_id")
                    chunk_idx = md.get("chunk_index") if md.get("chunk_index") is not None else md.get("chunk_seq")
                    fname = md.get("filename")
                    lines.append(
                        f"{rank:>3}. source={src} score={score} source_document_id={doc_id} chunk_index={chunk_idx} file={fname}"
                    )
                lines.append("")
                return "\n".join(lines)

            write_debug_file(
                project_id,
                f"rag/retrieval/{ts}_ordered_candidates.txt",
                _fmt_list("ORDERED_CANDIDATES (A.4.2)", ordered),
            )
            write_debug_file(
                project_id,
                f"rag/retrieval/{ts}_kept_candidates.txt",
                _fmt_list("KEPT_CANDIDATES (A.4.3)", kept_candidates),
            )
    except Exception:
        pass

    # Prompt assembly stage (after ordering + selection).
    tokens_used_total = 0
    pieces: List[str] = []
    daily_texts: List[str] = []
    main_texts: List[str] = []

    main_scores: List[float] = []
    daily_scores: List[float] = []

    for idx, c in enumerate(kept_candidates):
        txt = c.get("text") or ""
        src = c.get("source") or "unknown"
        # Canonical retrieval currently stores `score` as score01 (cosine mapped from [-1,1] -> [0,1]).
        # For human-readable prompt headers, show both:
        #   cos = 2*score01 - 1
        #   score01 = score
        score01 = float(c.get("score") or 0.0)
        cos = (2.0 * float(score01)) - 1.0
        md = (c.get("metadata") or {}) if isinstance(c.get("metadata"), dict) else {}

        t = _count_tokens(txt)
        if src == "daily":
            daily_texts.append(txt)
            daily_scores.append(score01)
        else:
            main_texts.append(txt)
            main_scores.append(score01)
        tokens_used_total += t

        # Candidate header (keeps ordering explicit; show cos + score for troubleshooting).
        if src == "ltm":
            header = (
                f"Snippet {idx+1} (source=ltm, cos={cos:.4f}, score={score01:.4f}, file={md.get('filename')}, page={md.get('page_number')})\n"
            )
        else:
            header = f"Snippet {idx+1} (source=daily, cos={cos:.4f}, score={score01:.4f}, route={md.get('route')})\n"
        pieces.append(header + txt)

    context_text = ("Context:\n---\n" + "\n\n---\n".join(pieces)) if pieces else ""
    main_hits = int(len(main_scores))
    daily_hits = int(len(daily_scores))
    main_avg = float(sum(main_scores) / main_hits) if main_hits else 0.0
    daily_avg = float(sum(daily_scores) / daily_hits) if daily_hits else 0.0
    logger.debug(
        "DailyRAG: merged context tokens=%s snippets=%s (kept=%s ordered=%s)",
        tokens_used_total,
        len(pieces),
        int(len(pieces)),
        int(len(ordered)),
    )

    return {
        "context_text": context_text,
        "tokens_used": int(tokens_used_total),
        "daily_texts": daily_texts,
        "main_texts": main_texts,
        "main_hits": int(main_hits),
        "main_avg": float(main_avg),
        "daily_hits": int(daily_hits),
        "daily_avg": float(daily_avg),
        "total_hits": int(main_hits + daily_hits),
        "ordered_candidates": int(len(ordered)),
        "kept_candidates": int(len(pieces)),
    }


# Legacy FAISS sidecar namespace map support removed in V2.5; namespaces are embedded during indexing.


