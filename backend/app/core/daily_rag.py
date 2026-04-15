"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
from __future__ import annotations

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

from .config import get_settings
from .embed_batching import iter_token_batches
from .vector_index import VectorEntry, VectorHit, VectorIndexInfo, VectorIndex
from ..llm_model.llm_client import get_llm_client
from ..utils.debug_utils import write_debug_file
logger = logging.getLogger(__name__)

def _normalize_rows(v: np.ndarray) -> np.ndarray:
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
        self.index: faiss.IndexFlatIP = faiss.IndexFlatIP(int(dim))
        self.index_to_id: List[str] = []
        self.docstore: Dict[str, Dict[str, Any]] = {}
        self._dim: int = int(dim)

    def size(self) -> int:
        return int(self.index.ntotal)

    def info(self) -> VectorIndexInfo:
        return VectorIndexInfo(index_kind="daily", dim=int(self._dim), score_mode="cosine_ip_mapped_01")

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

    def add(self, *, item_id: str, vector: List[float], text: str, metadata: Dict[str, Any]) -> None:
        mat = _normalize_rows(np.array([vector], dtype="float32"))
        if mat.shape[1] != int(self.index.d):
            raise RuntimeError(f"DailyVectorIndex dim mismatch: got={mat.shape[1]} expected={self.index.d}")
        self.index.add(mat)
        self.index_to_id.append(str(item_id))
        self.docstore[str(item_id)] = {"text": str(text or ""), "metadata": dict(metadata or {})}

    def add_many(
        self, *, item_ids: List[str], vectors: List[List[float]], texts: List[str], metadatas: List[dict]
    ) -> None:
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
    """
    Format tag metadata lines for inclusion in daily.txt.

    Uses the same 3-line convention as the roll-off tagger output.
    Returns a string that already ends with a newline (or "" if no tags).
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
    except Exception:
        return ""

def _project_daily_paths(project_id: str) -> Tuple[str, str, str]:
    base_dir = os.path.join("memory", project_id)
    os.makedirs(base_dir, exist_ok=True)
    meta_path = os.path.join(base_dir, "daily.json")
    lock_path = os.path.join(base_dir, "daily.lock")
    txt_path = os.path.join(base_dir, "daily.txt")
    return meta_path, lock_path, txt_path


@dataclass
class _DailyCache:
    """Per-project in-memory Daily cache state (raw FAISS, no LangChain)."""
    embedding_model: str
    vs: Optional[VectorIndex]  # None means empty (no vectors yet)
    # Canonical daily.json snapshot keyed by stable entry id.
    # Used to join retrieval hits (via metadata daily_entry_id) back to authoritative metadata.
    meta_by_id: Dict[str, Dict[str, Any]]
    # O(1) adjacency lookup by day_sequence (chunk_seq).
    id_by_seq: Dict[int, str]


@dataclass
class DailySource:
    """
    Source adapter boundary for Daily.

    Owns no retrieval mechanics. Provides a safe-to-use vectorstore handle plus
    authoritative metadata join map.
    """
    embedding_model: str
    vs: VectorIndex
    meta_by_id: Dict[str, Dict[str, Any]]
    id_by_seq: Dict[int, str]


def get_daily_source(project_id: str) -> Optional[DailySource]:
    """
    Provide a safe Daily vectorstore handle + authoritative metadata.

    - Daily lifecycle (warm/rebuild/mismatch) remains owned by daily_rag.py.
    - Canonical retrieval owns embedding + per-source K + search loop + shaping.
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
    if cache.embedding_model != settings.embedding_model:
        start_daily_cache_rebuild(project_id, reason="get_source_model_mismatch")
        return None
    return DailySource(
        embedding_model=cache.embedding_model,
        vs=cache.vs,
        meta_by_id=cache.meta_by_id,
        id_by_seq=cache.id_by_seq,
    )


