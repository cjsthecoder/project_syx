"""
LLM model provider boundary.

This package intentionally contains vendor SDK imports so core code can depend
on a plain-data interface via LLMClient.
"""

from .factory import get_llm_client, get_llm_client_mini, reset_llm_clients

__all__ = ["get_llm_client", "get_llm_client_mini", "reset_llm_clients"]

