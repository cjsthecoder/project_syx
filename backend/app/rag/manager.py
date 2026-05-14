"""
Copyright (c) 2025-2026 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
RAG manager for building FAISS indices per project.

Policy:
- Embedding model: text-embedding-3-large (configurable)
- Chunking: RecursiveCharacterTextSplitter(size=chunk_size, overlap=chunk_overlap)
- Metadata per chunk: project_id, filename, page_number (if pdf), chunk_id, timestamp
- Recreate FAISS index per upload (fresh build from uploads dir)
"""

from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any, Iterable, Set, cast
import json
import logging
import threading

import faiss  # type: ignore
import numpy as np  # type: ignore

from ..core.config import get_settings, compute_per_source_k, get_active_embedding_model
import os

logger = logging.getLogger(__name__)
from ..core.retrieval_ordering import order_candidates_by_similarity_score
from ..tracking import get_instrumentation
from ..utils.debug_utils import write_debug_file
from ..embedding.vector_index import VectorEntry, VectorHit, VectorIndexInfo, VectorIndex
from ..embedding.factory import get_embedding_client
from .chunk_utils import collapse_snippet_groups, trim_adjacent_chunk_overlap
from .manager_rebuild import count_tokens as _count_tokens
from .manager_rebuild import read_file_text as _read_file_text
from .manager_rebuild import rebuild_faiss_index
from .manager_index_io import (
    ADJACENCY_SCHEMA_VERSION as _ADJACENCY_SCHEMA_VERSION,
    LTM_ADJACENCY_INDEX_NAME as _LTM_ADJACENCY_INDEX_NAME,
    LTM_DOCSTORE_NAME as _LTM_DOCSTORE_NAME,
    LTM_INDEX_FILE_NAME as _LTM_INDEX_FILE_NAME,
    LTM_INDEX_TO_ID_NAME as _LTM_INDEX_TO_ID_NAME,
    LTM_MANIFEST_NAME as _LTM_MANIFEST_NAME,
    atomic_write_json as _atomic_write_json,
    cosine_to_01 as _cosine_to_01,
    normalize_rows as _normalize_rows,
    safe_load_json as _safe_load_json,
)

_LTM_REBUILDING: Set[str] = set()
_LTM_REBUILD_LOCK = threading.Lock()



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
            except Exception as exc:
                logger.warning(
                    "RAG: background LTM rebuild failed; operation=rebuild_faiss_index project_id=%s detail=%s",
                    project_id,
                    exc,
                    exc_info=True,
                )
            finally:
                with _LTM_REBUILD_LOCK:
                    _LTM_REBUILDING.discard(project_id)

        threading.Thread(target=_rebuild, name=f"ltm-rebuild-{project_id[:8]}", daemon=True).start()
        logger.warning("RAG: scheduled LTM rebuild project=%s reason=%s", project_id, reason)
    except Exception as exc:
        logger.warning(
            "RAG: failed scheduling LTM rebuild; operation=_schedule_ltm_rebuild project_id=%s reason=%s detail=%s",
            project_id,
            reason,
            exc,
        )


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
    faiss_dir = os.path.join(get_settings().memory_root, project_id, "faiss")
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
        # Validate adjacency sidecar only when the index claims adjacency support.
        try:
            manifest_path = os.path.join(faiss_dir, _LTM_MANIFEST_NAME)
            manifest = _safe_load_json(manifest_path)
            claims_adjacency_schema = bool(
                isinstance(manifest, dict) and manifest.get("schema_version") == _ADJACENCY_SCHEMA_VERSION
            )
            if claims_adjacency_schema:
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
                    # If missing/invalid, rebuild when adjacency is expected. Legacy absence is expected.
                    if not isinstance(adj_obj, dict) or adj_obj.get("schema_version") != _ADJACENCY_SCHEMA_VERSION:
                        _schedule_ltm_rebuild(project_id, reason="a441_adjacency_missing_or_invalid")
        except Exception as exc:
            # Best-effort only; never block retrieval.
            logger.warning(
                "RAG: failed validating adjacency manifest; operation=load_faiss_index project_id=%s detail=%s",
                project_id,
                exc,
            )
        built_at = None
        schema_version = None
        try:
            manifest_path = os.path.join(faiss_dir, _LTM_MANIFEST_NAME)
            manifest = _safe_load_json(manifest_path)
            if isinstance(manifest, dict):
                built_at = manifest.get("built_at") if isinstance(manifest.get("built_at"), str) else None
                schema_version = manifest.get("schema_version") if isinstance(manifest.get("schema_version"), str) else None
        except Exception as exc:
            logger.debug("RAG: failed loading optional manifest metadata project=%s detail=%s", project_id, exc)
        logger.debug(f"RAG: loaded index for '{project_id}' with {int(index.ntotal)} vectors")
        return LTMIndex(
            index=index,
            index_to_id=index_to_id,
            docstore=docstore,
            built_at=built_at,
            schema_version=schema_version,
        )
    except (OSError, ValueError, TypeError) as e:
        logger.debug(f"RAG: failed to load index for '{project_id}': {e}")
        return None


