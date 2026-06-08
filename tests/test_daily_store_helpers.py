"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Tests for the pure/IO helpers extracted from daily_store append/rebuild.

Covers ``_build_daily_entry`` (entry construction + day_sequence/scope/memory_id
rules), ``_cache_entry_metadata`` (vector metadata shape),
``_collect_daily_texts_and_maps`` (texts + adjacency map building), and
``_reconcile_daily_embedding_model`` (in-place model reconciliation in
daily.json).
"""
import json
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def _load_daily_store(monkeypatch):
    def ensure_module(name: str) -> types.ModuleType:
        module = sys.modules.get(name)
        if module is None:
            module = types.ModuleType(name)
            module.__path__ = []  # type: ignore[attr-defined]
            monkeypatch.setitem(sys.modules, name, module)
        return module

    ensure_module("app")
    ensure_module("app.core")
    ensure_module("app.embedding")
    ensure_module("app.rag")
    ensure_module("app.utils")

    faiss_module = types.ModuleType("faiss")
    faiss_module.IndexFlatIP = type("IndexFlatIP", (), {})  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faiss", faiss_module)

    numpy_module = types.ModuleType("numpy")
    numpy_module.ndarray = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "numpy", numpy_module)

    config_module = types.ModuleType("app.core.config")
    config_module.get_settings = lambda: SimpleNamespace(memory_root="")  # type: ignore[attr-defined]
    config_module.get_active_embedding_model = lambda: "test-embedding"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.config", config_module)

    batching_module = types.ModuleType("app.embedding.batching")
    batching_module.iter_token_batches = lambda *_args, **_kwargs: []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.embedding.batching", batching_module)

    vector_index_module = types.ModuleType("app.embedding.vector_index")
    for name in ("VectorEntry", "VectorHit", "VectorIndexInfo", "VectorIndex"):
        setattr(vector_index_module, name, type(name, (), {}))
    monkeypatch.setitem(sys.modules, "app.embedding.vector_index", vector_index_module)

    embedding_factory_module = types.ModuleType("app.embedding.factory")
    embedding_factory_module.get_embedding_client = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.embedding.factory", embedding_factory_module)

    debug_utils_module = types.ModuleType("app.utils.debug_utils")
    debug_utils_module.write_debug_file = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.utils.debug_utils", debug_utils_module)

    syx_module_path = Path(__file__).resolve().parents[1] / "backend" / "app" / "rag" / "syx_memory_artifact.py"
    syx_spec = importlib.util.spec_from_file_location("app.rag.syx_memory_artifact", syx_module_path)
    assert syx_spec is not None
    syx_module = importlib.util.module_from_spec(syx_spec)
    monkeypatch.setitem(sys.modules, "app.rag.syx_memory_artifact", syx_module)
    assert syx_spec.loader is not None
    syx_spec.loader.exec_module(syx_module)

    module_path = Path(__file__).resolve().parents[1] / "backend" / "app" / "rag" / "daily_store.py"
    spec = importlib.util.spec_from_file_location("app.rag.daily_store", module_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "app.rag.daily_store", module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "get_active_embedding_model", lambda: "test-embedding")
    return module


# ----- _build_daily_entry -----


def test_build_daily_entry_chat_pair_defaults(monkeypatch):
    daily_store = _load_daily_store(monkeypatch)
    entry = daily_store._build_daily_entry(
        project_id="p1",
        entries=[],
        pair_text="User: hi\nAssistant: yo",
        text_for_embed="User: hi\nAssistant: yo",
        user_text="hi",
        assistant_text="yo",
        user_msg_id=1,
        assistant_msg_id=2,
        tokens=7,
        namespace="Chat",
        keep=False,
        tags_meta=None,
        created_at_iso_utc="2026-05-07T13:45:04Z",
        memory_id=None,
        entry_type="chat_pair",
        source="chat",
        source_agent="syx",
        source_scope=None,
        current_scope=None,
        accepted_item_id=None,
        dream_output_type=None,
        origin_memory_ids=None,
    )

    assert entry["day_sequence"] == 1
    assert entry["route"] == "chat"  # lowercased
    assert entry["entry_type"] == "chat_pair"
    assert entry["source_scope"] == "daily"
    assert entry["current_scope"] == "daily"
    assert entry["scope"] == "daily"
    assert entry["tokens"] == 7
    assert entry["keep"] is False
    assert entry["text"] == "User: hi\nAssistant: yo"
    assert entry["embed_text"] == "User: hi\nAssistant: yo"
    assert entry["embedding_model"] == "test-embedding"
    assert entry["pair_ids"] == ["1", "2"]
    assert entry["memory_id"].startswith("mem_")
    assert "tags_meta" not in entry
    assert "accepted_item_id" not in entry


def test_build_daily_entry_increments_day_sequence(monkeypatch):
    daily_store = _load_daily_store(monkeypatch)
    entry = daily_store._build_daily_entry(
        project_id="p1",
        entries=[{"day_sequence": 5}],
        pair_text="User: a\nAssistant: b",
        text_for_embed="User: a\nAssistant: b",
        user_text="a",
        assistant_text="b",
        user_msg_id=1,
        assistant_msg_id=2,
        tokens=3,
        namespace="other",
        keep=True,
        tags_meta=None,
        created_at_iso_utc="2026-05-07T13:45:04Z",
        memory_id=None,
        entry_type="chat_pair",
        source="chat",
        source_agent="syx",
        source_scope=None,
        current_scope=None,
        accepted_item_id=None,
        dream_output_type=None,
        origin_memory_ids=None,
    )
    assert entry["day_sequence"] == 6
    assert entry["keep"] is True


def test_build_daily_entry_dream_output_scopes_and_fields(monkeypatch):
    daily_store = _load_daily_store(monkeypatch)
    entry = daily_store._build_daily_entry(
        project_id="p1",
        entries=[],
        pair_text="User: q\nAssistant: a",
        text_for_embed="EMBED",
        user_text="q",
        assistant_text="a",
        user_msg_id=-1,
        assistant_msg_id=-2,
        tokens=4,
        namespace="other",
        keep=False,
        tags_meta={"topics": "t", "semantic_handle": "sh"},
        created_at_iso_utc="2026-05-07T13:45:04Z",
        memory_id="mem_explicit",
        entry_type="dream_output",
        source="dream",
        source_agent="syx",
        source_scope=None,
        current_scope=None,
        accepted_item_id="item-9",
        dream_output_type="Open Question",
        origin_memory_ids=["mem_a", "mem_b"],
    )

    assert entry["memory_id"] == "mem_explicit"  # explicit id used verbatim
    assert entry["source_scope"] == "dream"
    assert entry["current_scope"] == "dream"
    assert entry["embed_text"] == "EMBED"
    assert entry["accepted_item_id"] == "item-9"
    assert entry["dream_output_type"] == "open_question"  # snake_cased
    assert entry["origin_memory_ids"] == ["mem_a", "mem_b"]
    assert entry["tags_meta"] == {"topics": "t", "semantic_handle": "sh"}


def test_build_daily_entry_explicit_scopes_override(monkeypatch):
    daily_store = _load_daily_store(monkeypatch)
    entry = daily_store._build_daily_entry(
        project_id="p1",
        entries=[],
        pair_text="User: q\nAssistant: a",
        text_for_embed="EMBED",
        user_text="q",
        assistant_text="a",
        user_msg_id=1,
        assistant_msg_id=2,
        tokens=4,
        namespace="other",
        keep=False,
        tags_meta=None,
        created_at_iso_utc="2026-05-07T13:45:04Z",
        memory_id=None,
        entry_type="chat_pair",
        source="chat",
        source_agent="syx",
        source_scope="custom_src",
        current_scope="custom_cur",
        accepted_item_id=None,
        dream_output_type=None,
        origin_memory_ids=None,
    )
    assert entry["source_scope"] == "custom_src"
    assert entry["current_scope"] == "custom_cur"


# ----- _cache_entry_metadata -----


def test_cache_entry_metadata_shape(monkeypatch):
    daily_store = _load_daily_store(monkeypatch)
    entry = {"id": "abc", "memory_id": "mem_x", "day_sequence": 3}
    md = daily_store._cache_entry_metadata(entry)
    assert md == {
        "source": "daily",
        "daily_entry_id": "abc",
        "memory_id": "mem_x",
        "day_sequence": 3,
        "doc_id": "daily",
        "chunk_seq": 3,
    }


# ----- _collect_daily_texts_and_maps -----


def test_collect_texts_and_maps_filters_and_indexes(monkeypatch):
    daily_store = _load_daily_store(monkeypatch)
    entries = [
        {"id": "e1", "embed_text": "alpha", "day_sequence": 1, "memory_id": "m1"},
        {"id": "e2", "text": "beta", "day_sequence": 2, "memory_id": "m2"},
        {"id": "e3", "embed_text": "   ", "text": "", "day_sequence": 3},  # skipped (empty)
        {"embed_text": "gamma", "day_sequence": 4},  # no id -> text kept, not in maps
    ]
    texts, metas, meta_by_id, id_by_seq = daily_store._collect_daily_texts_and_maps(entries, "p1")

    assert texts == ["alpha", "beta", "gamma"]
    assert set(meta_by_id.keys()) == {"e1", "e2"}
    assert id_by_seq == {1: "e1", 2: "e2"}
    # embed_text preferred over text for e1; text fallback for e2.
    assert metas[0]["daily_entry_id"] == "e1"
    assert metas[2]["daily_entry_id"] is None  # gamma entry had no id
    assert metas[1]["chunk_seq"] == 2


def test_collect_texts_and_maps_empty(monkeypatch):
    daily_store = _load_daily_store(monkeypatch)
    texts, metas, meta_by_id, id_by_seq = daily_store._collect_daily_texts_and_maps([], "p1")
    assert texts == []
    assert metas == []
    assert meta_by_id == {}
    assert id_by_seq == {}


# ----- _reconcile_daily_embedding_model -----


def test_reconcile_updates_stale_model_in_place(tmp_path, monkeypatch):
    daily_store = _load_daily_store(monkeypatch)
    monkeypatch.setattr(daily_store, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path)))
    project_id = "proj-reconcile"
    meta_path, lock_path, _md = daily_store._project_daily_paths(project_id)
    Path(meta_path).write_text(
        json.dumps([
            {"id": "e1", "text": "x", "day_sequence": 1, "embedding_model": "old-model"},
        ]),
        encoding="utf-8",
    )

    entries = daily_store._reconcile_daily_embedding_model(
        project_id, meta_path, lock_path, "test-embedding", reason="unit"
    )

    assert entries[0]["embedding_model"] == "test-embedding"
    on_disk = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    assert on_disk[0]["embedding_model"] == "test-embedding"


def test_reconcile_noop_when_model_matches(tmp_path, monkeypatch):
    daily_store = _load_daily_store(monkeypatch)
    monkeypatch.setattr(daily_store, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path)))
    project_id = "proj-match"
    meta_path, lock_path, _md = daily_store._project_daily_paths(project_id)
    Path(meta_path).write_text(
        json.dumps([
            {"id": "e1", "text": "x", "day_sequence": 1, "embedding_model": "test-embedding"},
        ]),
        encoding="utf-8",
    )

    entries = daily_store._reconcile_daily_embedding_model(
        project_id, meta_path, lock_path, "test-embedding", reason="unit"
    )
    assert entries[0]["embedding_model"] == "test-embedding"


def test_reconcile_empty_metadata_returns_empty(tmp_path, monkeypatch):
    daily_store = _load_daily_store(monkeypatch)
    monkeypatch.setattr(daily_store, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path)))
    project_id = "proj-empty"
    meta_path, lock_path, _md = daily_store._project_daily_paths(project_id)

    entries = daily_store._reconcile_daily_embedding_model(
        project_id, meta_path, lock_path, "test-embedding", reason="unit"
    )
    assert entries == []
