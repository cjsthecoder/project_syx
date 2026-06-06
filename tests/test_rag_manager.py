"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Tests for app.rag.manager retrieval/selection logic.

Pure metadata helpers are tested directly. The candidate-consuming functions
(``retrieve_context`` and ``merge_daily_and_main``) are driven with a patched
``canonical_retrieve_candidates`` so selection/threshold/assembly behavior is
verified without embeddings, FAISS, or network.
"""

from types import SimpleNamespace

import pytest

import app.rag.manager as manager
from app.rag.manager import (
    _ltm_candidate_metadata,
    _snippet_header_metadata_fields,
    merge_daily_and_main,
    retrieve_context,
)


def _ltm_cand(text, score, *, doc="doc", idx=0):
    return {
        "source": "ltm",
        "text": text,
        "score": score,
        "metadata": {
            "filename": "f.txt",
            "page_number": 1,
            "source_document_id": doc,
            "chunk_index": idx,
        },
    }


def test_ltm_candidate_metadata_derives_identity_fallbacks():
    md = {"doc_id": "d1", "chunk_seq": 3, "filename": "x.txt"}
    out = _ltm_candidate_metadata(md)
    assert out["source_document_id"] == "d1"
    assert out["chunk_index"] == 3
    assert out["filename"] == "x.txt"


def test_ltm_candidate_metadata_prefers_explicit_fields():
    md = {"source_document_id": "explicit", "chunk_index": 7, "doc_id": "d", "chunk_seq": 1}
    out = _ltm_candidate_metadata(md)
    assert out["source_document_id"] == "explicit"
    assert out["chunk_index"] == 7


def test_snippet_header_metadata_fields_skips_none_and_sanitizes():
    md = {
        "memory_id": "m1",
        "semantic_handle": "a, b\nc",
        "source_scope": None,
        "entry_type": "note",
    }
    fields = dict(_snippet_header_metadata_fields(md))
    assert fields["memory_id"] == "m1"
    assert fields["entry_type"] == "note"
    assert "source_scope" not in fields
    # commas -> ';' and newlines -> space
    assert fields["semantic_handle"] == "a; b c"


def test_retrieve_context_filters_below_threshold(monkeypatch):
    cands = [_ltm_cand("kept", 0.9, idx=0), _ltm_cand("dropped", 0.3, idx=1)]
    monkeypatch.setattr(manager, "canonical_retrieve_candidates", lambda *a, **k: cands)
    out = retrieve_context("p1", "q", score_threshold=0.5)
    assert out["hit_count"] == 1
    assert len(out["snippets"]) == 1
    assert "kept" in out["context_text"]
    assert "dropped" not in out["context_text"]


def test_retrieve_context_fallback_when_none_pass(monkeypatch):
    cands = [_ltm_cand("low1", 0.3, idx=0), _ltm_cand("low2", 0.2, idx=1)]
    monkeypatch.setattr(manager, "canonical_retrieve_candidates", lambda *a, **k: cands)
    out = retrieve_context("p1", "q", score_threshold=0.9)
    assert out["hit_count"] == 0
    assert "fallback" in out["context_text"]
    assert "low1" in out["context_text"]  # best-scoring snippet is included


def test_retrieve_context_empty(monkeypatch):
    monkeypatch.setattr(manager, "canonical_retrieve_candidates", lambda *a, **k: [])
    out = retrieve_context("p1", "q", score_threshold=0.5)
    assert out["context_text"] == ""
    assert out["snippets"] == []


def _patch_route_policy(monkeypatch, *, min_score):
    import app.core.route_policy as route_policy

    policy = SimpleNamespace(
        min_score=min_score,
        expansion_max_before=0,
        expansion_max_after=0,
    )
    monkeypatch.setattr(route_policy, "get_route_policy", lambda route: policy)


def test_merge_returns_empty_for_nonpositive_limits(monkeypatch, temp_memory_root):
    monkeypatch.setattr(manager, "canonical_retrieve_candidates", lambda *a, **k: [])
    out = merge_daily_and_main("p1", "q", daily_enabled=False, max_keep=0)
    assert out["context_text"] == ""
    assert out["kept_candidates"] == 0


def test_merge_selects_top_by_score_under_max_keep(monkeypatch, temp_memory_root):
    _patch_route_policy(monkeypatch, min_score=0.0)
    cands = [
        _ltm_cand("c1", 0.7, doc="d1", idx=0),
        _ltm_cand("c2", 0.9, doc="d2", idx=0),
        _ltm_cand("c3", 0.8, doc="d3", idx=0),
    ]
    monkeypatch.setattr(manager, "canonical_retrieve_candidates", lambda *a, **k: cands)
    out = merge_daily_and_main("p1", "q", daily_enabled=False, max_keep=2, route="OTHER")
    assert out["selected_candidates"] == 2
    assert out["main_hits"] == 2
    assert "Context:" in out["context_text"]
    # Highest-scoring kept; lowest excluded.
    assert "c2" in out["context_text"]
    assert "c3" in out["context_text"]
    assert "c1" not in out["context_text"]


def test_merge_min_score_gating(monkeypatch, temp_memory_root):
    _patch_route_policy(monkeypatch, min_score=0.75)
    cands = [
        _ltm_cand("c1", 0.9, doc="d1", idx=0),
        _ltm_cand("c2", 0.8, doc="d2", idx=0),
        _ltm_cand("c3", 0.7, doc="d3", idx=0),  # below 0.75 -> skipped
        _ltm_cand("c4", 0.6, doc="d4", idx=0),  # below 0.75 -> skipped
    ]
    monkeypatch.setattr(manager, "canonical_retrieve_candidates", lambda *a, **k: cands)
    out = merge_daily_and_main("p1", "q", daily_enabled=False, max_keep=10, route="OTHER")
    assert out["selected_candidates"] == 2
    assert "c1" in out["context_text"]
    assert "c2" in out["context_text"]
    assert "c3" not in out["context_text"]
