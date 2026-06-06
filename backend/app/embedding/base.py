"""
Copyright (c) 2025-2026 Syx Project Contributors

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
