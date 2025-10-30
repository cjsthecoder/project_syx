from __future__ import annotations

import os
import json
import time
import logging
from typing import List, Dict, Any, Optional, Tuple

from filelock import FileLock
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS

from .config import get_settings
from ..utils.logging import get_route

logger = logging.getLogger(__name__)


def _project_daily_paths(project_id: str) -> Tuple[str, str, str]:
    base_dir = os.path.join("memory", project_id)
    os.makedirs(base_dir, exist_ok=True)
    faiss_dir = os.path.join(base_dir, "daily_faiss")
    os.makedirs(faiss_dir, exist_ok=True)
    meta_path = os.path.join(base_dir, "daily.json")
    lock_path = os.path.join(base_dir, "daily.lock")
    return faiss_dir, meta_path, lock_path


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
    faiss_dir, meta_path, lock_path = _project_daily_paths(project_id)
    with FileLock(lock_path):
        # remove faiss dir contents
        try:
            if os.path.isdir(faiss_dir):
                for n in os.listdir(faiss_dir):
                    try:
                        os.remove(os.path.join(faiss_dir, n))
                    except Exception:
                        pass
        except Exception:
            pass
        # remove metadata
        for p in (meta_path,):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
        logger.info(f"DailyRAG: reset daily files for project={project_id}")


def append_pair(project_id: str, pair_text: str, user_msg_id: int, assistant_msg_id: int, tokens: int) -> bool:
    """Append a single embedded pair to the daily index and metadata.
    Note: We don't persist raw FAISS via langchain here; for V2.3 we only track metadata and rely on embeddings at retrieval-time for simplicity.
    """
    settings = get_settings()
    faiss_dir, meta_path, lock_path = _project_daily_paths(project_id)
    with FileLock(lock_path):
        entries = _load_metadata(meta_path)
        day_sequence = (entries[-1]["day_sequence"] + 1) if entries else 1
        ns = (get_route() or "general").lower() or "general"
        entry = {
            "id": f"{int(time.time()*1000)}-{len(entries)+1}",
            "project_id": project_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pair_ids": [str(user_msg_id), str(assistant_msg_id)],
            "text": pair_text,
            "tokens": int(tokens),
            "embedding_model": settings.embedding_model,
            "source": "chat",
            "scope": "daily",
            "namespace": ns,
            "confidence": 1.0,
            "tags": ["rolled_off"],
            "day_sequence": day_sequence,
        }
        entries.append(entry)
        _save_metadata(meta_path, entries)
        # Append to FAISS index (directory-based)
        try:
            embeddings = OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.openai_api_key)
            vs: Optional[FAISS] = None
            try:
                # load existing
                try:
                    vs = FAISS.load_local(faiss_dir, embeddings, allow_dangerous_deserialization=True)
                except TypeError:
                    vs = FAISS.load_local(faiss_dir, embeddings)
            except Exception:
                vs = None
            if vs is None:
                # create new with normalize_L2 when available
                try:
                    vs = FAISS.from_texts(texts=[pair_text], embedding=embeddings, metadatas=[{"source": "daily", "namespace": ns}], normalize_L2=True)
                except TypeError:
                    vs = FAISS.from_texts(texts=[pair_text], embedding=embeddings, metadatas=[{"source": "daily", "namespace": ns}])
            else:
                vs.add_texts([pair_text], metadatas=[{"source": "daily", "namespace": ns}])
            vs.save_local(faiss_dir)
        except Exception as e:
            logger.error(f"DailyRAG: failed to update FAISS daily index: {e}")
        return True


def _cosine_from_l2_dist_sq(d2: float) -> float:
    # For unit vectors: d^2 = 2(1 - cos)
    return max(0.0, min(1.0, 1.0 - (d2 / 2.0)))


def retrieve_daily(project_id: str, query: str, top_k: int, score_threshold: float) -> List[Tuple[str, float, Optional[str]]]:
    """Retrieve from daily FAISS index. Returns list of (text, cosine, namespace)."""
    settings = get_settings()
    faiss_dir, meta_path, lock_path = _project_daily_paths(project_id)
    with FileLock(lock_path):
        try:
            embeddings = OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.openai_api_key)
            try:
                vs = FAISS.load_local(faiss_dir, embeddings, allow_dangerous_deserialization=True)
            except TypeError:
                vs = FAISS.load_local(faiss_dir, embeddings)
        except Exception as e:
            # Attempt on-demand backfill from metadata if index missing
            logger.debug(f"DailyRAG: no daily index for project={project_id}: {e}")
            try:
                entries = _load_metadata(meta_path)
                if entries:
                    texts = [e.get("text") or "" for e in entries if e.get("text")]
                    if texts:
                        try:
                            embeddings = OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.openai_api_key)
                            try:
                                vs = FAISS.from_texts(texts=texts, embedding=embeddings, metadatas=[{"source": "daily"}] * len(texts), normalize_L2=True)
                            except TypeError:
                                vs = FAISS.from_texts(texts=texts, embedding=embeddings, metadatas=[{"source": "daily"}] * len(texts))
                            vs.save_local(faiss_dir)
                            logger.info(f"DailyRAG: backfilled daily FAISS index for project={project_id} from metadata ({len(texts)} entries)")
                        except Exception as be:
                            logger.error(f"DailyRAG: failed to backfill daily index: {be}")
                            return []
                    else:
                        return []
                else:
                    return []
            except Exception:
                return []
    try:
        results = vs.similarity_search_with_score(query, k=top_k)  # type: ignore[name-defined]
    except Exception:
        results = []
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


def daily_stats(project_id: str) -> Dict[str, int]:
    faiss_dir, meta_path, lock_path = _project_daily_paths(project_id)
    with FileLock(lock_path):
        entries = _load_metadata(meta_path)
    size_bytes = 0
    # Sum FAISS dir contents
    try:
        if os.path.isdir(faiss_dir):
            for n in os.listdir(faiss_dir):
                p = os.path.join(faiss_dir, n)
                if os.path.isfile(p):
                    size_bytes += os.path.getsize(p)
    except Exception:
        pass
    # Add metadata size (file or serialized estimate)
    try:
        if os.path.exists(meta_path):
            size_bytes += os.path.getsize(meta_path)
        else:
            size_bytes += len(json.dumps(entries).encode("utf-8")) if entries else 0
    except Exception:
        size_bytes += len(json.dumps(entries).encode("utf-8")) if entries else 0
    tokens = sum(int(e.get("tokens", 0)) for e in entries)
    logger.debug(
        "DailyRAG: stats project=%s vectors=%s tokens=%s size_bytes=%s (faiss_present=%s, meta_present=%s)",
        project_id,
        len(entries),
        tokens,
        size_bytes,
        os.path.isdir(faiss_dir) and any(os.path.isfile(os.path.join(faiss_dir, n)) for n in os.listdir(faiss_dir) or []),
        os.path.exists(meta_path),
    )
    return {"daily_index_size_bytes": size_bytes, "daily_tokens_indexed": tokens, "daily_vector_count": len(entries)}


