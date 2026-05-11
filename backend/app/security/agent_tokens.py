"""
Copyright (c) 2025-2026 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
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
