"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import logging

from ..core.config import get_settings
from ..llm_model.factory import get_llm_client
from ..utils.tokens import count_tokens as _count_tokens, trim_to_tokens as _trim_to_tokens

logger = logging.getLogger(__name__)


def count_tokens(text: str) -> int:
    return int(_count_tokens(text or ""))


def trim_to_tokens(text: str, max_tokens: int) -> str:
    return _trim_to_tokens(text or "", max_tokens)


def fetch_remote_research(query: str) -> str:
    """
    Fetch remote research via OpenAI web_search tool using the Responses API.
    Returns text blob (may be long); caller will cap tokens.
    """
    settings = get_settings()
    try:
        response = get_llm_client().generate_response(
            model=settings.dream_model,
            system_prompt=None,
            user_prompt=f"Perform web research to gather concise factual context for: {query}",
            tools=[{"type": "web_search"}],
            temperature=float(settings.dream_temperature),
            max_output_tokens=int(settings.dream_max_tokens),
        )
        return response.text
    except Exception as e:
        logger.warning("[DREAM][WARN] Remote research failed: %s", e)
        return ""



