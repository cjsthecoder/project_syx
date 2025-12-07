"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import logging
import os
import time
from typing import Optional

from .config import get_settings
from .agents.questions_agent import run_questions_agent
from .agents.idea_agent import run_idea_agent
from .dream_context import build_dream_context, _strip_open_questions_section

logger = logging.getLogger(__name__)


def _build_dream_context_safe(project_id: str) -> Optional[str]:
    """
    Build dream context with error handling.
    
    Args:
        project_id: Project identifier
    
    Returns:
        Context string on success, None on error
    """
    try:
        return build_dream_context(project_id)
    except Exception as e:
        logger.error("project=%s failed to build context: %s", project_id, e, exc_info=True)
        return None


def dream(project_id: str, summary_text: str) -> None:
    """
    Execute Dream cycle for a project after Sleep completes.
    
    This function processes questions and builds dream context synchronously.
    
    Args:
        project_id: Project identifier
        summary_text: The formatted sleep_summary.txt content (in-memory string)
    
    Returns:
        None (exceptions are logged but not raised)
    """
    try:
        settings = get_settings()
        if not settings.enable_dream:
            return
        t0 = time.monotonic()
        logger.info("[DREAM] Starting dreaming for project=%s", project_id)
        try:
            # Process questions synchronously (writes questions.json)
            _ = run_questions_agent(project_id, summary_text)

            # After extracting questions, strip the [Open Questions] section from the
            # on-disk sleep_summary.txt so that long-term summaries and RAG do not
            # contain the JSON appendix (questions now live in questions.json).
            try:
                cleaned = _strip_open_questions_section(summary_text or "")
                base_dir = os.path.join("memory", project_id)
                os.makedirs(base_dir, exist_ok=True)
                summary_path = os.path.join(base_dir, "sleep_summary.txt")
                with open(summary_path, "w", encoding="utf-8", newline="\n") as sf:
                    sf.write(cleaned)
                logger.info(
                    "[DREAM] Stripped [Open Questions] section from sleep_summary.txt for project=%s",
                    project_id,
                )
            except Exception as se:
                logger.warning(
                    "project=%s failed to strip [Open Questions] from sleep_summary.txt: %s",
                    project_id,
                    se,
                )

            # Build dream context after questions.json is written and sleep_summary.txt
            # has been cleaned on disk.
            dream_context = _build_dream_context_safe(project_id)
            if dream_context is None:
                logger.warning("project=%s dream context build failed", project_id)
                ideas = {"date": None, "items": []}
            else:
                # Run Idea Agent on the constructed dream context
                ideas = run_idea_agent(project_id, dream_context)

            # Currently, ideas are kept in-memory for downstream use in later versions
            _ = ideas  # placeholder to avoid lints until consumed

            elapsed = time.monotonic() - t0
            logger.info("[DREAM] Project %s complete in duration=%.2fs", project_id, elapsed)
        except Exception as de:
            logger.error("project=%s %s", project_id, de, exc_info=True)
    except Exception:
        # Non-fatal; continue loop
        pass

