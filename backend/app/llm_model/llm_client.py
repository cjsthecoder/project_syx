"""
Copyright (c) 2025-2026 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Backward-compatible shim for LLM client access.

Preferred import is now: app.llm_model.factory.get_llm_client.
"""


from .factory import get_llm_client, get_llm_client_mini, reset_llm_clients


__all__ = ["get_llm_client", "get_llm_client_mini", "reset_llm_clients"]

