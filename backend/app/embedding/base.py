"""
Provider-agnostic embedding interfaces and result envelope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol


@dataclass
class EmbedResult:
    vectors: List[List[float]]
    model: str


class EmbeddingClient(Protocol):
    def embed(
        self,
        texts: List[str],
        *,
        model: Optional[str] = None,
        retries: int = 2,
        rate_limit_retries: int = 10,
    ) -> EmbedResult:
        ...

    def embed_query(self, text: str, *, model: Optional[str] = None) -> List[float]:
        ...
