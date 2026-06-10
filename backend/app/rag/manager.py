"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
RAG manager for building FAISS indices per project.

Policy:
- Embedding model: text-embedding-3-large (configurable)
- Chunking: RecursiveCharacterTextSplitter(size=chunk_size, overlap=chunk_overlap)
- Metadata per chunk: project_id, filename, page_number (if pdf), chunk_id, timestamp
- Recreate FAISS index per upload (fresh build from uploads dir)
"""

import logging
import math
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple, cast

import faiss  # type: ignore
import numpy as np  # type: ignore

from ..core.config import compute_per_source_k, get_active_embedding_model, get_settings

logger = logging.getLogger(__name__)
from ..core.retrieval_ordering import order_candidates_by_similarity_score
from ..embedding.factory import get_embedding_client
from ..embedding.vector_index import VectorEntry, VectorHit, VectorIndexInfo
from ..tracking import get_instrumentation
from ..utils.debug_utils import write_debug_file
from .chunk_utils import collapse_snippet_groups, trim_adjacent_chunk_overlap
from .manager_index_io import ADJACENCY_SCHEMA_VERSION as _ADJACENCY_SCHEMA_VERSION
from .manager_index_io import LTM_ADJACENCY_INDEX_NAME as _LTM_ADJACENCY_INDEX_NAME
from .manager_index_io import LTM_DOCSTORE_NAME as _LTM_DOCSTORE_NAME
from .manager_index_io import LTM_INDEX_FILE_NAME as _LTM_INDEX_FILE_NAME
from .manager_index_io import LTM_INDEX_TO_ID_NAME as _LTM_INDEX_TO_ID_NAME
from .manager_index_io import LTM_MANIFEST_NAME as _LTM_MANIFEST_NAME
from .manager_index_io import cosine_to_01 as _cosine_to_01
from .manager_index_io import normalize_rows as _normalize_rows
from .manager_index_io import safe_load_json as _safe_load_json
from .manager_rebuild import count_tokens as _count_tokens
from .manager_rebuild import rebuild_faiss_index

_LTM_REBUILDING: Set[str] = set()
_LTM_REBUILD_LOCK = threading.Lock()


def _schedule_ltm_rebuild(project_id: str, reason: str) -> None:
    """Schedule a best-effort background rebuild of a project's LTM index.

    De-duplicated per project so a rebuild already in flight is not started again;
    the current request never retries. Scheduling and rebuild failures are logged
    at warning level.

    Args:
        project_id: Project whose FAISS index should be rebuilt off-thread.
        reason: Short reason recorded in logs for diagnostics.
    """
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
    except Exception as exc:  # pragma: no cover - defensive guard around lock/thread setup
        logger.warning(
            "RAG: failed scheduling LTM rebuild; operation=_schedule_ltm_rebuild project_id=%s reason=%s detail=%s",
            project_id,
            reason,
            exc,
        )


class LTMIndex:
    """In-memory wrapper over a persisted long-term-memory FAISS index.

    Holds the raw FAISS ``IndexFlatIP`` together with its row->item_id mapping and
    docstore, and exposes cosine-mapped similarity search over stored chunks.
    """

    def __init__(
        self,
        *,
        index: faiss.IndexFlatIP,
        index_to_id: List[str],
        docstore: Dict[str, Dict[str, Any]],
        built_at: Optional[str],
        schema_version: Optional[str],
    ):
        """Wrap a loaded FAISS index with its id mapping and docstore.

        Args:
            index: The raw FAISS ``IndexFlatIP`` over unit-normalized vectors.
            index_to_id: Row-ordered list mapping FAISS rows to item ids.
            docstore: Map of item_id to ``{text, metadata}`` entries.
            built_at: Optional manifest build timestamp for diagnostics.
            schema_version: Optional manifest schema version for diagnostics.
        """
        self.index = index
        self.index_to_id = index_to_id
        self.docstore = docstore
        self._built_at = built_at
        self._schema_version = schema_version

    def size(self) -> int:
        """Return the number of vectors held by the index."""
        return int(self.index.ntotal)

    def info(self) -> VectorIndexInfo:
        """Return descriptive metadata about this index (kind, dim, score mode)."""
        return VectorIndexInfo(
            index_kind="ltm",
            dim=int(self.index.d),
            score_mode="cosine_ip_mapped_01",
            built_at=self._built_at,
            schema_version=self._schema_version,
        )

    def get_by_id(self, item_id: str) -> Optional[VectorEntry]:
        """Return the stored entry for an item_id, or None if absent/malformed.

        Args:
            item_id: Docstore key to look up.

        Returns:
            The ``VectorEntry`` (text + metadata), or None when the id is unknown
            or the stored shape is malformed.
        """
        try:
            entry = self.docstore.get(str(item_id))
            if not isinstance(entry, dict):
                return None
            txt = entry.get("text") if isinstance(entry.get("text"), str) else ""
            md = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
            return VectorEntry(text=txt or "", metadata=md)
        except Exception:  # pragma: no cover - defensive guard around malformed docstore entries
            return None

    def search_by_vector(self, qvec_norm: np.ndarray, *, k: int) -> List[VectorHit]:
        """Search for the top-k nearest entries to a unit-normalized query vector.

        Args:
            qvec_norm: Unit-normalized query embedding.
            k: Maximum number of hits to return.

        Returns:
            Hits ordered by FAISS, each carrying the raw inner product and a
            cosine-to-[0,1] mapped score. Returns an empty list for an empty index.
        """
        if int(self.index.ntotal) <= 0:
            return []
        q = np.array([qvec_norm], dtype="float32")
        D, I = self.index.search(q, k=int(k))
        out: List[VectorHit] = []
        for idx, ip in zip(I[0].tolist(), D[0].tolist(), strict=False):
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
    """Load a project's persisted FAISS index, docstore, and id map.

    Validates the adjacency sidecar against the manifest and current chunking
    settings, scheduling a background rebuild (best-effort) when adjacency is
    expected but missing/invalid or chunk params changed since build.

    Args:
        project_id: Project whose persisted index is loaded.

    Returns:
        An ``LTMIndex`` when a non-empty, well-formed index exists; None when the
        directory/files are missing, the index is empty, or loading fails.
    """
    settings = get_settings()
    faiss_dir = os.path.join(get_settings().memory_root, project_id, "faiss")
    if not os.path.isdir(faiss_dir):
        logger.debug(f"RAG: index directory missing for project '{project_id}' at {faiss_dir}")
        return None
    try:
        idx_path = os.path.join(faiss_dir, _LTM_INDEX_FILE_NAME)
        ids_path = os.path.join(faiss_dir, _LTM_INDEX_TO_ID_NAME)
        ds_path = os.path.join(faiss_dir, _LTM_DOCSTORE_NAME)
        if (
            not os.path.isfile(idx_path)
            or not os.path.isfile(ids_path)
            or not os.path.isfile(ds_path)
        ):
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
                isinstance(manifest, dict)
                and manifest.get("schema_version") == _ADJACENCY_SCHEMA_VERSION
            )
            if claims_adjacency_schema:
                # Invalidate adjacency (trigger background rebuild) if chunking params changed since build.
                try:
                    built_cs = (
                        int(manifest.get("chunk_size"))
                        if manifest.get("chunk_size") is not None
                        else None
                    )
                    built_co = (
                        int(manifest.get("chunk_overlap"))
                        if manifest.get("chunk_overlap") is not None
                        else None
                    )
                except Exception:  # pragma: no cover - malformed manifest ints
                    built_cs, built_co = None, None
                if built_cs != int(settings.chunk_size) or built_co != int(settings.chunk_overlap):
                    _schedule_ltm_rebuild(project_id, reason="a441_chunk_params_mismatch")
                else:
                    adj_name = manifest.get("adjacency_index") or _LTM_ADJACENCY_INDEX_NAME
                    adj_path = os.path.join(faiss_dir, str(adj_name))
                    adj_obj = _safe_load_json(adj_path)
                    # If missing/invalid, rebuild when adjacency is expected. Legacy absence is expected.
                    if (
                        not isinstance(adj_obj, dict)
                        or adj_obj.get("schema_version") != _ADJACENCY_SCHEMA_VERSION
                    ):
                        _schedule_ltm_rebuild(
                            project_id, reason="a441_adjacency_missing_or_invalid"
                        )
        except Exception as exc:  # pragma: no cover - best-effort adjacency validation
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
                built_at = (
                    manifest.get("built_at") if isinstance(manifest.get("built_at"), str) else None
                )
                schema_version = (
                    manifest.get("schema_version")
                    if isinstance(manifest.get("schema_version"), str)
                    else None
                )
        except Exception as exc:  # pragma: no cover - best-effort optional manifest metadata read
            logger.debug(
                "RAG: failed loading optional manifest metadata project=%s detail=%s",
                project_id,
                exc,
            )
        logger.debug(f"RAG: loaded index for '{project_id}' with {int(index.ntotal)} vectors")
        return LTMIndex(
            index=index,
            index_to_id=index_to_id,
            docstore=docstore,
            built_at=built_at,
            schema_version=schema_version,
        )
    except (OSError, ValueError, TypeError) as e:  # pragma: no cover - corrupt index files
        logger.debug(f"RAG: failed to load index for '{project_id}': {e}")
        return None


def ltm_lookup_adjacent_docstore_ids(
    project_id: str,
    *,
    doc_id: str,
    chunk_seq: int,
) -> Dict[str, Optional[str]]:
    """Look up the deterministic neighbors of an LTM chunk via the adjacency sidecar.

    Schedules a background rebuild when adjacency is expected but the sidecar is
    missing/invalid or malformed.

    Args:
        project_id: Project whose adjacency sidecar is consulted.
        doc_id: Source document id whose ordered chunk list is indexed.
        chunk_seq: 0-based position of the central chunk within the document.

    Returns:
        A dict with ``prev_docstore_id`` and ``next_docstore_id``; both are None
        when adjacency is unavailable (legacy index, missing/corrupt sidecar) or
        the neighbor falls outside the document range.
    """
    faiss_dir = os.path.join(get_settings().memory_root, project_id, "faiss")
    manifest = _safe_load_json(os.path.join(faiss_dir, _LTM_MANIFEST_NAME))
    claims_adjacency_schema = bool(
        isinstance(manifest, dict) and manifest.get("schema_version") == _ADJACENCY_SCHEMA_VERSION
    )
    if not claims_adjacency_schema:
        return {"prev_docstore_id": None, "next_docstore_id": None}

    adj_name = (
        manifest.get("adjacency_index") if isinstance(manifest, dict) else None
    ) or _LTM_ADJACENCY_INDEX_NAME
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
    """Fetch a stored LTM chunk by its docstore id.

    Args:
        project_id: Project whose index is loaded.
        docstore_id: Docstore key of the chunk to fetch.

    Returns:
        A ``{text, metadata}`` dict, or None when the index/entry is missing or
        malformed.
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
    except Exception:  # pragma: no cover - defensive guard around malformed docstore entry
        return None


