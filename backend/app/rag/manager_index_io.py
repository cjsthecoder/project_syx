"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Long-term memory FAISS index I/O and adjacency helpers.

This module provides atomic JSON read/write utilities, vector normalization,
doc_id/item_id rules, and writes the LTM manifest and adjacency sidecar artifacts.
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np  # type: ignore

logger = logging.getLogger(__name__)

ADJACENCY_SCHEMA_VERSION = "A.4.4.1"
LTM_MANIFEST_NAME = "index_manifest.json"
LTM_ADJACENCY_INDEX_NAME = "adjacency_index.json"
LTM_DOCSTORE_NAME = "docstore.json"
LTM_INDEX_TO_ID_NAME = "index_to_id.json"
LTM_INDEX_FILE_NAME = "index.faiss"


def atomic_write_json(path: str, obj: Any) -> None:
    """Write JSON to ``path`` atomically via a temp file + ``os.replace``.

    Args:
        path: Destination file path; a sibling ``.tmp`` file is written first.
        obj: JSON-serializable object; encoded sorted-key and indented for
            stable, diff-friendly output.
    """
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


def safe_load_json(path: str) -> Optional[Any]:
    """Load JSON from ``path``, returning None if missing or unreadable.

    Args:
        path: File path to read.

    Returns:
        The parsed JSON object, or None when the file is absent or cannot be
        read/decoded (the failure is logged at warning level).
    """
    try:
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("RAG: failed reading json path=%s detail=%s", path, exc)
        return None


def uploads_relative_doc_id(uploads_dir: str, file_path: str) -> str:
    """Derive a stable, forward-slash relative document id under uploads/.

    Args:
        uploads_dir: Project uploads directory used as the relativity root.
        file_path: Absolute or relative path to the uploaded file.

    Returns:
        The path relative to ``uploads_dir`` with OS separators normalized to
        ``/``; falls back to the bare basename when a relative path cannot be
        computed.
    """
    try:
        rel = os.path.relpath(file_path, uploads_dir)
    except Exception:
        rel = os.path.basename(file_path)
    return str(rel).replace(os.sep, "/")


def ltm_doc_id(filename: Optional[str], page_number: Optional[Any]) -> Optional[str]:
    """Resolve the adjacency ``doc_id`` for a chunk, enforcing boundary rules.

    Adjacency is scoped within a single uploaded source document (no cross-file
    linkage), and PDFs are not supported in the current implementation, so the
    page number is intentionally ignored.

    Args:
        filename: Uploaded source filename; non-string/empty values yield None.
        page_number: Accepted for interface compatibility but unused.

    Returns:
        The filename as the doc_id, or None when ``filename`` is missing/invalid.
    """
    if not filename or not isinstance(filename, str):
        return None
    return filename


def normalize_rows(v: np.ndarray) -> np.ndarray:
    """Unit-normalize each row of a matrix, treating zero rows as unit-norm.

    Args:
        v: 2-D array of row vectors; cast to float32.

    Returns:
        A float32 array with each row divided by its L2 norm (zero-norm rows are
        left unchanged by using a norm of 1.0). Empty input is returned as-is.
    """
    if v.size == 0:
        return v.astype("float32")
    v = v.astype("float32")
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return v / norms


def cosine_to_01(cos: float) -> float:
    """Map a cosine similarity in [-1, 1] onto the [0, 1] range.

    Args:
        cos: Cosine similarity; clamped to [-1, 1] before mapping.

    Returns:
        The rescaled score ``(cos + 1) / 2``; returns 0.0 for non-numeric input.
    """
    try:
        c = float(cos)
    except (TypeError, ValueError):
        return 0.0
    if c < -1.0:
        c = -1.0
    if c > 1.0:
        c = 1.0
    return (c + 1.0) / 2.0


def clear_dir_contents(path: str) -> None:
    """Remove every file under a directory tree (best-effort).

    Per-file and top-level failures are logged at warning level and otherwise
    suppressed so a partial clear never aborts the caller. A non-existent path
    is a no-op.

    Args:
        path: Directory whose file contents are recursively deleted.
    """
    try:
        if not os.path.isdir(path):
            return
        for root, _dirs, files in os.walk(path):
            for fn in files:
                try:
                    os.remove(os.path.join(root, fn))
                except Exception as exc:
                    logger.warning(
                        "RAG: failed removing file during clear_dir path=%s file=%s detail=%s",
                        path,
                        os.path.join(root, fn),
                        exc,
                    )
    except Exception as exc:
        logger.warning(
            "RAG: failed clearing directory contents; operation=clear_dir_contents path=%s detail=%s",
            path,
            exc,
        )


