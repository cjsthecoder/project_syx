"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.dream.debug artifact writers.

The write_debug_file boundary is faked so the writers are exercised without
touching disk; the no-project short-circuits are covered too.
"""

from types import SimpleNamespace

from app.dream import debug as dream_debug


def test_safe_dream_purpose_sanitizes_and_defaults():
    assert dream_debug.safe_dream_purpose("dream:remote research!") == "dream_remote_research"
    assert dream_debug.safe_dream_purpose(None) == "dream"
    assert dream_debug.safe_dream_purpose("   ") == "dream"


def test_write_prompt_to_execute_noop_without_project(monkeypatch):
    writes = []
    monkeypatch.setattr(dream_debug, "write_debug_file", lambda *a, **k: writes.append(a))
    dream_debug.write_dream_prompt_to_execute(
        project_id=None, prompt="p", purpose="dream", model="m", max_output_tokens=10
    )
    assert writes == []


def test_write_prompt_to_execute_writes(monkeypatch):
    writes = []
    monkeypatch.setattr(
        dream_debug, "write_debug_file", lambda pid, path, body: writes.append((pid, path, body))
    )
    dream_debug.write_dream_prompt_to_execute(
        project_id="p1",
        prompt="hello",
        purpose="dream:idea",
        model="dream-mini",
        max_output_tokens=99,
    )
    assert len(writes) == 1
    pid, path, body = writes[0]
    assert pid == "p1" and "prompt_to_execute" in path
    assert "hello" in body and "dream-mini" in body


def test_write_context_summary_debug_noop_without_project(monkeypatch):
    writes = []
    monkeypatch.setattr(dream_debug, "write_debug_file", lambda *a, **k: writes.append(a))
    dream_debug.write_dream_context_summary_debug(project_id=None, summary_prompt="prompt")
    assert writes == []


def test_write_context_summary_debug_writes_dreaming_artifact(monkeypatch):
    writes = []
    monkeypatch.setattr(
        dream_debug, "write_debug_file", lambda pid, path, body: writes.append((pid, path, body))
    )
    dream_debug.write_dream_context_summary_debug(project_id="p1", summary_prompt="summarize me")

    assert len(writes) == 1
    pid, path, body = writes[0]
    assert pid == "p1"
    assert path.startswith("dreaming/")
    assert path.endswith("_context_summary.txt")
    assert "summarize me" in body and "dream_purpose: context_summary" in body


def test_write_response_usage_noop_without_project(monkeypatch):
    writes = []
    monkeypatch.setattr(dream_debug, "write_debug_file", lambda *a, **k: writes.append(a))
    dream_debug.write_dream_response_usage_debug(
        project_id="",
        response_text="r",
        purpose="dream",
        model="m",
        max_output_tokens=10,
        usage=SimpleNamespace(),
    )
    assert writes == []


def test_write_response_usage_writes(monkeypatch):
    writes = []
    monkeypatch.setattr(
        dream_debug, "write_debug_file", lambda pid, path, body: writes.append((pid, path, body))
    )
    usage = SimpleNamespace(
        prompt_tokens_reported=5,
        completion_tokens_reported=3,
        total_tokens_reported=8,
        usage_is_estimate=False,
        extra_usage={"reasoning": 1},
    )
    dream_debug.write_dream_response_usage_debug(
        project_id="p1",
        response_text="the answer",
        purpose="dream:research",
        model="dream-mini",
        max_output_tokens=99,
        usage=usage,
    )
    assert len(writes) == 1
    pid, path, body = writes[0]
    assert pid == "p1" and "response_usage" in path
    assert "the answer" in body and "total_tokens_reported: 8" in body and "reasoning" in body
