"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Daily memory vector store and metadata management.

This module maintains the per-project in-memory FAISS Daily index and the
daily.json/daily.md artifacts, handling pair appends, cache rebuilds, and adjacency lookups.
"""
from dataclasses import dataclass
import os
import json
import time
import logging
import threading
from typing import List, Dict, Any, Optional, Tuple, Set, Sequence

from filelock import FileLock
import faiss  # type: ignore
import numpy as np  # type: ignore

from ..core.config import get_active_embedding_model, get_settings
from ..embedding.batching import iter_token_batches
from ..embedding.vector_index import VectorEntry, VectorHit, VectorIndexInfo, VectorIndex
from ..embedding.factory import get_embedding_client
from ..utils.debug_utils import write_debug_file
from .syx_memory_artifact import (
    render_artifact_header,
    generate_memory_id,
    local_timestamp_from_iso,
    memory_date_from_local_timestamp,
    render_memory_entry,
    snake_case_value,
    split_pair_text,
    topics_to_list,
)
logger = logging.getLogger(__name__)

def _normalize_rows(v: np.ndarray) -> np.ndarray:
    """Unit-normalize each row of a matrix, treating zero rows as unit-norm.

    Args:
        v: 2-D array of row vectors; cast to float32.

    Returns:
        A float32 array with each row divided by its L2 norm (zero-norm rows use
        a divisor of 1.0). Empty input is returned as-is.
    """
    if v.size == 0:
        return v.astype("float32")
    v = v.astype("float32")
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return v / norms


class DailyVectorIndex:
    """
    Minimal in-memory vector index for Daily (raw FAISS IndexFlatIP).

    Stores:
      - index: FAISS index over unit-normalized vectors
      - index_to_id: row index -> item_id
      - docstore: item_id -> {text, metadata}
    """

    def __init__(self, *, dim: int) -> None:
        """Initialize an empty cosine (IndexFlatIP) index.

        Args:
            dim: Embedding dimensionality; vectors added later must match it.
        """
        self.index: faiss.IndexFlatIP = faiss.IndexFlatIP(int(dim))
        self.index_to_id: List[str] = []
        self.docstore: Dict[str, Dict[str, Any]] = {}
        self._dim: int = int(dim)

    def size(self) -> int:
        """Return the number of vectors held by the index."""
        return int(self.index.ntotal)

    def info(self) -> VectorIndexInfo:
        """Return descriptive metadata about this index (kind, dim, score mode)."""
        return VectorIndexInfo(index_kind="daily", dim=int(self._dim), score_mode="cosine_ip_mapped_01")

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
        except Exception:
            return None

    def add(self, *, item_id: str, vector: List[float], text: str, metadata: Dict[str, Any]) -> None:
        """Add a single entry, unit-normalizing its vector before insertion.

        Args:
            item_id: Docstore key for the entry.
            vector: Raw embedding; normalized before being added to FAISS.
            text: Source text stored alongside the vector.
            metadata: Arbitrary metadata stored with the entry.

        Raises:
            RuntimeError: If the vector dimension does not match the index.
        """
        mat = _normalize_rows(np.array([vector], dtype="float32"))
        if mat.shape[1] != int(self.index.d):
            raise RuntimeError(f"DailyVectorIndex dim mismatch: got={mat.shape[1]} expected={self.index.d}")
        self.index.add(mat)
        self.index_to_id.append(str(item_id))
        self.docstore[str(item_id)] = {"text": str(text or ""), "metadata": dict(metadata or {})}

    def add_many(
        self, *, item_ids: List[str], vectors: List[List[float]], texts: List[str], metadatas: List[dict]
    ) -> None:
        """Add a batch of entries, unit-normalizing their vectors before insertion.

        Args:
            item_ids: Docstore keys, aligned positionally with the other lists.
            vectors: Raw embeddings; normalized before being added to FAISS. An
                empty list is a no-op.
            texts: Source texts aligned with ``item_ids``.
            metadatas: Per-entry metadata aligned with ``item_ids``.

        Raises:
            RuntimeError: If the vector dimension does not match the index.
        """
        if not vectors:
            return
        mat = _normalize_rows(np.array(vectors, dtype="float32"))
        if mat.shape[1] != int(self.index.d):
            raise RuntimeError(f"DailyVectorIndex dim mismatch: got={mat.shape[1]} expected={self.index.d}")
        self.index.add(mat)
        for item_id, txt, md in zip(item_ids, texts, metadatas):
            self.index_to_id.append(str(item_id))
            self.docstore[str(item_id)] = {"text": str(txt or ""), "metadata": dict(md or {})}

    def search_by_vector(self, qvec_norm: np.ndarray, *, k: int) -> List[VectorHit]:
        """Search for the top-k nearest entries to a unit-normalized query vector.

        Args:
            qvec_norm: Unit-normalized query embedding.
            k: Maximum number of hits to return.

        Returns:
            Hits ordered by FAISS, each carrying the raw inner product and a
            cosine-to-[0,1] mapped score. Returns an empty list for an empty
            index.
        """
        if int(self.index.ntotal) <= 0:
            return []
        q = np.array([qvec_norm], dtype="float32")
        D, I = self.index.search(q, k=int(k))
        out: List[VectorHit] = []
        # NOTE: I[0] and D[0] are numpy arrays; do not use `or []` which triggers ambiguous truthiness.
        for idx, ip in zip(I[0].tolist(), D[0].tolist()):
            if int(idx) < 0 or int(idx) >= len(self.index_to_id):
                continue
            item_id = self.index_to_id[int(idx)]
            ve = self.get_by_id(str(item_id))
            if ve is None:
                continue
            ipf = float(ip)
            # map cosine [-1,1] -> [0,1]
            score01 = (max(-1.0, min(1.0, ipf)) + 1.0) / 2.0
            out.append(VectorHit(entry=ve, ip=ipf, score01=float(score01)))
        return out

def _nl(s: str) -> str:
    """Normalize line endings to LF to avoid mixed terminators."""
    return s.replace("\r\n", "\n").replace("\r", "\n")

_BEGIN_DAILY_PAIR = "=== BEGIN DAILY PAIR ==="
_END_DAILY_PAIR = "=== END DAILY PAIR ==="

def _format_tags_block(tags_meta: Optional[Dict[str, Any]]) -> str:
    """Format tag metadata lines for inclusion in daily.md.

    Uses the same 3-line convention as the roll-off tagger output. Formatting
    failures are logged at warning level and degrade to an empty string.

    Args:
        tags_meta: Tagger metadata with ``topics``/``intent``/``type`` and an
            optional ``semantic_handle``; falsy values yield no lines.

    Returns:
        The newline-terminated tag block, or an empty string when there are no
        tags or formatting fails.
    """
    if not tags_meta:
        return ""
    try:
        topics = str(tags_meta.get("topics", "") or "")
        intent = str(tags_meta.get("intent", "") or "")
        tag_type = str(tags_meta.get("type", "") or "")
        semantic_handle = tags_meta.get("semantic_handle", None)
        lines = [f"#topics: {topics}", f"#intent: {intent}", f"#type: {tag_type}"]
        # semantic_handle is required but may be empty; include only when present.
        if semantic_handle is not None:
            lines.append(f"#semantic_handle: {str(semantic_handle) if semantic_handle is not None else ''}")
        return "\n".join(lines) + "\n"
    except Exception as exc:
        logger.warning("DailyRAG: failed formatting tag metadata detail=%s", exc)
        return ""


def _entry_tags_meta(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Return an entry's ``tags_meta`` dict, or an empty dict when absent/invalid.

    Args:
        entry: A daily entry record.

    Returns:
        The ``tags_meta`` mapping, or ``{}`` when it is missing or not a dict.
    """
    tags_meta = entry.get("tags_meta")
    return tags_meta if isinstance(tags_meta, dict) else {}


