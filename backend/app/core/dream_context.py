"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import logging
import os
import re
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


def _strip_open_questions_section(text: str) -> str:
    """
    Remove the [Open Questions] section and its JSON block from sleep_summary.txt.
    This prevents duplicate questions since they're already in questions.json.
    
    Args:
        text: The full content of sleep_summary.txt
        
    Returns:
        Text with [Open Questions] section removed
    """
    # Find [Open Questions] marker (case-insensitive, with optional whitespace)
    pattern = r'\[Open Questions\][\s\S]*'
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    if match:
        # Remove everything from the marker to the end
        # But preserve END DAILY MEMORY tag if it exists after the section
        start_pos = match.start()
        # Check if there's an END DAILY MEMORY tag after the Open Questions section
        remaining = text[start_pos:]
        end_tag_match = re.search(r'=== END DAILY MEMORY.*?===', remaining, re.IGNORECASE)
        if end_tag_match:
            # Keep the END tag, remove everything between [Open Questions] and the tag
            end_pos = start_pos + end_tag_match.start()
            return text[:start_pos].rstrip() + "\n\n" + text[end_pos:].lstrip()
        else:
            # No END tag, just remove from [Open Questions] to end
            return text[:start_pos].rstrip()
    return text


def _get_user_profile(project_id: str) -> str:
    """
    Retrieve user profile from RAG or fallback file.
    Returns text or '(empty)' if not found.
    """
    settings = get_settings()
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
            logger.warning("User profile missing from RAG. Using fallback file.")
        else:
            logger.warning("User profile missing from RAG and fallback file not found.")
            user_profile_text = "(empty)"
    logger.info("[DREAM][CONTEXT] Retrieved user profile tokens=%s", _count_tokens(user_profile_text))
    return user_profile_text


def _get_project_system_prompt(project_id: str) -> str:
    """
    Retrieve project system prompt from RAG or fallback file.
    Returns text or '(empty)' if not found.
    """
    settings = get_settings()
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
            logger.warning("Project system rules missing.")
            system_prompt_text = "(empty)"
    logger.info("[DREAM][CONTEXT] Retrieved system prompt tokens=%s", _count_tokens(system_prompt_text))
    return system_prompt_text


def _get_project_context_summary(project_id: str) -> str:
    """
    Generate project context summary via RAG + LLM summarization.
    Returns text or '(empty)' if generation fails.
    """
    settings = get_settings()
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
        logger.warning("Project summary empty.")
        project_summary_text = "(empty)"
    logger.info("[DREAM][CONTEXT] Generated project summary tokens=%s", _count_tokens(project_summary_text))
    return project_summary_text


def _get_question_answers(project_id: str) -> str:
    """
    Load question answers from questions.json.
    Returns text or '(empty)' if missing or empty.
    """
    questions_path = os.path.join("memory", project_id, "questions.json")
    qa_text = _read_file_safe(questions_path)
    if not qa_text.strip():
        logger.warning("questions.json missing or empty.")
        qa_text = "(empty)"
    logger.info("[DREAM][CONTEXT] Loaded Q and A results tokens=%s", _count_tokens(qa_text))
    return qa_text


def _get_daily_memory(project_id: str) -> str:
    """
    Load daily memory from sleep_summary.txt with [Open Questions] section stripped.
    Returns text or '(empty)' if missing or empty.
    """
    summary_path = os.path.join("memory", project_id, "sleep_summary.txt")
    daily_text = _read_file_safe(summary_path)
    if not daily_text.strip():
        logger.warning("sleep_summary.txt missing or empty.")
        daily_text = "(empty)"
    else:
        # Strip [Open Questions] section to avoid duplicates (questions are already in questions.json)
        original_length = len(daily_text)
        daily_text = _strip_open_questions_section(daily_text)
        if len(daily_text) < original_length:
            logger.debug("[DREAM][CONTEXT] Stripped [Open Questions] section from daily memory")
    logger.info("[DREAM][CONTEXT] Loaded daily memory tokens=%s", _count_tokens(daily_text))
    return daily_text


def _write_debug_context_file(project_id: str, context_block: str) -> None:
    """
    Write debug context file if GENERATE_DEBUG_FILES is enabled.
    
    Args:
        project_id: Project identifier
        context_block: The complete context block string to write
    """
    settings = get_settings()
    if not settings.generate_debug_files:
        return
    
    try:
        base_dir = os.path.join("memory", project_id)
        os.makedirs(base_dir, exist_ok=True)
        debug_path = os.path.join(base_dir, "debug_context.txt")
        with open(debug_path, "w", encoding="utf-8", newline="\n") as dbg:
            dbg.write(context_block)
        logger.info("[DREAM][CONTEXT] Wrote debug context to %s", debug_path)
    except Exception as de:
        logger.warning("Failed writing debug context: %s", de)


def build_dream_context(project_id: str) -> str:
    """
    Build the Dream Context Block in this exact order with headers:
    USER PROFILE → PROJECT SYSTEM PROMPT → PROJECT CONTEXT SUMMARY → QUESTION ANSWERS → DAILY MEMORY
    Falls back per 4.1.3.1 and logs per-section token counts.
    """
    logger.info("[DREAM][CONTEXT] Building context for project=%s", project_id)

    # Retrieve each section via helper functions
    user_profile_text = _get_user_profile(project_id)
    system_prompt_text = _get_project_system_prompt(project_id)
    project_summary_text = _get_project_context_summary(project_id)
    qa_text = _get_question_answers(project_id)
    daily_text = _get_daily_memory(project_id)

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
    logger.info("[DREAM][CONTEXT] Combined context ready")
    # Write debug context file if enabled
    _write_debug_context_file(project_id, context_block)
    return context_block


