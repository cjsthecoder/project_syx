"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import logging
import os
import re
from typing import Any, Dict, List

from ..core.config import get_settings
from ..core.llm import generate_text_response
from ..utils.tokens import count_tokens
from .debug import safe_dream_purpose, write_dream_prompt_to_execute, write_dream_response_usage_debug
from .prompts import build_project_summary_prompt
from .rag import retrieve_dream_context
from app.utils.debug_utils import write_debug_file

logger = logging.getLogger(__name__)

# Simple process-local cache for the duration of a Dream task
_CONTEXT_CACHE: Dict[str, str] = {}


def _count_tokens(text: str) -> int:
    return int(count_tokens(text or ""))


def _read_file_safe(path: str) -> str:
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
    except OSError as exc:
        logger.warning("[DREAM][CONTEXT] Failed reading file path=%s detail=%s", path, exc)
    return ""


def _strip_open_questions_section(text: str) -> str:
    """
    Remove the [Open Questions] section and its JSON block from sleep_summary.md.
    This prevents duplicate questions since they're already in questions_data.
    
    Args:
        text: The full content of sleep_summary.md
        
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
    Retrieve user profile from summary file (if present) or RAG/fallback file.
    Returns text or '(empty)' if not found.
    """
    # 1) Prefer a precomputed user_profile_summary.txt if it exists
    summary_path = os.path.join(get_settings().memory_root, project_id, "user_profile_summary.txt")
    summary_text = _read_file_safe(summary_path)
    if summary_text.strip():
        logger.info(
            "[DREAM][CONTEXT] Loaded user_profile_summary.txt tokens=%s",
            _count_tokens(summary_text),
        )
        return summary_text

    # 2) Fall back to RAG lookup (e.g., DEFAULT_RAG.txt via User Profile Codex)
    up = retrieve_dream_context(
        project_id=project_id,
        query="User Profile Codex",
        route="DIRECT",
    )
    user_profile_text = up.get("context_text") or ""
    if not user_profile_text.strip():
        fallback_profile_path = os.path.join(get_settings().memory_root, project_id, "default_profile.txt")
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
    sp = retrieve_dream_context(
        project_id=project_id,
        query="Project system rules",
        route="DIRECT",
    )
    system_prompt_text = sp.get("context_text") or ""
    if not system_prompt_text.strip():
        fallback_sys_path = os.path.join(get_settings().memory_root, project_id, "system_prompt.txt")
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
    # Always use the latest sleep summary as source; skip RAG retrieval
    summary_path = os.path.join(get_settings().memory_root, project_id, "sleep_summary.md")
    summ_src = _read_file_safe(summary_path)
    summary_prompt = build_project_summary_prompt(summ_src)
    write_debug_file(project_id, "debug_context_summary.txt", summary_prompt)
    purpose = "context_summary"
    max_tokens = int(settings.dream_max_tokens)
    model = str(settings.dream_model)
    write_dream_prompt_to_execute(
        project_id=project_id,
        prompt=summary_prompt,
        purpose=purpose,
        model=model,
        max_output_tokens=max_tokens,
    )
    try:
        response = generate_text_response(
            summary_prompt,
            override_model=model,
            system_prompt=None,
            temperature_override=float(settings.dream_temperature),
            max_output_tokens=max_tokens,
            purpose=f"dream:{safe_dream_purpose(purpose)}",
        )
        write_dream_response_usage_debug(
            project_id=project_id,
            response_text=response.text,
            purpose=purpose,
            model=model,
            max_output_tokens=max_tokens,
            usage=response.usage,
        )
        project_summary_text = response.text
    except Exception as exc:
        logger.warning("[DREAM][WARN] LLM call failed project=%s purpose=%s detail=%s", project_id, purpose, exc)
        project_summary_text = '{"answer": "Dream agent failed to generate a valid answer."}'
    if not (project_summary_text or "").strip():
        logger.warning("Project summary empty.")
        project_summary_text = "(empty)"
    logger.info("[DREAM][CONTEXT] Generated project summary tokens=%s", _count_tokens(project_summary_text))
    return project_summary_text


