"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Deterministic similarity-score ordering for retrieval candidates.

This module sorts candidate dicts in descending order by their raw cosine
similarity score using a stable sort that preserves input order on ties.
"""
from typing import Any, Dict, List


def order_candidates_by_similarity_score(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deterministic candidate ordering by similarity score.

    - Sort descending by candidate["score"] (raw cosine similarity 0.0–1.0).
    - Use stable sorting (ties preserve original input order).
    - Do not round/normalize scores here (sort on full-precision floats).

    Args:
        candidates: Candidate dicts, each expected to carry a numeric
            ``score``; a missing or falsy score is treated as 0.0.

    Returns:
        A new list ordered by descending score (stable on ties), or an empty
        list when no candidates are given.
    """
    if not candidates:
        return []
    # Python's sort is stable; ties preserve original order.
    return sorted(
        candidates,
        key=lambda c: float(c.get("score") or 0.0),
        reverse=True,
    )

