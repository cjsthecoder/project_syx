"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import logging

from openai import OpenAI

from ..config import get_settings

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
    client = OpenAI(api_key=settings.openai_api_key)
    try:
        resp = client.responses.create(
            model=settings.dream_model,
            input=f"Perform web research to gather concise factual context for: {query}",
            tools=[{"type": "web_search"}],
            temperature=settings.dream_temperature,
            max_output_tokens=settings.dream_max_tokens,
        )
        text = getattr(resp, "output_text", None)
        if text:
            return text
        out = []
        for item in getattr(resp, "output", []) or []:
            if getattr(item, "type", "") == "message":
                for c in getattr(item, "content", []) or []:
                    if getattr(c, "type", "") == "output_text":
                        out.append(getattr(c, "text", "") or "")
        return "".join(out)
    except Exception as e:
        logger.warning("[DREAM][WARN] Remote research failed: %s", e)
        return ""



