"""
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

import json
from types import SimpleNamespace

import app.rag.manager as manager
import faiss
import numpy as np
import pytest
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


def _patch_route_policy(monkeypatch, *, min_score, before=0, after=0):
    import app.core.route_policy as route_policy

    policy = SimpleNamespace(
        min_score=min_score,
        expansion_max_before=before,
        expansion_max_after=after,
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


# --- Background LTM rebuild scheduler -------------------------------------
#
# rebuild_faiss_index itself is exercised in test_manager_rebuild_helpers.py;
# here we only verify the thin scheduler's own logic: the in-flight dedup
# guard and the worker's clean-up (the daemon thread is stubbed so nothing
# actually runs off-thread).


@pytest.fixture(autouse=True)
def _clear_ltm_rebuilding():
    """Keep the module-level in-flight set clean around each test."""
    manager._LTM_REBUILDING.clear()
    yield
    manager._LTM_REBUILDING.clear()


def _thread_recorder():
    """Return (created_list, FakeThread) where FakeThread records but never runs."""
    created = []

    class _FakeThread:
        def __init__(self, *args, target=None, name=None, daemon=None, **kwargs):
            self.target = target
            self.name = name
            self.daemon = daemon
            self.started = False
            created.append(self)

        def start(self):
            self.started = True

    return created, _FakeThread


def test_schedule_ltm_rebuild_skips_when_already_in_flight(monkeypatch):
    calls = []
    monkeypatch.setattr(manager, "rebuild_faiss_index", lambda pid: calls.append(pid))
    created, fake_thread = _thread_recorder()
    monkeypatch.setattr(manager.threading, "Thread", fake_thread)

    manager._LTM_REBUILDING.add("p1")
    manager._schedule_ltm_rebuild("p1", reason="test")

    assert created == []  # no thread spawned
    assert calls == []  # rebuild never invoked
    assert "p1" in manager._LTM_REBUILDING  # existing in-flight marker untouched


def test_schedule_ltm_rebuild_spawns_daemon_and_worker_runs_rebuild(monkeypatch):
    calls = []
    monkeypatch.setattr(manager, "rebuild_faiss_index", lambda pid: calls.append(pid))
    created, fake_thread = _thread_recorder()
    monkeypatch.setattr(manager.threading, "Thread", fake_thread)

    manager._schedule_ltm_rebuild("p2", reason="test")

    # Marked in-flight and a started daemon thread was created (not yet run).
    assert "p2" in manager._LTM_REBUILDING
    assert len(created) == 1
    worker = created[0]
    assert worker.daemon is True
    assert worker.started is True

    # Run the body the thread would have executed off-thread.
    worker.target()
    assert calls == ["p2"]  # rebuild invoked exactly once
    assert "p2" not in manager._LTM_REBUILDING  # finally-block cleared the marker


def test_schedule_ltm_rebuild_worker_clears_marker_on_failure(monkeypatch):
    def boom(pid):
        raise RuntimeError("index broke")

    monkeypatch.setattr(manager, "rebuild_faiss_index", boom)
    created, fake_thread = _thread_recorder()
    monkeypatch.setattr(manager.threading, "Thread", fake_thread)

    manager._schedule_ltm_rebuild("p3", reason="test")
    worker = created[0]

    # Worker swallows the error (best-effort) and still clears the in-flight marker.
    worker.target()  # must not raise
    assert "p3" not in manager._LTM_REBUILDING


# --- LTMIndex (in-memory FAISS wrapper) -----------------------------------
#
# LTMIndex is normally only built inside load_faiss_index() off persisted
# files. Its constructor takes plain objects, so we exercise it directly with
# a tiny real IndexFlatIP (3-dim, orthonormal rows) -- no disk, no mocking.


def _build_ltm_index():
    """Build an LTMIndex over three orthonormal 3-dim vectors a/b/c."""
    vecs = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype="float32")
    index = faiss.IndexFlatIP(3)
    index.add(vecs)
    docstore = {
        "a": {"text": "alpha", "metadata": {"filename": "a.txt"}},
        "b": {"text": "bravo", "metadata": {"filename": "b.txt"}},
        "c": {"text": "charlie", "metadata": {"filename": "c.txt"}},
    }
    return manager.LTMIndex(
        index=index,
        index_to_id=["a", "b", "c"],
        docstore=docstore,
        built_at="2026-01-01T00:00:00Z",
        schema_version="vtest",
    )


def test_ltm_index_size_and_info():
    ltm = _build_ltm_index()
    assert ltm.size() == 3
    info = ltm.info()
    assert info.index_kind == "ltm"
    assert info.dim == 3
    assert info.score_mode == "cosine_ip_mapped_01"
    assert info.built_at == "2026-01-01T00:00:00Z"
    assert info.schema_version == "vtest"


def test_ltm_index_get_by_id_variants():
    ltm = manager.LTMIndex(
        index=faiss.IndexFlatIP(3),
        index_to_id=[],
        docstore={
            "ok": {"text": "hello", "metadata": {"k": "v"}},
            "nondict": "oops",  # malformed: not a dict
            "notext": {"metadata": {"k": "v"}},  # missing text -> ""
            "nomd": {"text": "hi"},  # missing metadata -> {}
        },
        built_at=None,
        schema_version=None,
    )
    ok = ltm.get_by_id("ok")
    assert ok is not None
    assert ok.text == "hello"
    assert ok.metadata == {"k": "v"}
    assert ltm.get_by_id("unknown") is None  # absent id
    assert ltm.get_by_id("nondict") is None  # malformed entry
    notext = ltm.get_by_id("notext")
    assert notext is not None and notext.text == ""  # text defaulted
    nomd = ltm.get_by_id("nomd")
    assert nomd is not None and nomd.metadata == {}  # metadata defaulted


def test_ltm_index_search_returns_ordered_hits_with_mapped_scores():
    ltm = _build_ltm_index()
    # Query aligned with row "a": ip(a)=1.0, ip(b)=ip(c)=0.0.
    hits = ltm.search_by_vector(np.array([1.0, 0.0, 0.0], dtype="float32"), k=3)
    assert len(hits) == 3
    assert hits[0].entry.text == "alpha"  # nearest first
    assert hits[0].ip == 1.0
    assert hits[0].score01 == 1.0  # cosine_to_01(1.0) == (1+1)/2
    others = [h for h in hits if h.entry.text != "alpha"]
    assert all(h.ip == 0.0 for h in others)
    assert all(h.score01 == 0.5 for h in others)  # cosine_to_01(0.0) == 0.5


def test_ltm_index_search_empty_index_returns_empty():
    empty = manager.LTMIndex(
        index=faiss.IndexFlatIP(3),
        index_to_id=[],
        docstore={},
        built_at=None,
        schema_version=None,
    )
    assert empty.size() == 0
    assert empty.search_by_vector(np.array([1.0, 0.0, 0.0], dtype="float32"), k=3) == []


def test_ltm_index_search_skips_unmapped_and_missing_rows():
    vecs = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype="float32")
    index = faiss.IndexFlatIP(3)
    index.add(vecs)
    # Only two ids for three rows: row 2 has no mapping (out of range), and
    # row 1's id is absent from the docstore (resolves to None).
    ltm = manager.LTMIndex(
        index=index,
        index_to_id=["a", "missing"],
        docstore={"a": {"text": "alpha", "metadata": {}}},
        built_at=None,
        schema_version=None,
    )
    hits = ltm.search_by_vector(np.array([0.0, 1.0, 0.0], dtype="float32"), k=3)
    # Row 1 ("missing" -> None) and row 2 (unmapped) are skipped; only "a" survives.
    assert [h.entry.text for h in hits] == ["alpha"]


# --- load_faiss_index (persisted load path) -------------------------------
#
# Exercised against a real FAISS index written to a temp dir (no mocking).
# The deep best-effort except blocks are excluded via pragmas in the source.

_ADJ = manager._ADJACENCY_SCHEMA_VERSION


def _write_index_dir(root, project_id, *, vectors, ids, docstore, manifest=None, adjacency=None):
    """Write a real FAISS index plus its json sidecars under <root>/<pid>/faiss/."""
    faiss_dir = root / project_id / "faiss"
    faiss_dir.mkdir(parents=True, exist_ok=True)
    dim = int(vectors.shape[1]) if vectors.size else 3
    index = faiss.IndexFlatIP(dim)
    if vectors.size:
        index.add(vectors)
    faiss.write_index(index, str(faiss_dir / "index.faiss"))
    (faiss_dir / "index_to_id.json").write_text(json.dumps(ids))
    (faiss_dir / "docstore.json").write_text(json.dumps(docstore))
    if manifest is not None:
        (faiss_dir / "index_manifest.json").write_text(json.dumps(manifest))
    if adjacency is not None:
        (faiss_dir / "adjacency_index.json").write_text(json.dumps(adjacency))
    return faiss_dir


def _vecs():
    return np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype="float32")


def _docstore():
    return {
        "a": {"text": "alpha", "metadata": {"filename": "a.txt"}},
        "b": {"text": "bravo", "metadata": {"filename": "b.txt"}},
    }


def test_load_faiss_index_missing_directory_returns_none(temp_memory_root):
    assert manager.load_faiss_index("nope") is None


def test_load_faiss_index_missing_files_returns_none(temp_memory_root):
    (temp_memory_root / "p" / "faiss").mkdir(parents=True)
    assert manager.load_faiss_index("p") is None


def test_load_faiss_index_empty_index_returns_none(temp_memory_root):
    _write_index_dir(
        temp_memory_root,
        "p",
        vectors=np.zeros((0, 3), dtype="float32"),
        ids=[],
        docstore={},
    )
    assert manager.load_faiss_index("p") is None


def test_load_faiss_index_happy_path_without_manifest(temp_memory_root):
    _write_index_dir(temp_memory_root, "p", vectors=_vecs(), ids=["a", "b"], docstore=_docstore())
    ltm = manager.load_faiss_index("p")
    assert ltm is not None
    assert ltm.size() == 2
    entry = ltm.get_by_id("a")
    assert entry is not None and entry.text == "alpha"
    info = ltm.info()
    assert info.built_at is None and info.schema_version is None


def test_load_faiss_index_reads_manifest_metadata(temp_memory_root):
    # schema_version != adjacency schema -> adjacency block skipped; metadata still read.
    manifest = {"built_at": "2026-01-02T00:00:00Z", "schema_version": "X.1"}
    _write_index_dir(
        temp_memory_root,
        "p",
        vectors=_vecs(),
        ids=["a", "b"],
        docstore=_docstore(),
        manifest=manifest,
    )
    ltm = manager.load_faiss_index("p")
    assert ltm is not None
    info = ltm.info()
    assert info.built_at == "2026-01-02T00:00:00Z"
    assert info.schema_version == "X.1"


def test_load_faiss_index_schedules_rebuild_on_chunk_param_mismatch(temp_memory_root, monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        manager, "_schedule_ltm_rebuild", lambda pid, reason: scheduled.append((pid, reason))
    )
    s = manager.get_settings()
    manifest = {
        "schema_version": _ADJ,
        "chunk_size": int(s.chunk_size) + 999,  # mismatch vs current settings
        "chunk_overlap": int(s.chunk_overlap),
    }
    _write_index_dir(
        temp_memory_root,
        "p",
        vectors=_vecs(),
        ids=["a", "b"],
        docstore=_docstore(),
        manifest=manifest,
    )
    assert manager.load_faiss_index("p") is not None
    assert scheduled and scheduled[0][1] == "a441_chunk_params_mismatch"


def test_load_faiss_index_schedules_rebuild_when_adjacency_missing(temp_memory_root, monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        manager, "_schedule_ltm_rebuild", lambda pid, reason: scheduled.append((pid, reason))
    )
    s = manager.get_settings()
    manifest = {
        "schema_version": _ADJ,
        "chunk_size": int(s.chunk_size),
        "chunk_overlap": int(s.chunk_overlap),
    }
    # No adjacency sidecar -> expected but missing -> rebuild scheduled.
    _write_index_dir(
        temp_memory_root,
        "p",
        vectors=_vecs(),
        ids=["a", "b"],
        docstore=_docstore(),
        manifest=manifest,
    )
    assert manager.load_faiss_index("p") is not None
    assert scheduled and scheduled[0][1] == "a441_adjacency_missing_or_invalid"


def test_load_faiss_index_no_rebuild_when_adjacency_valid(temp_memory_root, monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        manager, "_schedule_ltm_rebuild", lambda pid, reason: scheduled.append((pid, reason))
    )
    s = manager.get_settings()
    manifest = {
        "schema_version": _ADJ,
        "chunk_size": int(s.chunk_size),
        "chunk_overlap": int(s.chunk_overlap),
    }
    _write_index_dir(
        temp_memory_root,
        "p",
        vectors=_vecs(),
        ids=["a", "b"],
        docstore=_docstore(),
        manifest=manifest,
        adjacency={"schema_version": _ADJ},
    )
    assert manager.load_faiss_index("p") is not None
    assert scheduled == []  # valid adjacency sidecar -> no rebuild


# --- Pure expansion / dedupe / ordering transforms ------------------------


def test_expansion_tier_counts_by_rank_tier():
    # k <= 0 short-circuits.
    assert manager._expansion_tier_counts(0, 0, 4, 2) == (0, 0)
    # k=9 -> t1_end=ceil(9/3)=3, t2_end=ceil(18/3)=6.
    # Tier 1 (i < 3): full budget.
    assert manager._expansion_tier_counts(0, 9, 4, 2) == (4, 2)
    assert manager._expansion_tier_counts(2, 9, 4, 2) == (4, 2)
    # Tier 2 (3 <= i < 6): half, rounded up.
    assert manager._expansion_tier_counts(3, 9, 4, 2) == (2, 1)
    assert manager._expansion_tier_counts(5, 9, 5, 3) == (3, 2)
    # Tier 3 (i >= 6): at most one neighbor each side.
    assert manager._expansion_tier_counts(6, 9, 4, 2) == (1, 1)
    assert manager._expansion_tier_counts(8, 9, 4, 0) == (1, 0)


def test_dedupe_returns_empty_when_no_expanded_chunks():
    cands = [{"source": "ltm", "text": "x", "metadata": {}}]
    out, audit = manager._dedupe_expanded_chunks(cands)
    assert out == []
    assert audit.input_chunk_count == 0


def test_dedupe_first_seen_wins_and_preserves_sparse():
    cands = [
        {
            "source": "ltm",
            "score": 0.9,
            "metadata": {"foo": "bar"},
            "expanded_chunks": [
                {"source_document_id": "d1", "chunk_index": 0, "text": "c0"},
                {"source_document_id": "d1", "chunk_index": 1, "text": "c1"},
                {"source_document_id": "d1", "chunk_index": 0, "text": "dup"},  # duplicate key
                {"text": "sparse"},  # no usable key -> preserved in order
            ],
        }
    ]
    out, audit = manager._dedupe_expanded_chunks(cands)
    assert [c["text"] for c in out] == ["c0", "c1", "sparse"]
    assert audit.input_chunk_count == 4
    assert audit.unique_keyed_count == 2
    assert audit.duplicate_skipped_count == 1
    assert audit.sparse_preserved_count == 1
    assert len(audit.duplicate_events) == 1
    # Kept chunks carry normalized identity in metadata.
    assert out[0]["metadata"]["source_document_id"] == "d1"
    assert out[0]["metadata"]["chunk_index"] == 0


def test_order_chunks_groups_by_source_and_sorts_by_index():
    chunks = [
        {"text": "d1c2", "metadata": {"source_document_id": "d1", "chunk_index": 2}},
        {"text": "d2c0", "metadata": {"source_document_id": "d2", "chunk_index": 0}},
        {"text": "d1c0", "metadata": {"source_document_id": "d1", "chunk_index": 0}},
        {"text": "sparse", "metadata": {}},  # no identity -> appended last
        {"text": "d1c1", "metadata": {"source_document_id": "d1", "chunk_index": 1}},
    ]
    out = manager._order_chunks_by_source_document(chunks)
    # d1 (first-seen) before d2; within d1 sorted by chunk_index; sparse last.
    assert [c["text"] for c in out] == ["d1c0", "d1c1", "d1c2", "d2c0", "sparse"]


def test_dedupe_skips_non_dict_candidate_and_chunk():
    cands = [
        123,  # non-dict candidate -> skipped
        {
            "source": "ltm",
            "score": 0.9,
            "metadata": {},
            "expanded_chunks": [
                "not-a-dict",  # non-dict chunk -> skipped
                {"source_document_id": "d1", "chunk_index": 0, "text": "c0"},
            ],
        },
    ]
    out, audit = manager._dedupe_expanded_chunks(cands)
    assert [c["text"] for c in out] == ["c0"]
    assert audit.input_chunk_count == 1  # only the dict chunk counted


def test_order_skips_non_dict_candidate():
    chunks = [
        456,  # non-dict -> skipped
        {"text": "d1c0", "metadata": {"source_document_id": "d1", "chunk_index": 0}},
    ]
    out = manager._order_chunks_by_source_document(chunks)
    assert [c["text"] for c in out] == ["d1c0"]


# --- ltm adjacency lookup / fetch helpers ---------------------------------


def test_ltm_lookup_adjacent_legacy_index_returns_none(temp_memory_root):
    # No manifest -> not adjacency schema -> both neighbors None, no rebuild.
    _write_index_dir(temp_memory_root, "p", vectors=_vecs(), ids=["a", "b"], docstore=_docstore())
    out = manager.ltm_lookup_adjacent_docstore_ids("p", doc_id="d1", chunk_seq=1)
    assert out == {"prev_docstore_id": None, "next_docstore_id": None}


def test_ltm_lookup_adjacent_missing_sidecar_schedules_rebuild(temp_memory_root, monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        manager, "_schedule_ltm_rebuild", lambda pid, reason: scheduled.append((pid, reason))
    )
    manifest = {"schema_version": _ADJ}
    _write_index_dir(
        temp_memory_root,
        "p",
        vectors=_vecs(),
        ids=["a", "b"],
        docstore=_docstore(),
        manifest=manifest,  # claims adjacency but no sidecar written
    )
    out = manager.ltm_lookup_adjacent_docstore_ids("p", doc_id="d1", chunk_seq=1)
    assert out == {"prev_docstore_id": None, "next_docstore_id": None}
    assert scheduled and scheduled[0][1] == "a441_lookup_missing_or_invalid"


def test_ltm_lookup_adjacent_bad_shape_schedules_rebuild(temp_memory_root, monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        manager, "_schedule_ltm_rebuild", lambda pid, reason: scheduled.append((pid, reason))
    )
    manifest = {"schema_version": _ADJ}
    # adjacency present and right schema, but by_doc_id is not a dict.
    adjacency = {"schema_version": _ADJ, "by_doc_id": ["bad"]}
    _write_index_dir(
        temp_memory_root,
        "p",
        vectors=_vecs(),
        ids=["a", "b"],
        docstore=_docstore(),
        manifest=manifest,
        adjacency=adjacency,
    )
    out = manager.ltm_lookup_adjacent_docstore_ids("p", doc_id="d1", chunk_seq=1)
    assert out == {"prev_docstore_id": None, "next_docstore_id": None}
    assert scheduled and scheduled[0][1] == "a441_lookup_bad_shape"


def test_ltm_lookup_adjacent_unknown_doc_returns_none(temp_memory_root):
    manifest = {"schema_version": _ADJ}
    adjacency = {"schema_version": _ADJ, "by_doc_id": {"d1": ["c0", "c1", "c2"]}}
    _write_index_dir(
        temp_memory_root,
        "p",
        vectors=_vecs(),
        ids=["a", "b"],
        docstore=_docstore(),
        manifest=manifest,
        adjacency=adjacency,
    )
    # doc not in by_doc_id -> seq_map not a list -> None neighbors.
    out = manager.ltm_lookup_adjacent_docstore_ids("p", doc_id="missing", chunk_seq=1)
    assert out == {"prev_docstore_id": None, "next_docstore_id": None}


def test_ltm_lookup_adjacent_returns_neighbors(temp_memory_root):
    manifest = {"schema_version": _ADJ}
    adjacency = {"schema_version": _ADJ, "by_doc_id": {"d1": ["c0", "c1", "c2"]}}
    _write_index_dir(
        temp_memory_root,
        "p",
        vectors=_vecs(),
        ids=["a", "b"],
        docstore=_docstore(),
        manifest=manifest,
        adjacency=adjacency,
    )
    # central seq=1 -> prev=c0, next=c2.
    out = manager.ltm_lookup_adjacent_docstore_ids("p", doc_id="d1", chunk_seq=1)
    assert out == {"prev_docstore_id": "c0", "next_docstore_id": "c2"}
    # boundary seq=0 -> no prev; seq=2 -> no next.
    assert manager.ltm_lookup_adjacent_docstore_ids("p", doc_id="d1", chunk_seq=0) == {
        "prev_docstore_id": None,
        "next_docstore_id": "c1",
    }
    assert manager.ltm_lookup_adjacent_docstore_ids("p", doc_id="d1", chunk_seq=2) == {
        "prev_docstore_id": "c1",
        "next_docstore_id": None,
    }


def test_ltm_fetch_chunk_no_index_returns_none(temp_memory_root):
    assert manager.ltm_fetch_chunk_by_docstore_id("nope", "a") is None


def test_ltm_fetch_chunk_happy_and_missing(temp_memory_root):
    _write_index_dir(temp_memory_root, "p", vectors=_vecs(), ids=["a", "b"], docstore=_docstore())
    found = manager.ltm_fetch_chunk_by_docstore_id("p", "a")
    assert found == {"text": "alpha", "metadata": {"filename": "a.txt"}}
    # Absent docstore key -> None.
    assert manager.ltm_fetch_chunk_by_docstore_id("p", "zzz") is None


# --- canonical_retrieve_candidates ----------------------------------------


class _FakeEmbed:
    def __init__(self, vec):
        self._vec = vec

    def embed_query(self, query, model=None):
        return self._vec


def _patch_embed(monkeypatch, vec):
    monkeypatch.setattr(manager, "get_embedding_client", lambda: _FakeEmbed(vec))
    monkeypatch.setattr(manager, "get_active_embedding_model", lambda: "fake-model")


def test_canonical_returns_empty_when_k_nonpositive(temp_memory_root):
    assert manager.canonical_retrieve_candidates("p", "q", per_source_k_override=0) == []


def test_canonical_returns_empty_when_embed_fails(monkeypatch, temp_memory_root):
    class _Boom:
        def embed_query(self, query, model=None):
            raise RuntimeError("no embed")

    monkeypatch.setattr(manager, "get_embedding_client", lambda: _Boom())
    monkeypatch.setattr(manager, "get_active_embedding_model", lambda: "m")
    out = manager.canonical_retrieve_candidates("p", "q", sources=["ltm"], per_source_k_override=3)
    assert out == []


def test_canonical_ltm_happy_path(monkeypatch, temp_memory_root):
    _write_index_dir(temp_memory_root, "p", vectors=_vecs(), ids=["a", "b"], docstore=_docstore())
    _patch_embed(monkeypatch, [1.0, 0.0, 0.0])
    out = manager.canonical_retrieve_candidates("p", "q", sources=["ltm"], per_source_k_override=2)
    assert out and all(c["source"] == "ltm" for c in out)
    assert "alpha" in {c["text"] for c in out}


def test_canonical_ltm_no_index_returns_empty(monkeypatch, temp_memory_root):
    # No index on disk -> load_faiss_index returns None -> LTM contributes nothing.
    _patch_embed(monkeypatch, [1.0, 0.0, 0.0])
    out = manager.canonical_retrieve_candidates(
        "missing", "q", sources=["ltm"], per_source_k_override=2
    )
    assert out == []


def test_canonical_ltm_search_exception_schedules_rebuild(monkeypatch, temp_memory_root):
    _write_index_dir(temp_memory_root, "p", vectors=_vecs(), ids=["a", "b"], docstore=_docstore())
    _patch_embed(monkeypatch, [1.0, 0.0, 0.0])
    scheduled = []
    monkeypatch.setattr(
        manager, "_schedule_ltm_rebuild", lambda pid, reason: scheduled.append((pid, reason))
    )

    class _BrokenIndex:
        def search_by_vector(self, *a, **k):
            raise RuntimeError("boom")

    monkeypatch.setattr(manager, "load_faiss_index", lambda pid: _BrokenIndex())
    out = manager.canonical_retrieve_candidates("p", "q", sources=["ltm"], per_source_k_override=2)
    assert out == []
    assert scheduled and scheduled[0][1] == "canonical_ltm_search_exception"


def _daily_hit(text, score01, *, eid="e1", chunk_seq=None):
    md = {"daily_entry_id": eid}
    if chunk_seq is not None:
        md["chunk_seq"] = chunk_seq
    return manager.VectorHit(
        entry=manager.VectorEntry(text=text, metadata=md), ip=score01, score01=score01
    )


def _fake_daily_source(hits, meta_by_id, *, raise_search=False):
    def _search(qvec, k=0):
        if raise_search:
            raise RuntimeError("daily boom")
        return hits

    return SimpleNamespace(
        vs=SimpleNamespace(search_by_vector=_search),
        meta_by_id=meta_by_id,
    )


def test_canonical_daily_happy_with_entry(monkeypatch, temp_memory_root):
    import app.rag.daily_store as daily_store

    _patch_embed(monkeypatch, [1.0, 0.0, 0.0])
    hit = _daily_hit("daily text", 0.9, eid="e1")
    entry = {
        "memory_id": "m1",
        "entry_type": "note",
        "source_scope": "s",
        "current_scope": "c",
        "created_at": "2026-01-01",
        "tags_meta": {"topics": ["t"], "intent": "i", "type": "ty"},
        "tags": ["x"],
        "keep": True,
        "day_sequence": 5,
        "pair_ids": ["p1"],
    }
    ds = _fake_daily_source([hit], {"e1": entry})
    monkeypatch.setattr(daily_store, "get_daily_source", lambda pid: ds)
    out = manager.canonical_retrieve_candidates(
        "p", "q", sources=["daily"], per_source_k_override=2
    )
    assert len(out) == 1
    c = out[0]
    assert c["source"] == "daily"
    assert c["metadata"]["id"] == "e1"
    assert c["metadata"]["memory_id"] == "m1"
    assert c["metadata"]["topics"] == ["t"]
    assert c["metadata"]["day_sequence"] == 5


def test_canonical_daily_join_miss(monkeypatch, temp_memory_root):
    import app.rag.daily_store as daily_store

    _patch_embed(monkeypatch, [1.0, 0.0, 0.0])
    hit = _daily_hit("orphan", 0.7, eid="e9", chunk_seq=3)
    ds = _fake_daily_source([hit], {})  # eid not present -> join miss
    monkeypatch.setattr(daily_store, "get_daily_source", lambda pid: ds)
    out = manager.canonical_retrieve_candidates(
        "p", "q", sources=["daily"], per_source_k_override=2
    )
    assert len(out) == 1
    md = out[0]["metadata"]
    assert md["id"] is None
    assert md["source_document_id"] == "daily"
    assert md["chunk_index"] == 3  # from md.chunk_seq fallback


def test_canonical_daily_search_exception_notifies(monkeypatch, temp_memory_root):
    import app.rag.daily_store as daily_store

    _patch_embed(monkeypatch, [1.0, 0.0, 0.0])
    notified = []
    monkeypatch.setattr(
        daily_store,
        "notify_daily_search_failure",
        lambda pid, reason: notified.append((pid, reason)),
    )
    ds = _fake_daily_source([], {}, raise_search=True)
    monkeypatch.setattr(daily_store, "get_daily_source", lambda pid: ds)
    out = manager.canonical_retrieve_candidates(
        "p", "q", sources=["daily"], per_source_k_override=2
    )
    assert out == []
    assert notified and notified[0][1] == "canonical_daily_search_exception"


# --- _resolve_route_min_score ---------------------------------------------


def test_resolve_route_min_score_returns_policy_value(monkeypatch):
    _patch_route_policy(monkeypatch, min_score=0.42)
    assert manager._resolve_route_min_score("p", "OTHER") == pytest.approx(0.42)


def test_resolve_route_min_score_defaults_on_error(monkeypatch):
    import app.core.route_policy as route_policy

    def boom(route):
        raise RuntimeError("policy broke")

    monkeypatch.setattr(route_policy, "get_route_policy", boom)
    assert manager._resolve_route_min_score("p", "OTHER") == 0.0


# --- _select_score_gated_candidates ---------------------------------------


def test_select_gated_skips_below_min_score():
    ordered = [
        _ltm_cand("a", 0.9, doc="d1", idx=0),
        _ltm_cand("b", 0.8, doc="d2", idx=0),
        _ltm_cand("c", 0.4, doc="d3", idx=0),  # <= 0.5 -> skipped
    ]
    sel, bonus = manager._select_score_gated_candidates(
        ordered, max_keep=5, min_score=0.5, project_id="p"
    )
    assert [c["text"] for c in sel] == ["a", "b"]
    assert bonus == 0


def test_select_gated_caps_at_max_keep():
    ordered = [_ltm_cand(str(i), 0.9, doc=f"d{i}", idx=0) for i in range(5)]
    sel, _ = manager._select_score_gated_candidates(
        ordered, max_keep=2, min_score=0.0, project_id="p"
    )
    assert len(sel) == 2


def test_select_gated_adjacent_same_doc_grants_bonus():
    ordered = [
        _ltm_cand("a", 0.9, doc="d1", idx=0),
        _ltm_cand("b", 0.85, doc="d1", idx=1),  # adjacent same doc -> +1 slot
        _ltm_cand("c", 0.8, doc="d2", idx=0),
    ]
    sel, bonus = manager._select_score_gated_candidates(
        ordered, max_keep=2, min_score=0.0, project_id="p"
    )
    assert bonus == 1
    assert [c["text"] for c in sel] == ["a", "b", "c"]


def test_select_gated_bad_score_treated_as_zero():
    ordered = [{"source": "ltm", "text": "x", "score": "abc", "metadata": {}}]
    sel, _ = manager._select_score_gated_candidates(
        ordered, max_keep=5, min_score=0.0, project_id="p"
    )
    assert sel == []  # float("abc") -> 0.0 -> not > min_score 0.0 -> skipped


def test_select_gated_adjacent_bad_index_no_bonus():
    ordered = [
        _ltm_cand("a", 0.9, doc="d1", idx=0),
        {
            "source": "ltm",
            "text": "b",
            "score": 0.85,
            "metadata": {"source_document_id": "d1", "chunk_index": "oops"},
        },
    ]
    sel, bonus = manager._select_score_gated_candidates(
        ordered, max_keep=2, min_score=0.0, project_id="p"
    )
    assert bonus == 0
    assert len(sel) == 2


# --- _resolve_expansion_resources -----------------------------------------


def test_resolve_expansion_resources_valid_adjacency(monkeypatch, temp_memory_root):
    import app.rag.daily_store as daily_store

    _patch_route_policy(monkeypatch, min_score=0.0, before=1, after=1)
    manifest = {"schema_version": _ADJ}
    adjacency = {"schema_version": _ADJ, "by_doc_id": {}}
    _write_index_dir(
        temp_memory_root,
        "p",
        vectors=_vecs(),
        ids=["a", "b"],
        docstore=_docstore(),
        manifest=manifest,
        adjacency=adjacency,
    )
    sentinel = object()
    monkeypatch.setattr(daily_store, "get_daily_source", lambda pid: sentinel)
    res = manager._resolve_expansion_resources("p", "OTHER", daily_enabled=True)
    assert res.max_before == 1 and res.max_after == 1
    assert res.ltm_expand_ok is True
    assert res.ltm_index is not None
    assert res.daily_src is sentinel


def test_resolve_expansion_resources_missing_adjacency_schedules_rebuild(
    monkeypatch, temp_memory_root
):
    _patch_route_policy(monkeypatch, min_score=0.0, before=1, after=1)
    scheduled = []
    monkeypatch.setattr(
        manager, "_schedule_ltm_rebuild", lambda pid, reason: scheduled.append((pid, reason))
    )
    manifest = {"schema_version": _ADJ}  # claims adjacency, no sidecar
    _write_index_dir(
        temp_memory_root,
        "p",
        vectors=_vecs(),
        ids=["a", "b"],
        docstore=_docstore(),
        manifest=manifest,
    )
    res = manager._resolve_expansion_resources("p", "OTHER", daily_enabled=False)
    assert res.ltm_expand_ok is False
    assert res.ltm_index is None
    assert scheduled and scheduled[0][1] == "a442_adjacency_missing_or_invalid"


def test_resolve_expansion_resources_legacy_index_disables_expansion(monkeypatch, temp_memory_root):
    _patch_route_policy(monkeypatch, min_score=0.0, before=1, after=1)
    # Manifest without adjacency schema -> legacy -> expansion disabled, no rebuild.
    _write_index_dir(
        temp_memory_root,
        "p",
        vectors=_vecs(),
        ids=["a", "b"],
        docstore=_docstore(),
        manifest={"schema_version": "legacy"},
    )
    res = manager._resolve_expansion_resources("p", "OTHER", daily_enabled=False)
    assert res.ltm_expand_ok is False
    assert res.ltm_index is None


# --- _materialize_candidate_chunks / _materialize_all_expansions ----------


def _resources(**kw):
    base = dict(max_before=1, max_after=1, ltm_expand_ok=True, ltm_index=None, daily_src=None)
    base.update(kw)
    return manager._ExpansionResources(**base)


def _cand(source, *, doc="d1", idx=0, text="central"):
    md = {}
    if doc is not None:
        md["source_document_id"] = doc
    if idx is not None:
        md["chunk_index"] = idx
    return {"source": source, "text": text, "metadata": md}


def test_materialize_central_only_when_no_chunk_index():
    res = _resources()
    c = _cand("ltm", idx=None)  # no chunk_index/chunk_seq -> ci None
    out = manager._materialize_candidate_chunks(0, 1, c, resources=res)
    assert len(out) == 1
    assert out[0]["chunk_index"] is None


def test_materialize_central_only_when_no_budget():
    res = _resources(max_before=0, max_after=0)
    c = _cand("ltm", idx=5)
    out = manager._materialize_candidate_chunks(0, 1, c, resources=res)
    assert [ch["chunk_index"] for ch in out] == [5]


def test_materialize_ltm_expands_neighbors():
    class _FakeLTM:
        def get_by_id(self, item_id):
            mapping = {
                "d1::chunk=4": manager.VectorEntry(text="prev", metadata={}),
                "d1::chunk=6": manager.VectorEntry(text="next", metadata={}),
            }
            return mapping.get(item_id)

    res = _resources(ltm_index=_FakeLTM())
    c = _cand("ltm", doc="d1", idx=5, text="mid")
    out = manager._materialize_candidate_chunks(0, 1, c, resources=res)
    assert [ch["chunk_index"] for ch in out] == [4, 5, 6]
    assert [ch["text"] for ch in out] == ["prev", "mid", "next"]


def test_materialize_ltm_central_only_when_expand_disabled():
    res = _resources(ltm_expand_ok=False, ltm_index=object())
    c = _cand("ltm", doc="d1", idx=5)
    out = manager._materialize_candidate_chunks(0, 1, c, resources=res)
    assert [ch["chunk_index"] for ch in out] == [5]


def test_materialize_ltm_skips_missing_neighbor():
    class _FakeLTM:
        def get_by_id(self, item_id):
            # Only the "after" neighbor exists; "before" is missing -> skipped.
            if item_id == "d1::chunk=6":
                return manager.VectorEntry(text="next", metadata={})
            return None

    res = _resources(ltm_index=_FakeLTM())
    c = _cand("ltm", doc="d1", idx=5, text="mid")
    out = manager._materialize_candidate_chunks(0, 1, c, resources=res)
    assert [ch["chunk_index"] for ch in out] == [5, 6]


def test_materialize_daily_expands_neighbors():
    daily = SimpleNamespace(
        id_by_seq={1: "e1", 3: "e3"},
        vs=SimpleNamespace(
            get_by_id=lambda eid: {
                "e1": manager.VectorEntry(text="prev", metadata={}),
                "e3": manager.VectorEntry(text="next", metadata={}),
            }.get(eid)
        ),
    )
    res = _resources(daily_src=daily)
    c = _cand("daily", doc="dd", idx=2, text="mid")
    out = manager._materialize_candidate_chunks(0, 1, c, resources=res)
    assert [ch["chunk_index"] for ch in out] == [1, 2, 3]
    assert [ch["text"] for ch in out] == ["prev", "mid", "next"]


def test_materialize_daily_central_only_when_no_source():
    res = _resources(daily_src=None)
    c = _cand("daily", doc="dd", idx=2)
    out = manager._materialize_candidate_chunks(0, 1, c, resources=res)
    assert [ch["chunk_index"] for ch in out] == [2]


def test_materialize_daily_skips_missing_seq_and_entry():
    daily = SimpleNamespace(
        id_by_seq={1: None, 3: "e3"},  # seq 1 has no id -> skipped
        vs=SimpleNamespace(get_by_id=lambda eid: None),  # e3 resolves to None -> skipped
    )
    res = _resources(daily_src=daily)
    c = _cand("daily", doc="dd", idx=2, text="mid")
    out = manager._materialize_candidate_chunks(0, 1, c, resources=res)
    assert [ch["chunk_index"] for ch in out] == [2]  # only central survives


def test_materialize_unknown_source_central_only():
    res = _resources()
    c = _cand("weird", doc="dw", idx=9)
    out = manager._materialize_candidate_chunks(0, 1, c, resources=res)
    assert [ch["chunk_index"] for ch in out] == [9]


def test_materialize_all_attaches_chunks_and_skips_non_dict():
    res = _resources(max_before=0, max_after=0)
    c = _cand("ltm", doc="d1", idx=5, text="mid")
    kept = [c, "not-a-dict"]
    manager._materialize_all_expansions(kept, res, project_id="p")
    assert "expanded_chunks" in c
    assert c["text"] == "mid"  # rebuilt from central chunk
    assert kept[1] == "not-a-dict"  # non-dict left untouched


# --- _write_retrieval_debug_artifacts (direct) ----------------------------


def test_write_retrieval_debug_artifacts_full(monkeypatch, temp_memory_root, settings_override):
    settings_override(generate_debug_files=True)

    class _FakeLTM:
        def get_by_id(self, item_id):
            if item_id == "d1::chunk=4":
                return manager.VectorEntry(text="prev", metadata={})
            return None  # d1::chunk=6 missing

    daily = SimpleNamespace(
        # seq 0 -> no id (missing); e1/e4 -> entries (materialized); e3 -> None (missing entry).
        id_by_seq={0: None, 1: "e1", 3: "e3", 4: "e4"},
        vs=SimpleNamespace(
            get_by_id=lambda eid: (
                manager.VectorEntry(text="dn", metadata={}) if eid in ("e1", "e4") else None
            )
        ),
    )
    res = _resources(
        max_before=2, max_after=2, ltm_index=_FakeLTM(), daily_src=daily, ltm_expand_ok=True
    )

    selected = [
        _cand("ltm", doc="d1", idx=5),  # ltm probing (mat + missing)
        _cand("daily", doc="dd", idx=2),  # daily probing (mat + missing)
        _cand("weird", doc="dw", idx=9),  # else-branch central
        _cand("ltm", idx=None),  # central_only_or_unavailable
    ]
    audit = manager._DedupeAudit()
    audit.input_chunk_count = 2
    audit.unique_keyed_count = 2
    audit.duplicate_events = [
        {"source_document_id": "d1", "chunk_index": 0, "first_seen_pos": 1, "duplicate_pos": 3}
    ]
    kept = [
        {
            "source": "ltm",
            "score": 0.9,
            "text": "k",
            "metadata": {"source_document_id": "d1", "chunk_index": 5},
        },
    ]

    manager._write_retrieval_debug_artifacts(
        project_id="p",
        query="hello\nworld",
        route="OTHER",
        per_source_k=4,
        max_keep=4,
        min_score=0.1,
        daily_enabled=True,
        adjacent_bonus=1,
        resources=res,
        ordered=[*selected, _cand("ltm", doc="dropped", idx=0)],
        selected_candidates=selected,
        kept_candidates=kept,
        audit=audit,
    )

    retrieval_dir = temp_memory_root / "p" / "debug" / "rag" / "retrieval"
    written = sorted(f.name for f in retrieval_dir.iterdir())
    assert any("ordered_candidates" in n for n in written)
    assert not any("kept_candidates" in n for n in written)
    assert any("expansion_plan" in n for n in written)
    assert any("deduped_chunks" in n for n in written)
    ordered = next(f for f in retrieval_dir.iterdir() if "ordered_candidates" in f.name)
    ordered_text = ordered.read_text()
    assert "selected_count: 4" in ordered_text
    assert "[KEPT]" in ordered_text
    assert "SELECTION CUTOFF: kept 4 of 5 candidates" in ordered_text
    assert "[NOT_KEPT]" in ordered_text
    plan = next(f for f in retrieval_dir.iterdir() if "expansion_plan" in f.name)
    text = plan.read_text()
    assert "EXPANSION_PLAN" in text
    assert "materialized_seqs" in text
    assert "missing_seqs" in text  # at least one neighbor was missing
