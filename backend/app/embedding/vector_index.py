"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Shared vector index protocol and plain-data types.

This module defines the stable interface that both:
  - Daily (in-memory) vector index
  - LTM (on-disk) vector index
must implement, so canonical retrieval can be source-agnostic.
"""


from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

import numpy as np  # type: ignore

Metadata = Dict[str, Any]


@dataclass(frozen=True)
class VectorEntry:
    """Stored document payload (plain-data)."""

    text: str
    metadata: Metadata


@dataclass(frozen=True)
class VectorHit:
    """One similarity search result."""

    entry: VectorEntry
    # raw cosine inner product in [-1, 1] (requires unit-normalized vectors)
    ip: float
    # mapped score in [0, 1] for downstream compatibility
    score01: float


@dataclass(frozen=True)
class VectorIndexInfo:
    index_kind: str  # "daily" | "ltm" | ...
    dim: int
    score_mode: str  # e.g., "cosine_ip_mapped_01"
    built_at: Optional[str] = None
    schema_version: Optional[str] = None


class VectorIndex(Protocol):
    """Shared contract for all vector sources."""

    def size(self) -> int:
        """Number of vectors indexed."""

    def search_by_vector(self, qvec_norm: np.ndarray, *, k: int) -> List[VectorHit]:
        """
        Search by a unit-normalized query vector (shape: (dim,), float32).

        Returns hits with both raw inner-product and mapped [0,1] score.
        """

    def get_by_id(self, item_id: str) -> Optional[VectorEntry]:
        """Fetch a stored entry by stable item id."""

    def info(self) -> VectorIndexInfo:
        """Debug/telemetry snapshot."""

