"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import logging
import time
from typing import Optional, List, Dict, Any
import json
import re
import os

from ..research import count_tokens, trim_to_tokens, fetch_remote_research
from ...config import get_settings
from ..llm import dream_llm_call
from ...rag_manager import retrieve_context
from app.utils.debug_utils import write_debug_file
from .prompts.questions_prompts import (
    build_answer_question_prompt_local,
    build_answer_question_prompt_remote,
)

logger = logging.getLogger(__name__)


def _extract_json_from_open_questions(summary_text: str) -> Optional[str]:
    """
    Locate the [Open Questions] section and extract the first JSON object that follows.
    Returns the JSON text or None if not found/invalid.
    """
    try:
        # Find the [Open Questions] marker
        m = re.search(r"^\[Open Questions\][\s\S]*", summary_text, flags=re.MULTILINE)
        start_idx = m.start() if m else -1
        if start_idx < 0:
            return None
        # From marker onward, find first '{' and extract balanced braces
        tail = summary_text[start_idx:]
        brace_start = tail.find("{")
        if brace_start < 0:
            return None
        i = brace_start
        depth = 0
        for j, ch in enumerate(tail[brace_start:], start=brace_start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    json_str = tail[brace_start:j + 1]
                    # Validate it's JSON
                    json.loads(json_str)
                    return json_str
        return None
    except Exception:
        return None


def _open_questions_agent(project_id: str, summary_text: str) -> dict:
    """
    Parse JSON block from [Open Questions] section.
    """
    json_text = _extract_json_from_open_questions(summary_text or "")
    if not json_text:
        logger.warning("project=%s no valid JSON found in [Open Questions]", project_id)
        return {"questions": []}
    try:
        obj = json.loads(json_text)
        # Expect { "questions": [...] } per 4.1.1 format guidance
        lst = obj.get("questions")
        if not isinstance(lst, list):
            logger.info("project=%s invalid JSON structure (no questions list)", project_id)
            return {"questions": []}
        # Just return parsed object; filtering already handled by formatter prompt
        return obj
    except Exception as e:
        logger.warning("project=%s invalid JSON payload: %s", project_id, e)
        return {"questions": []}


def _run_open_question_pipeline(project_id: str, question: str, topic: str, resolution: str) -> Dict[str, Any]:
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
        )
        local_context = rc.get("context_text") or ""
    except Exception as e:
        logger.warning("project=%s question=%s RAG retrieval failed: %s", project_id, question[:120], e)
        local_context = ""

    local_tokens = count_tokens(local_context)
    remote_context = ""
    remote_tokens = 0

    # Remote research only when enabled and resolution requires it
    if (resolution or "").lower() == "answer_remote" and settings.dream_enable_remote_research:
        raw_remote = fetch_remote_research(question)
        if raw_remote:
            # Cap remote context tokens
            remote_tokens_raw = count_tokens(raw_remote)
            capped_remote = trim_to_tokens(raw_remote, settings.dream_remote_context_max_tokens)
            remote_tokens = count_tokens(capped_remote)
            if remote_tokens_raw > remote_tokens:
                logger.warning("trimmed remote=%s→%s", remote_tokens_raw, remote_tokens)
            remote_context = capped_remote
            used_remote = True
        else:
            logger.warning("project=%s question=%s empty remote research result", project_id, question[:120])

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
            logger.warning("project=%s question=%s invalid answer JSON shape", project_id, question[:120])
    except Exception:
        logger.warning("project=%s question=%s invalid answer JSON", project_id, question[:120])

    # Combined token counts and trims
    combined_tokens = local_tokens + (remote_tokens or 0)
    logger.info(
        '[DREAM][QUESTIONS] Q answered question="%s" preview="%s" used_remote_research=%s tokens(local=%s, remote=%s, combined=%s)',
        (question or "")[:120],
        preview,
        str(used_remote).lower(),
        local_tokens,
        remote_tokens,
        combined_tokens,
    )
    return {"question": question, "topic": topic, "answer": answer_text}


def run_questions_agent(
    project_id: str,
    summary_text: str,
) -> Dict[str, Any]:
    """
    Run the Open Questions agent for a project.
    
    This function extracts questions from sleep_summary.txt, processes each question
    through the RAG pipeline, and returns an in-memory data structure.
    
    Args:
        project_id: Project identifier
        summary_text: The formatted sleep_summary.txt content (in-memory string)
    
    Returns:
        Dictionary with {"questions": [...]}
    """
    logger.info("[DREAM][QUESTIONS] Start project=%s", project_id)
    try:
        parsed = _open_questions_agent(project_id, summary_text)
        questions = parsed.get("questions") if isinstance(parsed, dict) else []
        if not isinstance(questions, list):
            questions = []
        # Process sequentially
        outputs: List[Dict[str, str]] = []
        for item in questions:
            try:
                q = (item or {}).get("question") or ""
                topic = (item or {}).get("topic") or ""
                resolution = (item or {}).get("resolution") or ""
                if not q:
                    continue
                out = _run_open_question_pipeline(project_id, q, topic, resolution)
                outputs.append(
                    {
                        "question": out.get("question") or q,
                        "topic": out.get("topic") or topic,
                        "answer": out.get("answer") or "Dream agent failed to generate a valid answer.",
                    }
                )
            except Exception as qe:
                logger.warning("project=%s per-question pipeline error: %s", project_id, qe)
        result: Dict[str, Any] = {"questions": outputs}

        # Optional debug file: debug_questions.txt
        try:
            debug_payload = json.dumps(result, ensure_ascii=False, indent=2)
            write_debug_file(project_id, "debug_questions.txt", debug_payload)
        except Exception as we:
            logger.warning("project=%s failed writing debug_questions.txt: %s", project_id, we)

        count = len(outputs)
        logger.info("[DREAM][QUESTIONS] Completed project=%s count=%s", project_id, count)
        return result
    except Exception as e:
        logger.error("project=%s %s", project_id, e, exc_info=True)
        return {"questions": []}



