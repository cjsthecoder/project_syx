"""
RAG manager for building FAISS indices per project (V2).

Policy:
- Embedding model: text-embedding-3-large (configurable)
- Chunking: RecursiveCharacterTextSplitter(size=chunk_size, overlap=chunk_overlap)
- Metadata per chunk: project_id, filename, page_number (if pdf), chunk_id, timestamp
- Recreate FAISS index per upload (fresh build from uploads dir)
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any
import json
import logging

try:
    # Newer split package
    from langchain_text_splitters import RecursiveCharacterTextSplitter  # type: ignore
except Exception:
    # Fallback to legacy import path
    from langchain.text_splitter import RecursiveCharacterTextSplitter  # type: ignore
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings

from .config import get_settings
import os
from .database import get_session
from .db_models import File as FileRow
from sqlmodel import select

logger = logging.getLogger(__name__)

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
        for name in os.listdir(uploads_dir):
            files.append(os.path.join(uploads_dir, name))

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
    # Normalize L2 to make cosine similarity computable via L2 distance relation
    try:
        vs = FAISS.from_texts(texts=texts, embedding=embeddings, metadatas=metadatas, normalize_L2=True)
    except TypeError:
        # Older versions may not support normalize_L2
        vs = FAISS.from_texts(texts=texts, embedding=embeddings, metadatas=metadatas)
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


def _cosine_from_l2_dist_sq(d2: float) -> float:
    # For unit vectors: d^2 = 2(1 - cos)
    return max(0.0, min(1.0, 1.0 - (d2 / 2.0)))


def retrieve_context(
    project_id: str,
    query: str,
    top_k: int,
    snippet_max_tokens: int,
    score_threshold: float,
    context_max_tokens: int,
) -> Dict[str, Any]:
    """Retrieve top-k snippets and assemble a single Context: block string.

    Returns dict with keys: context_text, snippets, tokens_used.
    """
    vs = load_faiss_index(project_id)
    if not vs:
        logger.debug(f"RAG: no index available for project '{project_id}', skipping retrieval")
        return {"context_text": "", "snippets": [], "tokens_used": 0}

    try:
        # similarity_search_with_score returns (Document, distance)
        results = vs.similarity_search_with_score(query, k=top_k)
    except Exception:
        results = []
    logger.debug(f"RAG: query='{query[:120]}...' top_k={top_k} got {len(results)} results (pre-filter)")

    filtered: List[Tuple[str, dict, float]] = []
    details = []
    scored: List[Tuple[str, dict, float, float]] = []  # (content, meta, cos, dist)
    for doc, dist in results:
        # dist is L2 distance; FAISS in LangChain returns distance (not squared) sometimes;
        # use d^2 approximation for cosine if needed
        d = float(dist)
        d2 = d * d
        # try both interpretations and pick the higher cosine within bounds
        cos_a = _cosine_from_l2_dist_sq(d2)
        cos_b = _cosine_from_l2_dist_sq(d) if d >= 0 else 0.0
        cos = max(min(cos_a, 1.0), min(cos_b, 1.0))
        if cos >= score_threshold:
            filtered.append((doc.page_content, doc.metadata or {}, cos))
        scored.append((doc.page_content, doc.metadata or {}, cos, d))
        details.append({
            "file": (doc.metadata or {}).get("filename"),
            "page": (doc.metadata or {}).get("page_number"),
            "cos": round(cos, 3),
            "dist": round(d, 4),
        })
    logger.debug(f"RAG: filtered {len(filtered)} >= threshold {score_threshold}; details={details}")

    # Build context respecting token caps
    tokens_used = 0
    pieces: List[str] = []
    for i, (content, meta, score) in enumerate(filtered):
        trimmed = _trim_to_tokens(content, snippet_max_tokens)
        snippet_tokens = _count_tokens(trimmed)
        if tokens_used + snippet_tokens > context_max_tokens:
            break
        header = f"Snippet {i+1} (score={score:.2f}, file={meta.get('filename')}, page={meta.get('page_number')})\n"
        pieces.append(header + trimmed)
        tokens_used += snippet_tokens

    if not pieces:
        # Fallback: if nothing passed threshold, include the best-scoring snippet
        if scored:
            best = sorted(scored, key=lambda t: t[2], reverse=True)[0]
            content, meta, cos, _ = best
            trimmed = _trim_to_tokens(content, snippet_max_tokens)
            tokens_used = _count_tokens(trimmed)
            header = f"Snippet 1 (fallback, score={cos:.2f}, file={meta.get('filename')}, page={meta.get('page_number')})\n"
            context_text = "Context:\n---\n" + header + trimmed
            logger.debug("RAG: fallback applied - included top-scoring snippet despite threshold")
            return {"context_text": context_text, "snippets": [trimmed], "tokens_used": tokens_used}
        logger.debug("RAG: no snippets selected after token capping and no fallback available")
        return {"context_text": "", "snippets": [], "tokens_used": 0}

    context_text = "Context:\n---\n" + "\n\n---\n".join(pieces)
    logger.debug(f"RAG: built context block tokens_used={tokens_used} snippets={len(pieces)}")
    return {"context_text": context_text, "snippets": pieces, "tokens_used": tokens_used}


def merge_daily_and_main(
    project_id: str,
    query: str,
    main_top_k: int,
    main_snippet_max_tokens: int,
    main_threshold: float,
    daily_top_k: int,
    daily_threshold: float,
    daily_weight: float,
    daily_max_tokens: int,
    global_context_max_tokens: int,
    dedupe_exact: bool,
    dedupe_near: bool,
    dedupe_similarity_threshold: float,
    prefer_daily: bool,
    topics: Optional[List[str]] = None,
    preferred_namespace: Optional[str] = None,
    topic_boost: Optional[float] = None,
    decision_boost: Optional[float] = None,
    question_boost: Optional[float] = None,
) -> Dict[str, Any]:
    """Retrieve from daily and main, apply weights/dedupe/budgets, return labeled context.
    Returns dict with keys: context_text, tokens_used.
    """
    from .daily_rag import retrieve_daily
    logger.debug(
        "DailyRAG: starting merged retrieval project=%s main_k=%s daily_k=%s thresholds(main=%.3f,daily=%.3f)", 
        project_id, main_top_k, daily_top_k, main_threshold, daily_threshold
    )
    # main
    main = retrieve_context(
        project_id,
        query,
        main_top_k,
        main_snippet_max_tokens,
        main_threshold,
        global_context_max_tokens,
    )
    main_snips = main.get("snippets", [])
    # daily
    daily_results = retrieve_daily(project_id, query, daily_top_k, daily_threshold)
    logger.debug("DailyRAG: daily results pre-cap=%s", len(daily_results))
    # build daily text chunks within daily_max_tokens
    tokens_used_daily = 0
    daily_texts: List[str] = []
    for text, score in daily_results:
        trimmed = _trim_to_tokens(text, main_snippet_max_tokens)
        t = _count_tokens(trimmed)
        if tokens_used_daily + t > daily_max_tokens:
            break
        daily_texts.append(trimmed)
        tokens_used_daily += t
    logger.debug("DailyRAG: daily included=%s tokens=%s", len(daily_texts), tokens_used_daily)
    # dedupe (exact, and optionally near-duplicate)
    def _hash(s: str) -> str:
        return s.strip()
    merged_daily = []
    seen_hashes = set()
    for s in daily_texts:
        h = _hash(s)
        if dedupe_exact and h in seen_hashes:
            continue
        seen_hashes.add(h)
        merged_daily.append(s)
    merged_main = []
    for s in main_snips:
        h = _hash(s)
        if dedupe_exact and h in seen_hashes:
            continue
        merged_main.append(s)
        seen_hashes.add(h)
    if dedupe_near:
        def sig(text: str) -> set:
            toks = (text or "").lower().split()
            return set(toks)
        def jaccard(a: set, b: set) -> float:
            if not a or not b:
                return 0.0
            return len(a & b) / len(a | b)
        kept_daily = []
        sigs = []
        for s in merged_daily:
            sa = sig(s)
            if any(jaccard(sa, sb) >= dedupe_similarity_threshold for sb in sigs):
                continue
            kept_daily.append(s)
            sigs.append(sa)
        merged_daily = kept_daily
        kept_main = []
        for s in merged_main:
            sa = sig(s)
            if any(jaccard(sa, sb) >= dedupe_similarity_threshold for sb in sigs):
                continue
            kept_main.append(s)
            sigs.append(sa)
        merged_main = kept_main
    # simple topic and namespace boosting via ordering (no metadata docstore available here)
    def _boost_score(text: str) -> float:
        score = 1.0
        if topics:
            for t in topics:
                if t and (t.lower() in (text or "").lower()):
                    score *= (topic_boost or 1.0)
                    break
        # namespace heuristic: parse filename from header if present and match via sidecar
        if preferred_namespace:
            try:
                fn = None
                # header format includes file=...
                if "file=" in text:
                    idx = text.find("file=")
                    tail = text[idx+5: idx+5+200]
                    fn = tail.split(",")[0].strip()
                ns_map = _load_namespace_map(project_id)
                if fn and ns_map.get(fn) == preferred_namespace:
                    score *= (topic_boost or 1.0)  # reuse topic_boost weight for namespace preference
            except Exception:
                pass
        return score

    merged_main.sort(key=lambda s: _boost_score(s), reverse=True)
    merged_daily.sort(key=lambda s: _boost_score(s), reverse=True)

    # assemble labeled context respecting global cap
    pieces: List[str] = []
    tokens_used = 0
    if merged_daily:
        daily_block = "Context (Daily):\n---\n" + "\n\n---\n".join(merged_daily)
        td = _count_tokens(daily_block)
        if tokens_used + td <= global_context_max_tokens:
            pieces.append(daily_block)
            tokens_used += td
    if merged_main and tokens_used < global_context_max_tokens:
        main_block = "Context (Main):\n---\n" + "\n\n---\n".join(merged_main)
        tm = _count_tokens(main_block)
        if tokens_used + tm > global_context_max_tokens:
            # trim main block to fit
            remain = global_context_max_tokens - tokens_used
            main_block = _trim_to_tokens(main_block, remain)
            tm = _count_tokens(main_block)
        pieces.append(main_block)
        tokens_used += tm
    context_text = "\n\n".join(pieces) if pieces else ""
    logger.debug("DailyRAG: merged context tokens=%s blocks(daily=%s,main=%s)", tokens_used, 1 if merged_daily else 0, 1 if merged_main else 0)
    # Also return the selected texts for optional telemetry events
    return {
        "context_text": context_text,
        "tokens_used": tokens_used,
        "daily_texts": merged_daily,
        "main_texts": merged_main,
    }


def _load_namespace_map(project_id: str) -> Dict[str, str]:
    try:
        base = os.path.join("memory", project_id, "faiss")
        path = os.path.join(base, "meta_namespaces.json")
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


