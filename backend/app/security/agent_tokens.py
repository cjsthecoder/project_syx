"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""Agent-token authorization boundary for local agent interfaces."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentAuthorizationResult:
    authorized: bool
    forbidden: bool = False
    message: str = ""


def authorize_agent_token(project_id: str, agent_token: str) -> AgentAuthorizationResult:
    """
    A.4 local-development authorization stub.

    The call boundary is intentional: later deltas can replace this with real
    token validation and project access checks without changing endpoint shape.
    """
    _ = project_id
    _ = agent_token
    return AgentAuthorizationResult(authorized=True)