def _ltm_candidate_metadata(md: Dict[str, Any]) -> Dict[str, Any]:
    """Project raw docstore metadata into the canonical candidate metadata shape.

    Normalizes adjacency identity (``source_document_id``/``chunk_index``) from
    legacy fallbacks and retains the downstream/telemetry fields used during
    selection and prompt assembly. Missing fields are preserved as None.

    Args:
        md: Raw chunk metadata from the docstore.

    Returns:
        A new metadata dict with the canonical candidate fields populated.
    """
    source_document_id = md.get("source_document_id") or md.get("doc_id")
    chunk_index = (
        md.get("chunk_index") if md.get("chunk_index") is not None else md.get("chunk_seq")
    )
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
    """Retrieve raw candidate chunks across the requested sources.

    Computes the query embedding exactly once and reuses it across all queried
    sources. No thresholding, boosting, or route-based eligibility pruning occurs
    here; scores are cosine similarity mapped to [0.0, 1.0]. On error querying a
    source, a best-effort rebuild/repair is triggered (where applicable) and that
    source contributes no candidates for the current request (no retry).

    Args:
        project_id: Project to retrieve from.
        query: Natural-language query; embedded once and shared.
        sources: Source names to query (subset of ``daily``/``ltm``); defaults to
            both.
        per_source_k_override: Per-source K to use instead of the computed
            default; a value <= 0 skips retrieval entirely.

    Returns:
        A flat list of candidate dicts, each with ``source``, ``text``, ``score``,
        and ``metadata``. Empty when K <= 0 or the query cannot be embedded.
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
        logger.warning(
            "RAG: failed to embed query for canonical retrieval project=%s: %s", project_id, e
        )
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
                    logger.warning(
                        "RAG: Daily candidate search failed project=%s: %s", project_id, e
                    )
                    notify_daily_search_failure(
                        project_id, reason="canonical_daily_search_exception"
                    )
                    results = []
                for hit in results:
                    score01 = float(hit.score01)
                    md = hit.entry.metadata if isinstance(hit.entry.metadata, dict) else {}
                    eid = md.get("daily_entry_id")
                    entry = None
                    try:
                        if eid is not None:
                            entry = ds.meta_by_id.get(str(eid))
                    except Exception:  # pragma: no cover - defensive guard around meta lookup
                        entry = None
                    # Authoritative from daily.json when available; otherwise best-effort from doc metadata.
                    if isinstance(entry, dict):
                        created_at = entry.get("created_at")
                        route = None
                        tags_meta = (
                            entry.get("tags_meta")
                            if isinstance(entry.get("tags_meta"), dict)
                            else None
                        )
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
                                    "route": (
                                        str(route).lower() if isinstance(route, str) else route
                                    ),
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
                                    "chunk_seq": (
                                        md.get("chunk_seq") if isinstance(md, dict) else None
                                    ),
                                    "source_document_id": "daily",
                                    "chunk_index": (
                                        md.get("chunk_seq") if isinstance(md, dict) else None
                                    ),
                                },
                            }
                        )
                daily_count = len(results)
        except Exception:  # pragma: no cover - defensive guard; daily owns rebuild semantics
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
                    logger.warning(
                        "RAG: LTM candidate search failed project=%s; scheduling rebuild: %s",
                        project_id,
                        e,
                    )
                    _schedule_ltm_rebuild(project_id, reason="canonical_ltm_search_exception")
                except Exception as exc:  # pragma: no cover - defensive nested guard
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
            '[CANONICAL_RETRIEVE] project_id=%s sources=%s per_source_k=%s daily_candidates=%s ltm_candidates=%s query_preview="%s"',
            project_id,
            srcs,
            int(per_source_k),
            int(daily_count),
            int(ltm_count),
            qprev,
        )
    except Exception as exc:  # pragma: no cover - best-effort debug logging guard
        logger.debug(
            "RAG: canonical retrieval debug logging failed project=%s detail=%s", project_id, exc
        )
    return out


def retrieve_context(
    project_id: str,
    query: str,
    score_threshold: float,
) -> Dict[str, Any]:
    """Retrieve top-k LTM snippets and assemble a single Context: block string.

    Orders LTM candidates by raw similarity, applies the cosine threshold, and
    builds a ``Context:`` block. When nothing passes the threshold, the
    best-scoring snippet is included as a labeled fallback.

    Args:
        project_id: Project to retrieve from.
        query: Natural-language query.
        score_threshold: Minimum cosine score for a snippet to be selected; below
            this, only the fallback snippet (if any) is returned.

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
        # Unreachable in practice: a non-empty `ltm` always populates `scored`,
        # so the fallback above fires. Kept as a defensive contract guarantee.
        logger.debug(  # pragma: no cover - unreachable defensive guard
            "RAG: no snippets selected and no fallback available"
        )
        return {  # pragma: no cover - unreachable defensive guard
            "context_text": "",
            "snippets": [],
            "tokens_used": 0,
            "hit_count": len(passed_cosines),
            "hit_avg": (sum(passed_cosines) / len(passed_cosines) if passed_cosines else 0.0),
            "hits": [],
        }

    # Build hits metadata aligned with pieces
    hits = []
    for content, meta, score in filtered[: len(pieces)]:
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


