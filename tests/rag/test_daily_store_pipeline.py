"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Pipeline/IO tests for app.rag.daily_store.

Exercises the in-memory DailyVectorIndex, markdown/tag rendering helpers, path
resolution and lock migration, cache lifecycle (warm/rebuild/mismatch/clear),
metadata load/save, embedding batches, the incremental cache update, append
flows, stats, and daily.md backfill. The embedding client, settings, and active
model are faked; FAISS and NumPy are real. Module-level caches are reset between
tests.
"""

import os
from types import SimpleNamespace

import app.rag.daily_store as ds
import numpy as np
import pytest

# --- fakes / fixtures -----------------------------------------------------


class _FakeLLM:
    def __init__(self, dim: int = 4, vectors=None):
        self._dim = dim
        self._vectors = vectors

    def embed(self, texts, model=None):
        if self._vectors is not None:
            return SimpleNamespace(vectors=self._vectors)
        return SimpleNamespace(vectors=[[0.1] * self._dim for _ in texts])


class _SyncThread:
    """threading.Thread stand-in that runs the target synchronously on start()."""

    def __init__(self, *, target, name=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


@pytest.fixture(autouse=True)
def _reset_daily_globals():
    with ds._CACHE_LOCK:
        ds._CACHE.clear()
        ds._WARMING.clear()
        ds._PROJECT_LOCKS.clear()
    yield
    with ds._CACHE_LOCK:
        ds._CACHE.clear()
        ds._WARMING.clear()
        ds._PROJECT_LOCKS.clear()


@pytest.fixture
def wired(tmp_path, monkeypatch):
    settings = SimpleNamespace(memory_root=str(tmp_path), max_embed_tokens_per_request=250_000)
    monkeypatch.setattr(ds, "get_settings", lambda: settings)
    monkeypatch.setattr(ds, "get_active_embedding_model", lambda: "fake-model")
    monkeypatch.setattr(ds, "get_embedding_client", lambda: _FakeLLM(dim=4))
    monkeypatch.setattr(ds, "write_debug_file", lambda *a, **k: None)
    return SimpleNamespace(tmp_path=tmp_path, settings=settings)


# --- _normalize_rows ------------------------------------------------------


def test_normalize_rows_empty_and_nonempty():
    assert ds._normalize_rows(np.zeros((0, 3))).size == 0
    out = ds._normalize_rows(np.array([[3.0, 4.0]], dtype="float32"))
    assert out[0] == pytest.approx([0.6, 0.8])


# --- DailyVectorIndex -----------------------------------------------------


def test_daily_vector_index_add_search_and_info():
    idx = ds.DailyVectorIndex(dim=4)
    assert idx.size() == 0
    info = idx.info()
    assert info.index_kind == "daily"
    assert info.dim == 4

    idx.add(item_id="a", vector=[1.0, 0.0, 0.0, 0.0], text="alpha", metadata={"k": 1})
    idx.add_many(
        item_ids=["b", "c"],
        vectors=[[0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]],
        texts=["beta", "gamma"],
        metadatas=[{"k": 2}, {"k": 3}],
    )
    assert idx.size() == 3

    entry = idx.get_by_id("a")
    assert entry is not None
    assert entry.text == "alpha"

    qvec = ds._normalize_rows(np.array([[1.0, 0.0, 0.0, 0.0]], dtype="float32"))[0]
    hits = idx.search_by_vector(qvec, k=3)
    assert hits
    assert 0.0 <= hits[0].score01 <= 1.0


def test_daily_vector_index_add_many_empty_is_noop():
    idx = ds.DailyVectorIndex(dim=4)
    idx.add_many(item_ids=[], vectors=[], texts=[], metadatas=[])
    assert idx.size() == 0


def test_daily_vector_index_add_dim_mismatch_raises():
    idx = ds.DailyVectorIndex(dim=4)
    with pytest.raises(RuntimeError, match="dim mismatch"):
        idx.add(item_id="a", vector=[1.0, 0.0], text="x", metadata={})


def test_daily_vector_index_add_many_dim_mismatch_raises():
    idx = ds.DailyVectorIndex(dim=4)
    with pytest.raises(RuntimeError, match="dim mismatch"):
        idx.add_many(item_ids=["a"], vectors=[[1.0, 0.0]], texts=["x"], metadatas=[{}])


def test_daily_vector_index_get_by_id_missing_and_malformed():
    idx = ds.DailyVectorIndex(dim=4)
    assert idx.get_by_id("nope") is None
    idx.docstore["weird"] = "not-a-dict"  # malformed shape
    assert idx.get_by_id("weird") is None
    idx.docstore["partial"] = {"text": 123, "metadata": "bad"}
    entry = idx.get_by_id("partial")
    assert entry is not None
    assert entry.text == ""  # non-string text coerced to empty
    assert entry.metadata == {}  # non-dict metadata coerced to empty


def test_daily_vector_index_get_by_id_swallows_unexpected_error():
    idx = ds.DailyVectorIndex(dim=4)
    idx.docstore = None  # type: ignore[assignment]  # corrupt shape -> .get raises
    assert idx.get_by_id("x") is None


def test_daily_vector_index_search_skips_entries_missing_from_docstore():
    idx = ds.DailyVectorIndex(dim=4)
    idx.add(item_id="a", vector=[1.0, 0.0, 0.0, 0.0], text="alpha", metadata={})
    # Corrupt the docstore so get_by_id returns None for the matched row.
    idx.docstore["a"] = "not-a-dict"
    qvec = ds._normalize_rows(np.array([[1.0, 0.0, 0.0, 0.0]], dtype="float32"))[0]
    assert idx.search_by_vector(qvec, k=1) == []


def test_daily_vector_index_search_empty_index_returns_empty():
    idx = ds.DailyVectorIndex(dim=4)
    qvec = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")
    assert idx.search_by_vector(qvec, k=3) == []


def test_daily_vector_index_search_skips_out_of_range_indices():
    idx = ds.DailyVectorIndex(dim=4)
    idx.add(item_id="a", vector=[1.0, 0.0, 0.0, 0.0], text="alpha", metadata={})
    # Asking for more neighbors than exist yields FAISS sentinel -1 entries, which are skipped.
    qvec = ds._normalize_rows(np.array([[1.0, 0.0, 0.0, 0.0]], dtype="float32"))[0]
    hits = idx.search_by_vector(qvec, k=5)
    assert len(hits) == 1


# --- _format_tags_block ---------------------------------------------------


def test_format_tags_block_empty_returns_empty():
    assert ds._format_tags_block(None) == ""
    assert ds._format_tags_block({}) == ""


def test_format_tags_block_with_and_without_semantic_handle():
    with_handle = ds._format_tags_block(
        {"topics": "a,b", "intent": "ask", "type": "q", "semantic_handle": "sh"}
    )
    assert "#topics: a,b" in with_handle
    assert "#semantic_handle: sh" in with_handle

    without = ds._format_tags_block({"topics": "x", "intent": "i", "type": "t"})
    assert "#semantic_handle" not in without


def test_format_tags_block_handles_formatting_error(caplog):
    class _RaisingDict(dict):
        def get(self, *_a, **_k):
            raise RuntimeError("boom")

    bad = _RaisingDict({"x": 1})  # truthy, but .get raises
    assert ds._format_tags_block(bad) == ""
    assert any("failed formatting tag metadata" in r.message for r in caplog.records)


# --- _render_markdown_entry (optional field branches) ---------------------


def test_render_markdown_entry_includes_optional_fields():
    entry = {
        "memory_id": "mem_20260507_214200_a8f3",
        "entry_type": "dream_output",
        "day_sequence": 3,
        "accepted_item_id": "item-1",
        "dream_output_type": "Open Question",
        "origin_memory_ids": ["mem_a"],
        "tags_meta": {
            "topics": "a, b",
            "intent": "reflect",
            "type": "note",
            "semantic_handle": "h",
        },
    }
    block = ds._render_markdown_entry(entry, user_text="u", assistant_text="a")
    assert "day_sequence: 3" in block
    assert "accepted_item_id: item-1" in block
    assert "dream_output_type: open_question" in block
    assert "semantic_handle: h" in block
    assert "intent: reflect" in block
    assert "type: note" in block


# --- _project_daily_paths -------------------------------------------------


def test_project_daily_paths_migrates_legacy_lock(wired):
    project_id = "proj-lock"
    base = os.path.join(str(wired.tmp_path), project_id)
    os.makedirs(base, exist_ok=True)
    legacy = os.path.join(base, "daily.lock")
    with open(legacy, "w") as f:
        f.write("")
    meta_path, lock_path, md_path = ds._project_daily_paths(project_id)
    assert lock_path.endswith(os.path.join("state", "daily.lock"))
    assert os.path.isfile(lock_path)  # migrated into state/
    assert not os.path.isfile(legacy)


def test_project_daily_paths_logs_when_migration_fails(wired, monkeypatch, caplog):
    project_id = "proj-lock-fail"
    base = os.path.join(str(wired.tmp_path), project_id)
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, "daily.lock"), "w") as f:
        f.write("")

    def boom(*_a, **_k):
        raise OSError("cannot move")

    monkeypatch.setattr(ds.os, "replace", boom)
    ds._project_daily_paths(project_id)
    assert any("lock migration failed" in r.message for r in caplog.records)


# --- cache primitives -----------------------------------------------------


def test_get_project_lock_is_stable():
    a = ds._get_project_lock("p")
    b = ds._get_project_lock("p")
    assert a is b


def test_clear_daily_cache_removes_state():
    ds._CACHE["p"] = ds._DailyCache(embedding_model="m", vs=None, meta_by_id={}, id_by_seq={})
    ds._WARMING.add("p")
    ds.clear_daily_cache("p")
    assert "p" not in ds._CACHE
    assert "p" not in ds._WARMING


def test_start_daily_cache_rebuild_dedupes(monkeypatch):
    calls = []
    monkeypatch.setattr(ds, "rebuild_daily_cache", lambda pid, reason: calls.append((pid, reason)))
    monkeypatch.setattr(ds.threading, "Thread", _SyncThread)
    ds.start_daily_cache_rebuild("p", reason="r1")
    assert calls == [("p", "r1")]
    # Second call while already warming would no-op, but the sync worker cleared
    # the warming flag, so a fresh call runs again.
    ds._WARMING.add("p")  # simulate in-flight rebuild
    ds.start_daily_cache_rebuild("p", reason="r2")
    assert calls == [("p", "r1")]  # deduped, not started again


# --- _load_metadata / _save_metadata --------------------------------------


def test_load_metadata_missing_returns_empty(tmp_path):
    assert ds._load_metadata(str(tmp_path / "none.json")) == []


def test_load_metadata_invalid_returns_empty(tmp_path, caplog):
    p = tmp_path / "daily.json"
    p.write_text("{not valid", encoding="utf-8")
    assert ds._load_metadata(str(p)) == []
    assert any("failed to load metadata" in r.message for r in caplog.records)


def test_save_and_load_metadata_roundtrip(tmp_path):
    p = str(tmp_path / "daily.json")
    ds._save_metadata(p, [{"id": "e1"}])
    assert ds._load_metadata(p) == [{"id": "e1"}]


def test_reconcile_logs_when_save_fails(wired, monkeypatch, caplog):
    project_id = "p-reconcile-fail"
    meta_path, lock_path, _md = ds._project_daily_paths(project_id)
    ds._save_metadata(
        meta_path, [{"id": "e1", "text": "x", "day_sequence": 1, "embedding_model": "old"}]
    )

    def boom(_p, _e):
        raise OSError("disk full")

    monkeypatch.setattr(ds, "_save_metadata", boom)
    entries = ds._reconcile_daily_embedding_model(
        project_id, meta_path, lock_path, "fake-model", reason="unit"
    )
    # In-memory entries are updated even though persistence failed (and was logged).
    assert entries[0]["embedding_model"] == "fake-model"
    assert any("failed updating daily.json embedding_model" in r.message for r in caplog.records)


def test_collect_texts_logs_invalid_day_sequence(wired, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    entries = [{"id": "e1", "embed_text": "alpha", "day_sequence": "not-an-int"}]
    texts, _metas, meta_by_id, id_by_seq = ds._collect_daily_texts_and_maps(entries, "p")
    assert texts == ["alpha"]
    assert "e1" in meta_by_id  # still indexed by id
    assert id_by_seq == {}  # bad sequence skipped
    assert any("invalid day_sequence" in r.message for r in caplog.records)


# --- reset_daily ----------------------------------------------------------


def test_reset_daily_removes_metadata_and_cache(wired):
    project_id = "proj-reset"
    meta_path, _lock, _md = ds._project_daily_paths(project_id)
    ds._save_metadata(meta_path, [{"id": "e1"}])
    ds._CACHE[project_id] = ds._DailyCache(
        embedding_model="m", vs=None, meta_by_id={}, id_by_seq={}
    )
    ds.reset_daily(project_id)
    assert not os.path.exists(meta_path)
    assert project_id not in ds._CACHE


def test_reset_daily_logs_remove_failure(wired, monkeypatch, caplog):
    project_id = "proj-reset-fail"
    meta_path, _lock, _md = ds._project_daily_paths(project_id)
    ds._save_metadata(meta_path, [{"id": "e1"}])

    def boom(_p):
        raise OSError("locked")

    monkeypatch.setattr(ds.os, "remove", boom)
    ds.reset_daily(project_id)  # must not raise
    assert any("failed to remove metadata" in r.message for r in caplog.records)


# --- get_daily_source -----------------------------------------------------


def test_get_daily_source_cold_schedules_rebuild_and_returns_none(wired, monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        ds, "start_daily_cache_rebuild", lambda pid, reason: scheduled.append((pid, reason))
    )
    assert ds.get_daily_source("p-cold") is None
    assert scheduled and scheduled[0][0] == "p-cold"


def test_get_daily_source_vs_none_returns_none(wired):
    ds._CACHE["p"] = ds._DailyCache(
        embedding_model="fake-model", vs=None, meta_by_id={}, id_by_seq={}
    )
    assert ds.get_daily_source("p") is None


def test_get_daily_source_model_mismatch_schedules_and_returns_none(wired, monkeypatch):
    vs = ds.DailyVectorIndex(dim=4)
    ds._CACHE["p"] = ds._DailyCache(embedding_model="OLD-model", vs=vs, meta_by_id={}, id_by_seq={})
    scheduled = []
    monkeypatch.setattr(
        ds, "start_daily_cache_rebuild", lambda pid, reason: scheduled.append((pid, reason))
    )
    assert ds.get_daily_source("p") is None
    assert scheduled and "mismatch" in scheduled[0][1]


def test_get_daily_source_warm_returns_source(wired):
    vs = ds.DailyVectorIndex(dim=4)
    ds._CACHE["p"] = ds._DailyCache(
        embedding_model="fake-model", vs=vs, meta_by_id={"e1": {}}, id_by_seq={1: "e1"}
    )
    src = ds.get_daily_source("p")
    assert src is not None
    assert src.embedding_model == "fake-model"
    assert src.id_by_seq == {1: "e1"}


# --- daily_lookup_adjacent_entry_ids --------------------------------------


def test_daily_lookup_adjacent_no_source_returns_none(wired, monkeypatch):
    monkeypatch.setattr(ds, "get_daily_source", lambda pid: None)
    out = ds.daily_lookup_adjacent_entry_ids("p", day_sequence=2)
    assert out == {"prev_entry_id": None, "next_entry_id": None}


def test_daily_lookup_adjacent_returns_neighbors(wired, monkeypatch):
    src = SimpleNamespace(id_by_seq={1: "e1", 2: "e2", 3: "e3"})
    monkeypatch.setattr(ds, "get_daily_source", lambda pid: src)
    out = ds.daily_lookup_adjacent_entry_ids("p", day_sequence=2)
    assert out == {"prev_entry_id": "e1", "next_entry_id": "e3"}


def test_daily_lookup_adjacent_invalid_sequence(wired, monkeypatch):
    src = SimpleNamespace(id_by_seq={1: "e1"})
    monkeypatch.setattr(ds, "get_daily_source", lambda pid: src)
    out = ds.daily_lookup_adjacent_entry_ids("p", day_sequence="bad")  # type: ignore[arg-type]
    assert out == {"prev_entry_id": None, "next_entry_id": None}


# --- notify_daily_search_failure ------------------------------------------


def test_notify_daily_search_failure_schedules(monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        ds, "start_daily_cache_rebuild", lambda pid, reason: scheduled.append((pid, reason))
    )
    ds.notify_daily_search_failure("p", "search_raised")
    assert scheduled == [("p", "search_raised")]


def test_notify_daily_search_failure_logs_on_error(monkeypatch, caplog):
    def boom(pid, reason):
        raise RuntimeError("scheduler down")

    monkeypatch.setattr(ds, "start_daily_cache_rebuild", boom)
    ds.notify_daily_search_failure("p", "search_raised")  # must not raise
    assert any("failed scheduling cache rebuild" in r.message for r in caplog.records)


# --- _embed_daily_batches -------------------------------------------------


def test_embed_daily_batches_builds_index(wired):
    texts = ["alpha", "beta"]
    metas = [
        {"daily_entry_id": "e1", "day_sequence": 1, "chunk_seq": 1},
        {"daily_entry_id": None, "day_sequence": 2, "chunk_seq": 2},
    ]
    vs = ds._embed_daily_batches(texts, metas, "fake-model", 250_000, "p", "unit")
    assert vs is not None
    assert vs.size() == 2
    assert "e1" in vs.docstore
    assert "daily::seq=2" in vs.docstore  # synthetic id when daily_entry_id is None


def test_embed_daily_batches_empty_vectors_yields_none(wired, monkeypatch):
    monkeypatch.setattr(ds, "get_embedding_client", lambda: _FakeLLM(vectors=[]))
    vs = ds._embed_daily_batches(
        ["alpha"], [{"daily_entry_id": "e1"}], "fake-model", 250_000, "p", "u"
    )
    assert vs is None


# --- _write_daily_rebuild_report ------------------------------------------


def test_write_daily_rebuild_report_happy(wired, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        ds, "write_debug_file", lambda pid, path, body: captured.update(pid=pid, body=body)
    )
    ds._write_daily_rebuild_report("p", "unit", "fake-model", 5, {1: "e1", 2: "e2"})
    assert captured["pid"] == "p"
    assert "vectors: 5" in captured["body"]


def test_write_daily_rebuild_report_swallows_error(wired, monkeypatch, caplog):
    def boom(*_a, **_k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(ds, "write_debug_file", boom)
    ds._write_daily_rebuild_report("p", "unit", "fake-model", 1, {})  # must not raise
    assert any("failed writing daily cache debug report" in r.message for r in caplog.records)


# --- rebuild_daily_cache --------------------------------------------------


def test_rebuild_daily_cache_no_texts_builds_empty(wired):
    project_id = "p-empty"
    meta_path, _lock, _md = ds._project_daily_paths(project_id)
    ds._save_metadata(meta_path, [{"id": "e1", "day_sequence": 1}])  # no text
    assert ds.rebuild_daily_cache(project_id, "unit") is True
    assert ds._CACHE[project_id].vs is None


def test_rebuild_daily_cache_builds_vectors(wired):
    project_id = "p-build"
    meta_path, _lock, _md = ds._project_daily_paths(project_id)
    ds._save_metadata(
        meta_path,
        [
            {"id": "e1", "embed_text": "alpha", "day_sequence": 1},
            {"id": "e2", "embed_text": "beta", "day_sequence": 2},
        ],
    )
    assert ds.rebuild_daily_cache(project_id, "unit") is True
    cache = ds._CACHE[project_id]
    assert cache.vs is not None
    assert cache.vs.size() == 2
    assert cache.id_by_seq == {1: "e1", 2: "e2"}


def test_rebuild_daily_cache_vs_none_when_embeddings_empty(wired, monkeypatch):
    monkeypatch.setattr(ds, "get_embedding_client", lambda: _FakeLLM(vectors=[]))
    project_id = "p-vsnone"
    meta_path, _lock, _md = ds._project_daily_paths(project_id)
    ds._save_metadata(meta_path, [{"id": "e1", "embed_text": "alpha", "day_sequence": 1}])
    assert ds.rebuild_daily_cache(project_id, "unit") is True
    assert ds._CACHE[project_id].vs is None


def test_rebuild_daily_cache_failure_returns_false(wired, monkeypatch):
    def boom(entries, project_id):
        raise RuntimeError("collect blew up")

    monkeypatch.setattr(ds, "_collect_daily_texts_and_maps", boom)
    project_id = "p-fail"
    meta_path, _lock, _md = ds._project_daily_paths(project_id)
    ds._save_metadata(meta_path, [{"id": "e1", "embed_text": "alpha", "day_sequence": 1}])
    assert ds.rebuild_daily_cache(project_id, "unit") is False
    assert project_id not in ds._CACHE


# --- ensure_daily_cache ---------------------------------------------------


def test_ensure_daily_cache_fast_path_returns_true(wired):
    project_id = "p-fast"
    meta_path, _lock, _md = ds._project_daily_paths(project_id)
    ds._save_metadata(meta_path, [{"id": "e1", "embedding_model": "fake-model", "day_sequence": 1}])
    ds._CACHE[project_id] = ds._DailyCache(
        embedding_model="fake-model", vs=None, meta_by_id={}, id_by_seq={}
    )
    assert ds.ensure_daily_cache(project_id, reason="warm") is True


def test_ensure_daily_cache_rebuilds_when_missing(wired):
    project_id = "p-missing"
    meta_path, _lock, _md = ds._project_daily_paths(project_id)
    ds._save_metadata(meta_path, [{"id": "e1", "embed_text": "alpha", "day_sequence": 1}])
    assert ds.ensure_daily_cache(project_id, reason="warm") is True
    assert ds._CACHE[project_id].vs is not None


def test_ensure_daily_cache_validation_error_triggers_rebuild(wired, monkeypatch):
    project_id = "p-valfail"
    meta_path, _lock, _md = ds._project_daily_paths(project_id)
    ds._save_metadata(meta_path, [{"id": "e1", "embed_text": "alpha", "day_sequence": 1}])
    ds._CACHE[project_id] = ds._DailyCache(
        embedding_model="fake-model", vs=None, meta_by_id={}, id_by_seq={}
    )
    calls = {"n": 0}
    real_load = ds._load_metadata

    def flaky(path):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("validate failed")
        return real_load(path)

    monkeypatch.setattr(ds, "_load_metadata", flaky)
    assert ds.ensure_daily_cache(project_id, reason="warm") is True


# --- _update_cache_with_entry ---------------------------------------------


def _entry(eid="e1", seq=1):
    return {"id": eid, "memory_id": "mem_x", "day_sequence": seq}


def test_update_cache_missing_cache_schedules_rebuild(wired, monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        ds, "start_daily_cache_rebuild", lambda pid, reason: scheduled.append(reason)
    )
    assert ds._update_cache_with_entry("p", _entry(), "text") is False
    assert "append_missing_cache" in scheduled


def test_update_cache_model_mismatch_schedules_rebuild(wired, monkeypatch):
    ds._CACHE["p"] = ds._DailyCache(embedding_model="OLD", vs=None, meta_by_id={}, id_by_seq={})
    scheduled = []
    monkeypatch.setattr(
        ds, "start_daily_cache_rebuild", lambda pid, reason: scheduled.append(reason)
    )
    assert ds._update_cache_with_entry("p", _entry(), "text") is False
    assert "append_model_mismatch" in scheduled


def test_update_cache_creates_vs_when_empty(wired):
    ds._CACHE["p"] = ds._DailyCache(
        embedding_model="fake-model", vs=None, meta_by_id={}, id_by_seq={}
    )
    assert ds._update_cache_with_entry("p", _entry("e9", 4), "text to embed") is True
    cache = ds._CACHE["p"]
    assert cache.vs is not None
    assert cache.vs.size() == 1
    assert cache.id_by_seq == {4: "e9"}


def test_update_cache_empty_embedding_schedules_rebuild(wired, monkeypatch):
    ds._CACHE["p"] = ds._DailyCache(
        embedding_model="fake-model", vs=None, meta_by_id={}, id_by_seq={}
    )
    monkeypatch.setattr(ds, "get_embedding_client", lambda: _FakeLLM(vectors=[]))
    scheduled = []
    monkeypatch.setattr(
        ds, "start_daily_cache_rebuild", lambda pid, reason: scheduled.append(reason)
    )
    assert ds._update_cache_with_entry("p", _entry(), "text") is False
    assert "append_embed_empty" in scheduled


def test_update_cache_incremental_add(wired):
    vs = ds.DailyVectorIndex(dim=4)
    vs.add(item_id="e0", vector=[1.0, 0.0, 0.0, 0.0], text="seed", metadata={})
    ds._CACHE["p"] = ds._DailyCache(
        embedding_model="fake-model", vs=vs, meta_by_id={}, id_by_seq={}
    )
    assert ds._update_cache_with_entry("p", _entry("e1", 2), "more text") is True
    cache = ds._CACHE["p"]
    assert cache.vs.size() == 2
    assert cache.meta_by_id["e1"]["id"] == "e1"
    assert cache.id_by_seq[2] == "e1"


def test_update_cache_incremental_empty_embedding_schedules(wired, monkeypatch):
    vs = ds.DailyVectorIndex(dim=4)
    vs.add(item_id="e0", vector=[1.0, 0.0, 0.0, 0.0], text="seed", metadata={})
    ds._CACHE["p"] = ds._DailyCache(
        embedding_model="fake-model", vs=vs, meta_by_id={}, id_by_seq={}
    )
    monkeypatch.setattr(ds, "get_embedding_client", lambda: _FakeLLM(vectors=[]))
    scheduled = []
    monkeypatch.setattr(
        ds, "start_daily_cache_rebuild", lambda pid, reason: scheduled.append(reason)
    )
    assert ds._update_cache_with_entry("p", _entry(), "text") is False
    assert "append_embed_empty" in scheduled


def test_update_cache_incremental_swallows_map_update_errors(wired, caplog):
    vs = ds.DailyVectorIndex(dim=4)
    vs.add(item_id="e0", vector=[1.0, 0.0, 0.0, 0.0], text="seed", metadata={})
    # Corrupt the join maps so the best-effort updates raise and are logged.
    cache = ds._DailyCache(embedding_model="fake-model", vs=vs, meta_by_id=None, id_by_seq=None)
    ds._CACHE["p"] = cache
    assert ds._update_cache_with_entry("p", _entry("e1", 2), "more text") is True
    assert any("failed updating meta_by_id" in r.message for r in caplog.records)
    assert any("failed updating id_by_seq" in r.message for r in caplog.records)


def test_update_cache_exception_schedules_rebuild(wired, monkeypatch):
    # Force an unexpected error path: _get_project_lock raises.
    def boom(_pid):
        raise RuntimeError("lock acquisition failed")

    monkeypatch.setattr(ds, "_get_project_lock", boom)
    scheduled = []
    monkeypatch.setattr(
        ds, "start_daily_cache_rebuild", lambda pid, reason: scheduled.append(reason)
    )
    assert ds._update_cache_with_entry("p", _entry(), "text") is False
    assert "append_exception" in scheduled


# --- _append_daily_md_block error paths -----------------------------------


def test_append_daily_md_block_writes_block(wired):
    project_id = "p-md"
    _meta, _lock, md_path = ds._project_daily_paths(project_id)
    ds._append_daily_md_block(
        project_id,
        md_path,
        {"memory_id": "mem_x", "entry_type": "chat_pair", "day_sequence": 1},
        user_text="u",
        assistant_text="a",
    )
    assert os.path.isfile(md_path)
    assert "syx_artifact_type" in open(md_path).read()


def test_append_daily_md_block_header_failure_is_logged(wired, monkeypatch, caplog):
    project_id = "p-md-hdr"
    _meta, _lock, md_path = ds._project_daily_paths(project_id)

    def boom(**_k):
        raise RuntimeError("header render failed")

    monkeypatch.setattr(ds, "render_artifact_header", boom)
    ds._append_daily_md_block(
        project_id,
        md_path,
        {"memory_id": "mem_x", "entry_type": "chat_pair", "day_sequence": 1},
        user_text="u",
        assistant_text="a",
    )
    assert any("failed ensuring daily BEGIN header" in r.message for r in caplog.records)


def test_append_daily_md_block_render_failure_is_logged(wired, monkeypatch, caplog):
    project_id = "p-md-render"
    _meta, _lock, md_path = ds._project_daily_paths(project_id)

    def boom(*_a, **_k):
        raise RuntimeError("render failed")

    monkeypatch.setattr(ds, "_render_markdown_entry", boom)
    ds._append_daily_md_block(
        project_id, md_path, {"memory_id": "mem_x"}, user_text="u", assistant_text="a"
    )
    assert any("failed writing daily.md" in r.message for r in caplog.records)


# --- append_pair ----------------------------------------------------------


def test_append_pair_persists_and_updates_warm_cache(wired):
    project_id = "p-append"
    # Pre-warm an empty (model-matched) cache so the incremental add path runs
    # in-request and returns True deterministically (no background rebuild).
    ds._CACHE[project_id] = ds._DailyCache(
        embedding_model="fake-model", vs=None, meta_by_id={}, id_by_seq={}
    )
    ok = ds.append_pair(
        project_id,
        pair_text="User: hi\nAssistant: hello",
        user_msg_id=1,
        assistant_msg_id=2,
        tokens=5,
        namespace="chat",
    )
    assert ok is True
    meta_path, _lock, md_path = ds._project_daily_paths(project_id)
    entries = ds._load_metadata(meta_path)
    assert len(entries) == 1
    assert os.path.isfile(md_path)
    assert ds._CACHE[project_id].vs is not None


def test_append_pair_cold_cache_persists_and_schedules_rebuild(wired, monkeypatch):
    project_id = "p-append-cold"
    monkeypatch.setattr(ds, "start_daily_cache_rebuild", lambda *a, **k: None)
    ok = ds.append_pair(
        project_id,
        pair_text="User: hi\nAssistant: hello",
        user_msg_id=1,
        assistant_msg_id=2,
        tokens=5,
    )
    # Disk write succeeded, but a cold cache schedules a rebuild and returns False.
    assert ok is False
    meta_path, _lock, _md = ds._project_daily_paths(project_id)
    assert len(ds._load_metadata(meta_path)) == 1


def test_append_pair_update_cache_false_skips_cache(wired):
    project_id = "p-append-nocache"
    ok = ds.append_pair(
        project_id,
        pair_text="User: hi\nAssistant: hello",
        user_msg_id=1,
        assistant_msg_id=2,
        tokens=5,
        update_cache=False,
        write_daily_md=False,
    )
    assert ok is True
    assert project_id not in ds._CACHE


# --- append_pair_text_only ------------------------------------------------


def test_append_pair_text_only_writes_block(wired):
    project_id = "p-textonly"
    ok = ds.append_pair_text_only(
        project_id,
        user_text="hello",
        assistant_text="hi there",
        created_at_iso_utc="2026-05-07T13:45:04Z",
        namespace="Chat",
        keep=True,
        tags_meta={"topics": "a", "intent": "ask", "type": "q", "semantic_handle": "h"},
    )
    assert ok is True
    _meta, _lock, md_path = ds._project_daily_paths(project_id)
    content = open(md_path).read()
    assert ds._BEGIN_DAILY_PAIR in content
    assert "#route: chat" in content
    assert "#keep: true" in content
    assert "hello" in content and "hi there" in content


def test_append_pair_text_only_header_failure_is_logged(wired, monkeypatch, caplog):
    project_id = "p-textonly-hdr"

    def boom(**_k):
        raise RuntimeError("header failed")

    monkeypatch.setattr(ds, "render_artifact_header", boom)
    ok = ds.append_pair_text_only(
        project_id,
        user_text="hello",
        assistant_text="hi",
        created_at_iso_utc="2026-05-07T13:45:04Z",
        namespace="chat",
        keep=False,
    )
    assert ok is True  # block still written despite header failure
    assert any("failed ensuring text-only BEGIN header" in r.message for r in caplog.records)


def test_append_pair_text_only_unparseable_timestamp_uses_raw(wired):
    project_id = "p-textonly-ts"
    ok = ds.append_pair_text_only(
        project_id,
        user_text="hello",
        assistant_text="hi",
        created_at_iso_utc="not-a-timestamp",  # strptime fails -> raw retained
        namespace="chat",
        keep=False,
    )
    assert ok is True
    _meta, _lock, md_path = ds._project_daily_paths(project_id)
    assert "#timestamp: not-a-timestamp" in open(md_path).read()


def test_append_pair_text_only_failure_returns_false(wired, monkeypatch):
    project_id = "p-textonly-fail"

    def boom(*_a, **_k):
        raise RuntimeError("tags render failed")

    monkeypatch.setattr(ds, "_format_tags_block", boom)
    ok = ds.append_pair_text_only(
        project_id,
        user_text="hello",
        assistant_text="hi",
        created_at_iso_utc="2026-05-07T13:45:04Z",
        namespace="chat",
        keep=False,
    )
    assert ok is False


# --- daily_stats ----------------------------------------------------------


def test_daily_stats_reports_counts(wired):
    project_id = "p-stats"
    meta_path, _lock, _md = ds._project_daily_paths(project_id)
    ds._save_metadata(
        meta_path,
        [{"id": "e1", "tokens": 10}, {"id": "e2", "tokens": 5}],
    )
    stats = ds.daily_stats(project_id)
    assert stats["daily_vector_count"] == 2
    assert stats["daily_tokens_indexed"] == 15
    assert stats["daily_index_size_bytes"] > 0


def test_daily_stats_no_metadata_file(wired):
    # No daily.json on disk -> size falls to the serialized-estimate branch (0 for empty).
    stats = ds.daily_stats("p-stats-none")
    assert stats == {
        "daily_index_size_bytes": 0,
        "daily_tokens_indexed": 0,
        "daily_vector_count": 0,
    }


def test_daily_stats_falls_back_when_getsize_fails(wired, monkeypatch):
    project_id = "p-stats-fallback"
    meta_path, _lock, _md = ds._project_daily_paths(project_id)
    ds._save_metadata(meta_path, [{"id": "e1", "tokens": 3}])

    def boom(_p):
        raise OSError("stat failed")

    monkeypatch.setattr(ds.os.path, "getsize", boom)
    stats = ds.daily_stats(project_id)
    # Falls back to a serialized-size estimate rather than raising.
    assert stats["daily_index_size_bytes"] > 0
    assert stats["daily_vector_count"] == 1


# --- backfill_daily_md_from_meta ------------------------------------------


def test_backfill_returns_false_when_md_exists(wired):
    project_id = "p-bf-exists"
    _meta, _lock, md_path = ds._project_daily_paths(project_id)
    with open(md_path, "w") as f:
        f.write("already here")
    assert ds.backfill_daily_md_from_meta(project_id) is False


def test_backfill_returns_false_when_no_entries(wired):
    project_id = "p-bf-empty"
    meta_path, _lock, _md = ds._project_daily_paths(project_id)
    ds._save_metadata(meta_path, [])
    assert ds.backfill_daily_md_from_meta(project_id) is False


def test_backfill_writes_md_and_backfills_fields(wired):
    project_id = "p-bf"
    meta_path, _lock, md_path = ds._project_daily_paths(project_id)
    ds._save_metadata(
        meta_path,
        [
            {
                "id": "e1",
                "text": "User: hi\nAssistant: hello",
                "day_sequence": 1,
                "created_at": "2026-05-07T13:45:04Z",
            }
        ],
    )
    assert ds.backfill_daily_md_from_meta(project_id) is True
    assert os.path.isfile(md_path)
    # Missing fields were synthesized and persisted back to daily.json.
    entries = ds._load_metadata(meta_path)
    assert entries[0]["memory_id"].startswith("mem_")
    assert entries[0]["entry_type"] == "chat_pair"


def test_backfill_failure_returns_false(wired, monkeypatch):
    project_id = "p-bf-fail"
    meta_path, _lock, _md = ds._project_daily_paths(project_id)
    ds._save_metadata(meta_path, [{"id": "e1", "text": "x", "day_sequence": 1}])

    def boom(**_k):
        raise RuntimeError("header failed")

    monkeypatch.setattr(ds, "render_artifact_header", boom)
    assert ds.backfill_daily_md_from_meta(project_id) is False
