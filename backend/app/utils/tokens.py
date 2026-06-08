"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
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
    """Resolve and cache a tiktoken encoding, preferring the model-specific one.

    Results are memoized per ``(model_name, encoding_name)`` pair. Lookup
    failures fall back from the model-specific encoding to the named encoding,
    and finally to None.

    Args:
        model_name: Optional model name to look up a tailored encoding.
        encoding_name: Named encoding used when no model-specific match exists.

    Returns:
        A tiktoken encoding, or None when tiktoken is unavailable or both
        lookups fail.
    """
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
    """Return a cached tiktoken encoding, preferring the model-specific one.

    Args:
        model_name: Optional model name to look up a tailored encoding.
        encoding_name: Fallback encoding name used when no model match exists.

    Returns:
        A tiktoken encoding, or ``None`` when tiktoken is unavailable or
        resolution fails.
    """
    return _resolve_encoding(model_name, encoding_name)


def count_tokens(
    text: str,
    *,
    model_name: Optional[str] = None,
    encoding_name: str = "cl100k_base",
) -> int:
    """Count tokens in text, falling back to whitespace word count.

    Best-effort: returns a word count when no encoding is available or encoding
    raises, so callers always get a usable estimate.

    Args:
        text: Text to count.
        model_name: Optional model name for encoding selection.
        encoding_name: Fallback encoding name.

    Returns:
        Estimated token count (0 for empty text).
    """
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
    """Trim text to at most ``max_tokens`` tokens.

    Best-effort: returns the original text unchanged when no encoding is
    available or encoding raises; returns an empty string for non-positive
    limits.

    Args:
        text: Text to trim.
        max_tokens: Maximum number of tokens to retain.
        model_name: Optional model name for encoding selection.
        encoding_name: Fallback encoding name.

    Returns:
        The trimmed text.
    """
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
    """Count tokens across the ``content`` fields of chat messages.

    Non-dict messages and missing content are ignored; malformed input yields 0.

    Args:
        messages: Iterable of message mappings with optional "content".
        model_name: Optional model name for encoding selection.
        encoding_name: Fallback encoding name.

    Returns:
        Total estimated token count over all message contents.
    """
    try:
        text = "\n".join(
            str((m.get("content") or ""))
            for m in (messages or [])
            if isinstance(m, dict)
        )
    except (AttributeError, TypeError, ValueError):
        return 0
    return count_tokens(text, model_name=model_name, encoding_name=encoding_name)