def _semantic_handle(tags_meta: Optional[Dict[str, Any]]) -> Optional[str]:
    """Extract a non-empty ``semantic_handle`` from tagger metadata.

    Args:
        tags_meta: Tagger metadata mapping, or None.

    Returns:
        The trimmed semantic handle, or None when absent, blank, or the input is
        not a dict.
    """
    if not isinstance(tags_meta, dict):
        return None
    value = tags_meta.get("semantic_handle")
    return str(value).strip() if value is not None and str(value).strip() else None


def _render_markdown_entry(entry: Dict[str, Any], *, user_text: str, assistant_text: str) -> str:
    """Assemble the canonical Syx metadata and render a daily.md entry block.

    Derives scope/source defaults from ``entry_type`` and only emits optional
    tag/dream fields when present, then delegates to ``render_memory_entry``.

    Args:
        entry: Daily entry record supplying ids, scopes, route, and tags.
        user_text: User message text rendered into the block.
        assistant_text: Assistant message text rendered into the block.

    Returns:
        The rendered bounded memory-entry markdown block.
    """
    tags_meta = _entry_tags_meta(entry)
    entry_type = str(entry.get("entry_type", "chat_pair") or "chat_pair")
    metadata: Dict[str, Any] = {
        "memory_id": entry.get("memory_id"),
        "entry_type": entry_type,
        "source": entry.get("source", "chat"),
        "source_agent": entry.get("source_agent", "syx"),
        "source_scope": entry.get("source_scope", "dream" if entry_type == "dream_output" else "daily"),
        "current_scope": entry.get("current_scope", "daily"),
        "timestamp": entry.get("timestamp"),
        "route": entry.get("route"),
        "keep": bool(entry.get("keep", False)),
    }
    topics = topics_to_list(tags_meta.get("topics"))
    if topics:
        metadata["topics"] = topics
    if tags_meta.get("intent") is not None:
        metadata["intent"] = str(tags_meta.get("intent"))
    if tags_meta.get("type") is not None:
        metadata["type"] = str(tags_meta.get("type"))
    semantic_handle = _semantic_handle(tags_meta)
    if semantic_handle:
        metadata["semantic_handle"] = semantic_handle
    if entry.get("day_sequence") is not None:
        metadata["day_sequence"] = entry.get("day_sequence")
    if entry.get("accepted_item_id"):
        metadata["accepted_item_id"] = entry.get("accepted_item_id")
    if entry.get("dream_output_type"):
        metadata["dream_output_type"] = snake_case_value(entry.get("dream_output_type"))
    if entry.get("origin_memory_ids"):
        metadata["origin_memory_ids"] = entry.get("origin_memory_ids")
    return render_memory_entry(
        memory_id=str(entry.get("memory_id")),
        metadata=metadata,
        user_text=user_text,
        assistant_text=assistant_text,
    )

def _project_daily_paths(project_id: str) -> Tuple[str, str, str]:
    """Resolve the (daily.json, daily.lock, daily.md) paths for a project.

    Creates the project and state directories and migrates a legacy top-level
    ``daily.lock`` into the ``state/`` directory when present (migration failures
    are logged at warning level).

    Args:
        project_id: Project whose memory directory paths are resolved.

    Returns:
        A ``(meta_path, lock_path, md_path)`` tuple for daily.json, the lock file,
        and daily.md respectively.
    """
    base_dir = os.path.join(get_settings().memory_root, project_id)
    os.makedirs(base_dir, exist_ok=True)
    meta_path = os.path.join(base_dir, "daily.json")
    state_dir = os.path.join(base_dir, "state")
    os.makedirs(state_dir, exist_ok=True)
    lock_path = os.path.join(state_dir, "daily.lock")
    legacy_lock_path = os.path.join(base_dir, "daily.lock")
    if os.path.isfile(legacy_lock_path) and not os.path.exists(lock_path):
        try:
            os.replace(legacy_lock_path, lock_path)
        except OSError as exc:
            logger.warning("daily_store lock migration failed project_id=%s detail=%s", project_id, exc)
    md_path = os.path.join(base_dir, "daily.md")
    return meta_path, lock_path, md_path


@dataclass
class _DailyCache:
    """Per-project in-memory Daily cache state (raw FAISS).

    Attributes:
        embedding_model: Embedding model the cached vectors were built with;
            used to detect model mismatches and trigger rebuilds.
        vs: The in-memory vector index, or ``None`` when no vectors exist yet.
        meta_by_id: Canonical ``daily.json`` snapshot keyed by stable entry id;
            used to join retrieval hits (via ``daily_entry_id``) back to
            authoritative metadata.
        id_by_seq: O(1) adjacency lookup mapping ``day_sequence`` to entry id.
    """
    embedding_model: str
    vs: Optional[VectorIndex]
    meta_by_id: Dict[str, Dict[str, Any]]
    id_by_seq: Dict[int, str]


@dataclass
class DailySource:
    """Source-adapter boundary exposing Daily to canonical retrieval.

    Owns no retrieval mechanics; it only provides a safe-to-use vectorstore
    handle plus the authoritative metadata join map. Lifecycle concerns
    (warm/rebuild/model-mismatch) stay inside this module.

    Attributes:
        embedding_model: Embedding model backing ``vs``.
        vs: Ready-to-query vector index for the project's Daily memory.
        meta_by_id: Authoritative metadata keyed by stable entry id.
        id_by_seq: Adjacency lookup mapping ``day_sequence`` to entry id.
    """
    embedding_model: str
    vs: VectorIndex
    meta_by_id: Dict[str, Dict[str, Any]]
    id_by_seq: Dict[int, str]


