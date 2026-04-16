"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import logging
import time
from typing import List, Dict, Any
import json
import os

from ..research import count_tokens, trim_to_tokens, fetch_remote_research
from ...core.config import get_settings
from ..llm import dream_llm_call
from ...rag.manager import retrieve_context
from app.utils.debug_utils import write_debug_file
from .prompts.questions_prompts import (
    build_answer_question_prompt_local,
    build_answer_question_prompt_remote,
)

logger = logging.getLogger(__name__)


def _load_consolidated_questions(project_id: str) -> Dict[str, Any]:
    """
    Load deterministic open-question consolidation artifact from sleep.
    """
    path = os.path.join(get_settings().memory_root, project_id, "open_questions_consolidated.json")
    if not os.path.isfile(path):
        return {"questions": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        if not isinstance(obj, dict):
            return {"questions": []}
        lst = obj.get("questions")
        if not isinstance(lst, list):
            return {"questions": []}
        return {"questions": lst}
    except Exception as e:
        logger.warning("project=%s failed reading open_questions_consolidated.json: %s", project_id, e)
        return {"questions": []}


def _run_open_question_pipeline(project_id: str, question: str, topic: str, resolution: str) -> Dict[str, Any]:
    """
    Process a single open question per 4.1.2.
    Returns dict with keys: question, topic, resolution, answer, used_remote_research.
    """
    settings = get_settings()
    used_remote = False

    normalized_resolution = str(resolution or "").strip().lower()

    # Retrieve local RAG context with topic-based hints
    try:
        rc = retrieve_context(
            project_id=project_id,
            query=question,
            score_threshold=settings.rag_score_threshold,
        )
        local_context = rc.get("context_text") or ""
    except Exception as e:
        logger.warning("project=%s question=%s RAG retrieval failed: %s", project_id, question[:120], e)
        local_context = ""

    local_tokens = count_tokens(local_context)
    remote_context = ""
    remote_tokens = 0

    # Remote research only when enabled and resolution requires it
    if normalized_resolution == "answer_remote" and settings.dream_enable_remote_research:
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
    return {
        "question": question,
        "topic": topic,
        "resolution": normalized_resolution,
        "answer": answer_text,
        "used_remote_research": bool(used_remote),
    }


def run_questions_agent(
    project_id: str,
    summary_text: str = "",
) -> Dict[str, Any]:
    """
    Run the Open Questions agent for a project.
    
    This function reads deterministic consolidated questions from
    open_questions_consolidated.json, processes each question through the RAG
    pipeline, and returns an in-memory data structure.
    
    Args:
        project_id: Project identifier
        summary_text: Backward-compatibility placeholder (unused).
    
    Returns:
        Dictionary with {"questions": [...]}
    """
    logger.info("[DREAM][QUESTIONS] Start project=%s", project_id)
    try:
        parsed = _load_consolidated_questions(project_id)
        questions = parsed.get("questions") if isinstance(parsed, dict) else []
        if not isinstance(questions, list):
            questions = []
        # Process sequentially
        outputs: List[Dict[str, Any]] = []
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
                        "resolution": str(out.get("resolution") or resolution or "").strip().lower(),
                        "answer": out.get("answer") or "Dream agent failed to generate a valid answer.",
                        "used_remote_research": bool(out.get("used_remote_research", False)),
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



