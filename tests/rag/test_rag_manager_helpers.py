"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for the pure helpers extracted from ``merge_daily_and_main``.

These helpers contain no FAISS/embedding/network I/O, so they are exercised
directly: route min-score resolution, score-gated selection with the adjacent
same-document bonus, expansion tier budgeting, chunk-identity dedupe, source
document ordering, and prompt assembly.
"""
from types import SimpleNamespace

from app.rag.manager import (
    _assemble_context_prompt,
    _dedupe_expanded_chunks,
    _expansion_tier_counts,
    _order_chunks_by_source_document,
    _resolve_route_min_score,
    _select_score_gated_candidates,
)


def _cand(text, score, *, source="ltm", doc="doc", idx=0):
    return {
        "source": source,
        "text": text,
        "score": score,
        "metadata": {
            "filename": "f.txt",
            "page_number": 1,
            "source_document_id": doc,
            "chunk_index": idx,
        },
    }


def _expanded(source, doc, idx, text, *, score=0.9):
    return {
        "source": source,
        "score": score,
        "metadata": {"filename": "f.txt"},
        "expanded_chunks": [
            {"source_document_id": doc, "chunk_index": idx, "text": text},
        ],
    }


# --- _resolve_route_min_score -------------------------------------------------


def test_resolve_route_min_score_reads_policy(monkeypatch):
    import app.core.route_policy as route_policy

    monkeypatch.setattr(
        route_policy, "get_route_policy", lambda route: SimpleNamespace(min_score=0.42)
    )
    assert _resolve_route_min_score("p1", "OTHER") == 0.42


def test_resolve_route_min_score_defaults_zero_on_error(monkeypatch):
    import app.core.route_policy as route_policy

    def _boom(route):
        raise RuntimeError("policy unavailable")

    monkeypatch.setattr(route_policy, "get_route_policy", _boom)
    assert _resolve_route_min_score("p1", "OTHER") == 0.0


# --- _select_score_gated_candidates ------------------------------------------


def test_select_keeps_top_under_max_keep():
    ordered = [
        _cand("c2", 0.9, doc="d2", idx=0),
        _cand("c3", 0.8, doc="d3", idx=0),
        _cand("c1", 0.7, doc="d1", idx=0),
    ]
    selected, bonus = _select_score_gated_candidates(
        ordered, max_keep=2, min_score=0.0, project_id="p1"
    )
    assert [c["text"] for c in selected] == ["c2", "c3"]
    assert bonus == 0


def test_select_skips_at_or_below_min_score():
    ordered = [
        _cand("c1", 0.9, doc="d1", idx=0),
        _cand("c2", 0.8, doc="d2", idx=0),
        _cand("c3", 0.7, doc="d3", idx=0),  # <= 0.75 -> skipped
    ]
    selected, bonus = _select_score_gated_candidates(
        ordered, max_keep=10, min_score=0.75, project_id="p1"
    )
    assert [c["text"] for c in selected] == ["c1", "c2"]
    assert bonus == 0


def test_select_grows_limit_for_adjacent_same_document():
    # c1/c2 are adjacent chunks of the same document -> bonus raises the limit.
    ordered = [
        _cand("c1", 0.9, doc="d1", idx=0),
        _cand("c2", 0.8, doc="d1", idx=1),
        _cand("c3", 0.7, doc="d2", idx=0),
    ]
    selected, bonus = _select_score_gated_candidates(
        ordered, max_keep=2, min_score=0.0, project_id="p1"
    )
    assert [c["text"] for c in selected] == ["c1", "c2", "c3"]
    assert bonus == 1


# --- _expansion_tier_counts ---------------------------------------------------


def test_expansion_tier_counts_zero_k():
    assert _expansion_tier_counts(0, 0, 4, 2) == (0, 0)


def test_expansion_tier_counts_tiers():
    # k=9 -> t1_end=3, t2_end=6
    assert _expansion_tier_counts(0, 9, 4, 2) == (4, 2)  # top tier: full budget
    assert _expansion_tier_counts(3, 9, 4, 2) == (2, 1)  # mid tier: half (ceil)
    assert _expansion_tier_counts(6, 9, 4, 2) == (1, 1)  # bottom tier: <=1 each
    assert _expansion_tier_counts(8, 9, 4, 2) == (1, 1)


def test_expansion_tier_counts_bottom_clamps_to_budget():
    # When max_before/after are 0, the bottom tier still cannot exceed budget.
    assert _expansion_tier_counts(8, 9, 0, 0) == (0, 0)


# --- _dedupe_expanded_chunks --------------------------------------------------


def test_dedupe_keeps_unique_keyed_chunks():
    kept = [
        _expanded("ltm", "d1", 0, "a"),
        _expanded("ltm", "d1", 1, "b"),
    ]
    deduped, audit = _dedupe_expanded_chunks(kept)
    assert [c["text"] for c in deduped] == ["a", "b"]
    assert audit.unique_keyed_count == 2
    assert audit.duplicate_skipped_count == 0
    assert audit.input_chunk_count == 2


def test_dedupe_skips_duplicate_keys_first_seen_wins():
    kept = [
        _expanded("ltm", "d1", 0, "first"),
        _expanded("ltm", "d1", 0, "dup"),  # same (doc, idx) -> skipped
    ]
    deduped, audit = _dedupe_expanded_chunks(kept)
    assert [c["text"] for c in deduped] == ["first"]
    assert audit.duplicate_skipped_count == 1
    assert len(audit.duplicate_events) == 1
    assert audit.duplicate_events[0]["source_document_id"] == "d1"


def test_dedupe_preserves_sparse_entries():
    sparse = {
        "source": "daily",
        "score": 0.5,
        "metadata": {},
        "expanded_chunks": [
            {"source_document_id": None, "chunk_index": None, "text": "sparse"},
        ],
    }
    deduped, audit = _dedupe_expanded_chunks([sparse])
    assert [c["text"] for c in deduped] == ["sparse"]
    assert audit.sparse_preserved_count == 1
    assert audit.unique_keyed_count == 0


# --- _order_chunks_by_source_document ----------------------------------------


def test_order_groups_by_source_then_sorts_chunk_index():
    kept = [
        {"text": "d1c1", "metadata": {"source_document_id": "d1", "chunk_index": 1}},
        {"text": "d2c0", "metadata": {"source_document_id": "d2", "chunk_index": 0}},
        {"text": "d1c0", "metadata": {"source_document_id": "d1", "chunk_index": 0}},
    ]
    ordered = _order_chunks_by_source_document(kept)
    # d1 seen first -> its chunks (sorted) come before d2's.
    assert [c["text"] for c in ordered] == ["d1c0", "d1c1", "d2c0"]


def test_order_appends_sparse_chunks_last():
    kept = [
        {"text": "sparse", "metadata": {"source_document_id": None, "chunk_index": None}},
        {"text": "d1c0", "metadata": {"source_document_id": "d1", "chunk_index": 0}},
    ]
    ordered = _order_chunks_by_source_document(kept)
    assert [c["text"] for c in ordered] == ["d1c0", "sparse"]


# --- _assemble_context_prompt -------------------------------------------------


def test_assemble_context_prompt_builds_headers_and_buckets():
    kept = [
        {
            "source": "ltm",
            "score": 0.9,
            "text": "main text",
            "metadata": {"filename": "f.txt", "page_number": 1, "chunk_index": 0},
        },
        {
            "source": "daily",
            "score": 0.8,
            "text": "daily text",
            "metadata": {"route": "OTHER", "chunk_index": 2},
        },
    ]
    out = _assemble_context_prompt(kept)
    assert out.context_text.startswith("Context:\n---\n")
    assert "Snippet 1 (source=ltm, score=0.9000)" in out.context_text
    assert "Snippet 2 (source=daily, score=0.8000)" in out.context_text
    assert "file=f.txt" not in out.context_text
    assert "chunk_index=" not in out.context_text
    assert "cos=" not in out.context_text
    assert out.main_texts == ["main text"]
    assert out.daily_texts == ["daily text"]
    assert out.tokens_used > 0
    assert len(out.main_scores) == 1 and len(out.daily_scores) == 1


def test_assemble_context_prompt_empty():
    out = _assemble_context_prompt([])
    assert out.context_text == ""
    assert out.main_texts == [] and out.daily_texts == []
    assert out.tokens_used == 0
