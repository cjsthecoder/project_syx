"""
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
    """Immutable stored document payload returned by a vector source.

    Attributes:
        text: The stored chunk/document text.
        metadata: Arbitrary metadata associated with the entry (ids, source
            document, chunk indexes, scoring hints, etc.).
    """

    text: str
    metadata: Metadata


@dataclass(frozen=True)
class VectorHit:
    """A single similarity search result with both raw and mapped scores.

    Attributes:
        entry: The stored entry that matched.
        ip: Raw cosine inner product in ``[-1, 1]``; only meaningful when the
            indexed and query vectors are unit-normalized.
        score01: ``ip`` mapped into ``[0, 1]`` for downstream compatibility.
    """

    entry: VectorEntry
    ip: float
    score01: float


@dataclass(frozen=True)
class VectorIndexInfo:
    """Debug/telemetry snapshot describing a vector index.

    Attributes:
        index_kind: Source kind, e.g. ``"daily"`` or ``"ltm"``.
        dim: Embedding dimensionality of the indexed vectors.
        score_mode: Scoring strategy label, e.g. ``"cosine_ip_mapped_01"``.
        built_at: Optional ISO timestamp recording when the index was built.
        schema_version: Optional schema/version tag for the index artifacts.
    """

    index_kind: str
    dim: int
    score_mode: str
    built_at: Optional[str] = None
    schema_version: Optional[str] = None


class VectorIndex(Protocol):
    """Shared contract for all vector sources used by canonical retrieval.

    Implemented by both the Daily (in-memory) and LTM (on-disk) indexes so the
    retrieval layer can search and join results without knowing the backing
    store. Search assumes unit-normalized vectors and cosine-mapped scoring.
    """

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

