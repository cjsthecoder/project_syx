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
    config_module.get_settings = lambda: SimpleNamespace(memory_root="")  # type: ignore[attr-defined]
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


def test_write_dream_output_appends_to_existing_dream_json(tmp_path, monkeypatch):
    dreams = _load_dreams_module(monkeypatch)
    project_id = "project-1"
    project_dir = tmp_path / project_id
    project_dir.mkdir()
    dream_path = project_dir / "dream.json"
    dream_path.write_text(
        json.dumps(
            {
                "date": "04/26/2026",
                "project_summary": "previous summary",
                "items": [
                    {
                        "id": "old-1",
                        "origin_text": "previous pending item",
                        "assistant_response": "Old response",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dreams, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path)))

    dreams.write_dream_output(
        project_id,
        {
            "date": "04/27/2026",
            "items": [
                {
                    "id": "new-1",
                    "origin_text": "new pending item",
                    "assistant_response": "New response",
                }
            ],
        },
        "latest summary",
    )

    written = json.loads(dream_path.read_text(encoding="utf-8"))
    assert written["date"] == "04/27/2026"
    assert written["project_summary"] == "latest summary"
    assert [item["id"] for item in written["items"]] == ["old-1", "new-1"]
    assert written["items"][0]["origin_text"] == "previous pending item"
    assert written["items"][1]["origin_text"] == "New pending item"


def test_write_dream_output_creates_dream_json_without_existing_file(tmp_path, monkeypatch):
    dreams = _load_dreams_module(monkeypatch)
    project_id = "project-2"
    monkeypatch.setattr(dreams, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path)))

    dreams.write_dream_output(
        project_id,
        {
            "date": "04/27/2026",
            "items": [
                {
                    "id": "new-1",
                    "origin_text": "fresh item",
                    "assistant_response": "Fresh response",
                }
            ],
        },
        "fresh summary",
    )

    dream_path = tmp_path / project_id / "dream.json"
    written = json.loads(dream_path.read_text(encoding="utf-8"))
    assert written["project_summary"] == "fresh summary"
    assert [item["id"] for item in written["items"]] == ["new-1"]
