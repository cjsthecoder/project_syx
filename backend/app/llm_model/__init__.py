"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
LLM model provider boundary.

This package intentionally contains vendor SDK imports so core code can depend
on a plain-data interface via LLMClient.
"""

from .factory import get_llm_client, get_llm_client_mini, reset_llm_clients

__all__ = ["get_llm_client", "get_llm_client_mini", "reset_llm_clients"]
