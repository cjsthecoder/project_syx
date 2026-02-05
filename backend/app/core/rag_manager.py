"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

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
from typing import List, Tuple, Optional, Dict, Any
import json
import logging
import threading

try:
    # Newer split package
    from langchain_text_splitters import RecursiveCharacterTextSplitter  # type: ignore
except Exception:
    # Fallback to legacy import path
    from langchain.text_splitter import RecursiveCharacterTextSplitter  # type: ignore
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings

from .config import get_settings, compute_per_source_k
from .embed_batching import iter_token_batches
import os
from .database import get_session
from .db_models import File as FileRow
from sqlmodel import select

logger = logging.getLogger(__name__)
from .similarity import cosine_from_l2_distance
from .retrieval_ordering import order_candidates_by_similarity_score

try:
    import tiktoken  # type: ignore
except Exception:
    tiktoken = None  # token counting optional until installed


def _read_file_text(path: str) -> List[Tuple[str, dict]]:
    """Return list of (text, metadata) chunks at file-level (before splitting)."""
    name = os.path.basename(path)
    _, ext = os.path.splitext(name)
    ext = ext.lower()
    if ext in {".txt", ".md"}:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        return [(content, {"filename": name})]
    elif ext == ".pdf":
        try:
            from pypdf import PdfReader
        except Exception as e:
            raise RuntimeError(f"pypdf not available: {e}")
        reader = PdfReader(path)
        chunks: List[Tuple[str, dict]] = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            chunks.append((text, {"filename": name, "page_number": i + 1}))
        return chunks
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
    """Rebuild FAISS index for a project from uploads directory.

    Returns the directory where the index is saved.
    """
    settings = get_settings()
    uploads_dir = os.path.join("memory", project_id, "uploads")
    faiss_dir = os.path.join("memory", project_id, "faiss")
    os.makedirs(faiss_dir, exist_ok=True)

    files = []
    if os.path.isdir(uploads_dir):
        for root, _, names in os.walk(uploads_dir):
            for name in names:
                files.append(os.path.join(root, name))

    texts: List[str] = []
    metadatas: List[dict] = []
    collected = []
    # For per-file stats
    file_token_sums: Dict[str, int] = {}
    file_page_max: Dict[str, int] = {}
    for f in files:
        for raw_text, meta in _read_file_text(f):
            collected.append((raw_text, meta))
            fname = meta.get("filename") or os.path.basename(f)
            file_token_sums[fname] = file_token_sums.get(fname, 0) + _count_tokens(raw_text)
            pg = int(meta.get("page_number") or 1)
            file_page_max[fname] = max(file_page_max.get(fname, 1), pg)

    if not collected:
        # No files -> clear any existing index
        try:
            for n in os.listdir(faiss_dir):
                os.remove(os.path.join(faiss_dir, n))
        except Exception:
            pass
        return faiss_dir

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )

    now_iso = datetime.utcnow().isoformat()
    for raw_text, base_meta in collected:
        for i, chunk in enumerate(splitter.split_text(raw_text)):
            texts.append(chunk)
            m = {
                "project_id": project_id,
                "filename": base_meta.get("filename"),
                "page_number": base_meta.get("page_number"),
                "chunk_id": i,
                "timestamp": now_iso,
            }
            metadatas.append(m)

    embeddings = OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.openai_api_key)
    max_req_tokens = int(getattr(settings, "max_embed_tokens_per_request", 250_000))

    # Build vectorstore incrementally with token-aware batching to avoid provider-side
    # "max tokens per request" failures on large corpora.
    vs: Optional[FAISS] = None
    batch_idx = 0
    for batch_texts, batch_metas, est_tokens in iter_token_batches(
        texts,
        metadatas=metadatas,
        max_tokens_per_batch=max_req_tokens,
        model_name=settings.embedding_model,
    ):
        batch_idx += 1
        vecs = embeddings.embed_documents(list(batch_texts))
        if vs is None:
            # Normalize L2 to make cosine similarity computable via L2 distance relation
            try:
                vs = FAISS.from_embeddings(
                    list(zip(batch_texts, vecs)),
                    embeddings,
                    metadatas=batch_metas,
                    normalize_L2=True,
                )
            except TypeError:
                # Older versions may not support normalize_L2
                vs = FAISS.from_embeddings(list(zip(batch_texts, vecs)), embeddings, metadatas=batch_metas)
        else:
            vs.add_embeddings(list(zip(batch_texts, vecs)), metadatas=batch_metas)
        logger.debug(
            "RAG: embedded batch=%s texts=%s est_tokens=%s max_req_tokens=%s",
            int(batch_idx),
            int(len(batch_texts)),
            int(est_tokens),
            int(max_req_tokens),
        )

    if vs is None:
        # Should be unreachable because collected/texts is non-empty, but keep safe behavior.
        try:
            for n in os.listdir(faiss_dir):
                os.remove(os.path.join(faiss_dir, n))
        except Exception:
            pass
        return faiss_dir
    # Save index
    vs.save_local(faiss_dir)

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
                    row.embedding_status = 'indexed'
                    session.add(row)
            session.commit()
    except Exception:
        pass
    return faiss_dir


