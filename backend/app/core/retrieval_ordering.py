"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""

from typing import Any, Dict, List


def order_candidates_by_similarity_score(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deterministic candidate ordering by similarity score.

    - Sort descending by candidate["score"] (raw cosine similarity 0.0–1.0).
    - Use stable sorting (ties preserve original input order).
    - Do not round/normalize scores here (sort on full-precision floats).
    """
    if not candidates:
        return []
    # Python's sort is stable; ties preserve original order.
    return sorted(
        candidates,
        key=lambda c: float(c.get("score") or 0.0),
        reverse=True,
    )

