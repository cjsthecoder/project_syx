"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for the dream auto-accept pipeline.

Exercises ``auto_accept.auto_accept_dreams``: filtering remote items without
research, pruning assistant text before tagging, persisting accepted items as
keep=false dream-output memories, writing the latest sleep summary, and
renaming ``dream.json`` to a bad-dream file on persistence failure.
"""
import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def _load_auto_accept_module(monkeypatch, *, append_ok=True, tagger_raises=False, pruned_text=None):
    def ensure_module(name: str) -> types.ModuleType:
        module = sys.modules.get(name)
        if module is None:
            module = types.ModuleType(name)
            module.__path__ = []  # type: ignore[attr-defined]
            monkeypatch.setitem(sys.modules, name, module)
        return module

    ensure_module("app")
    ensure_module("app.core")
    ensure_module("app.dream")
    ensure_module("app.rag")
    ensure_module("app.tagging")
    ensure_module("app.utils")

    config_module = types.ModuleType("app.core.config")
    config_module.get_settings = lambda: SimpleNamespace(memory_root="")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.config", config_module)

    calls = {"append": [], "rebuild": 0, "tagger": [], "pruner": []}

    memory_module = types.ModuleType("app.core.memory")

    def prune_assistant_for_tagger(*, project_id, assistant_text, settings):
        calls["pruner"].append(
            {"project_id": project_id, "assistant_text": assistant_text, "settings": settings}
        )
        return pruned_text if pruned_text is not None else assistant_text

    memory_module._prune_assistant_for_tagger = prune_assistant_for_tagger  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.memory", memory_module)

    daily_module = types.ModuleType("app.rag.daily_store")

    def append_pair(*args, **kwargs):
        calls["append"].append({"args": args, "kwargs": kwargs})
        return append_ok

    def rebuild_daily_cache(*_args, **_kwargs):
        calls["rebuild"] += 1
        return True

    daily_module.append_pair = append_pair  # type: ignore[attr-defined]
    daily_module.rebuild_daily_cache = rebuild_daily_cache  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.rag.daily_store", daily_module)

    syx_module_path = (
        Path(__file__).resolve().parents[1] / "backend" / "app" / "rag" / "syx_memory_artifact.py"
    )
    syx_spec = importlib.util.spec_from_file_location(
        "app.rag.syx_memory_artifact", syx_module_path
    )
    assert syx_spec is not None
    syx_module = importlib.util.module_from_spec(syx_spec)
    monkeypatch.setitem(sys.modules, "app.rag.syx_memory_artifact", syx_module)
    assert syx_spec.loader is not None
    syx_spec.loader.exec_module(syx_module)

    tagger_module = types.ModuleType("app.tagging.tagger")

    def tag_pair(*args, **kwargs):
        calls["tagger"].append({"args": args, "kwargs": kwargs})
        if tagger_raises:
            raise RuntimeError("tagger failed")
        return {
            "topics": "dream",
            "intent": "auto_accept",
            "type": "memory",
            "semantic_handle": "Dream item",
        }

    tagger_module.tag_pair = tag_pair  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.tagging.tagger", tagger_module)

    tokens_module = types.ModuleType("app.utils.tokens")
    tokens_module.count_tokens = lambda text: len(str(text).split())  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.utils.tokens", tokens_module)

    dream_summary_module = types.ModuleType("app.utils.dream_summary")

    def write_latest_sleep_summary(*, project_id, base_dir, project_summary, accepted_items):
        if not project_summary:
            return
        topics = []
        for item in accepted_items:
            for research in item.get("research", []) if isinstance(item, dict) else []:
                topic = str(research.get("research_topic") or "").strip()
                if topic:
                    topics.append(f"Topic: {topic}")
        body = str(project_summary).strip()
        if topics:
            body += "\n\n[RESEARCH]\n" + "\n\n".join(topics)
        Path(base_dir, "latest_sleep_summary.md").write_text(body + "\n", encoding="utf-8")

    dream_summary_module.write_latest_sleep_summary = write_latest_sleep_summary  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.utils.dream_summary", dream_summary_module)

    module_path = (
        Path(__file__).resolve().parents[1] / "backend" / "app" / "dream" / "auto_accept.py"
    )
    spec = importlib.util.spec_from_file_location("app.dream.auto_accept", module_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "app.dream.auto_accept", module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, calls


def test_auto_accept_processes_dream_json_with_keep_false(tmp_path, monkeypatch):
    auto_accept, calls = _load_auto_accept_module(monkeypatch)
    monkeypatch.setattr(
        auto_accept, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    project_id = "project-1"
    project_dir = tmp_path / project_id
    project_dir.mkdir()
    dream_path = project_dir / "dream.json"
    dream_path.write_text(
        json.dumps(
            {
                "project_summary": "Latest project summary",
                "items": [
                    {
                        "id": "local-1",
                        "origin_text": "local question",
                        "assistant_response": "local answer",
                        "source_resolution": "answer_local",
                    },
                    {
                        "id": "remote-1",
                        "origin_text": "remote question",
                        "assistant_response": "remote answer",
                        "source_resolution": "answer_remote",
                        "research": [
                            {"research_topic": "topic", "research_summary": "summary"},
                            {
                                "research_topic": "second topic",
                                "research_summary": "second summary",
                            },
                        ],
                    },
                    {
                        "id": "remote-bad",
                        "origin_text": "bad remote question",
                        "source_resolution": "answer_remote",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = auto_accept.auto_accept_dreams(project_id)

    assert result.processed == 3
    assert result.accepted == 3
    assert result.filtered_remote_without_research == 1
    assert result.deleted_dream is True
    assert not dream_path.exists()
    assert (project_dir / "latest_sleep_summary.md").read_text(encoding="utf-8").strip() == (
        "Latest project summary\n\n[RESEARCH]\nTopic: topic\n\nTopic: second topic"
    )
    assert len(calls["append"]) == 3
    assert all(call["kwargs"]["keep"] is False for call in calls["append"])
    assert calls["append"][0]["kwargs"]["source_scope"] == "dream"
    assert calls["append"][0]["kwargs"]["current_scope"] == "dream"
    assert calls["append"][1]["args"][1] == "User: topic\nAssistant: [RESEARCH]\nsummary"
    assert (
        calls["append"][2]["args"][1] == "User: second topic\nAssistant: [RESEARCH]\nsecond summary"
    )
    assert calls["rebuild"] == 1
    assert not (project_dir / "dream_summary.txt").exists()
    summary = (project_dir / "dream_summary.md").read_text(encoding="utf-8")
    assert "keep: false" in summary
    assert "entry_type: dream_output" in summary
    assert "source_scope: dream" in summary
    assert "current_scope: dream" in summary
    assert "<!-- begin syx:memory_id=mem_" in summary
    assert "local question" in summary
    assert "remote question" not in summary
    assert "Topic: topic" not in summary
    assert "[RESEARCH]\nsummary" in summary
    assert "[RESEARCH]\nsecond summary" in summary
    assert "To explore this idea" not in summary
    assert len(calls["pruner"]) == 3
    assert len(calls["tagger"]) == 3


def test_auto_accept_prunes_before_tagger(tmp_path, monkeypatch):
    auto_accept, calls = _load_auto_accept_module(monkeypatch, pruned_text="pruned assistant text")
    monkeypatch.setattr(
        auto_accept, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    project_id = "project-prune"
    project_dir = tmp_path / project_id
    project_dir.mkdir()
    (project_dir / "dream.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "local-1",
                        "origin_text": "q",
                        "assistant_response": "full assistant text",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = auto_accept.auto_accept_dreams(project_id)

    assert result.accepted == 1
    assert calls["pruner"][0]["assistant_text"] == "full assistant text"
    assert calls["tagger"][0]["args"][1] == "pruned assistant text"
    assert calls["append"][0]["args"][1] == "User: q\nAssistant: pruned assistant text"
    assert not (project_dir / "dream_summary.txt").exists()
    summary = (project_dir / "dream_summary.md").read_text(encoding="utf-8")
    assert "pruned assistant text" in summary
    assert "full assistant text" not in summary


def test_auto_accept_deletes_dream_json_when_no_items_survive_filter(tmp_path, monkeypatch):
    auto_accept, calls = _load_auto_accept_module(monkeypatch)
    monkeypatch.setattr(
        auto_accept, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    project_id = "project-2"
    project_dir = tmp_path / project_id
    project_dir.mkdir()
    dream_path = project_dir / "dream.json"
    dream_path.write_text(
        json.dumps({"items": [{"id": "remote-bad", "source_resolution": "answer_remote"}]}),
        encoding="utf-8",
    )

    result = auto_accept.auto_accept_dreams(project_id)

    assert result.processed == 0
    assert result.accepted == 0
    assert result.filtered_remote_without_research == 1
    assert result.deleted_dream is True
    assert not dream_path.exists()
    assert calls["append"] == []
    assert calls["rebuild"] == 0


def test_auto_accept_renames_dream_json_on_persist_failure(tmp_path, monkeypatch):
    auto_accept, _calls = _load_auto_accept_module(monkeypatch, append_ok=False)
    monkeypatch.setattr(
        auto_accept, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    project_id = "project-3"
    project_dir = tmp_path / project_id
    project_dir.mkdir()
    dream_path = project_dir / "dream.json"
    dream_path.write_text(
        json.dumps({"items": [{"id": "local-1", "origin_text": "q", "assistant_response": "a"}]}),
        encoding="utf-8",
    )

    result = auto_accept.auto_accept_dreams(project_id)

    assert result.failed > 0
    assert result.renamed_bad_path is not None
    assert not dream_path.exists()
    assert Path(result.renamed_bad_path).name.startswith("bad_dream_")
    assert Path(result.renamed_bad_path).exists()


# --- helper-level coverage -------------------------------------------------


def test_bad_dream_path_collision_uses_unique_suffix(tmp_path, monkeypatch):
    auto_accept, _ = _load_auto_accept_module(monkeypatch)
    # Force os.path.exists to report the first candidate as taken.
    monkeypatch.setattr(auto_accept.os.path, "exists", lambda _p: True)
    path = auto_accept._bad_dream_path(str(tmp_path))
    assert path.startswith(str(tmp_path)) and path.endswith(".json")
    # The unique form embeds an extra "_<nanoseconds>" before .json.
    assert auto_accept.os.path.basename(path).count("_") >= 3


def test_rename_bad_dream_logs_on_oserror(tmp_path, monkeypatch, caplog):
    auto_accept, _ = _load_auto_accept_module(monkeypatch)
    monkeypatch.setattr(
        auto_accept.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("locked"))
    )
    result = auto_accept._rename_bad_dream("p1", str(tmp_path / "dream.json"))
    assert result is None
    assert any("Failed renaming bad dream.json" in r.message for r in caplog.records)


def test_delete_dream_file_logs_on_oserror(tmp_path, monkeypatch, caplog):
    auto_accept, _ = _load_auto_accept_module(monkeypatch)
    dream_path = tmp_path / "dream.json"
    dream_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        auto_accept.os, "remove", lambda _p: (_ for _ in ()).throw(OSError("locked"))
    )
    assert auto_accept._delete_dream_file("p1", str(dream_path)) is False
    assert any("Failed deleting dream.json" in r.message for r in caplog.records)


def test_prepare_dream_summary_paths_migrates_legacy_lock(tmp_path, monkeypatch):
    auto_accept, _ = _load_auto_accept_module(monkeypatch)
    base_dir = tmp_path / "p1"
    base_dir.mkdir()
    (base_dir / "dream_summary.lock").write_text("", encoding="utf-8")
    summary_path, lock_path = auto_accept._prepare_dream_summary_paths(str(base_dir), "p1")
    assert lock_path.endswith("state/dream_summary.lock")
    assert Path(lock_path).exists() and not (base_dir / "dream_summary.lock").exists()


def test_prepare_dream_summary_paths_migration_failure_logged(tmp_path, monkeypatch, caplog):
    auto_accept, _ = _load_auto_accept_module(monkeypatch)
    base_dir = tmp_path / "p1"
    base_dir.mkdir()
    (base_dir / "dream_summary.lock").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        auto_accept.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("locked"))
    )
    auto_accept._prepare_dream_summary_paths(str(base_dir), "p1")
    assert any("lock migration failed" in r.message for r in caplog.records)


def test_tag_dream_pairs_skips_empty_pair(tmp_path, monkeypatch, caplog):
    auto_accept, _ = _load_auto_accept_module(monkeypatch)
    monkeypatch.setattr(
        auto_accept, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    # answer_local item with blank origin_text -> empty user_text -> skipped.
    item = {
        "id": "i1",
        "origin_text": "   ",
        "assistant_response": "a",
        "source_resolution": "answer_local",
    }
    tagged = auto_accept._tag_dream_pairs("p1", [item])
    assert tagged == []
    assert any("Skipping empty memory pair" in r.message for r in caplog.records)


def test_auto_accept_tagger_failure_persists_without_tags(tmp_path, monkeypatch, caplog):
    auto_accept, calls = _load_auto_accept_module(monkeypatch, tagger_raises=True)
    monkeypatch.setattr(
        auto_accept, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    project_dir = tmp_path / "p1"
    project_dir.mkdir()
    (project_dir / "dream.json").write_text(
        json.dumps({"items": [{"id": "i1", "origin_text": "q", "assistant_response": "a"}]}),
        encoding="utf-8",
    )
    result = auto_accept.auto_accept_dreams("p1")
    assert result.accepted == 1
    assert any("Tagger failed" in r.message for r in caplog.records)


def test_auto_accept_no_dream_json_returns_empty(tmp_path, monkeypatch):
    auto_accept, _ = _load_auto_accept_module(monkeypatch)
    monkeypatch.setattr(
        auto_accept, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    (tmp_path / "p1").mkdir()
    result = auto_accept.auto_accept_dreams("p1")
    assert result.processed == 0 and result.accepted == 0


def test_auto_accept_invalid_json_quarantines(tmp_path, monkeypatch):
    auto_accept, _ = _load_auto_accept_module(monkeypatch)
    monkeypatch.setattr(
        auto_accept, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    project_dir = tmp_path / "p1"
    project_dir.mkdir()
    (project_dir / "dream.json").write_text("{not valid json", encoding="utf-8")
    result = auto_accept.auto_accept_dreams("p1")
    assert result.failed == 1 and result.renamed_bad_path is not None


def test_auto_accept_invalid_shape_quarantines(tmp_path, monkeypatch):
    auto_accept, _ = _load_auto_accept_module(monkeypatch)
    monkeypatch.setattr(
        auto_accept, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    project_dir = tmp_path / "p1"
    project_dir.mkdir()
    (project_dir / "dream.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    result = auto_accept.auto_accept_dreams("p1")
    assert "invalid_dream_json_shape" in result.errors
    assert result.renamed_bad_path is not None


def test_auto_accept_no_items_delete_failure(tmp_path, monkeypatch):
    auto_accept, _ = _load_auto_accept_module(monkeypatch)
    monkeypatch.setattr(
        auto_accept, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    monkeypatch.setattr(auto_accept, "_delete_dream_file", lambda pid, path: False)
    project_dir = tmp_path / "p1"
    project_dir.mkdir()
    # All-remote-without-research -> nothing to process.
    (project_dir / "dream.json").write_text(
        json.dumps({"items": [{"id": "r1", "source_resolution": "answer_remote"}]}),
        encoding="utf-8",
    )
    result = auto_accept.auto_accept_dreams("p1")
    assert result.failed == 1 and "delete_dream_json_failed" in result.errors


def test_auto_accept_rebuild_cache_failure_recorded(tmp_path, monkeypatch):
    auto_accept, _ = _load_auto_accept_module(monkeypatch)
    monkeypatch.setattr(
        auto_accept, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    monkeypatch.setattr(
        auto_accept,
        "rebuild_daily_cache",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("rebuild boom")),
    )
    project_dir = tmp_path / "p1"
    project_dir.mkdir()
    (project_dir / "dream.json").write_text(
        json.dumps({"items": [{"id": "i1", "origin_text": "q", "assistant_response": "a"}]}),
        encoding="utf-8",
    )
    result = auto_accept.auto_accept_dreams("p1")
    assert any(err.startswith("rebuild_cache:") for err in result.errors)
    assert result.failed >= 1


def test_auto_accept_success_but_delete_fails(tmp_path, monkeypatch):
    auto_accept, _ = _load_auto_accept_module(monkeypatch)
    monkeypatch.setattr(
        auto_accept, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    monkeypatch.setattr(auto_accept, "_delete_dream_file", lambda pid, path: False)
    project_dir = tmp_path / "p1"
    project_dir.mkdir()
    (project_dir / "dream.json").write_text(
        json.dumps({"items": [{"id": "i1", "origin_text": "q", "assistant_response": "a"}]}),
        encoding="utf-8",
    )
    result = auto_accept.auto_accept_dreams("p1")
    assert result.accepted == 1
    assert result.failed == 1 and "delete_dream_json_failed" in result.errors
    assert result.renamed_bad_path is not None
