import logging
import os
from typing import Dict

try:
    import tiktoken  # type: ignore
except Exception:
    tiktoken = None

from .config import get_settings
from .rag_manager import retrieve_context
from .dream_llm import dream_llm_call
from .dream_prompts import build_project_summary_prompt

logger = logging.getLogger(__name__)

# Simple process-local cache for the duration of a Dream task
_CONTEXT_CACHE: Dict[str, str] = {}


def _count_tokens(text: str) -> int:
    if not text:
        return 0
    if not tiktoken:
        return len(text.split())
    try:
        enc = tiktoken.get_encoding("cl100k_base")
    except Exception:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def _read_file_safe(path: str) -> str:
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
    except Exception:
        pass
    return ""


def build_dream_context(project_id: str) -> str:
    """
    Build the Dream Context Block in this exact order with headers:
    USER PROFILE → PROJECT SYSTEM PROMPT → PROJECT CONTEXT SUMMARY → QUESTION ANSWERS → DAILY MEMORY
    Falls back per 4.1.3.1 and logs per-section token counts.
    """
    settings = get_settings()
    logger.info("[DREAM][CTX] Building context for project=%s", project_id)

    # 1) User Profile via RAG, fallback to default_profile.txt
    up = retrieve_context(
        project_id=project_id,
        query="User profile",
        top_k=settings.rag_top_k,
        snippet_max_tokens=settings.rag_snippet_max_tokens,
        score_threshold=settings.rag_score_threshold,
        context_max_tokens=settings.rag_context_max_tokens,
    )
    user_profile_text = up.get("context_text") or ""
    if not user_profile_text.strip():
        fallback_profile_path = os.path.join("memory", project_id, "default_profile.txt")
        user_profile_text = _read_file_safe(fallback_profile_path)
        if user_profile_text.strip():
            logger.warning("[DREAM][CTX][WARN] User profile missing from RAG. Using fallback file.")
        else:
            logger.warning("[DREAM][CTX][WARN] User profile missing from RAG and fallback file not found.")
            user_profile_text = "(empty)"
    logger.info("[DREAM][CTX] Retrieved user profile tokens=%s", _count_tokens(user_profile_text))

    # 2) Project System Prompt via RAG, fallback to memory/{project}/system_prompt.txt, else (empty)
    sp = retrieve_context(
        project_id=project_id,
        query="Project system rules",
        top_k=settings.rag_top_k,
        snippet_max_tokens=settings.rag_snippet_max_tokens,
        score_threshold=settings.rag_score_threshold,
        context_max_tokens=settings.rag_context_max_tokens,
    )
    system_prompt_text = sp.get("context_text") or ""
    if not system_prompt_text.strip():
        fallback_sys_path = os.path.join("memory", project_id, "system_prompt.txt")
        system_prompt_text = _read_file_safe(fallback_sys_path)
        if not system_prompt_text.strip():
            logger.warning("[DREAM][CTX][WARN] Project system rules missing.")
            system_prompt_text = "(empty)"
    logger.info("[DREAM][CTX] Retrieved system prompt tokens=%s", _count_tokens(system_prompt_text))

    # 3) Project Context Summary — RAG snippets → summarizer prompt (Responses API)
    summ_src = retrieve_context(
        project_id=project_id,
        query="Project overview and key context",
        top_k=settings.rag_top_k,
        snippet_max_tokens=settings.rag_snippet_max_tokens,
        score_threshold=settings.rag_score_threshold,
        context_max_tokens=settings.rag_context_max_tokens,
    ).get("context_text") or ""
    summary_prompt = build_project_summary_prompt(summ_src)
    project_summary_text = dream_llm_call(summary_prompt)
    if not (project_summary_text or "").strip():
        logger.warning("[DREAM][CTX][WARN] Project summary empty.")
        project_summary_text = "(empty)"
    logger.info("[DREAM][CTX] Generated project summary tokens=%s", _count_tokens(project_summary_text))

    # 4) Question Answering Results — questions.json verbatim
    questions_path = os.path.join("memory", project_id, "questions.json")
    qa_text = _read_file_safe(questions_path)
    if not qa_text.strip():
        logger.warning("[DREAM][CTX][WARN] questions.json missing or empty.")
        qa_text = "(empty)"
    logger.info("[DREAM][CTX] Loaded Q and A results tokens=%s", _count_tokens(qa_text))

    # 5) Daily Memory — sleep_summary.txt verbatim
    summary_path = os.path.join("memory", project_id, "sleep_summary.txt")
    daily_text = _read_file_safe(summary_path)
    if not daily_text.strip():
        logger.warning("[DREAM][CTX][WARN] sleep_summary.txt missing or empty.")
        daily_text = "(empty)"
    logger.info("[DREAM][CTX] Loaded daily memory tokens=%s", _count_tokens(daily_text))

    # Assemble in exact order with headers
    parts = [
        "=== USER PROFILE ===\n",
        user_profile_text.rstrip() + "\n\n",
        "=== PROJECT SYSTEM PROMPT ===\n",
        system_prompt_text.rstrip() + "\n\n",
        "=== PROJECT CONTEXT SUMMARY ===\n",
        project_summary_text.rstrip() + "\n\n",
        "=== QUESTION ANSWERS ===\n",
        qa_text.rstrip() + "\n\n",
        "=== DAILY MEMORY ===\n",
        daily_text.rstrip() + "\n",
    ]
    context_block = "".join(parts)
    _CONTEXT_CACHE[project_id] = context_block
    logger.info("[DREAM][CTX] Combined context ready")
    return context_block


