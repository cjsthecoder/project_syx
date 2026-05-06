"""
Backward-compatible shim for LLM client access.

Preferred import is now: app.llm_model.factory.get_llm_client.
"""


from .factory import get_llm_client, get_llm_client_mini, reset_llm_clients


__all__ = ["get_llm_client", "get_llm_client_mini", "reset_llm_clients"]

