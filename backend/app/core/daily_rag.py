"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

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
from typing import List, Dict, Any, Optional, Tuple, Set

from filelock import FileLock
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS

from .config import get_settings
from .similarity import cosine_from_l2_distance

logger = logging.getLogger(__name__)

def _nl(s: str) -> str:
    """Normalize line endings to LF to avoid mixed terminators."""
    return s.replace("\r\n", "\n").replace("\r", "\n")

_BEGIN_DAILY_PAIR = "=== BEGIN DAILY PAIR ==="
_END_DAILY_PAIR = "=== END DAILY PAIR ==="

def _format_tags_block(tags_meta: Optional[Dict[str, str]]) -> str:
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
        # Keep the lines stable; daily.txt readers can ignore them if undesired.
        return f"#topics: {topics}\n#intent: {intent}\n#type: {tag_type}\n"
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
    """Per-project in-memory Daily FAISS cache state."""
    embedding_model: str
    vs: Optional[FAISS]  # None means empty (no vectors yet)
    # Canonical daily.json snapshot keyed by stable entry id.
    # Used to join retrieval hits (via metadata daily_entry_id) back to authoritative metadata.
    meta_by_id: Dict[str, Dict[str, Any]]


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
    # DELTA-A.3: clear ephemeral previous rolled-off pair pointer (best-effort)
    try:
        from .memory import get_memory_manager
        try:
            get_memory_manager().clear_last_rolled_off_pair(project_id)
        except Exception:
            pass
    except Exception:
        pass
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
            for e in entries:
                t = e.get("embed_text") or e.get("text")
                if not isinstance(t, str) or not t.strip():
                    continue
                ns = (e.get("namespace") or "general")
                eid = e.get("id")
                if isinstance(eid, str) and eid.strip():
                    meta_by_id[eid] = e
                texts.append(t)
                metas.append(
                    {
                        "source": "daily",
                        "namespace": str(ns).lower(),
                        "daily_entry_id": str(eid) if eid is not None else None,
                        "day_sequence": e.get("day_sequence"),
                    }
                )
            if not texts:
                with _CACHE_LOCK:
                    _CACHE[project_id] = _DailyCache(embedding_model=runtime_model, vs=None, meta_by_id={})
                logger.debug("DailyRAG: rebuilt empty in-memory cache project=%s (reason=%s)", project_id, reason)
                return True
            embeddings = OpenAIEmbeddings(model=runtime_model, api_key=settings.openai_api_key)
            try:
                vs = FAISS.from_texts(texts=texts, embedding=embeddings, metadatas=metas, normalize_L2=True)
            except TypeError:
                vs = FAISS.from_texts(texts=texts, embedding=embeddings, metadatas=metas)
            with _CACHE_LOCK:
                _CACHE[project_id] = _DailyCache(embedding_model=runtime_model, vs=vs, meta_by_id=meta_by_id)
            logger.info("DailyRAG: rebuilt in-memory cache project=%s vectors=%s (reason=%s)", project_id, len(texts), reason)
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
                # If we can't validate, rebuild per delta (but do not retry this request elsewhere).
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
    tags_meta: Optional[Dict[str, str]] = None,
    write_daily_txt: bool = True,
) -> bool:
    """Append a single embedded pair to the daily index and metadata.
    Note: We don't persist raw FAISS via langchain here; for V2.3 we only track metadata and rely on embeddings at retrieval-time for simplicity.
    """
    settings = get_settings()
    meta_path, lock_path, txt_path = _project_daily_paths(project_id)
    text_for_embed = embed_override if embed_override else pair_text
    with FileLock(lock_path):
        entries = _load_metadata(meta_path)
        day_sequence = (entries[-1]["day_sequence"] + 1) if entries else 1
        ns = (namespace or "general").lower()
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
            "namespace": ns,
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
                except Exception:
                    pass
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
                embeddings = OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.openai_api_key)
                try:
                    vs = FAISS.from_texts(
                        texts=[text_for_embed],
                        embedding=embeddings,
                        metadatas=[{"source": "daily", "namespace": ns, "daily_entry_id": entry.get("id"), "day_sequence": entry.get("day_sequence")}],
                        normalize_L2=True,
                    )
                except TypeError:
                    vs = FAISS.from_texts(
                        texts=[text_for_embed],
                        embedding=embeddings,
                        metadatas=[{"source": "daily", "namespace": ns, "daily_entry_id": entry.get("id"), "day_sequence": entry.get("day_sequence")}],
                    )
                with _CACHE_LOCK:
                    _CACHE[project_id] = _DailyCache(
                        embedding_model=settings.embedding_model,
                        vs=vs,
                        meta_by_id={str(entry.get("id")): entry} if entry.get("id") else {},
                    )
                return True
            # Normal path: incremental add
            cache.vs.add_texts([text_for_embed], metadatas=[{"source": "daily", "namespace": ns, "daily_entry_id": entry.get("id"), "day_sequence": entry.get("day_sequence")}])
            # Update in-memory authoritative mapping for deterministic joins
            try:
                eid2 = entry.get("id")
                if eid2:
                    cache.meta_by_id[str(eid2)] = entry
            except Exception:
                pass
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
) -> bool:
    """
    Append a single pair to daily.txt only (no FAISS, no daily.json).
    Used by Sleep flush to move active DB pairs into daily text at start of cycle.
    """
    _meta_path, lock_path, txt_path = _project_daily_paths(project_id)
    ns = (namespace or "general").lower()
    with FileLock(lock_path):
        try:
            # Ensure BEGIN header exists
            try:
                if (not os.path.isfile(txt_path)) or os.path.getsize(txt_path) == 0:
                    begin_date = time.strftime("%m/%d/%Y", time.localtime())
                    with open(txt_path, "a", encoding="utf-8", newline="\n") as tf:
                        tf.write(_nl(f"=== BEGIN DAILY MEMORY: {begin_date} ===\n\n"))
            except Exception:
                pass
            ts = created_at_iso_utc or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            # Localize timestamp to MM-DD-YYYY_HH:MM:SS
            try:
                tstruct = time.strptime(ts.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
                ts_local = time.strftime("%m-%d-%Y_%H:%M:%S", time.localtime(time.mktime(tstruct)))
            except Exception:
                ts_local = ts
            block = (
                f"{_BEGIN_DAILY_PAIR}\n"
                f"#timestamp: {ts_local}\n"
                f"#route: {ns}\n"
                f"#keep: {str(bool(keep)).lower()}\n"
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


def _cosine_from_l2_dist_sq(d2: float) -> float:
    # For unit vectors: d^2 = 2(1 - cos)
    return max(0.0, min(1.0, 1.0 - (d2 / 2.0)))


def retrieve_daily(project_id: str, query: str, top_k: int, score_threshold: float) -> List[Tuple[str, float, Optional[str]]]:
    """Retrieve from the in-memory Daily FAISS cache. Returns list of (text, cosine, namespace)."""
    if top_k <= 0:
        return []
    settings = get_settings()
    # Warm lazily on first use for a project (non-blocking; return empty for this request).
    with _CACHE_LOCK:
        cache = _CACHE.get(project_id)
    if cache is None:
        start_daily_cache_rebuild(project_id, reason="retrieve_warm")
        return []
    with _CACHE_LOCK:
        cache = _CACHE.get(project_id)
    if cache is None or cache.vs is None:
        return []
    # If runtime model changed vs cache, rebuild but do not retry this request (return empty)
    if cache.embedding_model != settings.embedding_model:
        start_daily_cache_rebuild(project_id, reason="retrieve_model_mismatch")
        return []
    try:
        results = cache.vs.similarity_search_with_score(query, k=top_k)
    except Exception as e:
        logger.warning("DailyRAG: retrieve failed project=%s: %s", project_id, e)
        start_daily_cache_rebuild(project_id, reason="retrieve_exception")
        return []
    scored: List[Tuple[str, float, Optional[str]]] = []
    for doc, dist in results:
        d = float(dist)
        d2 = d * d
        cos_a = _cosine_from_l2_dist_sq(d2)
        cos_b = _cosine_from_l2_dist_sq(d) if d >= 0 else 0.0
        cos = max(min(cos_a, 1.0), min(cos_b, 1.0))
        if cos >= score_threshold:
            ns = (getattr(doc, "metadata", None) or {}).get("namespace")
            scored.append((doc.page_content, cos, ns))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:top_k]


def retrieve_daily_candidates(project_id: str, query: str, top_k: int) -> List[Dict[str, Any]]:
    """
    DELTA-A.4.1: Canonical Daily retrieval candidates (raw top-K, no thresholding, no boosting).

    Returns a list of candidate dicts in the same order returned by the underlying vector search.
    Each candidate includes authoritative metadata sourced from daily.json via the in-memory cache's
    `meta_by_id` mapping, keyed by stable `daily_entry_id`.
    """
    if top_k <= 0:
        return []
    settings = get_settings()
    # Warm lazily on first use for a project (non-blocking; return empty for this request).
    with _CACHE_LOCK:
        cache = _CACHE.get(project_id)
    if cache is None:
        start_daily_cache_rebuild(project_id, reason="retrieve_candidates_warm")
        return []
    with _CACHE_LOCK:
        cache = _CACHE.get(project_id)
    if cache is None or cache.vs is None:
        return []
    # If runtime model changed vs cache, rebuild but do not retry this request (return empty).
    if cache.embedding_model != settings.embedding_model:
        start_daily_cache_rebuild(project_id, reason="retrieve_candidates_model_mismatch")
        return []
    try:
        results = cache.vs.similarity_search_with_score(query, k=top_k)
    except Exception as e:
        logger.warning("DailyRAG: candidate retrieve failed project=%s: %s", project_id, e)
        start_daily_cache_rebuild(project_id, reason="retrieve_candidates_exception")
        return []

    out: List[Dict[str, Any]] = []
    for doc, dist in results:
        cos = cosine_from_l2_distance(dist)
        md = getattr(doc, "metadata", None) or {}
        eid = md.get("daily_entry_id")
        entry = None
        try:
            if eid is not None:
                entry = cache.meta_by_id.get(str(eid))
        except Exception:
            entry = None
        # Authoritative metadata from daily.json when available; otherwise best-effort from doc metadata.
        created_at = (entry.get("created_at") if isinstance(entry, dict) else None)
        route = (entry.get("namespace") if isinstance(entry, dict) else md.get("namespace"))
        tags_meta = (entry.get("tags_meta") if isinstance(entry, dict) else None)
        topics = (tags_meta.get("topics") if isinstance(tags_meta, dict) else None)
        intent = (tags_meta.get("intent") if isinstance(tags_meta, dict) else None)
        tag_type = (tags_meta.get("type") if isinstance(tags_meta, dict) else None)
        out.append(
            {
                "source": "daily",
                "text": getattr(doc, "page_content", "") or "",
                "score": float(cos),
                "metadata": {
                    "id": str(eid) if eid is not None else None,
                    "timestamp": created_at,
                    "route": (str(route).lower() if isinstance(route, str) else route),
                    "tags": (entry.get("tags") if isinstance(entry, dict) else None),
                    "topics": topics,
                    "intent": intent,
                    "type": tag_type,
                    "tags_meta": tags_meta,
                    "keep": (entry.get("keep") if isinstance(entry, dict) else None),
                    "day_sequence": (entry.get("day_sequence") if isinstance(entry, dict) else md.get("day_sequence")),
                    "pair_ids": (entry.get("pair_ids") if isinstance(entry, dict) else None),
                    "source": (entry.get("source") if isinstance(entry, dict) else "daily"),
                },
            }
        )
    return out


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
                    ns = (e.get("namespace") or "general").lower()
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


