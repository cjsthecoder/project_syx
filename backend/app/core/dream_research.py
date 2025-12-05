"""



Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.

"""

import json
import logging
from typing import Dict

from .config import get_settings
from .dream_llm import dream_llm_call
from .dream_prompts import (
    build_answer_question_prompt_local,
    build_answer_question_prompt_remote,
)
from .rag_manager import retrieve_context

logger = logging.getLogger(__name__)

try:
    import tiktoken  # type: ignore
except Exception:
    tiktoken = None

from openai import OpenAI


def _count_tokens(text: str) -> int:
    if not tiktoken:
        return len(text.split())
    try:
        enc = tiktoken.get_encoding("cl100k_base")
    except Exception:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text or ""))


def _trim_to_tokens(text: str, max_tokens: int) -> str:
    if not tiktoken:
        return text
    enc = tiktoken.get_encoding("cl100k_base")
    ids = enc.encode(text or "")
    if len(ids) <= max_tokens:
        return text
    ids = ids[:max_tokens]
    return enc.decode(ids)


def _fetch_remote_research(query: str) -> str:
    """
    Fetch remote research via OpenAI web_search tool using the Responses API.
    Returns text blob (may be long); caller will cap tokens.
    """
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    try:
        resp = client.responses.create(
            model=settings.dream_model,
            input=f"Perform web research to gather concise factual context for: {query}",
            tools=[{"type": "web_search"}],
            temperature=settings.dream_temperature,
            max_output_tokens=settings.dream_max_tokens,
        )
        text = getattr(resp, "output_text", None)
        if text:
            return text
        out = []
        for item in getattr(resp, "output", []) or []:
            if getattr(item, "type", "") == "message":
                for c in getattr(item, "content", []) or []:
                    if getattr(c, "type", "") == "output_text":
                        out.append(getattr(c, "text", "") or "")
        return "".join(out)
    except Exception as e:
        logger.warning("[DREAM][WARN] Remote research failed: %s", e)
        return ""


def run_open_question_pipeline(project_id: str, question: str, topic: str, resolution: str) -> Dict[str, any]:
    """
    Process a single open question per 4.1.2.
    Returns dict with keys: question, topic, answer.
    """
    settings = get_settings()
    used_remote = False

    if (resolution or "").lower() == "remind_user":
        return {"question": question, "topic": topic, "answer": "User input required"}

    # Retrieve local RAG context with topic-based hints
    try:
        rc = retrieve_context(
            project_id=project_id,
            query=question,
            top_k=settings.rag_top_k,
            snippet_max_tokens=settings.rag_snippet_max_tokens,
            score_threshold=settings.rag_score_threshold,
            context_max_tokens=settings.rag_context_max_tokens,
            route_namespaces=[topic] if topic else None,
            namespace_boost=settings.dream_topic_boost if topic else None,
        )
        local_context = rc.get("context_text") or ""
    except Exception as e:
        logger.warning("[DREAM][WARN] project=%s question=%s RAG retrieval failed: %s", project_id, question[:120], e)
        local_context = ""

    local_tokens = _count_tokens(local_context)
    remote_context = ""
    remote_tokens = 0

    # Remote research only when enabled and resolution requires it
    if (resolution or "").lower() == "answer_remote" and settings.dream_enable_remote_research:
        raw_remote = _fetch_remote_research(question)
        if raw_remote:
            # Cap remote context tokens
            remote_tokens_raw = _count_tokens(raw_remote)
            capped_remote = _trim_to_tokens(raw_remote, settings.dream_remote_context_max_tokens)
            remote_tokens = _count_tokens(capped_remote)
            if remote_tokens_raw > remote_tokens:
                logger.warning("[DREAM][WARN] trimmed remote=%s→%s", remote_tokens_raw, remote_tokens)
            remote_context = capped_remote
            used_remote = True
        else:
            logger.warning("[DREAM][WARN] project=%s question=%s empty remote research result", project_id, question[:120])

    # Build prompt based on availability
    if used_remote and remote_context:
        prompt = build_answer_question_prompt_remote(question, topic, local_context, remote_context)
    else:
        prompt = build_answer_question_prompt_local(question, topic, local_context)

    # Call Dream LLM
    raw = dream_llm_call(prompt, max_output_tokens=settings.dream_max_tokens)
    # Trim logs
    preview = (raw or "")[:250]

    # Parse strict JSON
    answer_text = "Dream agent failed to generate a valid answer."
    try:
        obj = json.loads(raw or "{}")
        if isinstance(obj, dict) and isinstance(obj.get("answer"), str):
            answer_text = obj["answer"]
        else:
            logger.warning("[DREAM][WARN] project=%s question=%s invalid answer JSON shape", project_id, question[:120])
    except Exception:
        logger.warning("[DREAM][WARN] project=%s question=%s invalid answer JSON", project_id, question[:120])

    # Combined token counts and trims
    combined_tokens = local_tokens + (remote_tokens or 0)
    logger.info(
        '[DREAM] Q answered question="%s" preview="%s" used_remote_research=%s tokens(local=%s, remote=%s, combined=%s)',
        (question or "")[:120],
        preview,
        str(used_remote).lower(),
        local_tokens,
        remote_tokens,
        combined_tokens,
    )
    return {"question": question, "topic": topic, "answer": answer_text}


