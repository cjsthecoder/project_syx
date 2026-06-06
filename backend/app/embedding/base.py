"""
Copyright (c) 2025-2026 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Provider-agnostic embedding interfaces and result envelope.
"""


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
