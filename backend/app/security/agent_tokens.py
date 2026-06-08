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
    """Outcome of an agent-token authorization check.

    Attributes:
        authorized: True when the agent is allowed to proceed.
        forbidden: True when access was explicitly denied (as opposed to simply
            unauthenticated); maps to an HTTP 403 at the call boundary.
        message: Optional human-readable reason, surfaced on denial.
    """

    authorized: bool
    forbidden: bool = False
    message: str = ""


def authorize_agent_token(project_id: str, agent_token: str) -> AgentAuthorizationResult:
    """Authorize an agent token against a project (A.4 stub).

    This is the security authorization boundary for local agent interfaces.
    The stub currently authorizes every request; the call boundary is
    intentional so later deltas can add real token validation and project
    access checks without changing the endpoint shape.

    Args:
        project_id: Project the agent is requesting access to.
        agent_token: Opaque agent token supplied by the caller.

    Returns:
        An ``AgentAuthorizationResult`` indicating authorization status.
    """
    _ = project_id
    _ = agent_token
    return AgentAuthorizationResult(authorized=True)
