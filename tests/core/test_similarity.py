"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for app.core.similarity.cosine_from_l2_distance.

Covers non-numeric/negative guards, the dual distance/squared-distance
interpretation, and clamping into [0.0, 1.0].
"""

import pytest
from app.core.similarity import cosine_from_l2_distance


def test_non_numeric_returns_zero():
    assert cosine_from_l2_distance("not-a-number") == 0.0


def test_negative_distance_returns_zero():
    assert cosine_from_l2_distance(-1.0) == 0.0


def test_zero_distance_is_perfect_similarity():
    # d=0 -> both interpretations give cos 1.0.
    assert cosine_from_l2_distance(0.0) == 1.0


def test_squared_distance_interpretation_wins_when_higher():
    # d=1.0: as distance d^2=1 -> cos_a=0.5; as squared distance -> cos_b=0.5.
    assert cosine_from_l2_distance(1.0) == pytest.approx(0.5)


def test_small_distance_maps_near_one():
    # d=0.1: distance interpretation d^2=0.01 -> 1 - 0.005 = 0.995 dominates the
    # squared interpretation (1 - 0.05 = 0.95); the higher in-bounds value wins.
    assert cosine_from_l2_distance(0.1) == pytest.approx(0.995)


def test_large_distance_clamps_to_zero():
    # Both interpretations fall out of bounds and clamp to 0.0.
    assert cosine_from_l2_distance(10.0) == 0.0


def test_result_always_within_unit_interval():
    for d in (0.0, 0.25, 0.5, 0.75, 1.0, 1.4142, 2.0, 5.0):
        cos = cosine_from_l2_distance(d)
        assert 0.0 <= cos <= 1.0
