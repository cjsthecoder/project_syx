"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Token-aware batching helpers for embeddings API calls.

Goal: keep each embeddings request under a configurable total token budget
to avoid provider-side "max tokens per request" errors on large corpora.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from ..utils.tokens import count_tokens


def estimate_tokens(text: str, *, model_name: Optional[str] = None) -> int:
    """Best-effort token estimate for batching.

    Notes:
    - This is an estimate used only for batching; exact provider-side tokenization
      can differ slightly. Callers should leave headroom (e.g., 250k vs 300k cap).
    - If tiktoken isn't installed, falls back to a word-count approximation.
    """
    return int(count_tokens(text or "", model_name=model_name))


def iter_token_batches(
    texts: Sequence[str],
    *,
    metadatas: Optional[Sequence[Dict[str, Any]]] = None,
    max_tokens_per_batch: int = 250_000,
    model_name: Optional[str] = None,
) -> Iterator[Tuple[List[str], Optional[List[Dict[str, Any]]], int]]:
    """Yield (batch_texts, batch_metas, est_tokens) under a token budget.

    This is intended for embeddings calls where the provider enforces a maximum
    total tokens per request across the entire input array.
    """
    max_tok = int(max_tokens_per_batch)
    if max_tok <= 0:
        raise ValueError("max_tokens_per_batch must be > 0")

    use_metas = metadatas is not None
    if use_metas and len(metadatas or []) != len(texts):
        raise ValueError("metadatas length must match texts length when provided")

    batch_texts: List[str] = []
    batch_metas: List[Dict[str, Any]] = []
    batch_tokens = 0

    for i, t in enumerate(texts):
        tok = estimate_tokens(t, model_name=model_name)

        # If adding this item would exceed budget, flush current batch first.
        if batch_texts and (batch_tokens + tok) > max_tok:
            yield batch_texts, (batch_metas if use_metas else None), int(batch_tokens)
            batch_texts = []
            batch_metas = []
            batch_tokens = 0

        batch_texts.append(t)
        if use_metas:
            batch_metas.append(dict((metadatas or [])[i]))  # defensive copy
        batch_tokens += tok

    if batch_texts:
        yield batch_texts, (batch_metas if use_metas else None), int(batch_tokens)

