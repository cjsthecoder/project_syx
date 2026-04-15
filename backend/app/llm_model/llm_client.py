"""
Backward-compatible shim for embedding client access.

Preferred import is now: app.embedding.factory.get_embedding_client
"""

from __future__ import annotations

from ..embedding.factory import get_embedding_client


def get_llm_client():
    return get_embedding_client()

