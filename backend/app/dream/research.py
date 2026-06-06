"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
import logging

from ..core.config import get_settings
from ..core.llm import generate_text_response
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
        response = generate_text_response(
            f"Perform web research to gather concise factual context for: {query}",
            override_model=settings.dream_model,
            system_prompt=None,
            tools=[{"type": "web_search"}],
            temperature_override=float(settings.dream_temperature),
            max_output_tokens=int(settings.dream_max_tokens),
            purpose="dream:remote_research",
        )
        return response.text
    except Exception as e:
        logger.warning("[DREAM][WARN] Remote research failed: %s", e)
        return ""



