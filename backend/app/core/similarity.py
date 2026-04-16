"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""

from __future__ import annotations


def cosine_from_l2_distance(dist: float) -> float:
    """
    Convert an L2 distance returned by FAISS retrieval
    into an approximate cosine similarity in [0.0, 1.0] under unit-normalized embeddings.

    Note: some integrations may return squared L2 distance vs L2 distance.
    To be robust, compute both interpretations and take the higher cosine within bounds.
    """
    try:
        d = float(dist)
    except Exception:
        return 0.0
    if d < 0:
        return 0.0

    def _cos_from_d2(d2: float) -> float:
        # For unit vectors: d^2 = 2(1 - cos)
        return max(0.0, min(1.0, 1.0 - (float(d2) / 2.0)))

    # Interpret `d` as distance, compute d^2.
    cos_a = _cos_from_d2(d * d)
    # Interpret `d` as squared distance (legacy), use it directly.
    cos_b = _cos_from_d2(d)
    return max(min(cos_a, 1.0), min(cos_b, 1.0))