def ltm_lookup_adjacent_docstore_ids(
    project_id: str,
    *,
    doc_id: str,
    chunk_seq: int,
) -> Dict[str, Optional[str]]:
    """
    Deterministic neighbor lookup for LTM chunks.

    Returns dict with keys: prev_docstore_id, next_docstore_id.
    If adjacency is unavailable (legacy index, missing/corrupt sidecar), returns None values.
    """
    faiss_dir = os.path.join(get_settings().memory_root, project_id, "faiss")
    manifest = _safe_load_json(os.path.join(faiss_dir, _LTM_MANIFEST_NAME))
    claims_adjacency_schema = bool(
        isinstance(manifest, dict) and manifest.get("schema_version") == _ADJACENCY_SCHEMA_VERSION
    )
    if not claims_adjacency_schema:
        return {"prev_docstore_id": None, "next_docstore_id": None}

    adj_name = (manifest.get("adjacency_index") if isinstance(manifest, dict) else None) or _LTM_ADJACENCY_INDEX_NAME
    adj = _safe_load_json(os.path.join(faiss_dir, str(adj_name)))
    if not isinstance(adj, dict) or adj.get("schema_version") != _ADJACENCY_SCHEMA_VERSION:
        # Adjacency expected but missing/invalid: degrade (no expansion) and schedule rebuild.
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


def _ltm_candidate_metadata(md: Dict[str, Any]) -> Dict[str, Any]:
    source_document_id = md.get("source_document_id") or md.get("doc_id")
    chunk_index = md.get("chunk_index") if md.get("chunk_index") is not None else md.get("chunk_seq")
    return {
        # Allow missing/absent metadata fields.
        "timestamp": md.get("timestamp"),
        "route": md.get("route"),
        "tags": md.get("tags"),
        "topics": md.get("topics"),
        "intent": md.get("intent"),
        "type": md.get("type"),
        "id": md.get("id"),
        "tags_meta": md.get("tags_meta"),
        "keep": md.get("keep"),
        "day_sequence": md.get("day_sequence"),
        "pair_ids": md.get("pair_ids"),
        # Existing main index metadata retained for downstream use/telemetry.
        "filename": md.get("filename"),
        "page_number": md.get("page_number"),
        "chunk_id": md.get("chunk_id"),
        # Syx bounded-entry metadata, when available.
        "memory_id": md.get("memory_id"),
        "entry_type": md.get("entry_type"),
        "source": md.get("source"),
        "source_agent": md.get("source_agent"),
        "source_scope": md.get("source_scope"),
        "current_scope": md.get("current_scope"),
        "semantic_handle": md.get("semantic_handle"),
        "artifact_path": md.get("artifact_path"),
        "entry_start_line": md.get("entry_start_line"),
        "entry_end_line": md.get("entry_end_line"),
        # Adjacency identity fields.
        "doc_id": md.get("doc_id"),
        "chunk_seq": md.get("chunk_seq"),
        "source_document_id": source_document_id,
        "chunk_index": chunk_index,
    }


