"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import logging

from ..core.config import get_settings
from ..llm_model.factory import get_llm_client

logger = logging.getLogger(__name__)

try:
    import tiktoken  # type: ignore
except Exception:
    tiktoken = None


def count_tokens(text: str) -> int:
    if not tiktoken:
        return len(text.split())
    try:
        enc = tiktoken.get_encoding("cl100k_base")
    except Exception:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text or ""))


def trim_to_tokens(text: str, max_tokens: int) -> str:
    if not tiktoken:
        return text
    enc = tiktoken.get_encoding("cl100k_base")
    ids = enc.encode(text or "")
    if len(ids) <= max_tokens:
        return text
    ids = ids[:max_tokens]
    return enc.decode(ids)


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



