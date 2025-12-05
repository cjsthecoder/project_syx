"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import logging
import time
from typing import Optional

from .config import get_settings
from .agents.questions_agent import run_questions_agent
from .dream_context import build_dream_context

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
            # Process questions synchronously
            _ = run_questions_agent(project_id, summary_text)
            # Build dream context after questions.json is written and unlocked
            dream_context = _build_dream_context_safe(project_id)
            if dream_context is None:
                logger.warning("project=%s dream context build failed", project_id)
            elapsed = time.monotonic() - t0
            logger.info("[DREAM] Project %s complete in duration=%.2fs", project_id, elapsed)
        except Exception as de:
            logger.error("project=%s %s", project_id, de, exc_info=True)
    except Exception:
        # Non-fatal; continue loop
        pass

