"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Provider-agnostic embedding interfaces and result envelope.
"""


from dataclasses import dataclass
from typing import List, Optional, Protocol


@dataclass
class EmbedResult:
    """Envelope holding embedding vectors and the model that produced them.

    Attributes:
        vectors: One embedding vector per input text, in input order.
        model: Identifier of the embedding model that produced the vectors.
    """

    vectors: List[List[float]]
    model: str


class EmbeddingClient(Protocol):
    """Provider-agnostic contract for embedding backends.

    Defines the boundary that lets the RAG/memory layers embed text without
    depending on a specific provider (OpenAI, local sentence-transformers,
    etc.). Implementations own retries/backoff and model selection.
    """

    def embed(
        self,
        texts: List[str],
        *,
        model: Optional[str] = None,
        retries: int = 2,
        rate_limit_retries: int = 10,
    ) -> EmbedResult:
        """Embed a batch of texts and return their vectors.

        Args:
            texts: Input strings to embed.
            model: Optional model override; falls back to the active model.
            retries: Maximum general (non-rate-limit) retry attempts.
            rate_limit_retries: Maximum rate-limit retry attempts.

        Returns:
            An ``EmbedResult`` with one vector per input text.
        """
        ...

    def embed_query(self, text: str, *, model: Optional[str] = None) -> List[float]:
        """Embed a single query string and return its vector.

        Args:
            text: Query string to embed.
            model: Optional model override; falls back to the active model.

        Returns:
            The embedding vector for ``text``, or an empty list when no vector
            is produced.
        """
        ...
