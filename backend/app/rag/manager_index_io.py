"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
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
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


def safe_load_json(path: str) -> Optional[Any]:
    try:
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("RAG: failed reading json path=%s detail=%s", path, exc)
        return None


def uploads_relative_doc_id(uploads_dir: str, file_path: str) -> str:
    """Stable relative path identity under uploads/."""
    try:
        rel = os.path.relpath(file_path, uploads_dir)
    except Exception:
        rel = os.path.basename(file_path)
    return str(rel).replace(os.sep, "/")


def ltm_doc_id(filename: Optional[str], page_number: Optional[Any]) -> Optional[str]:
    """
    doc_id boundary rules.

    - Adjacency is within the same uploaded source document only (no cross-file).
    - PDFs are not supported in the current implementation.
    """
    if not filename or not isinstance(filename, str):
        return None
    return filename


def normalize_rows(v: np.ndarray) -> np.ndarray:
    """Unit-normalize rows (safe for zero vectors)."""
    if v.size == 0:
        return v.astype("float32")
    v = v.astype("float32")
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return v / norms


def cosine_to_01(cos: float) -> float:
    """Map cosine in [-1,1] to [0,1]."""
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
    """Remove all files under directory (best-effort)."""
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
    """
    Build ordered adjacency list per doc_id:
      doc_id -> [item_id0, item_id1, ...]
    Validates chunk_seq is gap-free starting at 0 within each doc_id.
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
    """
    Persist adjacency sidecar + manifest.
    If this fails, retrieval may still work, but adjacency is treated as unavailable.
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
                "built_at": datetime.utcnow().isoformat(),
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
                "built_at": datetime.utcnow().isoformat(),
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
        logger.warning("RAG: failed writing manifest/adjacency project=%s detail=%s", project_id, exc)
        return False
