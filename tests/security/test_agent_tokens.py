"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.security.agent_tokens.

The current implementation is an A.4 local-development authorization stub that
always authorizes. These tests pin that contract so a future replacement with
real validation is an intentional, visible change.
"""

import dataclasses

import pytest
from app.security.agent_tokens import (
    authorize_agent_token,
)


def test_stub_authorizes_any_inputs():
    result = authorize_agent_token("proj-1", "any-token")
    assert result.authorized is True
    assert result.forbidden is False
    assert result.message == ""


def test_stub_authorizes_empty_inputs():
    result = authorize_agent_token("", "")
    assert result.authorized is True
    assert result.forbidden is False


def test_result_is_frozen():
    result = authorize_agent_token("p", "t")
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.authorized = False  # type: ignore[misc]
