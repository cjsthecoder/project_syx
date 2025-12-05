"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import logging
import time
from typing import List, Tuple

from .llm import get_llm_provider

logger = logging.getLogger(__name__)

try:
    import tiktoken  # type: ignore
except Exception:
    tiktoken = None


def _count_tokens(text: str) -> int:
    if not tiktoken:
        return len(text.split())
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return len(text.split())


def chunk_by_tokens(text: str, max_tokens: int, overlap: int = 0) -> List[str]:
    if max_tokens <= 0:
        return [text]
    if not tiktoken:
        # naive fallback by words
        words = text.split()
        chunks = []
        i = 0
        step = max(1, max_tokens - overlap)
        while i < len(words):
            chunk_words = words[i : i + max_tokens]
            chunks.append(" ".join(chunk_words))
            i += step
        return chunks
    enc = tiktoken.get_encoding("cl100k_base")
    tokens = enc.encode(text)
    chunks = []
    i = 0
    step = max(1, max_tokens - overlap)
    while i < len(tokens):
        chunk_ids = tokens[i : i + max_tokens]
        chunks.append(enc.decode(chunk_ids))
        i += step
    return chunks


def run_llm(prompt: str, retries: int = 2) -> str:
    provider = get_llm_provider()
    last_err = None
    for attempt in range(retries):
        try:
            resp = provider.generate_response(message=prompt)
            if resp.get("success"):
                return resp.get("response", "")
            last_err = resp.get("error") or "unknown_error"
        except Exception as e:
            last_err = str(e)
        # simple backoff
        time.sleep(1.5 * (attempt + 1))
    logger.error("[SLEEP][ERROR] LLM failed after %s attempts: %s", retries, last_err)
    raise RuntimeError(last_err or "LLM failed")


def execute_prompt(prompt: str) -> str:
    return run_llm(prompt)


def execute_prompt_chunked(prompt_builder, content: str, max_tokens: int, overlap: int = 0) -> str:
    chunks = chunk_by_tokens(content, max_tokens=max_tokens, overlap=overlap)
    outputs: List[str] = []
    for idx, ch in enumerate(chunks):
        prompt = prompt_builder(ch)
        out = run_llm(prompt)
        outputs.append(out)
    return "\n\n".join(outputs)