def load_faiss_index(project_id: str) -> Optional[FAISS]:
    """Load FAISS index for project if exists and non-empty."""
    settings = get_settings()
    faiss_dir = os.path.join("memory", project_id, "faiss")
    if not os.path.isdir(faiss_dir):
        logger.debug(f"RAG: index directory missing for project '{project_id}' at {faiss_dir}")
        return None
    try:
        embeddings = OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.openai_api_key)
        try:
            vs = FAISS.load_local(faiss_dir, embeddings, allow_dangerous_deserialization=True)
        except TypeError:
            # Fallback for older versions without allow_dangerous_deserialization
            vs = FAISS.load_local(faiss_dir, embeddings)
        # Heuristic: if docstore empty, treat as no index
        if not getattr(vs, "docstore", None) or len(vs.docstore._dict) == 0:  # type: ignore
            logger.debug(f"RAG: loaded index for '{project_id}' but docstore is empty")
            return None
        logger.debug(f"RAG: loaded index for '{project_id}' with {len(vs.docstore._dict)} documents")
        return vs
    except Exception as e:
        logger.debug(f"RAG: failed to load index for '{project_id}': {e}")
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

    # Embed ONCE (shared query vector)
    qvec: Optional[List[float]] = None
    try:
        embeddings = OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.openai_api_key)
        qvec = embeddings.embed_query(query or "")
    except Exception as e:
        logger.warning("RAG: failed to embed query for canonical retrieval project=%s: %s", project_id, e)
        return []

    # Daily
    if "daily" in srcs:
        try:
            from .daily_rag import get_daily_source, notify_daily_search_failure

            ds = get_daily_source(project_id)
            if ds is not None:
                try:
                    results = ds.vs.similarity_search_with_score_by_vector(qvec, k=int(per_source_k))  # type: ignore[attr-defined]
                except Exception as e:
                    logger.warning("RAG: Daily candidate search failed project=%s: %s", project_id, e)
                    notify_daily_search_failure(project_id, reason="canonical_daily_search_exception")
                    results = []
                for doc, dist in results:
                    cos = cosine_from_l2_distance(dist)
                    md = getattr(doc, "metadata", None) or {}
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
                                "text": getattr(doc, "page_content", "") or "",
                                "score": float(cos),
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
                                },
                            }
                        )
                    else:
                        # Join-miss: return candidate with partial metadata (lossless recall).
                        out.append(
                            {
                                "source": "daily",
                                "text": getattr(doc, "page_content", "") or "",
                                "score": float(cos),
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
                                },
                            }
                        )
                daily_count = len(results)
        except Exception:
            # Daily source owns rebuild semantics; degrade gracefully.
            pass

    # LTM (main FAISS index)
    if "ltm" in srcs:
        def _ltm_search_by_vector() -> List[Tuple[Any, float]]:
            """
            Source-owned LTM search wrapper (best-effort rebuild-on-error; no retry in-request).
            Canonical retrieval calls this but does not own rebuild semantics.
            """
            vs = load_faiss_index(project_id)
            if not vs:
                return []
            try:
                return list(vs.similarity_search_with_score_by_vector(qvec, k=int(per_source_k)))  # type: ignore[attr-defined]
            except Exception as e:
                try:
                    logger.warning("RAG: LTM candidate search failed project=%s; scheduling rebuild: %s", project_id, e)

                    def _rebuild() -> None:
                        try:
                            rebuild_faiss_index(project_id)
                        except Exception:
                            pass

                    threading.Thread(target=_rebuild, name=f"ltm-rebuild-{project_id[:8]}", daemon=True).start()
                except Exception:
                    pass
                return []

        results = _ltm_search_by_vector()
        for doc, dist in results:
                md = getattr(doc, "metadata", None) or {}
                cos = cosine_from_l2_distance(dist)
                out.append(
                    {
                        "source": "ltm",
                        "text": getattr(doc, "page_content", "") or "",
                        "score": float(cos),
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
        score = float(c.get("score") or 0.0)  # raw cosine
        md = (c.get("metadata") or {}) if isinstance(c.get("metadata"), dict) else {}

        t = _count_tokens(txt)
        if src == "daily":
            daily_texts.append(txt)
            daily_scores.append(score)
        else:
            main_texts.append(txt)
            main_scores.append(score)
        tokens_used_total += t

        # Candidate header (keeps ordering explicit; score is raw cosine).
        if src == "ltm":
            header = f"Snippet {idx+1} (source=ltm, score={score:.2f}, file={md.get('filename')}, page={md.get('page_number')})\n"
        else:
            header = f"Snippet {idx+1} (source=daily, score={score:.2f}, route={md.get('route')})\n"
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


