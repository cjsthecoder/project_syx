"""
Copyright (c) 2025-2026 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
from typing import Any, Dict, List


def split_text_simple(text: str, *, chunk_size: int, chunk_overlap: int) -> List[str]:
    """Deterministic character splitter."""
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
    """
    Adjacent chunk overlap trimming.

    In-place: for each consecutive pair (A, B) with the same valid source_document_id,
    find the longest exact overlap of A's suffix and B's prefix (capped by chunk_overlap)
    and remove that prefix from B. Skips sparse/legacy chunks (missing or invalid
    source_document_id). Never empties B; if full overlap would empty B, leave B unchanged.
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
    """
    Snippet-group collapse.

    Groups adjacent chunks that share the same (source_document_id, source)
    into one entry per group. Each group entry has: source, score from first chunk;
    text = direct concatenation of chunk texts; metadata from first chunk, with
    chunk_index as "first..last" when the group has more than one chunk.
    Sparse/legacy chunks (invalid or missing source_document_id) do not merge.
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
