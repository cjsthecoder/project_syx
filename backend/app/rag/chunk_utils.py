"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Text chunking and chunk post-processing helpers for RAG.

This module provides deterministic character-based text splitting plus adjacent
chunk overlap trimming and snippet-group collapsing of retrieved chunks.
"""
from typing import Any, Dict, List


def split_text_simple(text: str, *, chunk_size: int, chunk_overlap: int) -> List[str]:
    """Split text into fixed-size character windows with deterministic overlap.

    Args:
        text: Source text to split; None is treated as empty.
        chunk_size: Window width in characters. A non-positive value yields no
            chunks.
        chunk_overlap: Number of characters each window shares with the previous
            one; clamped to ``chunk_size - 1`` and floored at 0.

    Returns:
        The ordered list of non-blank character chunks. Whitespace-only windows
        are dropped.
    """
    t = text or ""
    if int(chunk_size) <= 0:
        return []
    ov = max(0, int(chunk_overlap))
    if ov >= int(chunk_size):
        ov = max(0, int(chunk_size) - 1)
    step = int(chunk_size) - ov
    out: List[str] = []
    i = 0
    n = len(t)
    while i < n:
        ch = t[i : i + int(chunk_size)]
        if ch and ch.strip():
            out.append(ch)
        i += step
    return out


def trim_adjacent_chunk_overlap(
    chunks: List[Dict[str, Any]],
    chunk_overlap: int,
) -> None:
    """Trim duplicated overlap text between adjacent same-document chunks in place.

    For each consecutive pair (A, B) with the same valid ``source_document_id``,
    finds the longest exact overlap of A's suffix and B's prefix (capped by
    ``chunk_overlap``) and removes that prefix from B. Sparse/legacy chunks
    (missing or invalid ``source_document_id``) are skipped. B is never emptied;
    if the full overlap would empty B, B is left unchanged.

    Args:
        chunks: Ordered candidate chunk dicts, each with ``text`` and ``metadata``;
            mutated in place.
        chunk_overlap: Maximum number of overlapping characters to consider when
            matching a suffix/prefix pair. Non-positive values disable trimming.
    """
    if not chunks or chunk_overlap <= 0:
        return
    n = len(chunks)
    for i in range(n - 1):
        a = chunks[i]
        b = chunks[i + 1]
        if not isinstance(a, dict) or not isinstance(b, dict):
            continue
        md_a = a.get("metadata") if isinstance(a.get("metadata"), dict) else {}
        md_b = b.get("metadata") if isinstance(b.get("metadata"), dict) else {}
        sid_a = md_a.get("source_document_id")
        sid_b = md_b.get("source_document_id")
        if not isinstance(sid_a, str) or not isinstance(sid_b, str) or sid_a != sid_b:
            continue
        a_text = str(a.get("text") or "")
        b_text = str(b.get("text") or "")
        max_overlap = min(chunk_overlap, len(a_text), len(b_text))
        if max_overlap <= 0:
            continue
        k = 0
        for length in range(max_overlap, 0, -1):
            if a_text[-length:] == b_text[:length]:
                k = length
                break
        if k > 0 and k < len(b_text):
            b["text"] = b_text[k:]


def collapse_snippet_groups(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse adjacent same-document chunk runs into one snippet per group.

    Groups consecutive chunks that share the same ``(source_document_id, source)``
    and form a contiguous ``chunk_index`` run into a single entry. Each group entry
    carries the ``source`` and ``score`` of its first chunk, ``text`` formed by
    direct concatenation of member texts, and metadata copied from the first chunk
    with ``chunk_index`` rewritten as ``"first..last"`` for multi-chunk groups.
    Sparse/legacy chunks (invalid or missing ``source_document_id``) never merge.

    Args:
        chunks: Ordered candidate chunk dicts to collapse.

    Returns:
        A new list of collapsed snippet entries, preserving input order.
    """
    if not chunks:
        return []
    out: List[Dict[str, Any]] = []
    group: List[Dict[str, Any]] = []

    def _chunk_index(c: Dict[str, Any]) -> int | None:
        m = c.get("metadata") if isinstance(c.get("metadata"), dict) else {}
        ci = m.get("chunk_index") if m.get("chunk_index") is not None else m.get("chunk_seq")
        return ci if isinstance(ci, int) else None

    def _flush() -> None:
        if not group:
            return
        first = group[0]
        md = dict(first.get("metadata") or {}) if isinstance(first.get("metadata"), dict) else {}
        if len(group) > 1:
            indices = [ci for c in group if (ci := _chunk_index(c)) is not None]
            if indices:
                md["chunk_index"] = f"{min(indices)}..{max(indices)}"
        texts = [str(c.get("text") or "") for c in group]
        out.append(
            {
                "source": first.get("source"),
                "score": first.get("score"),
                "text": "".join(texts),
                "metadata": md,
            }
        )
        group.clear()

    for c in chunks:
        if not isinstance(c, dict):
            _flush()
            continue
        md = c.get("metadata") if isinstance(c.get("metadata"), dict) else {}
        sid = md.get("source_document_id")
        src = c.get("source")
        if not isinstance(sid, str) or src is None:
            _flush()
            group.append(c)
            _flush()
            continue
        if group:
            first_md = group[0].get("metadata") if isinstance(group[0].get("metadata"), dict) else {}
            first_sid = first_md.get("source_document_id")
            first_src = group[0].get("source")
            prev_idx = _chunk_index(group[-1])
            cur_idx = _chunk_index(c)
            if first_sid != sid or first_src != src or prev_idx is None or cur_idx != prev_idx + 1:
                _flush()
        group.append(c)
    _flush()
    return out
