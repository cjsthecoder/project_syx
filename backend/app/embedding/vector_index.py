"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
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
    """Debug/telemetry snapshot describing a vector index."""

    index_kind: str  # "daily" | "ltm" | ...
    dim: int
    score_mode: str  # e.g., "cosine_ip_mapped_01"
    built_at: Optional[str] = None
    schema_version: Optional[str] = None


class VectorIndex(Protocol):
    """Shared contract for all vector sources."""

    def size(self) -> int:
        """Return the number of vectors currently indexed.

        Returns:
            Count of stored vectors.
        """

    def search_by_vector(self, qvec_norm: np.ndarray, *, k: int) -> List[VectorHit]:
        """Search by a unit-normalized query vector.

        Args:
            qvec_norm: Unit-normalized query vector with shape ``(dim,)`` and
                dtype ``float32``; normalization is required for the cosine
                inner-product scoring to be valid.
            k: Maximum number of nearest neighbors to return.

        Returns:
            Up to ``k`` hits, each carrying the raw cosine inner-product and the
            mapped ``[0, 1]`` score, ordered most-similar first.
        """

    def get_by_id(self, item_id: str) -> Optional[VectorEntry]:
        """Fetch a stored entry by stable item id.

        Args:
            item_id: Stable identifier of the stored entry.

        Returns:
            The matching ``VectorEntry``, or ``None`` if no entry has that id.
        """

    def info(self) -> VectorIndexInfo:
        """Return a debug/telemetry snapshot describing this index.

        Returns:
            A ``VectorIndexInfo`` describing the index kind, dimensionality, and
            scoring mode.
        """

