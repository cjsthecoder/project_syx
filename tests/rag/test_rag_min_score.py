"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for route policy minimum-score configuration.

Verifies that the live route policy config satisfies the retrieval-selection
contract without freezing tunable calibration values in the test suite.
"""
from app.core.route_policy import EXPECTED_ROUTES, load_and_validate_route_policy


def test_route_policy_live_config_is_valid():
    policy = load_and_validate_route_policy()

    assert set(policy) == set(EXPECTED_ROUTES)
    assert policy["CHITCHAT"].retrieval_multiplier == 0

    for route, route_policy in policy.items():
        assert route_policy.retrieval_multiplier >= 0
        assert route_policy.max_keep >= 0
        assert 0 <= route_policy.min_score <= 1
        assert route_policy.expansion_max_before >= 0
        assert route_policy.expansion_max_after >= 0

        if route != "CHITCHAT":
            assert route_policy.retrieval_multiplier > 0
            assert route_policy.max_keep > 0