@dataclass
class _ExpansionResources:
    """Resources needed to expand kept candidates into adjacency windows.

    Attributes:
        max_before: Route-derived maximum neighbors to expand before a chunk.
        max_after: Route-derived maximum neighbors to expand after a chunk.
        ltm_expand_ok: Whether the LTM index/sidecar support adjacency expansion.
        ltm_index: Loaded LTM index used for neighbor lookups (or ``None``).
        daily_src: Daily source providing sequence/vector lookups (or ``None``).
    """

    max_before: int
    max_after: int
    ltm_expand_ok: bool
    ltm_index: Optional["LTMIndex"]
    daily_src: Any


@dataclass
class _DedupeAudit:
    """Counters and events produced by chunk-identity dedupe.

    Attributes:
        input_chunk_count: Chunks examined before dedupe.
        unique_keyed_count: Distinct ``(source_document_id, chunk_index)`` keys
            kept.
        duplicate_skipped_count: Chunks dropped as duplicates of a kept key.
        sparse_preserved_count: Chunks without a usable key, preserved as-is.
        key_first_pos: First output position seen for each chunk key.
        duplicate_events: Per-duplicate diagnostic records for debug dumps.
    """

    input_chunk_count: int = 0
    unique_keyed_count: int = 0
    duplicate_skipped_count: int = 0
    sparse_preserved_count: int = 0
    key_first_pos: Dict[Tuple[str, int], int] = field(default_factory=dict)
    duplicate_events: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class _PromptAssembly:
    """Result of assembling kept chunks into a prompt ``Context:`` block.

    Attributes:
        context_text: The rendered context block injected into the prompt.
        daily_texts: Snippet texts sourced from Daily memory.
        main_texts: Snippet texts sourced from the main (LTM) index.
        main_scores: Mapped scores aligned with ``main_texts``.
        daily_scores: Mapped scores aligned with ``daily_texts``.
        tokens_used: Token count of ``context_text``.
    """

    context_text: str
    daily_texts: List[str]
    main_texts: List[str]
    main_scores: List[float]
    daily_scores: List[float]
    tokens_used: int


