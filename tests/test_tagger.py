"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Tests for app.tagging.tagger.

Pure prompt-assembly helpers are tested directly. ``tag_pair`` is exercised with
a fake mini-LLM client so parsing/normalization is covered without any network.
"""

from types import SimpleNamespace

import pytest

import app.tagging.tagger as tagger
from app.tagging.tagger import (
    _build_previous_turn_block,
    _extract_prev_tag_value,
    _middle_cut_assistant_text,
    _safe_min_len,
    _safe_percent,
    _slice_first_json,
    tag_pair,
)


def _fake_response(text):
    usage = SimpleNamespace(
        prompt_tokens_reported=1,
        completion_tokens_reported=1,
        total_tokens_reported=2,
        usage_is_estimate=True,
        extra_usage=None,
    )
    return SimpleNamespace(text=text, model="gpt-mini", usage=usage)


def _patch_client(monkeypatch, text):
    client = SimpleNamespace(generate_response=lambda **kwargs: _fake_response(text))
    monkeypatch.setattr(tagger, "get_llm_client_mini", lambda: client)


def test_safe_percent_valid_and_clamped():
    assert _safe_percent("62.5", default=50, name="x") == 62
    assert _safe_percent(5, default=50, name="x") == 50  # below 10 -> default
    assert _safe_percent(95, default=50, name="x") == 50  # above 90 -> default
    assert _safe_percent("nope", default=40, name="x") == 40


def test_safe_min_len_valid_and_fallback():
    assert _safe_min_len("600", default=300, name="x") == 600
    assert _safe_min_len(0, default=300, name="x") == 300
    assert _safe_min_len("bad", default=300, name="x") == 300


def test_middle_cut_short_text_unchanged():
    assert _middle_cut_assistant_text("short", 50, 600) == "short"


def test_middle_cut_long_text_omits_middle():
    text = "A" * 2000
    out = _middle_cut_assistant_text(text, 50, 600)
    assert "[middle omitted for tagging]" in out
    assert len(out) < len(text)


def test_extract_prev_tag_value():
    block = "#route: DIRECT\n#topics: a, b\n"
    assert _extract_prev_tag_value(block, "route") == "DIRECT"
    assert _extract_prev_tag_value(block, "topics") == "a, b"
    assert _extract_prev_tag_value(block, "missing") == ""


def test_build_previous_turn_block_with_pair():
    prev = "#route: DIRECT\nUser: hello\nAssistant: hi there"
    out = _build_previous_turn_block(prev, prev_cut_percent=75, min_length_for_chop=600)
    assert "PREVIOUS TURN" in out
    assert "#route: DIRECT" in out
    assert "hello" in out
    assert "hi there" in out


def test_build_previous_turn_block_empty_uses_none_markers():
    out = _build_previous_turn_block("", prev_cut_percent=75, min_length_for_chop=600)
    assert "(none)" in out


def test_slice_first_json_balances_braces():
    assert _slice_first_json('noise {"a": 1} tail') == '{"a": 1}'


def test_tag_pair_success_normalizes(monkeypatch):
    payload = (
        '{"topics": "a, b", "intent": "explain", "type": "technical", '
        '"semantic_handle": "the thing", '
        '"questions": [{"question": "Why?", "topic": "t", "resolution": "answer_remote"}]}'
    )
    _patch_client(monkeypatch, payload)
    out = tag_pair("user msg", "assistant msg", project_id=None)
    assert out["topics"] == "a, b"
    assert out["intent"] == "explain"
    assert out["type"] == "technical"
    assert out["semantic_handle"] == "the thing"
    assert out["questions"] == [
        {"question": "Why?", "topic": "t", "resolution": "answer_remote"}
    ]


def test_tag_pair_filters_bad_questions(monkeypatch):
    payload = (
        '{"topics": "", "intent": "", "type": "", "semantic_handle": "",'
        '"questions": ['
        '{"question": "", "resolution": "ignore"},'  # empty -> dropped
        '{"question": "Keep me", "resolution": "weird"},'  # bad res -> ignore
        '"not-a-dict"'
        ']}'
    )
    _patch_client(monkeypatch, payload)
    out = tag_pair("u", "a", project_id=None)
    assert out["questions"] == [
        {"question": "Keep me", "topic": "", "resolution": "ignore"}
    ]


def test_tag_pair_missing_semantic_handle_is_empty(monkeypatch):
    _patch_client(monkeypatch, '{"topics": "x", "intent": "y", "type": "z", "questions": []}')
    out = tag_pair("u", "a", project_id=None)
    assert out["semantic_handle"] == ""


def test_tag_pair_strips_code_fences(monkeypatch):
    _patch_client(monkeypatch, '```json\n{"topics":"t","intent":"","type":"","semantic_handle":"h","questions":[]}\n```')
    out = tag_pair("u", "a", project_id=None)
    assert out["topics"] == "t"
    assert out["semantic_handle"] == "h"


def test_tag_pair_non_json_returns_none(monkeypatch):
    _patch_client(monkeypatch, "I cannot comply, here is prose with no json object")
    assert tag_pair("u", "a", project_id=None) is None
