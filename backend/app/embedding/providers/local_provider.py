"""
Stub local embedding provider for upcoming local models.
"""

from __future__ import annotations

from typing import List, Optional

from ..base import EmbedResult


class LocalEmbeddingProvider:
    def embed(
        self,
        texts: List[str],
        *,
        model: Optional[str] = None,
        retries: int = 2,
        rate_limit_retries: int = 10,
    ) -> EmbedResult:
        raise NotImplementedError(
            "Local embedding provider is not implemented yet. "
            "Set EMBEDDING_PROVIDER=openai for now."
        )

    def embed_query(self, text: str, *, model: Optional[str] = None) -> List[float]:
        raise NotImplementedError(
            "Local embedding provider is not implemented yet. "
            "Set EMBEDDING_PROVIDER=openai for now."
        )