def get_daily_source(project_id: str) -> Optional[DailySource]:
    """Provide a safe Daily vectorstore handle plus authoritative metadata.

    Daily lifecycle (warm/rebuild/model-mismatch) remains owned by this module;
    canonical retrieval owns embedding, per-source K, the search loop, and result
    shaping. A cold or stale cache triggers a background rebuild and yields None
    for the current request (no in-request retry).

    Args:
        project_id: Project whose Daily source is requested.

    Returns:
        A ``DailySource`` when a warm, model-matched, non-empty cache exists;
        otherwise None.
    """
    settings = get_settings()
    # Warm lazily on first use for a project (non-blocking; return None for this request).
    with _CACHE_LOCK:
        cache = _CACHE.get(project_id)
    if cache is None:
        start_daily_cache_rebuild(project_id, reason="get_source_warm")
        return None
    with _CACHE_LOCK:
        cache = _CACHE.get(project_id)
    if cache is None or cache.vs is None:
        return None
    # If runtime model changed vs cache, rebuild but do not retry this request.
    if cache.embedding_model != get_active_embedding_model():
        start_daily_cache_rebuild(project_id, reason="get_source_model_mismatch")
        return None
    return DailySource(
        embedding_model=cache.embedding_model,
        vs=cache.vs,
        meta_by_id=cache.meta_by_id,
        id_by_seq=cache.id_by_seq,
    )


def daily_lookup_adjacent_entry_ids(project_id: str, *, day_sequence: int) -> Dict[str, Optional[str]]:
    """Look up the deterministic neighbors of a Daily entry by day sequence.

    Args:
        project_id: Project whose Daily adjacency map is consulted.
        day_sequence: 1-based sequence number of the central entry.

    Returns:
        A dict with ``prev_entry_id`` and ``next_entry_id``; both are None when
        the cache is cold/unavailable or the sequence is invalid (no expansion).
    """
    ds = get_daily_source(project_id)
    if ds is None:
        return {"prev_entry_id": None, "next_entry_id": None}
    try:
        seq = int(day_sequence)
    except Exception:
        return {"prev_entry_id": None, "next_entry_id": None}
    prev_id = ds.id_by_seq.get(seq - 1)
    next_id = ds.id_by_seq.get(seq + 1)
    return {
        "prev_entry_id": str(prev_id) if isinstance(prev_id, str) else None,
        "next_entry_id": str(next_id) if isinstance(next_id, str) else None,
    }


def notify_daily_search_failure(project_id: str, reason: str) -> None:
    """Schedule a Daily cache rebuild after a canonical search failure.

    This is the source-owned rebuild trigger canonical retrieval calls when a
    Daily search raises; scheduling failures are logged at warning level.

    Args:
        project_id: Project whose Daily cache should be rebuilt.
        reason: Short rebuild reason recorded for diagnostics.
    """
    try:
        start_daily_cache_rebuild(project_id, reason=reason)
    except Exception as exc:
        logger.warning("DailyRAG: failed scheduling cache rebuild project=%s reason=%s detail=%s", project_id, reason, exc)


_CACHE: Dict[str, _DailyCache] = {}
_CACHE_LOCK = threading.Lock()
_PROJECT_LOCKS: Dict[str, threading.RLock] = {}
_WARMING: Set[str] = set()


def _get_project_lock(project_id: str) -> threading.RLock:
    """Return the per-project re-entrant lock, creating it on first use.

    Re-entrant so that ``ensure_daily_cache`` can call ``rebuild_daily_cache``
    while already holding the lock.

    Args:
        project_id: Project whose lock is requested.

    Returns:
        The shared ``threading.RLock`` for the project.
    """
    with _CACHE_LOCK:
        lock = _PROJECT_LOCKS.get(project_id)
        if lock is None:
            # Re-entrant: ensure_daily_cache() may call rebuild_daily_cache()
            lock = threading.RLock()
            _PROJECT_LOCKS[project_id] = lock
        return lock


def clear_daily_cache(project_id: str) -> None:
    """Drop the in-memory Daily cache for a project (no disk changes).

    Args:
        project_id: Project whose cache entry and warming flag are removed.
    """
    with _CACHE_LOCK:
        _CACHE.pop(project_id, None)
        _WARMING.discard(project_id)


def start_daily_cache_rebuild(project_id: str, reason: str) -> None:
    """Kick off a background rebuild of the in-memory cache (non-blocking).

    De-duplicated per project via a warming set, so a rebuild already in flight is
    not started again.

    Args:
        project_id: Project whose cache should be rebuilt off-thread.
        reason: Short rebuild reason propagated to ``rebuild_daily_cache``.
    """
    with _CACHE_LOCK:
        if project_id in _WARMING:
            return
        _WARMING.add(project_id)

    def _worker() -> None:
        try:
            rebuild_daily_cache(project_id, reason=reason)
        finally:
            with _CACHE_LOCK:
                _WARMING.discard(project_id)

    t = threading.Thread(target=_worker, name=f"daily-rebuild-{project_id[:8]}", daemon=True)
    t.start()


def _recorded_models(entries: List[Dict[str, Any]]) -> Set[str]:
    """Collect the distinct ``embedding_model`` values recorded across entries.

    Args:
        entries: Daily metadata records.

    Returns:
        The set of non-empty embedding model names found.
    """
    models: Set[str] = set()
    for e in entries:
        m = e.get("embedding_model")
        if isinstance(m, str) and m.strip():
            models.add(m.strip())
    return models


def _load_metadata(meta_path: str) -> List[Dict[str, Any]]:
    """Load the daily.json metadata list, degrading to empty on error.

    Args:
        meta_path: Path to the project's daily.json file.

    Returns:
        The parsed list of entry dicts, or an empty list when the file is missing
        or cannot be read/decoded (failures are logged at error level).
    """
    if not os.path.isfile(meta_path):
        return []
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"DailyRAG: failed to load metadata {meta_path}: {e}")
        return []


def _save_metadata(meta_path: str, entries: List[Dict[str, Any]]) -> None:
    """Persist the daily.json metadata list atomically.

    Args:
        meta_path: Destination daily.json path; a sibling ``.tmp`` is written then
            renamed into place.
        entries: Entry dicts to serialize.
    """
    tmp_path = meta_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(entries, f)
    os.replace(tmp_path, meta_path)


def reset_daily(project_id: str) -> None:
    """Delete a project's daily.json and clear its in-memory cache.

    Holds the daily file lock while removing daily.json (removal failures are
    logged at warning level), then drops the in-memory cache. daily.md is left
    untouched.

    Args:
        project_id: Project whose Daily metadata and cache are reset.
    """
    meta_path, lock_path, _txt_path = _project_daily_paths(project_id)
    with FileLock(lock_path):
        for p in (meta_path,):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception as e:
                logger.warning("DailyRAG: failed to remove metadata %s: %s", p, e)
    clear_daily_cache(project_id)
    logger.info("DailyRAG: reset daily metadata and cleared cache for project=%s", project_id)