def canonical_retrieve_candidates(
    project_id: str,
    query: str,
    *,
    sources: Optional[List[str]] = None,
    per_source_k_override: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Canonical retrieval entry point.

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
    active_embedding_model = get_active_embedding_model()
    try:
        qvec = get_embedding_client().embed_query(query or "", model=active_embedding_model)
    except Exception as e:
        logger.warning("RAG: failed to embed query for canonical retrieval project=%s: %s", project_id, e)
        return []
    qmat = _normalize_rows(np.array([qvec], dtype="float32"))

    # Daily
    if "daily" in srcs:
        try:
            from .daily_store import get_daily_source, notify_daily_search_failure

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
                                    "memory_id": entry.get("memory_id"),
                                    "entry_type": entry.get("entry_type"),
                                    "source_scope": entry.get("source_scope"),
                                    "current_scope": entry.get("current_scope"),
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
                                    # Adjacency identity for Daily entries.
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
                except Exception as exc:
                    logger.warning(
                        "RAG: failed scheduling LTM rebuild after search exception project=%s detail=%s",
                        project_id,
                        exc,
                    )
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
                        "metadata": _ltm_candidate_metadata(md),
                    }
                )
        ltm_count = len(results)

    try:
        qprev = (query or "")[:120].replace("\n", " ")
        logger.debug(
            "[CANONICAL_RETRIEVE] project_id=%s sources=%s per_source_k=%s daily_candidates=%s ltm_candidates=%s query_preview=\"%s\"",
            project_id,
            srcs,
            int(per_source_k),
            int(daily_count),
            int(ltm_count),
            qprev,
        )
    except Exception as exc:
        logger.debug("RAG: canonical retrieval debug logging failed project=%s detail=%s", project_id, exc)
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
    # All retrieval passes through canonical entry point (LTM-only here; embed-once).
    # Order candidates by raw similarity score before selection and assembly.
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

    # Build context with no token caps here; trimming/budgeting is deferred to selection policy.
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
    route: Optional[str] = None,
    per_source_k_override: Optional[int] = None,
) -> Dict[str, Any]:
    """Retrieve from daily and main, then apply positional truncation.

    Candidate ordering is by raw similarity score across all sources
    before selection/truncation/prompt assembly.

    Selection is score-gated and deterministic:
    - consume the globally ordered list
    - skip candidates whose score is not greater than route min_score
    - retain the first MAX_KEEP passing candidates
    - no reordering, boosting, or dedupe occurs here
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
            "selected_candidates": 0,
            "kept_candidates": 0,
            "expanded_unique_chunks_after_merge": 0,
        }
    min_score = 0.0
    try:
        from ..core.route_policy import get_route_policy

        policy = get_route_policy(route or "OTHER")
        min_score = float(getattr(policy, "min_score", 0.0) or 0.0)
    except Exception as exc:
        logger.warning(
            "RAG: failed resolving route min_score project=%s route=%s detail=%s",
            project_id,
            route or "OTHER",
            exc,
        )
        min_score = 0.0
    logger.debug(
        "DailyRAG: starting merged retrieval project=%s per_source_k=%s daily_enabled=%s max_keep=%s min_score=%.4f",
        project_id,
        int(per_source_k),
        str(bool(daily_enabled)).lower(),
        int(max_keep),
        float(min_score),
    )
    # Retrieval via canonical entry point (raw candidates; no thresholding/boosting here).
    sources = ["ltm"] + (["daily"] if bool(daily_enabled) else [])
    cands = canonical_retrieve_candidates(project_id, query, sources=sources, per_source_k_override=per_source_k)
    # Global ordering by raw similarity score (stable; ties preserve pre-sort order).
    ordered = order_candidates_by_similarity_score(list(cands or []))

    # Policy-driven selection with adjacent-chunk rule (effective limit can grow when we retain adjacent same-doc chunks).
    adjacent_bonus = 0
    kept_candidates = []
    effective_limit = int(max_keep)
    for c in list(ordered or []):
        if len(kept_candidates) >= effective_limit:
            break
        try:
            score = float(c.get("score") or 0.0)
        except (AttributeError, TypeError, ValueError):
            score = 0.0
        if score <= float(min_score):
            continue
        kept_candidates.append(c)
        if len(kept_candidates) >= 2:
            prev = kept_candidates[-2]
            md_prev = (prev.get("metadata") or {}) if isinstance(prev.get("metadata"), dict) else {}
            md_cur = (c.get("metadata") or {}) if isinstance(c.get("metadata"), dict) else {}
            sid_prev = md_prev.get("source_document_id")
            sid_cur = md_cur.get("source_document_id")
            if isinstance(sid_prev, str) and sid_prev == sid_cur:
                ci_prev = md_prev.get("chunk_index") if md_prev.get("chunk_index") is not None else md_prev.get("chunk_seq")
                ci_cur = md_cur.get("chunk_index") if md_cur.get("chunk_index") is not None else md_cur.get("chunk_seq")
                try:
                    a, b = int(ci_prev), int(ci_cur)
                    if abs(a - b) == 1:
                        effective_limit += 1
                        adjacent_bonus += 1
                except (TypeError, ValueError) as exc:
                    logger.debug(
                        "RAG: adjacent bonus check skipped due to invalid chunk index project=%s detail=%s",
                        project_id,
                        exc,
                    )
    selected_candidates = list(kept_candidates)

    # Rank-weighted adjacency expansion (materialized per-candidate; no dedupe, no token pruning).
    # This stage preserves kept candidate order and expands within the same source document only.
    try:
        from ..core.route_policy import get_route_policy
        from .daily_store import get_daily_source
    except Exception:
        get_route_policy = None  # type: ignore
        get_daily_source = None  # type: ignore

    # Route-derived expansion parameters (validated at startup).
    max_before = 0
    max_after = 0
    try:
        if get_route_policy is not None:
            pol = get_route_policy(route or "OTHER")
            max_before = int(getattr(pol, "expansion_max_before", 0) or 0)
            max_after = int(getattr(pol, "expansion_max_after", 0) or 0)
    except Exception:
        max_before, max_after = 0, 0

    # Best-effort check: LTM expansion is only allowed when the index supports adjacency and sidecar is valid.
    ltm_expand_ok = False
    try:
        faiss_dir = os.path.join(get_settings().memory_root, project_id, "faiss")
        manifest = _safe_load_json(os.path.join(faiss_dir, _LTM_MANIFEST_NAME))
        claims_adjacency_schema = bool(
            isinstance(manifest, dict) and manifest.get("schema_version") == _ADJACENCY_SCHEMA_VERSION
        )
        if claims_adjacency_schema:
            adj_name = manifest.get("adjacency_index") or _LTM_ADJACENCY_INDEX_NAME
            adj = _safe_load_json(os.path.join(faiss_dir, str(adj_name)))
            if isinstance(adj, dict) and adj.get("schema_version") == _ADJACENCY_SCHEMA_VERSION:
                ltm_expand_ok = True
            else:
                _schedule_ltm_rebuild(project_id, reason="a442_adjacency_missing_or_invalid")
                ltm_expand_ok = False
        else:
            # Legacy index format: expansion treated as disabled.
            ltm_expand_ok = False
    except Exception:
        ltm_expand_ok = False

    ltm_index = None
    try:
        if ltm_expand_ok and int(max_before) + int(max_after) > 0:
            ltm_index = load_faiss_index(project_id)
    except Exception:
        ltm_index = None

    daily_src = None
    try:
        if get_daily_source is not None and bool(daily_enabled) and int(max_before) + int(max_after) > 0:
            daily_src = get_daily_source(project_id)
    except Exception:
        daily_src = None

    def _tier_counts(i: int, k: int) -> tuple[int, int]:
        # Tiering by candidate rank (K is actual runtime len(kept_candidates)).
        if k <= 0:
            return 0, 0
        import math

        t1_end = int(math.ceil(k / 3.0))
        t2_end = int(math.ceil((2.0 * k) / 3.0))
        if i < t1_end:
            return int(max_before), int(max_after)
        if i < t2_end:
            return int(math.ceil(int(max_before) / 2.0)), int(math.ceil(int(max_after) / 2.0))
        return min(1, int(max_before)), min(1, int(max_after))

    def _materialize_candidate_chunks(i: int, k: int, c: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Structured expansion materialization.

        Returns ordered chunk objects in before…central…after order, with fields:
          - source_document_id
          - chunk_index
          - text

        This stage does not dedupe or mutate chunk text.
        """
        txt0 = (c.get("text") or "") if isinstance(c, dict) else ""
        src0 = (c.get("source") or "") if isinstance(c, dict) else ""
        md0 = (c.get("metadata") or {}) if isinstance(c.get("metadata"), dict) else {}
        doc_id_raw = md0.get("source_document_id") or md0.get("doc_id")
        source_document_id = str(doc_id_raw) if isinstance(doc_id_raw, str) else None
        chunk_idx_raw = md0.get("chunk_index") if md0.get("chunk_index") is not None else md0.get("chunk_seq")
        try:
            ci: Optional[int] = int(chunk_idx_raw)
        except Exception:
            ci = None

        central_chunk = {
            "source_document_id": source_document_id,
            "chunk_index": ci,
            "text": str(txt0 or ""),
        }

        # If identity/adjacency is unavailable, degrade to central-only.
        if ci is None:
            return [central_chunk]

        before_n, after_n = _tier_counts(int(i), int(k))
        if int(before_n) <= 0 and int(after_n) <= 0:
            return [central_chunk]

        # LTM: expand only when adjacency is available and doc_id is valid.
        if str(src0).lower() == "ltm":
            if not ltm_expand_ok or ltm_index is None or source_document_id is None:
                return [central_chunk]
            chunks_local: List[Dict[str, Any]] = []
            for seq in range(int(ci) - int(before_n), int(ci) + int(after_n) + 1):
                if int(seq) == int(ci):
                    chunks_local.append(central_chunk)
                    continue
                item_id = f"{source_document_id}::chunk={int(seq)}"
                ve = None
                try:
                    ve = ltm_index.get_by_id(str(item_id))  # type: ignore[union-attr]
                except Exception:
                    ve = None
                if ve is None:
                    # Non-fatal skip-neighbor event.
                    continue
                chunks_local.append(
                    {
                        "source_document_id": source_document_id,
                        "chunk_index": int(seq),
                        "text": str(ve.text or ""),
                    }
                )
            return chunks_local

        # Daily: expand only when daily cache/source is available.
        if str(src0).lower() == "daily":
            if daily_src is None:
                return [central_chunk]
            chunks_local: List[Dict[str, Any]] = []
            for seq in range(int(ci) - int(before_n), int(ci) + int(after_n) + 1):
                if int(seq) == int(ci):
                    chunks_local.append(central_chunk)
                    continue
                try:
                    eid = daily_src.id_by_seq.get(int(seq))  # type: ignore[union-attr]
                except Exception:
                    eid = None
                if not isinstance(eid, str) or not eid:
                    # Non-fatal skip-neighbor event.
                    continue
                try:
                    ve = daily_src.vs.get_by_id(str(eid))  # type: ignore[union-attr]
                except Exception:
                    ve = None
                if ve is None:
                    continue
                chunks_local.append(
                    {
                        "source_document_id": source_document_id,
                        "chunk_index": int(seq),
                        "text": str(ve.text or ""),
                    }
                )
            return chunks_local

        # Unknown source: central-only degrade.
        return [central_chunk]

    try:
        k_actual = int(len(kept_candidates or []))
        if k_actual > 0:
            for i, c in enumerate(list(kept_candidates)):
                if not isinstance(c, dict):
                    continue
                # Output artifact: per-candidate ordered chunk objects.
                chunks = _materialize_candidate_chunks(int(i), int(k_actual), c)
                c["expanded_chunks"] = chunks
                # Keep downstream prompt assembly compatible by materializing candidate text from chunks.
                c["text"] = "\n".join(str(ch.get("text") or "") for ch in chunks if isinstance(ch, dict))
    except Exception as exc:
        # Best-effort: never block retrieval/prompt assembly.
        logger.warning("RAG: failed materializing expanded chunks project=%s detail=%s", project_id, exc, exc_info=True)

    # Chunk identity dedupe (first-seen wins) over structured expansion output.
    # Operates in kept_candidates order, then per-candidate chunk order.
    dedupe_input_chunk_count = 0
    dedupe_unique_keyed_count = 0
    dedupe_duplicate_skipped_count = 0
    dedupe_sparse_preserved_count = 0
    dedupe_key_first_pos: Dict[Tuple[str, int], int] = {}
    dedupe_duplicate_events: List[Dict[str, Any]] = []
    dedupe_stream_pos = 0
    try:
        deduped_chunks: List[Dict[str, Any]] = []
        seen_keys: Set[Tuple[str, int]] = set()
        for c in list(kept_candidates or []):
            if not isinstance(c, dict):
                continue
            src = c.get("source")
            score = c.get("score")
            base_md = c.get("metadata") if isinstance(c.get("metadata"), dict) else {}
            expanded = c.get("expanded_chunks")
            chunks_list = expanded if isinstance(expanded, list) else []
            if not chunks_list:
                continue
            for ch in chunks_list:
                if not isinstance(ch, dict):
                    continue
                dedupe_stream_pos += 1
                dedupe_input_chunk_count += 1
                source_document_id = ch.get("source_document_id")
                chunk_index = ch.get("chunk_index")
                text = str(ch.get("text") or "")

                # Compatibility behavior: preserve sparse/legacy entries in-order.
                if not isinstance(source_document_id, str) or not isinstance(chunk_index, int):
                    dedupe_sparse_preserved_count += 1
                    md = dict(base_md)
                    md["source_document_id"] = source_document_id
                    md["chunk_index"] = chunk_index
                    deduped_chunks.append(
                        {
                            "source": src,
                            "score": score,
                            "text": text,
                            "metadata": md,
                        }
                    )
                    continue

                key = (str(source_document_id), int(chunk_index))
                if key in seen_keys:
                    dedupe_duplicate_skipped_count += 1
                    dedupe_duplicate_events.append(
                        {
                            "source_document_id": key[0],
                            "chunk_index": key[1],
                            "first_seen_pos": dedupe_key_first_pos.get(key),
                            "duplicate_pos": dedupe_stream_pos,
                        }
                    )
                    continue
                seen_keys.add(key)
                dedupe_key_first_pos[key] = dedupe_stream_pos
                dedupe_unique_keyed_count += 1
                md = dict(base_md)
                md["source_document_id"] = str(source_document_id)
                md["chunk_index"] = int(chunk_index)
                deduped_chunks.append(
                    {
                        "source": src,
                        "score": score,
                        "text": text,
                        "metadata": md,
                    }
                )
        kept_candidates = deduped_chunks
    except Exception as exc:
        # Best-effort: never block retrieval/prompt assembly.
        logger.warning("RAG: failed deduping expanded chunks project=%s detail=%s", project_id, exc, exc_info=True)

    # Source-document ordering and narrative coherence.
    # Extract sources (first-seen order); per source sort by chunk_index ascending; sparse chunks in first-seen order at end.
    try:
        by_source: Dict[str, List[Dict[str, Any]]] = {}
        source_order: List[str] = []
        sparse_chunks: List[Dict[str, Any]] = []
        for c in list(kept_candidates or []):
            if not isinstance(c, dict):
                continue
            md = c.get("metadata") if isinstance(c.get("metadata"), dict) else {}
            doc_id = md.get("source_document_id")
            chunk_idx = md.get("chunk_index")
            if isinstance(doc_id, str) and isinstance(chunk_idx, int):
                if doc_id not in by_source:
                    source_order.append(doc_id)
                    by_source[doc_id] = []
                by_source[doc_id].append(c)
            else:
                sparse_chunks.append(c)
        ordered_chunks_list: List[Dict[str, Any]] = []
        for doc_id in source_order:
            chunks = by_source.get(doc_id) or []
            def _chunk_index(c: Dict[str, Any]) -> int:
                try:
                    ci = (c.get("metadata") or {}).get("chunk_index")
                    return int(ci) if ci is not None else 0
                except (TypeError, ValueError):
                    return 0

            chunks = sorted(chunks, key=_chunk_index)
            ordered_chunks_list.extend(chunks)
        ordered_chunks_list.extend(sparse_chunks)
        kept_candidates = ordered_chunks_list
    except Exception as exc:
        # Best-effort: never block retrieval/prompt assembly.
        logger.warning("RAG: failed ordering deduped chunks project=%s detail=%s", project_id, exc, exc_info=True)

    # Adjacent chunk overlap trimming (in-place; same-doc consecutive pairs only).
    try:
        settings = get_settings()
        trim_adjacent_chunk_overlap(
            kept_candidates or [],
            int(settings.chunk_overlap),
        )
    except Exception as exc:
        # Best-effort: never block retrieval/prompt assembly.
        logger.warning("RAG: failed trimming adjacent overlap project=%s detail=%s", project_id, exc, exc_info=True)

    # Snippet-group collapse (one entry per adjacent same-document run).
    try:
        kept_candidates = collapse_snippet_groups(kept_candidates or [])
    except Exception as exc:
        # Best-effort: never block retrieval/prompt assembly.
        logger.warning("RAG: failed collapsing snippet groups project=%s detail=%s", project_id, exc, exc_info=True)

    # Debug dumps (human-readable .txt) for ordering and selection.
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
                    f"# min_score: {float(min_score):.4f}",
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

            def _fmt_expansion_plan(items: List[Dict[str, Any]]) -> str:
                """
                Human-readable expansion plan dump:
                shows per-candidate requested ranges and which neighbors were materialized.
                """
                k_actual = int(len(items or []))
                lines = [
                    f"# timestamp: {ts}",
                    f"# project_id: {project_id}",
                    f"# route: {(route or 'OTHER')}",
                    f"# query_preview: {qprev}",
                    f"# per_source_k: {int(per_source_k)}",
                    f"# max_keep: {int(max_keep)}",
                    f"# min_score: {float(min_score):.4f}",
                    f"# kept: {k_actual}  adjacent_bonus: {int(adjacent_bonus)}",
                    f"# daily_enabled: {str(bool(daily_enabled)).lower()}",
                    f"# expansion.max_before: {int(max_before)}",
                    f"# expansion.max_after: {int(max_after)}",
                    f"# ltm_expand_ok: {str(bool(ltm_expand_ok)).lower()}",
                    f"# daily_cache_available: {str(bool(daily_src is not None)).lower()}",
                    "",
                    "====== EXPANSION_PLAN ======",
                    "",
                ]
                for rank, c in enumerate(items, start=1):
                    md = c.get("metadata") if isinstance(c.get("metadata"), dict) else {}
                    src = str(c.get("source") or "unknown").lower()
                    score = c.get("score")
                    doc_id = md.get("source_document_id") or md.get("doc_id")
                    chunk_idx = md.get("chunk_index") if md.get("chunk_index") is not None else md.get("chunk_seq")
                    fname = md.get("filename")
                    try:
                        ci = int(chunk_idx)
                    except Exception:
                        ci = None

                    before_n, after_n = _tier_counts(int(rank - 1), int(k_actual))
                    if ci is None or not isinstance(doc_id, str) or (before_n <= 0 and after_n <= 0):
                        lines.append(
                            f"{rank:>3}. source={src} score={score} source_document_id={doc_id} chunk_index={chunk_idx} file={fname} tier_before={before_n} tier_after={after_n}"
                        )
                        lines.append("     materialized: central_only_or_unavailable")
                        continue

                    seqs = list(range(int(ci) - int(before_n), int(ci) + int(after_n) + 1))
                    mat: List[str] = []
                    missing: List[str] = []

                    if src == "ltm" and ltm_index is not None and bool(ltm_expand_ok):
                        for s in seqs:
                            if int(s) == int(ci):
                                mat.append(f"{s}(central)")
                                continue
                            item_id = f"{doc_id}::chunk={int(s)}"
                            try:
                                ve = ltm_index.get_by_id(str(item_id))  # type: ignore[union-attr]
                            except Exception:
                                ve = None
                            if ve is None:
                                missing.append(str(s))
                            else:
                                mat.append(str(s))
                    elif src == "daily" and daily_src is not None:
                        for s in seqs:
                            if int(s) == int(ci):
                                mat.append(f"{s}(central)")
                                continue
                            try:
                                eid = daily_src.id_by_seq.get(int(s))  # type: ignore[union-attr]
                            except Exception:
                                eid = None
                            if not isinstance(eid, str) or not eid:
                                missing.append(str(s))
                                continue
                            try:
                                ve = daily_src.vs.get_by_id(str(eid))  # type: ignore[union-attr]
                            except Exception:
                                ve = None
                            if ve is None:
                                missing.append(str(s))
                            else:
                                mat.append(str(s))
                    else:
                        mat.append(f"{int(ci)}(central)")

                    lines.append(
                        f"{rank:>3}. source={src} score={score} source_document_id={doc_id} chunk_index={ci} file={fname} tier_before={before_n} tier_after={after_n} requested_range=[{seqs[0]}..{seqs[-1]}]"
                    )
                    lines.append(f"     materialized_seqs: {', '.join(mat) if mat else '(none)'}")
                    if missing:
                        lines.append(f"     missing_seqs: {', '.join(missing)}")
                lines.append("")
                return "\n".join(lines)

            def _fmt_deduped_chunks_with_audit(items: List[Dict[str, Any]]) -> str:
                """Chunk list plus audit summary and duplicate_events (same file)."""
                chunk_section = _fmt_list("DEDUPED_CHUNKS", items)
                audit_lines = [
                    "",
                    "====== DEDUPE_AUDIT ======",
                    "",
                    f"input_chunks: {int(dedupe_input_chunk_count)}",
                    f"unique_keyed_chunks_kept: {int(dedupe_unique_keyed_count)}",
                    f"duplicate_keyed_chunks_skipped: {int(dedupe_duplicate_skipped_count)}",
                    f"sparse_or_legacy_chunks_preserved: {int(dedupe_sparse_preserved_count)}",
                    f"final_output_chunks: {int(len(items or []))}",
                    "",
                    "---- duplicate_events (first-seen wins) ----",
                ]
                if not dedupe_duplicate_events:
                    audit_lines.append("(none)")
                else:
                    for i, ev in enumerate(dedupe_duplicate_events, start=1):
                        audit_lines.append(
                            f"{i:>3}. source_document_id={ev.get('source_document_id')} chunk_index={ev.get('chunk_index')} "
                            f"first_seen_pos={ev.get('first_seen_pos')} duplicate_pos={ev.get('duplicate_pos')}"
                        )
                audit_lines.append("")
                return chunk_section + "\n".join(audit_lines)

            write_debug_file(
                project_id,
                f"rag/retrieval/{ts}_ordered_candidates.txt",
                _fmt_list("ORDERED_CANDIDATES", ordered),
            )
            write_debug_file(
                project_id,
                f"rag/retrieval/{ts}_kept_candidates.txt",
                _fmt_list("KEPT_CANDIDATES", selected_candidates),
            )
            write_debug_file(
                project_id,
                f"rag/retrieval/{ts}_expansion_plan.txt",
                _fmt_expansion_plan(selected_candidates),
            )
            write_debug_file(
                project_id,
                f"rag/retrieval/{ts}_deduped_chunks.txt",
                _fmt_deduped_chunks_with_audit(kept_candidates),
            )
    except Exception as exc:
        logger.warning("RAG: failed writing retrieval debug artifacts project=%s detail=%s", project_id, exc, exc_info=True)

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

        extra_header_fields = _snippet_header_metadata_fields(md)
        extra_header = "".join(f", {key}={value}" for key, value in extra_header_fields)
        # Candidate header (keeps ordering explicit; show cos + score for troubleshooting).
        if src == "ltm":
            chunk_index = md.get("chunk_index") if isinstance(md, dict) else None
            header = (
                f"Snippet {idx+1} (source=ltm, cos={cos:.4f}, score={score01:.4f}, file={md.get('filename')}, page={md.get('page_number')}, chunk_index={chunk_index}{extra_header})\n"
            )
        else:
            chunk_index = md.get("chunk_index") if isinstance(md, dict) else None
            header = f"Snippet {idx+1} (source=daily, cos={cos:.4f}, score={score01:.4f}, route={md.get('route')}, chunk_index={chunk_index}{extra_header})\n"
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
    try:
        get_instrumentation().record_stage(
            "retrieval_selection_expansion",
            {
                "project_id": project_id,
                "route": route or "OTHER",
                "daily_enabled": bool(daily_enabled),
                "per_source_k": int(per_source_k),
                "max_keep": int(max_keep),
                "min_score": float(min_score),
                "ordered_candidates": int(len(ordered)),
                "selected_candidates": int(len(selected_candidates)),
                "kept_candidates": int(len(pieces)),
                "expanded_unique_chunks_after_merge": int(dedupe_unique_keyed_count),
                "adjacent_bonus": int(adjacent_bonus),
                "main_hits": int(main_hits),
                "daily_hits": int(daily_hits),
                "total_hits": int(main_hits + daily_hits),
                "tokens_used": int(tokens_used_total),
            },
        )
    except Exception as exc:
        logger.warning(
            "RAG: instrumentation stage record failed project=%s op=retrieval_selection_expansion detail=%s",
            project_id,
            exc,
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
        "selected_candidates": int(len(selected_candidates)),
        "kept_candidates": int(len(pieces)),
        "expanded_unique_chunks_after_merge": int(dedupe_unique_keyed_count),
        "min_score": float(min_score),
    }


def _snippet_header_metadata_fields(metadata: Dict[str, Any]) -> List[Tuple[str, str]]:
    keys = (
        "memory_id",
        "source_document_id",
        "artifact_path",
        "entry_type",
        "source_agent",
        "source_scope",
        "current_scope",
        "semantic_handle",
    )
    fields: List[Tuple[str, str]] = []
    for key in keys:
        value = metadata.get(key) if isinstance(metadata, dict) else None
        if value is None:
            continue
        rendered = str(value).replace("\n", " ").replace(",", ";").strip()
        if rendered:
            fields.append((key, rendered))
    return fields


# Legacy FAISS sidecar namespace map support removed; namespaces are embedded during indexing.


