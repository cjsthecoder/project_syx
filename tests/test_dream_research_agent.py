"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.dream.agents.research_agent.

The retrieval and LLM boundaries (retrieve_dream_context, generate_text_response)
plus the debug writers are faked so no FAISS/model/network/disk is touched.
"""

from types import SimpleNamespace

from app.dream.agents import research_agent


def _patch(
    monkeypatch, *, llm_text="## Header\n- finding", retrieve_raises=False, llm_raises=False
):
    monkeypatch.setattr(
        research_agent,
        "get_settings",
        lambda: SimpleNamespace(
            dream_max_tokens=128, dream_model="dream-mini", dream_temperature=0.7
        ),
    )
    monkeypatch.setattr(research_agent, "write_debug_file", lambda *a, **k: None)
    monkeypatch.setattr(research_agent, "write_dream_prompt_to_execute", lambda **k: None)
    monkeypatch.setattr(research_agent, "write_dream_response_usage_debug", lambda **k: None)

    def _retrieve(**k):
        if retrieve_raises:
            raise RuntimeError("retrieval boom")
        return {"context_text": "local ctx"}

    monkeypatch.setattr(research_agent, "retrieve_dream_context", _retrieve)

    def _gen(*a, **k):
        if llm_raises:
            raise RuntimeError("llm down")
        return SimpleNamespace(text=llm_text, usage=SimpleNamespace())

    monkeypatch.setattr(research_agent, "generate_text_response", _gen)


def _remote_entry(**overrides):
    entry = {
        "id": "e1",
        "origin_text": "ot",
        "origin_type": "Open Question",
        "assistant_response": "ar",
        "source_resolution": "answer_remote",
        "metadata": {"theme": "themeX", "recommended_research": ["topicA"]},
    }
    entry.update(overrides)
    return entry


def test_run_research_agent_invalid_items_returns_empty(monkeypatch):
    _patch(monkeypatch)
    out = research_agent.run_research_agent("p1", {"items": "not-a-list"}, "summary")
    assert out["items"] == []


def test_run_research_agent_blank_date_uses_today(monkeypatch):
    _patch(monkeypatch)
    out = research_agent.run_research_agent("p1", {"date": "  ", "items": []}, "summary")
    assert out["date"]


def test_run_research_agent_attaches_research(monkeypatch):
    _patch(monkeypatch, llm_text="## topicA\n- key finding\n- second")
    data = {"date": "06/09/2026", "items": [_remote_entry()]}
    out = research_agent.run_research_agent("p1", data, "summary", debug_ts="2026-06-09T00-00-00")
    research = out["items"][0]["research"]
    assert len(research) == 1
    assert research[0]["research_topic"] == "topicA"
    assert "second" in research[0]["research_summary"]


def test_run_research_agent_skips_non_dict_entry(monkeypatch):
    _patch(monkeypatch)
    out = research_agent.run_research_agent("p1", {"items": ["not-a-dict"]}, "summary")
    assert out["items"] == ["not-a-dict"]  # passed through untouched


def test_run_research_agent_invalid_metadata_flags_failed(monkeypatch):
    _patch(monkeypatch)
    entry = _remote_entry(metadata="not-a-dict")
    out = research_agent.run_research_agent("p1", {"items": [entry]}, "summary")
    assert out["items"][0]["research"] == [] and out["items"][0]["research_failed"] is True


def test_run_research_agent_skips_non_remote(monkeypatch):
    _patch(monkeypatch)
    entry = _remote_entry(source_resolution="answer_local")
    out = research_agent.run_research_agent("p1", {"items": [entry]}, "summary")
    assert out["items"][0]["research"] == []


def test_run_research_agent_no_recommended_research(monkeypatch):
    _patch(monkeypatch)
    entry = _remote_entry()
    entry["metadata"]["recommended_research"] = []
    out = research_agent.run_research_agent("p1", {"items": [entry]}, "summary")
    assert out["items"][0]["research"] == []


def test_run_research_agent_recommended_scalar_wrapped(monkeypatch):
    _patch(monkeypatch, llm_text="## solo\n- f")
    entry = _remote_entry()
    entry["metadata"]["recommended_research"] = "solo"  # non-list scalar
    out = research_agent.run_research_agent("p1", {"items": [entry]}, "summary")
    assert out["items"][0]["research"][0]["research_topic"] == "solo"


def test_run_research_agent_blank_topic_skipped(monkeypatch):
    _patch(monkeypatch)
    entry = _remote_entry()
    entry["metadata"]["recommended_research"] = ["   "]  # blank topic
    out = research_agent.run_research_agent("p1", {"items": [entry]}, "summary")
    # blank topic produced no research and topics_list was non-empty -> failed flag
    assert out["items"][0]["research"] == [] and out["items"][0]["research_failed"] is True


def test_run_research_agent_retrieval_failure_degrades(monkeypatch):
    _patch(monkeypatch, retrieve_raises=True, llm_text="## topicA\n- f")
    out = research_agent.run_research_agent("p1", {"items": [_remote_entry()]}, "summary")
    assert out["items"][0]["research"][0]["research_topic"] == "topicA"


def test_run_research_agent_llm_failure_marks_failed(monkeypatch):
    # LLM raises -> fallback JSON has no second line -> empty summary -> failure.
    _patch(monkeypatch, llm_raises=True)
    out = research_agent.run_research_agent("p1", {"items": [_remote_entry()]}, "summary")
    assert out["items"][0].get("research_failed") is True


def test_run_research_agent_empty_output_skips_topic(monkeypatch):
    _patch(monkeypatch, llm_text="   \n   ")  # all whitespace -> no first non-empty line
    out = research_agent.run_research_agent("p1", {"items": [_remote_entry()]}, "summary")
    assert out["items"][0]["research"] == [] and out["items"][0]["research_failed"] is True


def test_run_research_agent_header_only_no_summary_skips(monkeypatch):
    _patch(monkeypatch, llm_text="## only header")  # header but no body lines
    out = research_agent.run_research_agent("p1", {"items": [_remote_entry()]}, "summary")
    assert out["items"][0]["research"] == [] and out["items"][0]["research_failed"] is True


def test_run_research_agent_debug_write_failures_are_logged(monkeypatch, caplog):
    _patch(monkeypatch, llm_text="## topicA\n- f")
    # Make the final debug writes raise to cover the warning branches.
    monkeypatch.setattr(
        research_agent, "write_debug_file", lambda *a, **k: (_ for _ in ()).throw(OSError("disk"))
    )
    out = research_agent.run_research_agent(
        "p1", {"items": [_remote_entry()]}, "summary", debug_ts="2026-06-09T00-00-00"
    )
    assert out["items"][0]["research"]  # research still attached despite debug failures
    assert any("failed to write" in r.message.lower() for r in caplog.records)