def _reconcile_daily_embedding_model(
    project_id: str,
    meta_path: str,
    lock_path: str,
    runtime_model: str,
    reason: str,
) -> List[Dict[str, Any]]:
    """Load daily.json and reconcile its recorded embedding model in place.

    When the snapshot does not uniformly reflect ``runtime_model``, every entry's
    ``embedding_model`` is rewritten and daily.json is re-saved under the file
    lock. Reconciliation failures are logged and do not raise.

    Args:
        project_id: Project being reconciled (for logging).
        meta_path: Path to the project's daily.json.
        lock_path: Path to the daily file lock.
        runtime_model: The currently active embedding model.
        reason: Short reason recorded in logs.

    Returns:
        The loaded (and possibly model-updated) list of daily entries.
    """
    with FileLock(lock_path):
        entries = _load_metadata(meta_path)
        models = _recorded_models(entries)
        # If daily.json doesn't reflect current EMBEDDING_MODEL, update it in-place
        if entries and (not models or models != {runtime_model}):
            try:
                for e in entries:
                    e["embedding_model"] = runtime_model
                _save_metadata(meta_path, entries)
                logger.info(
                    "DailyRAG: updated daily.json embedding_model to %s for project=%s (reason=%s)",
                    runtime_model,
                    project_id,
                    reason,
                )
            except Exception as ue:
                logger.warning(
                    "DailyRAG: failed updating daily.json embedding_model project=%s: %s",
                    project_id,
                    ue,
                )
    return entries


def _collect_daily_texts_and_maps(
    entries: List[Dict[str, Any]],
    project_id: str,
) -> Tuple[List[str], List[dict], Dict[str, Dict[str, Any]], Dict[int, str]]:
    """Collect embeddable texts and adjacency maps from daily entries.

    Skips entries without usable text (preferring ``embed_text`` over ``text``),
    builds the per-vector metadata list, and the ``meta_by_id``/``id_by_seq``
    join maps used by the cache.

    Args:
        entries: Daily metadata entries.
        project_id: Project being rebuilt (for logging).

    Returns:
        Tuple of ``(texts, metas, meta_by_id, id_by_seq)`` aligned by entry order.
    """
    texts: List[str] = []
    metas: List[dict] = []
    meta_by_id: Dict[str, Dict[str, Any]] = {}
    id_by_seq: Dict[int, str] = {}
    for e in entries:
        t = e.get("embed_text") or e.get("text")
        if not isinstance(t, str) or not t.strip():
            continue
        eid = e.get("id")
        if isinstance(eid, str) and eid.strip():
            meta_by_id[eid] = e
            try:
                seq = int(e.get("day_sequence"))
                if seq > 0:
                    id_by_seq[seq] = eid
            except Exception as exc:
                logger.debug("DailyRAG: invalid day_sequence for entry id=%s project=%s detail=%s", eid, project_id, exc)
        texts.append(t)
        metas.append(
            {
                "source": "daily",
                "daily_entry_id": str(eid) if eid is not None else None,
                "memory_id": e.get("memory_id"),
                "day_sequence": e.get("day_sequence"),
                # Adjacency identity for Daily entries.
                "doc_id": "daily",
                "chunk_seq": e.get("day_sequence"),
            }
        )
    return texts, metas, meta_by_id, id_by_seq


def _embed_daily_batches(
    texts: List[str],
    metas: List[dict],
    runtime_model: str,
    max_req_tokens: int,
    project_id: str,
    reason: str,
) -> Optional["DailyVectorIndex"]:
    """Embed daily texts in token batches into a fresh vector index.

    Iterates token-bounded batches, embeds each, and adds the resulting vectors
    to a lazily-created :class:`DailyVectorIndex`. Empty embedding batches are
    skipped.

    Args:
        texts: Embeddable texts aligned with ``metas``.
        metas: Per-vector metadata aligned with ``texts``.
        runtime_model: Embedding model to use.
        max_req_tokens: Token budget per embedding request.
        project_id: Project being rebuilt (for logging).
        reason: Short reason recorded in logs.

    Returns:
        The populated vector index, or ``None`` when no vectors were produced.
    """
    vs: Optional[DailyVectorIndex] = None
    batch_idx = 0
    llm = get_embedding_client()
    for batch_texts, batch_metas, est_tokens in iter_token_batches(
        texts,
        metadatas=metas,
        max_tokens_per_batch=max_req_tokens,
        model_name=runtime_model,
    ):
        batch_idx += 1
        res = llm.embed(list(batch_texts), model=runtime_model)
        vecs = res.vectors
        if not vecs:
            continue
        if vs is None:
            vs = DailyVectorIndex(dim=len(vecs[0]))
        item_ids = []
        for md in list(batch_metas):
            # Stable daily item id for docstore: use daily_entry_id when present else synthetic.
            eid = md.get("daily_entry_id")
            seq = md.get("day_sequence") or md.get("chunk_seq")
            item_ids.append(str(eid) if eid is not None else f"daily::seq={seq}")
        vs.add_many(
            item_ids=item_ids,
            vectors=vecs,
            texts=list(batch_texts),
            metadatas=list(batch_metas),
        )
        logger.debug(
            "DailyRAG: embedded batch=%s texts=%s est_tokens=%s max_req_tokens=%s project=%s reason=%s",
            int(batch_idx),
            int(len(batch_texts)),
            int(est_tokens),
            int(max_req_tokens),
            project_id,
            reason,
        )
    return vs


def _write_daily_rebuild_report(
    project_id: str,
    reason: str,
    runtime_model: str,
    vector_count: int,
    id_by_seq: Dict[int, str],
) -> None:
    """Write a best-effort human-readable rebuild report for the Daily cache.

    Args:
        project_id: Project whose report is written.
        reason: Short reason recorded in the report.
        runtime_model: Embedding model used for the rebuild.
        vector_count: Number of vectors built into the cache.
        id_by_seq: Adjacency map used to report the day_sequence range.
    """
    try:
        ts = time.strftime("%Y-%m-%dT%H-%M-%S", time.localtime())
        seqs = sorted(id_by_seq.keys())
        body = (
            f"# timestamp: {ts}\n"
            f"# project_id: {project_id}\n"
            f"# reason: {reason}\n"
            f"# embedding_model: {runtime_model}\n"
            f"# vectors: {vector_count}\n"
            f"# day_sequence_min: {seqs[0] if seqs else None}\n"
            f"# day_sequence_max: {seqs[-1] if seqs else None}\n"
        )
        write_debug_file(project_id, f"rag/daily/{ts}_daily_cache_report.txt", body)
    except Exception as exc:
        logger.warning("DailyRAG: failed writing daily cache debug report project=%s detail=%s", project_id, exc)


