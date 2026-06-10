"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.dream.agents.idea_agent.

The LLM boundary (generate_text_response) and the debug writers are faked so no
model/network/disk is hit; the validation branches are driven by feeding crafted
JSON response payloads.
"""

import json
from types import SimpleNamespace

from app.dream.agents import idea_agent


def _valid_item(**overrides):
    item = {
        "id": "i1",
        "agent": "wrong",
        "timestamp": "2026-06-09T00:00:00Z",
        "origin_text": "ot",
        "origin_type": "Open Question",
        "assistant_response": "ar",
        "context_link": "cl",
        "metadata": {
            "priority": 2,
            "confidence": 0.55,
            "theme": "themeX",
            "recommended_research": ["topicA"],
        },
    }
    item.update(overrides)
    return item


def _patch_llm(monkeypatch, *, text=None, raise_exc=False):
    monkeypatch.setattr(
        idea_agent,
        "get_settings",
        lambda: SimpleNamespace(
            dream_max_tokens=128, dream_model="dream-mini", dream_temperature=0.7
        ),
    )
    monkeypatch.setattr(idea_agent, "write_dream_prompt_to_execute", lambda **k: None)
    monkeypatch.setattr(idea_agent, "write_dream_response_usage_debug", lambda **k: None)

    def _gen(*a, **k):
        if raise_exc:
            raise RuntimeError("llm down")
        return SimpleNamespace(text=text, usage=SimpleNamespace())

    monkeypatch.setattr(idea_agent, "generate_text_response", _gen)


# --- _normalize_recommended_research --------------------------------------


def test_normalize_recommended_research_variants():
    assert idea_agent._normalize_recommended_research(["a"]) == ["a"]
    assert idea_agent._normalize_recommended_research("") == []
    assert idea_agent._normalize_recommended_research(None) == []
    assert idea_agent._normalize_recommended_research({}) == []
    assert idea_agent._normalize_recommended_research("solo") == ["solo"]


# --- run_idea_agent happy + LLM failure -----------------------------------


def test_run_idea_agent_happy_validates_item(monkeypatch):
    _patch_llm(monkeypatch, text=json.dumps({"date": "06/09/2026", "items": [_valid_item()]}))
    out = idea_agent.run_idea_agent("p1", "ctx")
    assert out["date"] == "06/09/2026"
    assert len(out["items"]) == 1
    assert out["items"][0]["agent"] == "idea_agent"  # auto-corrected
    assert out["items"][0]["metadata"]["priority"] == 2


def test_run_idea_agent_llm_failure_then_parse_fallback(monkeypatch):
    # On LLM failure the agent falls back to a non-DreamEntry JSON, which parses
    # but lacks items -> empty items list.
    _patch_llm(monkeypatch, raise_exc=True)
    out = idea_agent.run_idea_agent("p1", "ctx")
    assert out["items"] == []


def test_run_idea_agent_invalid_json_returns_empty(monkeypatch):
    _patch_llm(monkeypatch, text="not valid json")
    out = idea_agent.run_idea_agent("p1", "ctx")
    assert out["items"] == []


def test_run_idea_agent_items_dict_is_wrapped(monkeypatch):
    _patch_llm(monkeypatch, text=json.dumps({"items": _valid_item()}))  # dict, not list
    out = idea_agent.run_idea_agent("p1", "ctx")
    assert len(out["items"]) == 1


def test_run_idea_agent_items_missing_returns_empty(monkeypatch):
    _patch_llm(monkeypatch, text=json.dumps({"date": "06/09/2026", "items": "nope"}))
    out = idea_agent.run_idea_agent("p1", "ctx")
    assert out["items"] == []


def test_run_idea_agent_blank_date_uses_today(monkeypatch):
    _patch_llm(monkeypatch, text=json.dumps({"date": "  ", "items": []}))
    out = idea_agent.run_idea_agent("p1", "ctx")
    assert out["date"]  # filled with today's MM/DD/YYYY


# --- per-item skip branches -----------------------------------------------


def _run_with_item(monkeypatch, item):
    _patch_llm(monkeypatch, text=json.dumps({"date": "06/09/2026", "items": [item]}))
    return idea_agent.run_idea_agent("p1", "ctx")


def test_skip_non_dict_item(monkeypatch):
    assert _run_with_item(monkeypatch, "not-a-dict")["items"] == []


def test_skip_missing_required_fields(monkeypatch):
    item = _valid_item()
    del item["context_link"]
    assert _run_with_item(monkeypatch, item)["items"] == []


def test_skip_invalid_origin_type(monkeypatch):
    assert _run_with_item(monkeypatch, _valid_item(origin_type="Bogus"))["items"] == []


def test_skip_non_open_question_origin_type(monkeypatch):
    assert _run_with_item(monkeypatch, _valid_item(origin_type="Insight"))["items"] == []


def test_skip_invalid_metadata(monkeypatch):
    assert _run_with_item(monkeypatch, _valid_item(metadata="not-a-dict"))["items"] == []


def test_skip_incomplete_metadata(monkeypatch):
    item = _valid_item()
    del item["metadata"]["theme"]
    assert _run_with_item(monkeypatch, item)["items"] == []


def test_skip_non_integer_priority(monkeypatch):
    item = _valid_item()
    item["metadata"]["priority"] = "abc"
    assert _run_with_item(monkeypatch, item)["items"] == []


def test_skip_priority_below_one(monkeypatch):
    item = _valid_item()
    item["metadata"]["priority"] = 0
    assert _run_with_item(monkeypatch, item)["items"] == []


def test_skip_recommended_research_none(monkeypatch):
    item = _valid_item()
    item["metadata"]["recommended_research"] = None
    assert _run_with_item(monkeypatch, item)["items"] == []


def test_recommended_research_dedup_and_cap(monkeypatch):
    item = _valid_item()
    item["metadata"]["recommended_research"] = ["A", "a", "", "B", "C"]  # dup + empty + >2
    out = _run_with_item(monkeypatch, item)
    rec = out["items"][0]["metadata"]["recommended_research"]
    assert rec == ["A", "B"]  # deduped (case-insensitive), empty dropped, capped at 2
