"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
LLM model provider boundary.

This package intentionally contains vendor SDK imports so core code can depend
on a plain-data interface via LLMClient.
"""

from .factory import get_llm_client, get_llm_client_mini, reset_llm_clients

__all__ = ["get_llm_client", "get_llm_client_mini", "reset_llm_clients"]