def rebuild_daily_cache(project_id: str, reason: str) -> bool:
    """Force a rebuild of the in-memory Daily cache from daily.json.

    Clears the existing cache, reconciles each entry's ``embedding_model`` to the
    active model (rewriting daily.json when stale), re-embeds every entry in token
    batches, and repopulates the vector index plus the metadata/adjacency maps.
    A human-readable debug report is written best-effort.

    Args:
        project_id: Project whose cache is rebuilt.
        reason: Short reason recorded in logs and the debug report.

    Returns:
        True when the cache (possibly empty) is rebuilt; False when an unexpected
        error aborts the rebuild (the cache is dropped in that case).
    """
    settings = get_settings()
    runtime_model = get_active_embedding_model()
    meta_path, lock_path, _txt_path = _project_daily_paths(project_id)
    lock = _get_project_lock(project_id)
    with lock:
        # Always clear first to avoid using a corrupt instance
        clear_daily_cache(project_id)
        entries = _reconcile_daily_embedding_model(project_id, meta_path, lock_path, runtime_model, reason)
        # Build the in-memory vectorstore from the snapshot we just loaded/updated.
        try:
            texts, metas, meta_by_id, id_by_seq = _collect_daily_texts_and_maps(entries, project_id)
            if not texts:
                with _CACHE_LOCK:
                    _CACHE[project_id] = _DailyCache(
                        embedding_model=runtime_model,
                        vs=None,
                        meta_by_id={},
                        id_by_seq={},
                    )
                logger.debug("DailyRAG: rebuilt empty in-memory cache project=%s (reason=%s)", project_id, reason)
                return True
            max_req_tokens = int(getattr(settings, "max_embed_tokens_per_request", 250_000))
            vs = _embed_daily_batches(texts, metas, runtime_model, max_req_tokens, project_id, reason)
            if vs is None:
                with _CACHE_LOCK:
                    _CACHE[project_id] = _DailyCache(
                        embedding_model=runtime_model,
                        vs=None,
                        meta_by_id=meta_by_id,
                        id_by_seq=id_by_seq,
                    )
                logger.debug("DailyRAG: rebuilt empty in-memory cache project=%s (reason=%s)", project_id, reason)
                return True
            with _CACHE_LOCK:
                _CACHE[project_id] = _DailyCache(
                    embedding_model=runtime_model,
                    vs=vs,
                    meta_by_id=meta_by_id,
                    id_by_seq=id_by_seq,
                )
            logger.info("DailyRAG: rebuilt in-memory cache project=%s vectors=%s (reason=%s)", project_id, len(texts), reason)
            _write_daily_rebuild_report(project_id, reason, runtime_model, len(texts), id_by_seq)
            return True
        except Exception as be:
            logger.error("DailyRAG: rebuild failed project=%s reason=%s err=%s", project_id, reason, be)
            with _CACHE_LOCK:
                _CACHE.pop(project_id, None)
            return False


def ensure_daily_cache(project_id: str, reason: str = "warm") -> bool:
    """Ensure a project's in-memory cache exists and matches daily.json + model.

    Fast-paths when the cache is already on the active embedding model and
    daily.json agrees; otherwise rebuilds.

    Args:
        project_id: Project whose cache is validated/ensured.
        reason: Short reason forwarded to a rebuild when one is required.

    Returns:
        True when the cache is present and consistent (or successfully rebuilt);
        False when a rebuild fails.
    """
    settings = get_settings()
    runtime_model = get_active_embedding_model()
    meta_path, lock_path, _txt_path = _project_daily_paths(project_id)
    lock = _get_project_lock(project_id)
    with lock:
        with _CACHE_LOCK:
            cache = _CACHE.get(project_id)
        # Fast path: cache exists and is already on current runtime model, and daily.json agrees
        if cache is not None and cache.embedding_model == runtime_model:
            try:
                with FileLock(lock_path):
                    entries = _load_metadata(meta_path)
                models = _recorded_models(entries)
                if not entries or (models == {runtime_model}):
                    return True
            except Exception as exc:
                # If we can't validate, rebuild and do not retry this request elsewhere.
                logger.warning("DailyRAG: cache validation failed project=%s detail=%s", project_id, exc)
        # Rebuild if missing or if daily.json indicates mismatch with runtime model.
        return rebuild_daily_cache(project_id, reason=reason)


def _build_daily_entry(
    *,
    project_id: str,
    entries: List[Dict[str, Any]],
    pair_text: str,
    text_for_embed: str,
    user_text: str,
    assistant_text: str,
    user_msg_id: int,
    assistant_msg_id: int,
    tokens: int,
    namespace: Optional[str],
    keep: bool,
    tags_meta: Optional[Dict[str, Any]],
    created_at_iso_utc: Optional[str],
    memory_id: Optional[str],
    entry_type: str,
    source: str,
    source_agent: str,
    source_scope: Optional[str],
    current_scope: Optional[str],
    accepted_item_id: Optional[str],
    dream_output_type: Optional[str],
    origin_memory_ids: Optional[List[str]],
) -> Dict[str, Any]:
    """Construct a single daily.json entry dict from append inputs.

    Computes the next ``day_sequence`` from ``entries``, resolves scopes and a
    deterministic ``memory_id`` (unless one is supplied), and assembles the
    entry record. The entry is neither appended nor persisted here.

    Args:
        project_id: Owning project id.
        entries: Existing daily entries (used for day_sequence and id suffix).
        pair_text: Combined ``User:/Assistant:`` body text.
        text_for_embed: Text actually embedded (may differ from ``pair_text``).
        user_text: User-side text used for memory-id generation.
        assistant_text: Assistant-side text used for memory-id generation.
        user_msg_id: Source user message id recorded in ``pair_ids``.
        assistant_msg_id: Source assistant message id recorded in ``pair_ids``.
        tokens: Token count attributed to the pair.
        namespace: Route/namespace label; lowercased, defaults to ``other``.
        keep: Whether the entry is pinned (exempt from pruning).
        tags_meta: Optional tagger metadata stored on the entry.
        created_at_iso_utc: Creation timestamp; defaults to now (UTC).
        memory_id: Explicit memory id; generated deterministically when omitted.
        entry_type: Entry kind (e.g. ``chat_pair`` or ``dream_output``).
        source: Origin label for the entry.
        source_agent: Producing agent label.
        source_scope: Source scope; defaults by entry type when omitted.
        current_scope: Current scope; defaults by entry type when omitted.
        accepted_item_id: Accepted item id for dream outputs.
        dream_output_type: Dream subtype, snake-cased when stored.
        origin_memory_ids: Source memory ids for dream outputs.

    Returns:
        The assembled entry dict ready to append and persist.
    """
    day_sequence = (entries[-1]["day_sequence"] + 1) if entries else 1
    ns = (namespace or "other").lower()
    created_at = created_at_iso_utc or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    ts_local = local_timestamp_from_iso(created_at)
    public_tags_meta = tags_meta if isinstance(tags_meta, dict) else {}
    semantic_handle = _semantic_handle(public_tags_meta)
    resolved_current_scope = current_scope or ("dream" if entry_type == "dream_output" else "daily")
    resolved_source_scope = source_scope or ("dream" if entry_type == "dream_output" else "daily")
    resolved_memory_id = memory_id or generate_memory_id(
        project_id=project_id,
        timestamp=ts_local,
        source=source,
        entry_type=entry_type,
        user_text=user_text,
        assistant_text=assistant_text,
        route=ns,
        semantic_handle=semantic_handle,
        dream_output_type=dream_output_type,
        accepted_item_id=accepted_item_id,
        origin_memory_ids=origin_memory_ids,
        dream_content=assistant_text if entry_type == "dream_output" else None,
    )
    entry = {
        "id": f"{int(time.time()*1000)}-{len(entries)+1}",
        "memory_id": resolved_memory_id,
        "entry_type": entry_type,
        "project_id": project_id,
        "created_at": created_at,
        "timestamp": ts_local,
        "pair_ids": [str(user_msg_id), str(assistant_msg_id)],
        "text": pair_text,
        # The in-memory FAISS cache is rebuilt from daily.json; preserve vector content explicitly.
        "embed_text": text_for_embed,
        "tokens": int(tokens),
        "embedding_model": get_active_embedding_model(),
        "source": source,
        "source_agent": source_agent,
        "source_scope": resolved_source_scope,
        "current_scope": resolved_current_scope,
        "scope": "daily",
        "route": ns,
        "keep": bool(keep),
        "confidence": 1.0,
        "tags": ["rolled_off"],
        "day_sequence": day_sequence,
    }
    if accepted_item_id:
        entry["accepted_item_id"] = accepted_item_id
    if dream_output_type:
        entry["dream_output_type"] = snake_case_value(dream_output_type)
    if origin_memory_ids:
        entry["origin_memory_ids"] = list(origin_memory_ids)
    if tags_meta:
        entry["tags_meta"] = tags_meta
    return entry