def _format_question_answers(questions_data: Dict[str, Any]) -> str:
    """
    Render question/answer pairs from the in-memory questions_data dict
    into a simple, human-friendly text block.

    Expected shape:
        {"questions": [ { "question": "...", "topic": "...", "answer": "..." }, ... ]}
    """
    if not isinstance(questions_data, dict):
        logger.warning("questions_data missing or invalid; treating as empty.")
        return "(empty)"

    items = questions_data.get("questions")
    if not isinstance(items, list) or not items:
        logger.info("[DREAM][CONTEXT] No question answers available.")
        return "(empty)"

    lines: List[str] = []
    for idx, q in enumerate(items, start=1):
        if not isinstance(q, dict):
            continue
        question = (q.get("question") or "").strip()
        topic = (q.get("topic") or "").strip()
        answer = (q.get("answer") or "").strip()
        if not question and not answer:
            continue
        lines.append(f"Q{idx}: {question or '(no question text)'}")
        if topic:
            lines.append(f"Topic: {topic}")
        lines.append("Answer:")
        lines.append(answer or "(no answer)")
        lines.append("")  # blank line between entries

    if not lines:
        return "(empty)"

    result = "\n".join(lines).rstrip() + "\n"
    logger.info("[DREAM][CONTEXT] Loaded Q and A results tokens=%s", _count_tokens(result))
    return result


def _get_daily_memory(project_id: str) -> str:
    """
    Load daily memory from sleep_summary.md with [Open Questions] section stripped.
    Returns text or '(empty)' if missing or empty.
    """
    summary_path = os.path.join(get_settings().memory_root, project_id, "sleep_summary.md")
    daily_text = _read_file_safe(summary_path)
    if not daily_text.strip():
        logger.warning("sleep_summary.md missing or empty.")
        daily_text = "(empty)"
    else:
        # Strip [Open Questions] section to avoid duplicates (questions are already represented in questions_data)
        original_length = len(daily_text)
        daily_text = _strip_open_questions_section(daily_text)
        if len(daily_text) < original_length:
            logger.debug("[DREAM][CONTEXT] Stripped [Open Questions] section from daily memory")
    logger.info("[DREAM][CONTEXT] Loaded daily memory tokens=%s", _count_tokens(daily_text))
    return daily_text


def _extract_rag_topics(project_id: str) -> List[str]:
    """
    Extract topic queries from sleep_summary.md per 4.1.3.2.

    Returns:
        Ordered, deduplicated list of topic queries (section titles + individual topics).
    """
    summary_path = os.path.join(get_settings().memory_root, project_id, "sleep_summary.md")
    text = _read_file_safe(summary_path)
    if not text.strip():
        logger.debug("[DREAM][CONTEXT] RAG enrichment: sleep_summary.md missing or empty for project=%s", project_id)
        return []

    lines = text.splitlines()
    topics: List[str] = []
    seen: Dict[str, bool] = {}

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("=== TOPIC:") and line.endswith("==="):
            # Extract section title between "=== TOPIC:" and "==="
            try:
                title = line[len("=== TOPIC:") : -3].strip()
            except Exception:
                title = ""
            # Look for immediate #topics line (next non-empty line)
            j = i + 1
            topics_line = ""
            while j < len(lines):
                candidate = lines[j].strip()
                if not candidate:
                    j += 1
                    continue
                if candidate.lower().startswith("#topics:"):
                    topics_line = candidate
                break
            # Add section title
            if title and title not in seen:
                seen[title] = True
                topics.append(title)
            # Add individual topics from #topics:
            if topics_line:
                raw = topics_line.split(":", 1)[1] if ":" in topics_line else ""
                for part in raw.split(","):
                    t = part.strip()
                    if t and t not in seen:
                        seen[t] = True
                        topics.append(t)
            i = j
        else:
            i += 1

    logger.info("[DREAM][CONTEXT] RAG enrichment extracted_topics=%s", len(topics))
    return topics