def _resolve_route_min_score(project_id: str, route: Optional[str]) -> float:
    """Resolve the route's ``min_score`` gate, defaulting to ``0.0`` on failure.

    Args:
        project_id: Project id used for log context.
        route: Route name; ``None`` resolves to ``OTHER``.

    Returns:
        The route's ``min_score`` as a float, or ``0.0`` when resolution fails.
    """
    try:
        from ..core.route_policy import get_route_policy

        policy = get_route_policy(route or "OTHER")
        return float(getattr(policy, "min_score", 0.0) or 0.0)
    except Exception as exc:
        logger.warning(
            "RAG: failed resolving route min_score project=%s route=%s detail=%s",
            project_id,
            route or "OTHER",
            exc,
        )
        return 0.0


def _select_score_gated_candidates(
    ordered: List[Dict[str, Any]],
    *,
    max_keep: int,
    min_score: float,
    project_id: str,
) -> Tuple[List[Dict[str, Any]], int]:
    """Select the top score-passing candidates with an adjacent same-doc bonus.

    Consumes the globally ordered list, skipping any candidate whose score is
    not greater than ``min_score`` and stopping at the effective limit. The
    limit grows by one each time a retained candidate is an adjacent chunk
    (``|chunk_index delta| == 1``) of the same source document as the prior
    retained candidate.

    Args:
        ordered: Candidates pre-ordered by descending similarity score.
        max_keep: Base cap on retained candidates.
        min_score: Exclusive score threshold; candidates ``<= min_score`` skip.
        project_id: Project id used for log context.

    Returns:
        A tuple ``(selected_candidates, adjacent_bonus)``.
    """
    adjacent_bonus = 0
    kept_candidates: List[Dict[str, Any]] = []
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
                ci_prev = (
                    md_prev.get("chunk_index")
                    if md_prev.get("chunk_index") is not None
                    else md_prev.get("chunk_seq")
                )
                ci_cur = (
                    md_cur.get("chunk_index")
                    if md_cur.get("chunk_index") is not None
                    else md_cur.get("chunk_seq")
                )
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
    return kept_candidates, adjacent_bonus


