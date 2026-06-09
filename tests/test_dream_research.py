"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.dream.research.

Token helpers are exercised directly; fetch_remote_research fakes the LLM
boundary (generate_text_response) so neither the network nor a model is hit.
"""

from types import SimpleNamespace

from app.dream import research as dream_research


def test_count_tokens_handles_none():
    assert dream_research.count_tokens(None) == 0
    assert dream_research.count_tokens("hello world") > 0


def test_trim_to_tokens_handles_none():
    assert dream_research.trim_to_tokens(None, 5) == ""


def _settings():
    return SimpleNamespace(dream_model="dream-mini", dream_temperature=0.7, dream_max_tokens=128)


def test_fetch_remote_research_returns_text(monkeypatch):
    monkeypatch.setattr(dream_research, "get_settings", _settings)
    monkeypatch.setattr(
        dream_research,
        "generate_text_response",
        lambda *a, **k: SimpleNamespace(text="research blob"),
    )
    assert dream_research.fetch_remote_research("topic") == "research blob"


def test_fetch_remote_research_returns_empty_on_failure(monkeypatch, caplog):
    monkeypatch.setattr(dream_research, "get_settings", _settings)

    def _boom(*a, **k):
        raise RuntimeError("tool down")

    monkeypatch.setattr(dream_research, "generate_text_response", _boom)
    assert dream_research.fetch_remote_research("topic") == ""
    assert any("Remote research failed" in r.message for r in caplog.records)
