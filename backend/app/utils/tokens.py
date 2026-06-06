"""
Copyright (c) 2025-2026 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Shared tokenization helpers for best-effort counting and trimming.
"""


from functools import lru_cache
from typing import Any, Iterable, Optional

try:
    import tiktoken  # type: ignore
except Exception:
    tiktoken = None


@lru_cache(maxsize=32)
def _resolve_encoding(model_name: Optional[str], encoding_name: str):
    if not tiktoken:
        return None
    if model_name:
        try:
            return tiktoken.encoding_for_model(model_name)
        except Exception:
            pass
    try:
        return tiktoken.get_encoding(encoding_name)
    except Exception:
        return None


def get_encoding_cached(
    *,
    model_name: Optional[str] = None,
    encoding_name: str = "cl100k_base",
):
    return _resolve_encoding(model_name, encoding_name)


def count_tokens(
    text: str,
    *,
    model_name: Optional[str] = None,
    encoding_name: str = "cl100k_base",
) -> int:
    if not text:
        return 0
    enc = get_encoding_cached(model_name=model_name, encoding_name=encoding_name)
    if enc is None:
        return len(text.split())
    try:
        return int(len(enc.encode(text)))
    except Exception:
        return len(text.split())


def trim_to_tokens(
    text: str,
    max_tokens: int,
    *,
    model_name: Optional[str] = None,
    encoding_name: str = "cl100k_base",
) -> str:
    if not text:
        return ""
    if max_tokens <= 0:
        return ""
    enc = get_encoding_cached(model_name=model_name, encoding_name=encoding_name)
    if enc is None:
        return text
    try:
        ids = enc.encode(text)
    except Exception:
        return text
    if len(ids) <= max_tokens:
        return text
    return enc.decode(ids[:max_tokens])


def count_message_content_tokens(
    messages: Iterable[Any],
    *,
    model_name: Optional[str] = None,
    encoding_name: str = "cl100k_base",
) -> int:
    try:
        text = "\n".join(
            str((m.get("content") or ""))
            for m in (messages or [])
            if isinstance(m, dict)
        )
    except (AttributeError, TypeError, ValueError):
        return 0
    return count_tokens(text, model_name=model_name, encoding_name=encoding_name)