def daily_lookup_adjacent_entry_ids(project_id: str, *, day_sequence: int) -> Dict[str, Optional[str]]:
    """
    Deterministic neighbor lookup for Daily entries.

    Returns dict with keys: prev_entry_id, next_entry_id.
    If cache is cold/unavailable, returns None values (no expansion).
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
    """Source-owned rebuild trigger for canonical to call on Daily search failure."""
    try:
        start_daily_cache_rebuild(project_id, reason=reason)
    except Exception as exc:
        logger.warning("DailyRAG: failed scheduling cache rebuild project=%s reason=%s detail=%s", project_id, reason, exc)


_CACHE: Dict[str, _DailyCache] = {}
_CACHE_LOCK = threading.Lock()
_PROJECT_LOCKS: Dict[str, threading.RLock] = {}
_WARMING: Set[str] = set()


def _get_project_lock(project_id: str) -> threading.RLock:
    with _CACHE_LOCK:
        lock = _PROJECT_LOCKS.get(project_id)
        if lock is None:
            # Re-entrant: ensure_daily_cache() may call rebuild_daily_cache()
            lock = threading.RLock()
            _PROJECT_LOCKS[project_id] = lock
        return lock


def clear_daily_cache(project_id: str) -> None:
    """Drop the in-memory Daily cache for a project (no disk changes)."""
    with _CACHE_LOCK:
        _CACHE.pop(project_id, None)
        _WARMING.discard(project_id)


def start_daily_cache_rebuild(project_id: str, reason: str) -> None:
    """Kick off a background rebuild of the in-memory cache (non-blocking)."""
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
    models: Set[str] = set()
    for e in entries:
        m = e.get("embedding_model")
        if isinstance(m, str) and m.strip():
            models.add(m.strip())
    return models


def _load_metadata(meta_path: str) -> List[Dict[str, Any]]:
    if not os.path.isfile(meta_path):
        return []
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"DailyRAG: failed to load metadata {meta_path}: {e}")
        return []


def _save_metadata(meta_path: str, entries: List[Dict[str, Any]]) -> None:
    tmp_path = meta_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(entries, f)
    os.replace(tmp_path, meta_path)


def reset_daily(project_id: str) -> None:
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


def rebuild_daily_cache(project_id: str, reason: str) -> bool:
    """Force rebuild of the in-memory cache from daily.json (updating metadata as required)."""
    settings = get_settings()
    runtime_model = settings.embedding_model
    meta_path, lock_path, _txt_path = _project_daily_paths(project_id)
    lock = _get_project_lock(project_id)
    with lock:
        # Always clear first to avoid using a corrupt instance
        clear_daily_cache(project_id)
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
        # Build the in-memory vectorstore from the snapshot we just loaded/updated.
        try:
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
                        "day_sequence": e.get("day_sequence"),
                        # Adjacency identity for Daily entries.
                        "doc_id": "daily",
                        "chunk_seq": e.get("day_sequence"),
                    }
                )
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

            vs: Optional[DailyVectorIndex] = None
            batch_idx = 0
            llm = get_llm_client()
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
            # Debug report (human-readable .txt)
            try:
                ts = time.strftime("%Y-%m-%dT%H-%M-%S", time.localtime())
                seqs = sorted(id_by_seq.keys())
                body = (
                    f"# timestamp: {ts}\n"
                    f"# project_id: {project_id}\n"
                    f"# reason: {reason}\n"
                    f"# embedding_model: {runtime_model}\n"
                    f"# vectors: {len(texts)}\n"
                    f"# day_sequence_min: {seqs[0] if seqs else None}\n"
                    f"# day_sequence_max: {seqs[-1] if seqs else None}\n"
                )
                write_debug_file(project_id, f"rag/daily/{ts}_daily_cache_report.txt", body)
            except Exception as exc:
                logger.warning("DailyRAG: failed writing daily cache debug report project=%s detail=%s", project_id, exc)
            return True
        except Exception as be:
            logger.error("DailyRAG: rebuild failed project=%s reason=%s err=%s", project_id, reason, be)
            with _CACHE_LOCK:
                _CACHE.pop(project_id, None)
            return False


def ensure_daily_cache(project_id: str, reason: str = "warm") -> bool:
    """Ensure a project's in-memory cache exists and matches daily.json + EMBEDDING_MODEL."""
    settings = get_settings()
    runtime_model = settings.embedding_model
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
            except Exception:
                # If we can't validate, rebuild and do not retry this request elsewhere.
                pass
        # Rebuild if missing or if daily.json indicates mismatch with runtime model.
        return rebuild_daily_cache(project_id, reason=reason)


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
    write_daily_txt: bool = True,
    update_cache: bool = True,
) -> bool:
    """Append a single embedded pair to the daily index and metadata.
    Note: We don't persist raw FAISS via langchain here; for V2.3 we only track metadata and rely on embeddings at retrieval-time for simplicity.
    When update_cache is False, only daily.json (and optionally daily.txt) are updated; caller is responsible for rebuilding the in-memory RAG once (e.g. dream batch).
    """
    settings = get_settings()
    meta_path, lock_path, txt_path = _project_daily_paths(project_id)
    text_for_embed = embed_override if embed_override else pair_text
    with FileLock(lock_path):
        entries = _load_metadata(meta_path)
        day_sequence = (entries[-1]["day_sequence"] + 1) if entries else 1
        ns = (namespace or "other").lower()
        entry = {
            "id": f"{int(time.time()*1000)}-{len(entries)+1}",
            "project_id": project_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pair_ids": [str(user_msg_id), str(assistant_msg_id)],
            "text": pair_text,
            # The in-memory FAISS cache is rebuilt from daily.json; preserve vector content explicitly.
            "embed_text": text_for_embed,
            "tokens": int(tokens),
            "embedding_model": settings.embedding_model,
            "source": "chat",
            "scope": "daily",
            "keep": bool(keep),
            "confidence": 1.0,
            "tags": ["rolled_off"],
            "day_sequence": day_sequence,
        }
        if tags_meta:
            entry["tags_meta"] = tags_meta
        entries.append(entry)
        _save_metadata(meta_path, entries)
        # Append to daily.txt (human-readable) unless explicitly skipped
        if write_daily_txt:
            try:
                # If first write, add BEGIN header with local date (MM/DD/YYYY)
                try:
                    if (not os.path.isfile(txt_path)) or os.path.getsize(txt_path) == 0:
                        begin_date = time.strftime("%m/%d/%Y", time.localtime())
                        with open(txt_path, "a", encoding="utf-8", newline="\n") as tf:
                            tf.write(_nl(f"=== BEGIN DAILY MEMORY: {begin_date} ===\n\n"))
                except Exception as exc:
                    logger.warning("DailyRAG: failed ensuring daily BEGIN header project=%s path=%s detail=%s", project_id, txt_path, exc)
                ts = entry["created_at"]
                # Split pair_text into user and assistant parts safely
                if "\nAssistant:" in pair_text:
                    _user_part, _assistant_part = pair_text.split("\nAssistant:", 1)
                    user_text = _user_part.replace("User:", "", 1).strip()
                    assistant_text = _assistant_part.strip()
                else:
                    user_text = ""
                    assistant_text = pair_text.strip()
                # New V3.2 header + block format (local time MM-DD-YYYY_HH:MM:SS)
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
                    f"{user_text}\n"
                    f"\n"
                    f"*** ASSISTANT (data-message-author-role: assistant) ***\n"
                    f"{assistant_text}\n"
                    f"\n"
                    f"{_END_DAILY_PAIR}\n"
                    f"\n"
                )
                with open(txt_path, "a", encoding="utf-8", newline="\n") as tf:
                    tf.write(_nl(block))
                logger.debug("[DAILYTXT] project=%s wrote %s bytes", project_id, len(block.encode('utf-8')))
            except Exception as te:
                logger.error("DailyRAG: failed writing daily.txt: %s", te)
    if not update_cache:
        return True
    # Update in-memory cache
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
            if cache.embedding_model != settings.embedding_model:
                start_daily_cache_rebuild(project_id, reason="append_model_mismatch")
                return False
            # If empty cache, create a new vectorstore with this single entry
            if cache.vs is None:
                llm = get_llm_client()
                vecs = llm.embed([text_for_embed], model=settings.embedding_model).vectors
                if not vecs:
                    start_daily_cache_rebuild(project_id, reason="append_embed_empty")
                    return False
                vs = DailyVectorIndex(dim=len(vecs[0]))
                md0 = {
                    "source": "daily",
                    "daily_entry_id": entry.get("id"),
                    "day_sequence": entry.get("day_sequence"),
                    "doc_id": "daily",
                    "chunk_seq": entry.get("day_sequence"),
                }
                vs.add(item_id=str(entry.get("id") or f"daily::seq={entry.get('day_sequence')}"), vector=vecs[0], text=text_for_embed, metadata=md0)
                with _CACHE_LOCK:
                    _CACHE[project_id] = _DailyCache(
                        embedding_model=settings.embedding_model,
                        vs=vs,
                        meta_by_id={str(entry.get("id")): entry} if entry.get("id") else {},
                        id_by_seq={int(entry.get("day_sequence")): str(entry.get("id"))}
                        if entry.get("id") and entry.get("day_sequence") is not None
                        else {},
                    )
                return True
            # Normal path: incremental add
            llm = get_llm_client()
            vecs2 = llm.embed([text_for_embed], model=settings.embedding_model).vectors
            if not vecs2:
                start_daily_cache_rebuild(project_id, reason="append_embed_empty")
                return False
            md2 = {
                "source": "daily",
                "daily_entry_id": entry.get("id"),
                "day_sequence": entry.get("day_sequence"),
                "doc_id": "daily",
                "chunk_seq": entry.get("day_sequence"),
            }
            cache.vs.add(
                item_id=str(entry.get("id") or f"daily::seq={entry.get('day_sequence')}"),
                vector=vecs2[0],
                text=text_for_embed,
                metadata=md2,
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


def append_pair_text_only(
    project_id: str,
    user_text: str,
    assistant_text: str,
    created_at_iso_utc: Optional[str],
    namespace: Optional[str],
    keep: bool,
    tags_meta: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Append a single pair to daily.txt only (no FAISS, no daily.json).
    Used by Sleep flush to move active DB pairs into daily text at start of cycle.
    When tags_meta is provided, writes #topics, #intent, #type, #semantic_handle (same format as roll-off).
    """
    _meta_path, lock_path, txt_path = _project_daily_paths(project_id)
    ns = (namespace or "other").lower()
    with FileLock(lock_path):
        try:
            # Ensure BEGIN header exists
            try:
                if (not os.path.isfile(txt_path)) or os.path.getsize(txt_path) == 0:
                    begin_date = time.strftime("%m/%d/%Y", time.localtime())
                    with open(txt_path, "a", encoding="utf-8", newline="\n") as tf:
                        tf.write(_nl(f"=== BEGIN DAILY MEMORY: {begin_date} ===\n\n"))
            except Exception as exc:
                logger.warning("DailyRAG: failed ensuring text-only BEGIN header project=%s path=%s detail=%s", project_id, txt_path, exc)
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
            with open(txt_path, "a", encoding="utf-8", newline="\n") as tf:
                tf.write(_nl(block))
            logger.info("[DAILYTXT] Text-only append project=%s bytes=%s", project_id, len(block.encode("utf-8")))
            return True
        except Exception as e:
            logger.error("[DAILYTXT][ERROR] Text-only append failed project=%s: %s", project_id, e)
            return False


def daily_stats(project_id: str) -> Dict[str, int]:
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


def backfill_daily_txt_from_meta(project_id: str) -> bool:
    """If daily.json exists and daily.txt missing, write out text blocks for all entries (V3.2 format)."""
    meta_path, lock_path, txt_path = _project_daily_paths(project_id)
    if os.path.isfile(txt_path):
        return False
    with FileLock(lock_path):
        entries = _load_metadata(meta_path)
        if not entries:
            return False
        try:
            with open(txt_path, "a", encoding="utf-8", newline="\n") as tf:
                # Write BEGIN header once (local date MM/DD/YYYY)
                begin_date = time.strftime("%m/%d/%Y", time.localtime())
                tf.write(_nl(f"=== BEGIN DAILY MEMORY: {begin_date} ===\n\n"))
                for e in entries:
                    ts = e.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    ns = "other"
                    keep = bool(e.get("keep", False))
                    text = e.get("text") or ""
                    # Localize timestamp to MM-DD-YYYY_HH:MM:SS
                    try:
                        tstruct = time.strptime(ts.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
                        ts_local = time.strftime("%m-%d-%Y_%H:%M:%S", time.localtime(time.mktime(tstruct)))
                    except Exception:
                        ts_local = ts
                    # Best-effort split back into prompt/response
                    if "\nAssistant:" in text:
                        u, a = text.split("\nAssistant:", 1)
                        u = u.replace("User:", "", 1).strip()
                        a = a.strip()
                    else:
                        u, a = "", text.strip()
                    tags_meta = e.get("tags_meta") if isinstance(e, dict) else None
                    tags_block = _format_tags_block(tags_meta if isinstance(tags_meta, dict) else None)
                    block = (
                        f"{_BEGIN_DAILY_PAIR}\n"
                        f"#timestamp: {ts_local}\n"
                        f"#route: {ns}\n"
                        f"#keep: {str(keep).lower()}\n"
                        f"{tags_block}"
                        f"\n"
                        f"--- USER (data-message-author-role: user) ---\n"
                        f"{u}\n"
                        f"\n"
                        f"*** ASSISTANT (data-message-author-role: assistant) ***\n"
                        f"{a}\n"
                        f"\n"
                        f"{_END_DAILY_PAIR}\n"
                        f"\n"
                    )
                    tf.write(_nl(block))
            logger.warning("[DAILYTXT] Backfilled daily.txt (V3.2 format) for project=%s", project_id)
            return True
        except Exception as e:
            logger.error("[DAILYTXT] Failed backfill for project=%s: %s", project_id, e)
            return False


