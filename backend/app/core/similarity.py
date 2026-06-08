"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
FAISS distance-to-cosine similarity conversion.

This module converts L2 distances returned by FAISS retrieval into approximate
cosine similarities in [0.0, 1.0], handling both distance and squared-distance inputs.
"""


def cosine_from_l2_distance(dist: float) -> float:
    """Convert a FAISS L2 distance into an approximate cosine similarity.

    The result lies in [0.0, 1.0] assuming unit-normalized embeddings. Some
    integrations return squared L2 distance rather than L2 distance, so both
    interpretations are computed and the higher in-bounds cosine is returned.

    Args:
        dist: L2 (or squared L2) distance from FAISS; non-numeric or negative
            values yield 0.0.

    Returns:
        The approximate cosine similarity in [0.0, 1.0].
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
