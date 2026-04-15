"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import logging
from typing import Optional

from ..core.config import get_settings
from ..llm_model.factory import get_llm_client

logger = logging.getLogger(__name__)


def dream_llm_call(prompt: str, max_output_tokens: Optional[int] = None) -> str:
    """
    Thin wrapper over OpenAI Responses API for Dream.
    Returns the text content (string) of the response.
    """
    settings = get_settings()
    max_tokens = int(max_output_tokens or settings.dream_max_tokens)
    try:
        response = get_llm_client().generate_response(
            model=settings.dream_model,
            system_prompt=None,
            user_prompt=prompt,
            temperature=float(settings.dream_temperature),
            max_output_tokens=max_tokens,
        )
        return response.text
    except Exception as e:
        logger.warning("[DREAM][WARN] LLM call failed: %s", e)
        return '{"answer": "Dream agent failed to generate a valid answer."}'