def build_ltm_adjacency_lists(
    *, docstore: Dict[str, Dict[str, Any]], index_to_id: List[str]
) -> Optional[Dict[str, List[str]]]:
    """Build the per-doc ordered adjacency lists used for neighbor expansion.

    Groups item ids by their ``doc_id`` and orders each group by ``chunk_seq``,
    validating that the sequence is gap-free and starts at 0 within every doc_id.

    Args:
        docstore: Map of item_id to a stored entry whose ``metadata`` carries
            ``doc_id`` and ``chunk_seq``.
        index_to_id: Row-ordered list of item ids backing the FAISS index.

    Returns:
        A mapping ``doc_id -> [item_id0, item_id1, ...]`` in chunk order, or None
        if any doc_id's sequence is non-contiguous or an unexpected error occurs.
    """
    try:
        by_doc: Dict[str, List[Tuple[int, str]]] = {}
        for item_id in index_to_id:
            entry = docstore.get(item_id) or {}
            md = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
            doc_id = md.get("doc_id")
            seq = md.get("chunk_seq")
            if not isinstance(doc_id, str):
                continue
            try:
                si = int(seq)
            except (TypeError, ValueError):
                continue
            by_doc.setdefault(doc_id, []).append((si, str(item_id)))

        out: Dict[str, List[str]] = {}
        for doc_id, pairs in by_doc.items():
            pairs = sorted(pairs, key=lambda p: p[0])
            if not pairs:
                continue
            seqs = [p[0] for p in pairs]
            if seqs[0] != 0 or seqs != list(range(0, len(seqs))):
                return None
            out[doc_id] = [p[1] for p in pairs]
        return out
    except Exception as exc:
        logger.warning("RAG: failed building adjacency list detail=%s", exc)
        return None


def write_ltm_manifest_and_adjacency(
    *,
    project_id: str,
    faiss_dir: str,
    index_dim: int,
    chunk_size: int,
    chunk_overlap: int,
    docstore: Dict[str, Dict[str, Any]],
    index_to_id: List[str],
) -> bool:
    """Persist the LTM adjacency sidecar and index manifest for a project.

    On failure retrieval may still work, but adjacency-based expansion is treated
    as unavailable. The function returns False (rather than raising) when the
    adjacency list cannot be built or the writes fail.

    Args:
        project_id: Owning project id, recorded in both artifacts.
        faiss_dir: Directory where the sidecar and manifest are written.
        index_dim: Embedding dimensionality of the persisted index.
        chunk_size: Chunk size used when building the index (recorded for
            invalidation when settings change).
        chunk_overlap: Chunk overlap used when building the index (recorded for
            invalidation when settings change).
        docstore: Map of item_id to stored entry, used to build adjacency.
        index_to_id: Row-ordered list of item ids backing the index.

    Returns:
        True when both the adjacency sidecar and manifest are written; False when
        adjacency could not be built or persistence failed.
    """
    try:
        adj_list = build_ltm_adjacency_lists(docstore=docstore, index_to_id=index_to_id)
        if adj_list is None:
            return False

        adj_path = os.path.join(faiss_dir, LTM_ADJACENCY_INDEX_NAME)
        atomic_write_json(
            adj_path,
            {
                "schema_version": ADJACENCY_SCHEMA_VERSION,
                "project_id": project_id,
                "built_at": datetime.now(timezone.utc).isoformat(),
                "by_doc_id": adj_list,
            },
        )
        manifest_path = os.path.join(faiss_dir, LTM_MANIFEST_NAME)
        atomic_write_json(
            manifest_path,
            {
                "schema_version": ADJACENCY_SCHEMA_VERSION,
                "index_kind": "ltm",
                "project_id": project_id,
                "built_at": datetime.now(timezone.utc).isoformat(),
                "chunk_size": int(chunk_size),
                "chunk_overlap": int(chunk_overlap),
                "index_dim": int(index_dim),
                "score_mode": "cosine_ip_mapped_01",
                "index_file": LTM_INDEX_FILE_NAME,
                "docstore_file": LTM_DOCSTORE_NAME,
                "index_to_id_file": LTM_INDEX_TO_ID_NAME,
                "adjacency_index": LTM_ADJACENCY_INDEX_NAME,
            },
        )
        return True
    except Exception as exc:
        logger.warning(
            "RAG: failed writing manifest/adjacency project=%s detail=%s", project_id, exc
        )
        return False
