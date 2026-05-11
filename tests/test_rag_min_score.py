"""
Copyright (c) 2025-2026 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
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