def _cache_entry_metadata(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Build the in-memory vector-index metadata for a single daily entry.

    Args:
        entry: Daily entry dict.

    Returns:
        The metadata dict stored alongside the entry's vector in the cache.
    """
    return {
        "source": "daily",
        "daily_entry_id": entry.get("id"),
        "memory_id": entry.get("memory_id"),
        "day_sequence": entry.get("day_sequence"),
        "doc_id": "daily",
        "chunk_seq": entry.get("day_sequence"),
    }


def _append_daily_md_block(
    project_id: str,
    md_path: str,
    entry: Dict[str, Any],
    *,
    user_text: str,
    assistant_text: str,
) -> None:
    """Append a human-readable daily.md block for an entry (best-effort).

    Writes the BEGIN artifact header when daily.md is new/empty, then appends the
    rendered markdown entry. All failures are logged and suppressed so a daily.md
    write never aborts the append.

    Args:
        project_id: Owning project id.
        md_path: Path to the project's daily.md.
        entry: The daily entry being rendered.
        user_text: User-side text for the rendered block.
        assistant_text: Assistant-side text for the rendered block.
    """
    try:
        # If first write, add BEGIN header with local date (MM/DD/YYYY)
        try:
            if (not os.path.isfile(md_path)) or os.path.getsize(md_path) == 0:
                memory_date = time.strftime("%m-%d-%Y", time.localtime())
                with open(md_path, "a", encoding="utf-8", newline="\n") as tf:
                    tf.write(_nl(render_artifact_header(
                        artifact_type="daily_memory",
                        project_id=project_id,
                        memory_date=memory_date,
                    )))
        except Exception as exc:
            logger.warning("DailyRAG: failed ensuring daily BEGIN header project=%s path=%s detail=%s", project_id, md_path, exc)
        block = _render_markdown_entry(entry, user_text=user_text, assistant_text=assistant_text)
        with open(md_path, "a", encoding="utf-8", newline="\n") as tf:
            tf.write(_nl(block))
        logger.debug("[DAILYMD] project=%s wrote %s bytes", project_id, len(block.encode('utf-8')))
    except Exception as te:
        logger.error("DailyRAG: failed writing daily.md: %s", te)


def _update_cache_with_entry(project_id: str, entry: Dict[str, Any], text_for_embed: str) -> bool:
    """Incrementally add a persisted entry to the in-memory Daily cache.

    Handles the lazy-warm, model-mismatch, empty-cache, and normal incremental
    paths. On any condition that cannot be satisfied incrementally, schedules a
    background rebuild and returns False (the on-disk write already succeeded).

    Args:
        project_id: Owning project id.
        entry: The persisted daily entry to add to the cache.
        text_for_embed: Text to embed for the entry's vector.

    Returns:
        True when the cache was updated in place; False when a background rebuild
        was scheduled instead.
    """
    try:
        lock = _get_project_lock(project_id)
        with lock:
            with _CACHE_LOCK:
                cache = _CACHE.get(project_id)
            # If cache doesn't exist yet, build it from daily.json (lazy warm semantics)
            if cache is None:
                start_daily_cache_rebuild(project_id, reason="append_missing_cache")
                return False
            # If cache model mismatched, rebuild and return error for this request (no retry)
            if cache.embedding_model != get_active_embedding_model():
                start_daily_cache_rebuild(project_id, reason="append_model_mismatch")
                return False
            # If empty cache, create a new vectorstore with this single entry
            if cache.vs is None:
                llm = get_embedding_client()
                vecs = llm.embed([text_for_embed], model=get_active_embedding_model()).vectors
                if not vecs:
                    start_daily_cache_rebuild(project_id, reason="append_embed_empty")
                    return False
                vs = DailyVectorIndex(dim=len(vecs[0]))
                vs.add(
                    item_id=str(entry.get("id") or f"daily::seq={entry.get('day_sequence')}"),
                    vector=vecs[0],
                    text=text_for_embed,
                    metadata=_cache_entry_metadata(entry),
                )
                with _CACHE_LOCK:
                    _CACHE[project_id] = _DailyCache(
                        embedding_model=get_active_embedding_model(),
                        vs=vs,
                        meta_by_id={str(entry.get("id")): entry} if entry.get("id") else {},
                        id_by_seq={int(entry.get("day_sequence")): str(entry.get("id"))}
                        if entry.get("id") and entry.get("day_sequence") is not None
                        else {},
                    )
                return True
            # Normal path: incremental add
            llm = get_embedding_client()
            vecs2 = llm.embed([text_for_embed], model=get_active_embedding_model()).vectors
            if not vecs2:
                start_daily_cache_rebuild(project_id, reason="append_embed_empty")
                return False
            cache.vs.add(
                item_id=str(entry.get("id") or f"daily::seq={entry.get('day_sequence')}"),
                vector=vecs2[0],
                text=text_for_embed,
                metadata=_cache_entry_metadata(entry),
            )
            # Update in-memory authoritative mapping for deterministic joins
            try:
                eid2 = entry.get("id")
                if eid2:
                    cache.meta_by_id[str(eid2)] = entry
            except Exception as exc:
                logger.warning("DailyRAG: failed updating meta_by_id project=%s entry_id=%s detail=%s", project_id, entry.get("id"), exc)
            # Update adjacency map (best-effort)
            try:
                seq2 = entry.get("day_sequence")
                eid3 = entry.get("id")
                if eid3 is not None and seq2 is not None:
                    cache.id_by_seq[int(seq2)] = str(eid3)
            except Exception as exc:
                logger.warning("DailyRAG: failed updating id_by_seq project=%s entry_id=%s detail=%s", project_id, entry.get("id"), exc)
            return True
    except Exception as e:
        logger.error("DailyRAG: in-memory add failed project=%s: %s", project_id, e)
        start_daily_cache_rebuild(project_id, reason="append_exception")
        return False


def append_pair(
    project_id: str,
    pair_text: str,
    user_msg_id: int,
    assistant_msg_id: int,
    tokens: int,
    namespace: Optional[str] = None,
    keep: bool = False,
    embed_override: Optional[str] = None,
    tags_meta: Optional[Dict[str, Any]] = None,
    write_daily_md: bool = True,
    update_cache: bool = True,
    created_at_iso_utc: Optional[str] = None,
    memory_id: Optional[str] = None,
    entry_type: str = "chat_pair",
    source: str = "chat",
    source_agent: str = "syx",
    source_scope: Optional[str] = None,
    current_scope: Optional[str] = None,
    accepted_item_id: Optional[str] = None,
    dream_output_type: Optional[str] = None,
    origin_memory_ids: Optional[List[str]] = None,
) -> bool:
    """Append a single embedded pair to the Daily index and metadata.

    Persists the entry to daily.json (and optionally daily.md) under the file
    lock, then incrementally updates the in-memory cache. Raw FAISS is never
    persisted here; vectors are rebuilt from daily.json at retrieval time. When
    ``update_cache`` is False, only the on-disk artifacts are written and the
    caller is responsible for rebuilding the in-memory cache once (e.g. a dream
    batch).

    Args:
        project_id: Owning project id.
        pair_text: Combined ``User:/Assistant:`` text stored as the entry body.
        user_msg_id: Source user message id recorded in ``pair_ids``.
        assistant_msg_id: Source assistant message id recorded in ``pair_ids``.
        tokens: Token count attributed to the pair.
        namespace: Route/namespace label; lowercased, defaults to ``other``.
        keep: Whether the entry is pinned (exempt from pruning).
        embed_override: Alternate text to embed instead of ``pair_text``.
        tags_meta: Optional tagger metadata (topics/intent/type/semantic_handle).
        write_daily_md: When True, also append a human-readable daily.md block.
        update_cache: When False, skip the in-memory cache update.
        created_at_iso_utc: Creation timestamp; defaults to now (UTC).
        memory_id: Explicit memory id; generated deterministically when omitted.
        entry_type: Entry kind (e.g. ``chat_pair`` or ``dream_output``).
        source: Origin label for the entry.
        source_agent: Producing agent label.
        source_scope: Source scope; defaults by entry type when omitted.
        current_scope: Current scope; defaults by entry type when omitted.
        accepted_item_id: Accepted item id for dream outputs.
        dream_output_type: Dream subtype, snake-cased when stored.
        origin_memory_ids: Source memory ids for dream outputs.

    Returns:
        True on success. False when the cache update could not complete and a
        background rebuild was scheduled instead (the disk write still succeeded).
    """
    meta_path, lock_path, md_path = _project_daily_paths(project_id)
    text_for_embed = embed_override if embed_override else pair_text
    user_text, assistant_text = split_pair_text(pair_text)
    with FileLock(lock_path):
        entries = _load_metadata(meta_path)
        entry = _build_daily_entry(
            project_id=project_id,
            entries=entries,
            pair_text=pair_text,
            text_for_embed=text_for_embed,
            user_text=user_text,
            assistant_text=assistant_text,
            user_msg_id=user_msg_id,
            assistant_msg_id=assistant_msg_id,
            tokens=tokens,
            namespace=namespace,
            keep=keep,
            tags_meta=tags_meta,
            created_at_iso_utc=created_at_iso_utc,
            memory_id=memory_id,
            entry_type=entry_type,
            source=source,
            source_agent=source_agent,
            source_scope=source_scope,
            current_scope=current_scope,
            accepted_item_id=accepted_item_id,
            dream_output_type=dream_output_type,
            origin_memory_ids=origin_memory_ids,
        )
        entries.append(entry)
        _save_metadata(meta_path, entries)
        # Append to daily.md (human-readable) unless explicitly skipped.
        if write_daily_md:
            _append_daily_md_block(project_id, md_path, entry, user_text=user_text, assistant_text=assistant_text)
    if not update_cache:
        return True
    return _update_cache_with_entry(project_id, entry, text_for_embed)


def append_pair_text_only(
    project_id: str,
    user_text: str,
    assistant_text: str,
    created_at_iso_utc: Optional[str],
    namespace: Optional[str],
    keep: bool,
    tags_meta: Optional[Dict[str, Any]] = None,
) -> bool:
    """Append a single pair to daily.md only (no FAISS, no daily.json).

    Used by the Sleep flush to move active DB pairs into daily text at the start
    of a cycle. Failures are logged at error level and reported via the return
    value rather than raised.

    Args:
        project_id: Owning project id.
        user_text: User message text.
        assistant_text: Assistant message text.
        created_at_iso_utc: Creation timestamp; defaults to now (UTC).
        namespace: Route/namespace label; lowercased, defaults to ``other``.
        keep: Whether the pair is marked as pinned in the rendered block.
        tags_meta: Optional tagger metadata; when present, writes the
            ``#topics``/``#intent``/``#type``/``#semantic_handle`` lines.

    Returns:
        True when the block is appended; False on write failure.
    """
    _meta_path, lock_path, md_path = _project_daily_paths(project_id)
    ns = (namespace or "other").lower()
    with FileLock(lock_path):
        try:
            # Ensure BEGIN header exists
            try:
                if (not os.path.isfile(md_path)) or os.path.getsize(md_path) == 0:
                    memory_date = time.strftime("%m-%d-%Y", time.localtime())
                    with open(md_path, "a", encoding="utf-8", newline="\n") as tf:
                        tf.write(_nl(render_artifact_header(
                            artifact_type="daily_memory",
                            project_id=project_id,
                            memory_date=memory_date,
                        )))
            except Exception as exc:
                logger.warning("DailyRAG: failed ensuring text-only BEGIN header project=%s path=%s detail=%s", project_id, md_path, exc)
            ts = created_at_iso_utc or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            # Localize timestamp to MM-DD-YYYY_HH:MM:SS
            try:
                tstruct = time.strptime(ts.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
                ts_local = time.strftime("%m-%d-%Y_%H:%M:%S", time.localtime(time.mktime(tstruct)))
            except Exception:
                ts_local = ts
            tags_block = _format_tags_block(tags_meta)
            block = (
                f"{_BEGIN_DAILY_PAIR}\n"
                f"#timestamp: {ts_local}\n"
                f"#route: {ns}\n"
                f"#keep: {str(bool(keep)).lower()}\n"
                f"{tags_block}"
                f"\n"
                f"--- USER (data-message-author-role: user) ---\n"
                f"{user_text or ''}\n"
                f"\n"
                f"*** ASSISTANT (data-message-author-role: assistant) ***\n"
                f"{assistant_text or ''}\n"
                f"\n"
                f"{_END_DAILY_PAIR}\n"
                f"\n"
            )
            with open(md_path, "a", encoding="utf-8", newline="\n") as tf:
                tf.write(_nl(block))
            logger.info("[DAILYMD] Text-only append project=%s bytes=%s", project_id, len(block.encode("utf-8")))
            return True
        except Exception as e:
            logger.error("[DAILYMD][ERROR] Text-only append failed project=%s: %s", project_id, e)
            return False


def daily_stats(project_id: str) -> Dict[str, int]:
    """Return Daily index size, indexed token count, and vector count.

    Args:
        project_id: Project whose Daily metadata is measured.

    Returns:
        A dict with ``daily_index_size_bytes`` (metadata file/serialized size),
        ``daily_tokens_indexed`` (summed entry tokens), and ``daily_vector_count``
        (number of entries).
    """
    meta_path, lock_path, _txt_path = _project_daily_paths(project_id)
    with FileLock(lock_path):
        entries = _load_metadata(meta_path)
    size_bytes = 0
    # Add metadata size (file or serialized estimate)
    try:
        if os.path.exists(meta_path):
            size_bytes += os.path.getsize(meta_path)
        else:
            size_bytes += len(json.dumps(entries).encode("utf-8")) if entries else 0
    except Exception:
        size_bytes += len(json.dumps(entries).encode("utf-8")) if entries else 0
    tokens = sum(int(e.get("tokens", 0)) for e in entries)
    with _CACHE_LOCK:
        cache_present = project_id in _CACHE and (_CACHE.get(project_id) is not None)
    logger.debug(
        "DailyRAG: stats project=%s vectors=%s tokens=%s size_bytes=%s (cache_present=%s, meta_present=%s)",
        project_id,
        len(entries),
        tokens,
        size_bytes,
        cache_present,
        os.path.exists(meta_path),
    )
    return {"daily_index_size_bytes": size_bytes, "daily_tokens_indexed": tokens, "daily_vector_count": len(entries)}


def backfill_daily_md_from_meta(project_id: str) -> bool:
    """Recreate a missing daily.md from daily.json in the canonical format.

    No-ops when daily.md already exists or daily.json has no entries. Backfills
    missing per-entry fields (timestamp, scopes, route, memory_id, etc.) and
    persists those updates back to daily.json when any were synthesized.

    Args:
        project_id: Project whose daily.md is regenerated.

    Returns:
        True when daily.md is written; False when skipped (already present or no
        entries) or the backfill fails.
    """
    meta_path, lock_path, md_path = _project_daily_paths(project_id)
    if os.path.isfile(md_path):
        return False
    with FileLock(lock_path):
        entries = _load_metadata(meta_path)
        if not entries:
            return False
        try:
            with open(md_path, "a", encoding="utf-8", newline="\n") as tf:
                first_ts = entries[0].get("timestamp") or entries[0].get("created_at") if entries else None
                memory_date = memory_date_from_local_timestamp(str(first_ts or ""))
                tf.write(_nl(render_artifact_header(
                    artifact_type="daily_memory",
                    project_id=project_id,
                    memory_date=memory_date,
                )))
                changed = False
                for e in entries:
                    ts = e.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    ns = "other"
                    keep = bool(e.get("keep", False))
                    text = e.get("text") or ""
                    ts_local = str(e.get("timestamp") or local_timestamp_from_iso(str(ts)))
                    # Best-effort split back into prompt/response
                    u, a = split_pair_text(str(text))
                    tags_meta = e.get("tags_meta") if isinstance(e, dict) else None
                    semantic_handle = _semantic_handle(tags_meta if isinstance(tags_meta, dict) else None)
                    if not e.get("timestamp"):
                        e["timestamp"] = ts_local
                        changed = True
                    if not e.get("entry_type"):
                        e["entry_type"] = "chat_pair"
                        changed = True
                    if not e.get("source_agent"):
                        e["source_agent"] = "syx"
                        changed = True
                    if not e.get("source_scope"):
                        e["source_scope"] = "dream" if e.get("entry_type") == "dream_output" else "daily"
                        changed = True
                    if not e.get("current_scope"):
                        e["current_scope"] = "dream" if e.get("entry_type") == "dream_output" else "daily"
                        changed = True
                    if not e.get("route"):
                        e["route"] = ns
                        changed = True
                    if not e.get("memory_id"):
                        e["memory_id"] = generate_memory_id(
                            project_id=project_id,
                            timestamp=ts_local,
                            source=str(e.get("source") or "chat"),
                            entry_type=str(e.get("entry_type") or "chat_pair"),
                            user_text=u,
                            assistant_text=a,
                            route=str(e.get("route") or ns),
                            semantic_handle=semantic_handle,
                            dream_output_type=e.get("dream_output_type") if isinstance(e.get("dream_output_type"), str) else None,
                            accepted_item_id=e.get("accepted_item_id") if isinstance(e.get("accepted_item_id"), str) else None,
                            origin_memory_ids=e.get("origin_memory_ids") if isinstance(e.get("origin_memory_ids"), list) else None,
                            dream_content=a if e.get("entry_type") == "dream_output" else None,
                        )
                        changed = True
                    block = _render_markdown_entry(
                        e,
                        user_text=u,
                        assistant_text=a,
                    )
                    tf.write(_nl(block))
                if changed:
                    _save_metadata(meta_path, entries)
            logger.warning("[DAILYMD] Backfilled daily.md (canonical format) for project=%s", project_id)
            return True
        except Exception as e:
            logger.error("[DAILYMD] Failed backfill for project=%s: %s", project_id, e)
            return False