def _resolve_expansion_resources(
    project_id: str,
    route: Optional[str],
    daily_enabled: bool,
) -> _ExpansionResources:
    """Resolve route expansion limits and load adjacency sources (best-effort).

    Determines the route's before/after expansion budget, validates the LTM
    adjacency sidecar (scheduling a rebuild when it is missing/invalid), and
    lazily loads the LTM index and Daily source only when expansion is enabled.

    Args:
        project_id: Project being retrieved from.
        route: Route name used to look up expansion limits.
        daily_enabled: Whether the Daily source participates in expansion.

    Returns:
        An ``_ExpansionResources`` describing the available expansion budget and
        loaded sources.
    """
    try:
        from ..core.route_policy import get_route_policy
        from .daily_store import get_daily_source
    except Exception:  # pragma: no cover - import-time guard; modules always present
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
    except Exception:  # pragma: no cover - defensive guard around route policy lookup
        max_before, max_after = 0, 0

    # Best-effort check: LTM expansion is only allowed when the index supports adjacency and sidecar is valid.
    ltm_expand_ok = False
    try:
        faiss_dir = os.path.join(get_settings().memory_root, project_id, "faiss")
        manifest = _safe_load_json(os.path.join(faiss_dir, _LTM_MANIFEST_NAME))
        claims_adjacency_schema = bool(
            isinstance(manifest, dict)
            and manifest.get("schema_version") == _ADJACENCY_SCHEMA_VERSION
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
    except Exception:  # pragma: no cover - defensive guard around sidecar validation
        ltm_expand_ok = False

    ltm_index = None
    try:
        if ltm_expand_ok and int(max_before) + int(max_after) > 0:
            ltm_index = load_faiss_index(project_id)
    except Exception:  # pragma: no cover - defensive guard around index load
        ltm_index = None

    daily_src = None
    try:
        if (
            get_daily_source is not None
            and bool(daily_enabled)
            and int(max_before) + int(max_after) > 0
        ):
            daily_src = get_daily_source(project_id)
    except Exception:  # pragma: no cover - defensive guard around daily source load
        daily_src = None

    return _ExpansionResources(
        max_before=int(max_before),
        max_after=int(max_after),
        ltm_expand_ok=bool(ltm_expand_ok),
        ltm_index=ltm_index,
        daily_src=daily_src,
    )


def _expansion_tier_counts(i: int, k: int, max_before: int, max_after: int) -> Tuple[int, int]:
    """Compute the before/after expansion budget for a candidate by rank tier.

    Splits the kept candidates into thirds: the top tier gets the full
    ``max_before``/``max_after`` budget, the middle tier half (rounded up), and
    the bottom tier at most one neighbor on each side.

    Args:
        i: 0-based rank of the candidate within the kept list.
        k: Total number of kept candidates.
        max_before: Maximum neighbors to expand before a chunk.
        max_after: Maximum neighbors to expand after a chunk.

    Returns:
        A ``(before_n, after_n)`` neighbor budget; ``(0, 0)`` when ``k <= 0``.
    """
    if k <= 0:
        return 0, 0
    t1_end = int(math.ceil(k / 3.0))
    t2_end = int(math.ceil((2.0 * k) / 3.0))
    if i < t1_end:
        return int(max_before), int(max_after)
    if i < t2_end:
        return int(math.ceil(int(max_before) / 2.0)), int(math.ceil(int(max_after) / 2.0))
    return min(1, int(max_before)), min(1, int(max_after))


def _materialize_candidate_chunks(
    i: int,
    k: int,
    c: Dict[str, Any],
    *,
    resources: _ExpansionResources,
) -> List[Dict[str, Any]]:
    """Materialize a candidate's expansion window as ordered chunk objects.

    Expands within the same source document only, honoring the route-tiered
    neighbor budget and source-specific adjacency (LTM sidecar or Daily sequence
    map). Degrades to central-only when identity/adjacency is unavailable. This
    stage does not dedupe or mutate chunk text.

    Args:
        i: 0-based rank of the candidate within the kept list (drives tiering).
        k: Total number of kept candidates.
        c: The candidate dict (``text``/``source``/``metadata``).
        resources: Expansion budget and loaded adjacency sources.

    Returns:
        Ordered chunk dicts in before…central…after order, each with
        ``source_document_id``, ``chunk_index``, and ``text``.
    """
    txt0 = (c.get("text") or "") if isinstance(c, dict) else ""
    src0 = (c.get("source") or "") if isinstance(c, dict) else ""
    md0 = (c.get("metadata") or {}) if isinstance(c.get("metadata"), dict) else {}
    doc_id_raw = md0.get("source_document_id") or md0.get("doc_id")
    source_document_id = str(doc_id_raw) if isinstance(doc_id_raw, str) else None
    chunk_idx_raw = (
        md0.get("chunk_index") if md0.get("chunk_index") is not None else md0.get("chunk_seq")
    )
    try:
        ci: Optional[int] = int(chunk_idx_raw)
    except (TypeError, ValueError):
        ci = None

    central_chunk = {
        "source_document_id": source_document_id,
        "chunk_index": ci,
        "text": str(txt0 or ""),
    }

    # If identity/adjacency is unavailable, degrade to central-only.
    if ci is None:
        return [central_chunk]

    before_n, after_n = _expansion_tier_counts(
        int(i), int(k), resources.max_before, resources.max_after
    )
    if int(before_n) <= 0 and int(after_n) <= 0:
        return [central_chunk]

    # LTM: expand only when adjacency is available and doc_id is valid.
    if str(src0).lower() == "ltm":
        if not resources.ltm_expand_ok or resources.ltm_index is None or source_document_id is None:
            return [central_chunk]
        chunks_local: List[Dict[str, Any]] = []
        for seq in range(int(ci) - int(before_n), int(ci) + int(after_n) + 1):
            if int(seq) == int(ci):
                chunks_local.append(central_chunk)
                continue
            item_id = f"{source_document_id}::chunk={int(seq)}"
            ve = None
            try:
                ve = resources.ltm_index.get_by_id(str(item_id))  # type: ignore[union-attr]
            except Exception:  # pragma: no cover - defensive guard around neighbor lookup
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
        if resources.daily_src is None:
            return [central_chunk]
        chunks_local: List[Dict[str, Any]] = []
        for seq in range(int(ci) - int(before_n), int(ci) + int(after_n) + 1):
            if int(seq) == int(ci):
                chunks_local.append(central_chunk)
                continue
            try:
                eid = resources.daily_src.id_by_seq.get(int(seq))  # type: ignore[union-attr]
            except Exception:  # pragma: no cover - defensive guard around seq lookup
                eid = None
            if not isinstance(eid, str) or not eid:
                # Non-fatal skip-neighbor event.
                continue
            try:
                ve = resources.daily_src.vs.get_by_id(str(eid))  # type: ignore[union-attr]
            except Exception:  # pragma: no cover - defensive guard around entry lookup
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


def _materialize_all_expansions(
    kept_candidates: List[Dict[str, Any]],
    resources: _ExpansionResources,
    project_id: str,
) -> None:
    """Attach ``expanded_chunks`` and rebuild ``text`` for each kept candidate.

    Best-effort: a failure here is logged and otherwise suppressed so retrieval
    and prompt assembly are never blocked.

    Args:
        kept_candidates: Selected candidates, mutated in place.
        resources: Expansion budget and loaded adjacency sources.
        project_id: Project id used for log context.
    """
    try:
        k_actual = int(len(kept_candidates or []))
        if k_actual > 0:
            for i, c in enumerate(list(kept_candidates)):
                if not isinstance(c, dict):
                    continue
                # Output artifact: per-candidate ordered chunk objects.
                chunks = _materialize_candidate_chunks(
                    int(i), int(k_actual), c, resources=resources
                )
                c["expanded_chunks"] = chunks
                # Keep downstream prompt assembly compatible by materializing candidate text from chunks.
                c["text"] = "\n".join(
                    str(ch.get("text") or "") for ch in chunks if isinstance(ch, dict)
                )
    except Exception as exc:  # pragma: no cover - best-effort guard; never blocks assembly
        # Best-effort: never block retrieval/prompt assembly.
        logger.warning(
            "RAG: failed materializing expanded chunks project=%s detail=%s",
            project_id,
            exc,
            exc_info=True,
        )


def _dedupe_expanded_chunks(
    kept_candidates: List[Dict[str, Any]],
    *,
    project_id: str = "(unknown)",
) -> Tuple[List[Dict[str, Any]], _DedupeAudit]:
    """Flatten expansion output into deduped chunks (first-seen wins).

    Operates in kept-candidate order, then per-candidate chunk order. Chunks
    keyed by ``(source_document_id, chunk_index)`` are deduplicated; sparse or
    legacy chunks lacking a full key are preserved in order. Returns the input
    list unchanged when no candidate carries an ``expanded_chunks`` list.

    Args:
        kept_candidates: Candidates carrying ``expanded_chunks`` lists.

    Returns:
        A tuple ``(deduped_chunks, audit)``.
    """
    audit = _DedupeAudit()
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
                audit.input_chunk_count += 1
                source_document_id = ch.get("source_document_id")
                chunk_index = ch.get("chunk_index")
                text = str(ch.get("text") or "")

                # Compatibility behavior: preserve sparse/legacy entries in-order.
                if not isinstance(source_document_id, str) or not isinstance(chunk_index, int):
                    audit.sparse_preserved_count += 1
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
                    audit.duplicate_skipped_count += 1
                    audit.duplicate_events.append(
                        {
                            "source_document_id": key[0],
                            "chunk_index": key[1],
                            "first_seen_pos": audit.key_first_pos.get(key),
                            "duplicate_pos": dedupe_stream_pos,
                        }
                    )
                    continue
                seen_keys.add(key)
                audit.key_first_pos[key] = dedupe_stream_pos
                audit.unique_keyed_count += 1
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
        return deduped_chunks, audit
    except Exception as exc:  # pragma: no cover - best-effort guard; never blocks prompt assembly
        # Best-effort: never block retrieval/prompt assembly.
        logger.warning(
            "RAG: failed deduping expanded chunks project=%s detail=%s",
            project_id,
            exc,
            exc_info=True,
        )
        return list(kept_candidates or []), audit


def _order_chunks_by_source_document(
    kept_candidates: List[Dict[str, Any]],
    *,
    project_id: str = "(unknown)",
) -> List[Dict[str, Any]]:
    """Group deduped chunks by source document and sort within each by index.

    Source documents are emitted in first-seen order; within each, chunks sort
    by ascending ``chunk_index``. Sparse/legacy chunks lacking identity are
    appended in first-seen order. Returns the input unchanged on failure.

    Args:
        kept_candidates: Deduped chunk dicts to order.

    Returns:
        The reordered chunk list.
    """
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
                except (TypeError, ValueError):  # pragma: no cover - chunk_index pre-validated
                    return 0

            chunks = sorted(chunks, key=_chunk_index)
            ordered_chunks_list.extend(chunks)
        ordered_chunks_list.extend(sparse_chunks)
        return ordered_chunks_list
    except Exception as exc:  # pragma: no cover - best-effort guard; never blocks prompt assembly
        # Best-effort: never block retrieval/prompt assembly.
        logger.warning(
            "RAG: failed ordering deduped chunks project=%s detail=%s",
            project_id,
            exc,
            exc_info=True,
        )
        return list(kept_candidates or [])


def _write_retrieval_debug_artifacts(
    *,
    project_id: str,
    query: str,
    route: Optional[str],
    per_source_k: int,
    max_keep: int,
    min_score: float,
    daily_enabled: bool,
    adjacent_bonus: int,
    resources: _ExpansionResources,
    ordered: List[Dict[str, Any]],
    selected_candidates: List[Dict[str, Any]],
    kept_candidates: List[Dict[str, Any]],
    audit: _DedupeAudit,
) -> None:
    """Write human-readable retrieval debug dumps (best-effort).

    Emits ordered-candidate, expansion-plan, and deduped-chunk artifacts. Any
    failure is logged and otherwise suppressed.

    Args:
        project_id: Project the dumps belong to (a falsy id skips writing).
        query: Query string (preview is truncated/sanitized in the dump).
        route: Route name shown in the expansion plan.
        per_source_k: Per-source K used for retrieval.
        max_keep: Base selection cap.
        min_score: Score gate applied during selection.
        daily_enabled: Whether the Daily source participated.
        adjacent_bonus: Number of adjacent same-doc bonus slots granted.
        resources: Expansion resources (for plan header + neighbor probing).
        ordered: Globally ordered candidates.
        selected_candidates: Score-gated selected candidates.
        kept_candidates: Final deduped/ordered chunks.
        audit: Dedupe audit counters and events.
    """
    max_before = resources.max_before
    max_after = resources.max_after
    ltm_expand_ok = resources.ltm_expand_ok
    ltm_index = resources.ltm_index
    daily_src = resources.daily_src
    try:
        if project_id:
            ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
            qprev = (query or "")[:240].replace("\n", " ")

            def _fmt_list(title: str, items: List[Dict[str, Any]]) -> str:
                """Render a titled, header-prefixed candidate/chunk listing for debug dumps.

                Args:
                    title: Section title shown in the dump banner.
                    items: Candidate/chunk dicts to enumerate.

                Returns:
                    The formatted multi-line debug text.
                """
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
                    chunk_idx = (
                        md.get("chunk_index")
                        if md.get("chunk_index") is not None
                        else md.get("chunk_seq")
                    )
                    fname = md.get("filename")
                    lines.append(
                        f"{rank:>3}. source={src} score={score} source_document_id={doc_id} chunk_index={chunk_idx} file={fname}"
                    )
                lines.append("")
                return "\n".join(lines)

            def _fmt_ordered_candidates(
                items: List[Dict[str, Any]], selected: List[Dict[str, Any]]
            ) -> str:
                """Render ordered candidates with selection tags and cutoff marker."""
                selected_ids = {id(c) for c in selected or []}
                total_count = int(len(items or []))
                selected_count = int(len(selected or []))
                lines = [
                    f"# timestamp: {ts}",
                    f"# project_id: {project_id}",
                    f"# query_preview: {qprev}",
                    f"# per_source_k: {int(per_source_k)}",
                    f"# max_keep: {int(max_keep)}",
                    f"# min_score: {float(min_score):.4f}",
                    f"# daily_enabled: {str(bool(daily_enabled)).lower()}",
                    f"# total_candidates: {total_count}",
                    f"# selected_count: {selected_count}",
                    f"# adjacent_bonus: {int(adjacent_bonus)}",
                    "",
                    "====== ORDERED_CANDIDATES ======",
                    "",
                ]
                cutoff_written = False
                for rank, c in enumerate(items, start=1):
                    is_kept = id(c) in selected_ids
                    if not is_kept and not cutoff_written:
                        lines.extend(
                            [
                                "",
                                f"------ SELECTION CUTOFF: kept {selected_count} of {total_count} candidates ------",
                                "",
                            ]
                        )
                        cutoff_written = True

                    md = c.get("metadata") if isinstance(c.get("metadata"), dict) else {}
                    src = c.get("source")
                    score = c.get("score")
                    doc_id = md.get("source_document_id") or md.get("doc_id")
                    chunk_idx = (
                        md.get("chunk_index")
                        if md.get("chunk_index") is not None
                        else md.get("chunk_seq")
                    )
                    fname = md.get("filename")
                    tag = "[KEPT]" if is_kept else "[NOT_KEPT]"
                    lines.append(
                        f"{rank:>3}. {tag} source={src} score={score} source_document_id={doc_id} chunk_index={chunk_idx} file={fname}"
                    )
                lines.append("")
                return "\n".join(lines)

            def _fmt_expansion_plan(items: List[Dict[str, Any]]) -> str:
                """Render a per-candidate expansion plan for debug dumps.

                Shows each candidate's requested neighbor range and which
                neighbors could actually be materialized from the LTM index or
                Daily source.

                Args:
                    items: Selected candidate dicts to plan expansion for.

                Returns:
                    The formatted multi-line debug text.
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
                    chunk_idx = (
                        md.get("chunk_index")
                        if md.get("chunk_index") is not None
                        else md.get("chunk_seq")
                    )
                    fname = md.get("filename")
                    try:
                        ci = int(chunk_idx)
                    except (TypeError, ValueError):
                        ci = None

                    before_n, after_n = _expansion_tier_counts(
                        int(rank - 1), int(k_actual), max_before, max_after
                    )
                    if (
                        ci is None
                        or not isinstance(doc_id, str)
                        or (before_n <= 0 and after_n <= 0)
                    ):
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
                            except Exception:  # pragma: no cover - defensive guard around lookup
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
                            except Exception:  # pragma: no cover - defensive guard around lookup
                                eid = None
                            if not isinstance(eid, str) or not eid:
                                missing.append(str(s))
                                continue
                            try:
                                ve = daily_src.vs.get_by_id(str(eid))  # type: ignore[union-attr]
                            except Exception:  # pragma: no cover - defensive guard around lookup
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
                """Render the deduped chunk listing plus the dedupe audit summary.

                Args:
                    items: Final deduped chunk dicts to enumerate.

                Returns:
                    The chunk listing followed by an audit section with the
                    input/kept/skipped/preserved counts and duplicate events.
                """
                chunk_section = _fmt_list("DEDUPED_CHUNKS", items)
                audit_lines = [
                    "",
                    "====== DEDUPE_AUDIT ======",
                    "",
                    f"input_chunks: {int(audit.input_chunk_count)}",
                    f"unique_keyed_chunks_kept: {int(audit.unique_keyed_count)}",
                    f"duplicate_keyed_chunks_skipped: {int(audit.duplicate_skipped_count)}",
                    f"sparse_or_legacy_chunks_preserved: {int(audit.sparse_preserved_count)}",
                    f"final_output_chunks: {int(len(items or []))}",
                    "",
                    "---- duplicate_events (first-seen wins) ----",
                ]
                if not audit.duplicate_events:
                    audit_lines.append("(none)")
                else:
                    for i, ev in enumerate(audit.duplicate_events, start=1):
                        audit_lines.append(
                            f"{i:>3}. source_document_id={ev.get('source_document_id')} chunk_index={ev.get('chunk_index')} "
                            f"first_seen_pos={ev.get('first_seen_pos')} duplicate_pos={ev.get('duplicate_pos')}"
                        )
                audit_lines.append("")
                return chunk_section + "\n".join(audit_lines)

            write_debug_file(
                project_id,
                f"rag/retrieval/{ts}_ordered_candidates.txt",
                _fmt_ordered_candidates(ordered, selected_candidates),
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
    except Exception as exc:  # pragma: no cover - best-effort guard; never blocks assembly
        logger.warning(
            "RAG: failed writing retrieval debug artifacts project=%s detail=%s",
            project_id,
            exc,
            exc_info=True,
        )


def _assemble_context_prompt(kept_candidates: List[Dict[str, Any]]) -> _PromptAssembly:
    """Assemble kept chunks into a prompt ``Context:`` block with snippet headers.

    Each chunk gets a per-source header showing cosine/score and identity
    metadata; chunk texts are bucketed into daily/main lists and token counts
    are summed for telemetry.

    Args:
        kept_candidates: Final ordered chunk dicts (``text``/``source``/
            ``score``/``metadata``).

    Returns:
        A ``_PromptAssembly`` with the assembled context, per-source text lists,
        per-source score lists, and total token count.
    """
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
            header = f"Snippet {idx+1} (source=ltm, cos={cos:.4f}, score={score01:.4f}, file={md.get('filename')}, page={md.get('page_number')}, chunk_index={chunk_index}{extra_header})\n"
        else:
            chunk_index = md.get("chunk_index") if isinstance(md, dict) else None
            header = f"Snippet {idx+1} (source=daily, cos={cos:.4f}, score={score01:.4f}, route={md.get('route')}, chunk_index={chunk_index}{extra_header})\n"
        pieces.append(header + txt)

    context_text = ("Context:\n---\n" + "\n\n---\n".join(pieces)) if pieces else ""
    return _PromptAssembly(
        context_text=context_text,
        daily_texts=daily_texts,
        main_texts=main_texts,
        main_scores=main_scores,
        daily_scores=daily_scores,
        tokens_used=int(tokens_used_total),
    )


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

    After selection the kept candidates undergo route-tiered adjacency expansion,
    chunk-identity dedupe, source-document ordering, overlap trimming, and
    snippet-group collapse before the prompt ``Context:`` block is assembled.

    Args:
        project_id: Project to retrieve from.
        query: Natural-language query.
        daily_enabled: Whether to include the Daily source alongside LTM.
        max_keep: Base cap on selected candidates (may grow via the adjacent
            same-document bonus).
        route: Route name used to resolve ``min_score`` and expansion limits;
            defaults to ``OTHER``.
        per_source_k_override: Per-source K to use instead of the computed
            default; a value <= 0 (or ``max_keep`` <= 0) returns an empty result.

    Returns:
        A dict with the assembled ``context_text``, ``tokens_used``, per-source
        text lists (``daily_texts``/``main_texts``), hit counts/averages, and
        selection/expansion telemetry counters (e.g. ``ordered_candidates``,
        ``selected_candidates``, ``kept_candidates``,
        ``expanded_unique_chunks_after_merge``, ``min_score``).
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
    min_score = _resolve_route_min_score(project_id, route)
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
    cands = canonical_retrieve_candidates(
        project_id, query, sources=sources, per_source_k_override=per_source_k
    )
    # Global ordering by raw similarity score (stable; ties preserve pre-sort order).
    ordered = order_candidates_by_similarity_score(list(cands or []))

    # Policy-driven selection with adjacent-chunk rule (effective limit can grow when we retain adjacent same-doc chunks).
    selected_candidates, adjacent_bonus = _select_score_gated_candidates(
        ordered, max_keep=int(max_keep), min_score=float(min_score), project_id=project_id
    )

    # Rank-weighted adjacency expansion (materialized per-candidate; no dedupe, no token pruning).
    resources = _resolve_expansion_resources(project_id, route, bool(daily_enabled))
    kept_candidates: List[Dict[str, Any]] = list(selected_candidates)
    _materialize_all_expansions(kept_candidates, resources, project_id)

    # Chunk identity dedupe (first-seen wins) over structured expansion output.
    kept_candidates, audit = _dedupe_expanded_chunks(kept_candidates, project_id=project_id)

    # Source-document ordering and narrative coherence.
    kept_candidates = _order_chunks_by_source_document(kept_candidates, project_id=project_id)

    # Adjacent chunk overlap trimming (in-place; same-doc consecutive pairs only).
    try:
        trim_adjacent_chunk_overlap(
            kept_candidates or [],
            int(get_settings().chunk_overlap),
        )
    except Exception as exc:  # pragma: no cover - best-effort guard; never blocks assembly
        # Best-effort: never block retrieval/prompt assembly.
        logger.warning(
            "RAG: failed trimming adjacent overlap project=%s detail=%s",
            project_id,
            exc,
            exc_info=True,
        )

    # Snippet-group collapse (one entry per adjacent same-document run).
    try:
        kept_candidates = collapse_snippet_groups(kept_candidates or [])
    except Exception as exc:  # pragma: no cover - best-effort guard; never blocks assembly
        # Best-effort: never block retrieval/prompt assembly.
        logger.warning(
            "RAG: failed collapsing snippet groups project=%s detail=%s",
            project_id,
            exc,
            exc_info=True,
        )

    # Debug dumps (human-readable .txt) for ordering and selection.
    _write_retrieval_debug_artifacts(
        project_id=project_id,
        query=query,
        route=route,
        per_source_k=int(per_source_k),
        max_keep=int(max_keep),
        min_score=float(min_score),
        daily_enabled=bool(daily_enabled),
        adjacent_bonus=int(adjacent_bonus),
        resources=resources,
        ordered=ordered,
        selected_candidates=selected_candidates,
        kept_candidates=kept_candidates,
        audit=audit,
    )

    # Prompt assembly stage (after ordering + selection).
    assembled = _assemble_context_prompt(kept_candidates)
    main_hits = int(len(assembled.main_scores))
    daily_hits = int(len(assembled.daily_scores))
    main_avg = float(sum(assembled.main_scores) / main_hits) if main_hits else 0.0
    daily_avg = float(sum(assembled.daily_scores) / daily_hits) if daily_hits else 0.0
    kept_count = int(main_hits + daily_hits)
    logger.debug(
        "DailyRAG: merged context tokens=%s snippets=%s (kept=%s ordered=%s)",
        assembled.tokens_used,
        kept_count,
        kept_count,
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
                "kept_candidates": kept_count,
                "expanded_unique_chunks_after_merge": int(audit.unique_keyed_count),
                "adjacent_bonus": int(adjacent_bonus),
                "main_hits": int(main_hits),
                "daily_hits": int(daily_hits),
                "total_hits": int(main_hits + daily_hits),
                "tokens_used": int(assembled.tokens_used),
            },
        )
    except Exception as exc:  # pragma: no cover - best-effort instrumentation guard
        logger.warning(
            "RAG: instrumentation stage record failed project=%s op=retrieval_selection_expansion detail=%s",
            project_id,
            exc,
        )

    return {
        "context_text": assembled.context_text,
        "tokens_used": int(assembled.tokens_used),
        "daily_texts": assembled.daily_texts,
        "main_texts": assembled.main_texts,
        "main_hits": int(main_hits),
        "main_avg": float(main_avg),
        "daily_hits": int(daily_hits),
        "daily_avg": float(daily_avg),
        "total_hits": int(main_hits + daily_hits),
        "ordered_candidates": int(len(ordered)),
        "selected_candidates": int(len(selected_candidates)),
        "kept_candidates": kept_count,
        "expanded_unique_chunks_after_merge": int(audit.unique_keyed_count),
        "min_score": float(min_score),
    }


def _snippet_header_metadata_fields(metadata: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Select and sanitize identity metadata for inclusion in snippet headers.

    Args:
        metadata: Candidate metadata to extract identity fields from.

    Returns:
        Ordered ``(key, value)`` pairs for present fields, with newlines removed
        and commas replaced by semicolons so values are safe inside a single-line
        header. Absent or empty fields are omitted.
    """
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