def _build_project_rag_context(project_id: str) -> str:
    """
    Build the PROJECT RAG CONTEXT section by querying RAG per extracted topic.

    Returns:
        Section string starting with '=== PROJECT RAG CONTEXT ===' (may be minimal/empty).
    """
    topic_list = _extract_rag_topics(project_id)

    # Debug: write topics file if enabled
    if topic_list:
        write_debug_file(project_id, "debug_rag_topics.txt", "\n".join(topic_list))

    total_docs = 0
    lines: List[str] = ["=== PROJECT RAG CONTEXT ==="]

    if not topic_list:
        logger.debug("[DREAM][CONTEXT] RAG enrichment: No topics extracted for project=%s", project_id)
        # Header only; downstream agents see the presence of the section but no entries
        return "\n".join(lines) + "\n"

    # Accumulate human-readable debug output for hits
    debug_hits: List[str] = []

    for topic in topic_list:
        try:
            res = retrieve_dream_context(
                project_id=project_id,
                query=topic,
                route="EXPLORATORY",
            )
        except Exception as re_err:
            logger.debug(
                "[DREAM][CONTEXT] RAG enrichment retrieval failed for topic='%s' project=%s: %s",
                topic,
                project_id,
                re_err,
            )
            continue

        context_text = str(res.get("context_text") or "").strip()
        if not context_text:
            continue

        lines.append(f"Topic Query: {topic}")
        lines.append(context_text)
        lines.append("")
        total_docs += int(res.get("total_hits", 0) or res.get("kept_candidates", 0) or 1)
        debug_hits.append(
            f"Topic: {topic}\n"
            f"Route: {res.get('route')}\n"
            f"Per-source K: {res.get('per_source_k')}\n"
            f"Max keep: {res.get('max_keep')}\n"
            f"Daily enabled: {res.get('daily_enabled')}\n"
            f"Expanded unique chunks: {res.get('expanded_unique_chunks_after_merge')}\n"
            f"Context:\n{context_text}\n\n"
        )

    if total_docs == 0:
        lines.append("(No relevant long-term memory found for today’s topics.)")

    logger.info(
        "[DREAM][CONTEXT] RAG enrichment retrieved_docs=%s for project=%s",
        total_docs,
        project_id,
    )

    # Debug: write raw results file if enabled
    if debug_hits:
        write_debug_file(project_id, "debug_rag_results.txt", "".join(debug_hits))

    return "\n".join(lines) + "\n"


def build_dream_context(project_id: str, questions_data: Dict[str, Any]) -> tuple[str, str]:
    """
    Build the Dream Context Block in this exact order with headers:
    USER PROFILE → PROJECT SYSTEM PROMPT → PROJECT CONTEXT SUMMARY → QUESTION ANSWERS → DAILY MEMORY → PROJECT RAG CONTEXT
    Falls back per 4.1.3.1/4.1.3.2 and logs per-section token counts.

    Returns:
        (context_block, project_summary_text)
    """
    logger.info("[DREAM][CONTEXT] Building context for project=%s", project_id)

    try:
        # Retrieve each section via helper functions
        user_profile_text = _get_user_profile(project_id)
        system_prompt_text = _get_project_system_prompt(project_id)
        project_summary_text = _get_project_context_summary(project_id)
        qa_text = _format_question_answers(questions_data)
        daily_text = _get_daily_memory(project_id)
        rag_context_text = _build_project_rag_context(project_id)

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
            daily_text.rstrip() + "\n\n",
            rag_context_text.rstrip() + "\n",
        ]
        context_block = "".join(parts)
        _CONTEXT_CACHE[project_id] = context_block
        logger.info("[DREAM][CONTEXT] Combined context ready")
        # Write debug context file if enabled via shared debug helper
        write_debug_file(project_id, "debug_context.txt", context_block)
        return context_block, project_summary_text
    except Exception as e:
        # Per 4.1.3.x: errors inside the context builder must not be fatal.
        logger.error(
            "project=%s dream context build failed inside context builder: %s",
            project_id,
            e,
            exc_info=True,
        )
        # Minimal fallback: DAILY MEMORY only, project_summary_text set to "(empty)".
        try:
            daily_text = _get_daily_memory(project_id)
        except Exception as daily_exc:
            logger.warning(
                "project=%s dream context fallback failed loading daily memory: %s",
                project_id,
                daily_exc,
            )
            daily_text = "(empty)"
        fallback_parts = [
            "=== DAILY MEMORY ===\n",
            (daily_text or "(empty)").rstrip() + "\n",
        ]
        context_block = "".join(fallback_parts)
        _CONTEXT_CACHE[project_id] = context_block
        write_debug_file(project_id, "debug_context.txt", context_block)
        return context_block, "(empty)"



