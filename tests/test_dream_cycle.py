"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Tests for Dream cycle orchestration and remote-question bridging.

Exercises ``dreams.dream`` end-to-end with stubbed agents (verifying stage
ordering, data flow, dream.json persistence, and question-artifact cleanup) and
the ``_bridge_remote_questions_into_ideas`` match/inject branches directly.
"""
import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def _load_dreams_module(monkeypatch):
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
    ensure_module("app.dream.agents")
    ensure_module("app.utils")

    config_module = types.ModuleType("app.core.config")
    config_module.get_settings = lambda: SimpleNamespace(memory_root="", enable_dream=True)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.config", config_module)

    questions_module = types.ModuleType("app.dream.agents.questions_agent")
    questions_module.run_questions_agent = lambda _project_id: {"questions": []}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.dream.agents.questions_agent", questions_module)

    idea_module = types.ModuleType("app.dream.agents.idea_agent")
    idea_module.run_idea_agent = lambda _project_id, _context: {"items": []}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.dream.agents.idea_agent", idea_module)

    research_module = types.ModuleType("app.dream.agents.research_agent")
    research_module.run_research_agent = lambda *_args, **_kwargs: {"items": []}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.dream.agents.research_agent", research_module)

    context_module = types.ModuleType("app.dream.context")
    context_module.build_dream_context = lambda _project_id, _questions: ("", "")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.dream.context", context_module)

    debug_module = types.ModuleType("app.utils.debug_utils")
    debug_module.write_debug_file = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.utils.debug_utils", debug_module)

    module_path = Path(__file__).resolve().parents[1] / "backend" / "app" / "dream" / "dreams.py"
    spec = importlib.util.spec_from_file_location("app.dream.dreams", module_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "app.dream.dreams", module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_dream_runs_full_pipeline_and_cleans_artifacts(tmp_path, monkeypatch):
    dreams = _load_dreams_module(monkeypatch)
    project_id = "proj"
    project_dir = tmp_path / project_id
    project_dir.mkdir()
    # Seed a consumed question artifact that should be removed after a clean run.
    (project_dir / "open_questions_consolidated.json").write_text(
        json.dumps({"questions": []}), encoding="utf-8"
    )

    monkeypatch.setattr(
        dreams, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path), enable_dream=True)
    )

    calls = []
    captured = {}

    monkeypatch.setattr(
        dreams,
        "run_questions_agent",
        lambda pid: (calls.append("questions"), {"questions": [{"question": "Q1?", "resolution": "answer_local"}]})[1],
    )
    monkeypatch.setattr(
        dreams,
        "build_dream_context",
        lambda pid, qd: (calls.append("context"), ("CTX", "SUMMARY"))[1],
    )
    monkeypatch.setattr(
        dreams,
        "run_idea_agent",
        lambda pid, ctx: (calls.append("idea"), {"items": [{"id": "i1", "origin_text": "Q1?"}]})[1],
    )

    def fake_research(pid, ideas, summary, debug_ts=None):
        calls.append("research")
        captured["ideas"] = ideas
        captured["summary"] = summary
        return {"items": [{"id": "i1", "origin_text": "Q1?", "assistant_response": "ans"}]}

    monkeypatch.setattr(dreams, "run_research_agent", fake_research)

    dreams.dream(project_id)

    # Stages ran in order.
    assert calls == ["questions", "context", "idea", "research"]
    # Research stage received the filtered ideas and the project summary.
    assert captured["summary"] == "SUMMARY"
    assert [it["id"] for it in captured["ideas"]["items"]] == ["i1"]
    # dream.json persisted with the summary and items.
    dream_path = project_dir / "dream.json"
    assert dream_path.exists()
    written = json.loads(dream_path.read_text(encoding="utf-8"))
    assert written["project_summary"] == "SUMMARY"
    assert [it["id"] for it in written["items"]] == ["i1"]
    # Consumed question artifact removed.
    assert not (project_dir / "open_questions_consolidated.json").exists()


def test_dream_no_op_when_disabled(tmp_path, monkeypatch):
    dreams = _load_dreams_module(monkeypatch)
    monkeypatch.setattr(
        dreams, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path), enable_dream=False)
    )
    called = []
    monkeypatch.setattr(dreams, "run_questions_agent", lambda pid: called.append(pid))

    dreams.dream("proj")

    assert called == []


def test_bridge_annotates_matching_item(monkeypatch):
    dreams = _load_dreams_module(monkeypatch)
    ideas = {"items": [{"id": "i1", "origin_text": "What is the budget for next quarter?"}]}
    questions = {
        "questions": [
            {"question": "What is the budget for next quarter?", "topic": "finance", "used_remote_research": True}
        ]
    }

    bridged, stats = dreams._bridge_remote_questions_into_ideas(ideas, questions)

    item = bridged["items"][0]
    assert item["source_resolution"] == "answer_remote"
    assert "What is the budget for next quarter?" in item["metadata"]["recommended_research"]
    assert stats["remote_questions"] == 1
    assert stats["matched_items"] == 1
    assert stats["injected_items"] == 0
    assert stats["seeded_research_topics"] == 1
    assert stats["decisions"][0]["action"] == "matched_existing_item"
    assert stats["decisions"][0]["recommended_research_count"] == 1


def test_bridge_injects_synthetic_item_when_no_match(monkeypatch):
    dreams = _load_dreams_module(monkeypatch)
    ideas = {"items": []}
    questions = {
        "questions": [
            {
                "question": "How does X scale?",
                "topic": "infra",
                "answer": "It scales horizontally.",
                "used_remote_research": True,
            }
        ]
    }

    bridged, stats = dreams._bridge_remote_questions_into_ideas(ideas, questions)

    assert stats["matched_items"] == 0
    assert stats["injected_items"] == 1
    assert len(bridged["items"]) == 1
    new_item = bridged["items"][0]
    assert new_item["source_resolution"] == "answer_remote"
    assert new_item["origin_text"] == "How does X scale?"
    assert new_item["assistant_response"] == "It scales horizontally."
    assert new_item["metadata"]["recommended_research"] == ["How does X scale?"]
    assert stats["decisions"][0]["action"] == "injected_synthetic_item"


def test_bridge_fuzzy_matches_existing_item(monkeypatch):
    dreams = _load_dreams_module(monkeypatch)
    ideas = {
        "items": [
            {"id": "i1", "origin_text": "What is our long term product roadmap for 2027 and beyond?"}
        ]
    }
    questions = {
        "questions": [
            {"question": "what is our long term product roadmap for 2027", "used_remote_research": True}
        ]
    }

    bridged, stats = dreams._bridge_remote_questions_into_ideas(ideas, questions)

    assert stats["matched_items"] == 1
    assert stats["injected_items"] == 0
    assert bridged["items"][0]["source_resolution"] == "answer_remote"


def test_bridge_ignores_questions_without_remote_research(monkeypatch):
    dreams = _load_dreams_module(monkeypatch)
    ideas = {"items": [{"id": "i1", "origin_text": "Local only question?"}]}
    questions = {
        "questions": [
            {"question": "Local only question?", "used_remote_research": False},
            {"question": "", "used_remote_research": True},
        ]
    }

    bridged, stats = dreams._bridge_remote_questions_into_ideas(ideas, questions)

    assert stats["remote_questions"] == 0
    assert stats["matched_items"] == 0
    assert stats["injected_items"] == 0
    assert "source_resolution" not in bridged["items"][0]
