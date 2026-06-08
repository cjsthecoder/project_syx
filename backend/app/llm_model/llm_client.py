"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Backward-compatible shim for LLM client access.

Preferred import is now: app.llm_model.factory.get_llm_client.
"""


from .factory import get_llm_client, get_llm_client_mini, reset_llm_clients

__all__ = ["get_llm_client", "get_llm_client_mini", "reset_llm_clients"]
