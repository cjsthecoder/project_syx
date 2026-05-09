"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
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
    return module


def test_append_pair_writes_daily_md_not_daily_txt(tmp_path, monkeypatch):
    daily_store = _load_daily_store(monkeypatch)
    monkeypatch.setattr(daily_store, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path)))
    monkeypatch.setattr(daily_store, "get_active_embedding_model", lambda: "test-embedding")

    project_id = "project-1"
    project_dir = tmp_path / project_id
    project_dir.mkdir()
    legacy_txt = project_dir / "daily.txt"
    legacy_txt.write_text("historical txt remains\n", encoding="utf-8")

    ok = daily_store.append_pair(
        project_id,
        "User: hello\nAssistant: hi",
        1,
        2,
        4,
        namespace="chat",
        update_cache=False,
    )

    assert ok is True
    assert (project_dir / "daily.md").is_file()
    daily_md = (project_dir / "daily.md").read_text(encoding="utf-8")
    assert "hello" in daily_md
    assert "<!-- begin syx:memory_id=mem_" in daily_md
    assert "### Syx Metadata" in daily_md
    assert "### User Message" in daily_md
    assert "=== BEGIN DAILY PAIR ===" not in daily_md
    assert legacy_txt.read_text(encoding="utf-8") == "historical txt remains\n"


def test_append_pair_preserves_created_at_for_daily_md_and_metadata(tmp_path, monkeypatch):
    daily_store = _load_daily_store(monkeypatch)
    monkeypatch.setattr(daily_store, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path)))
    monkeypatch.setattr(daily_store, "get_active_embedding_model", lambda: "test-embedding")

    project_id = "project-created-at"
    project_dir = tmp_path / project_id
    project_dir.mkdir()

    ok = daily_store.append_pair(
        project_id,
        "User: timestamp question\nAssistant: timestamp answer",
        10,
        11,
        5,
        namespace="chat",
        update_cache=False,
        created_at_iso_utc="2026-05-07T13:45:04Z",
    )

    assert ok is True
    entries = json.loads((project_dir / "daily.json").read_text(encoding="utf-8"))
    assert entries[0]["created_at"] == "2026-05-07T13:45:04Z"
    assert entries[0]["memory_id"].startswith("mem_20260507_134504_")
    daily_md = (project_dir / "daily.md").read_text(encoding="utf-8")
    assert "timestamp: 05-07-2026_13:45:04" in daily_md
    assert "#timestamp:" not in daily_md


def test_backfill_daily_md_from_meta_ignores_legacy_txt(tmp_path, monkeypatch):
    daily_store = _load_daily_store(monkeypatch)
    monkeypatch.setattr(daily_store, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path)))

    project_id = "project-2"
    project_dir = tmp_path / project_id
    project_dir.mkdir()
    (project_dir / "daily.txt").write_text("old txt artifact\n", encoding="utf-8")
    (project_dir / "daily.json").write_text(
        json.dumps(
            [
                {
                    "created_at": "2026-05-07T10:00:00Z",
                    "text": "User: daily question\nAssistant: daily answer",
                    "keep": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    assert daily_store.backfill_daily_md_from_meta(project_id) is True
    daily_md = (project_dir / "daily.md").read_text(encoding="utf-8")
    assert "daily answer" in daily_md
    assert "<!-- begin syx:memory_id=mem_" in daily_md
    assert (project_dir / "daily.txt").read_text(encoding="utf-8") == "old txt artifact\n"
    entries = json.loads((project_dir / "daily.json").read_text(encoding="utf-8"))
    assert entries[0]["memory_id"].startswith("mem_20260507_100000_")
