"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Tests for route policy minimum-score defaults.

Verifies that ``load_and_validate_route_policy`` exposes the expected
per-route ``min_score`` thresholds for each retrieval category.
"""
from backend.app.core.route_policy import load_and_validate_route_policy


def test_route_policy_loads_min_score_defaults():
    policy = load_and_validate_route_policy()

    assert policy["CHITCHAT"].min_score == 0
    assert policy["DIRECT"].min_score == 0.82
    assert policy["PROCEDURAL"].min_score == 0.80
    assert policy["EXPLORATORY"].min_score == 0.78
    assert policy["SYNTHESIS"].min_score == 0.78
    assert policy["OTHER"].min_score == 0.80
