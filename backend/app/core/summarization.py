"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import logging
import time
from typing import List, Tuple

from .llm import get_llm_provider
from .tracking import get_instrumentation

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
    instr = get_instrumentation()
    for attempt in range(retries):
        invocation_id = ""
        t0 = time.perf_counter()
        try:
            invocation_id = instr.start_invocation(
                purpose="sleep",
                model=str(provider.settings.model_name),
                meta={"attempt": int(attempt + 1), "retries": int(retries)},
            )
            # Avoid duplicate sleep/main invocation records; sleep owns instrumentation here.
            resp = provider.generate_response(message=prompt, instrument=False)
            if resp.get("success"):
                total_tokens = resp.get("tokens_used")
                prompt_tokens = resp.get("input_tokens")
                completion_tokens = resp.get("output_tokens")
                usage_is_estimate = not isinstance(total_tokens, int)
                if not isinstance(prompt_tokens, int):
                    prompt_tokens = _count_tokens(prompt)
                if not isinstance(completion_tokens, int):
                    completion_tokens = _count_tokens(resp.get("response", ""))
                if not isinstance(total_tokens, int):
                    total_tokens = int(prompt_tokens + completion_tokens)
                if invocation_id:
                    instr.end_invocation(
                        invocation_id,
                        usage={
                            "purpose": "sleep",
                            "model": str(provider.settings.model_name),
                            "prompt_tokens_reported": int(prompt_tokens),
                            "completion_tokens_reported": int(completion_tokens),
                            "total_tokens_reported": int(total_tokens),
                            "usage_is_estimate": bool(usage_is_estimate),
                        },
                        timing={"ttlt_ms": int((time.perf_counter() - t0) * 1000.0)},
                    )
                return resp.get("response", "")
            last_err = resp.get("error") or "unknown_error"
            if invocation_id:
                instr.end_invocation(
                    invocation_id,
                    usage={
                        "purpose": "sleep",
                        "model": str(provider.settings.model_name),
                        "prompt_tokens_reported": 0,
                        "completion_tokens_reported": 0,
                        "total_tokens_reported": 0,
                        "usage_is_estimate": True,
                    },
                    timing={"ttlt_ms": int((time.perf_counter() - t0) * 1000.0)},
                )
        except Exception as e:
            last_err = str(e)
            if invocation_id:
                try:
                    instr.end_invocation(
                        invocation_id,
                        usage={
                            "purpose": "sleep",
                            "model": str(provider.settings.model_name),
                            "prompt_tokens_reported": 0,
                            "completion_tokens_reported": 0,
                            "total_tokens_reported": 0,
                            "usage_is_estimate": True,
                        },
                        timing={"ttlt_ms": int((time.perf_counter() - t0) * 1000.0)},
                    )
                except Exception:
                    pass
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


