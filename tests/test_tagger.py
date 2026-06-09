"""
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

import app.tagging.tagger as tagger
from app.tagging.tagger import (
    _build_previous_turn_block,
    _build_tagger_prompt,
    _extract_prev_tag_value,
    _extract_tagger_fields,
    _middle_cut_assistant_text,
    _parse_tagger_response,
    _safe_min_len,
    _safe_percent,
    _slice_first_json,
    _tagger_usage_from_response,
    _write_tagger_failure_debug,
    _write_tagger_success_debug,
    tag_pair,
)


def _settings(current=50, previous=75, min_len=600):
    return SimpleNamespace(
        tagger_current_response_middle_cut_percent=current,
        tagger_previous_response_middle_cut_percent=previous,
        tagger_min_response_length_for_chop=min_len,
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


def test_middle_cut_zero_percent_returns_raw():
    # cut <= 0 -> nothing to remove even though text exceeds the chop threshold.
    text = "B" * 700
    assert _middle_cut_assistant_text(text, 0, 600) == text


def test_middle_cut_keeps_min_sides_then_returns_raw_when_too_short():
    # n just above the threshold with a large cut forces left/right below the
    # 100-char minimum; restoring the minimum makes both sides span the whole
    # string, so the original text is returned unchanged.
    text = "C" * 180
    assert _middle_cut_assistant_text(text, 90, 100) == text


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


def test_build_previous_turn_block_fallback_regex_without_leading_newline():
    # No leading newline before "User:" -> first regex misses, fallback matches.
    prev = "User: q text\nAssistant: a text"
    out = _build_previous_turn_block(prev, prev_cut_percent=75, min_length_for_chop=600)
    assert "q text" in out and "a text" in out


def test_build_previous_turn_block_renders_all_tag_lines():
    prev = (
        "#route: DIRECT\n#keep: true\n#topics: a, b\n#intent: explain\n"
        "#type: technical\n#semantic_handle: the-handle\n"
        "User: hello\nAssistant: hi"
    )
    out = _build_previous_turn_block(prev, prev_cut_percent=75, min_length_for_chop=600)
    for line in (
        "#route: DIRECT",
        "#keep: true",
        "#topics: a, b",
        "#intent: explain",
        "#type: technical",
        "#semantic_handle: the-handle",
    ):
        assert line in out


def test_slice_first_json_balances_braces():
    assert _slice_first_json('noise {"a": 1} tail') == '{"a": 1}'


def test_slice_first_json_empty_returns_input():
    assert _slice_first_json("") == ""


def test_slice_first_json_ignores_braces_and_escapes_inside_strings():
    # A string value containing an escaped quote and a brace must not confuse
    # the brace-balancing scanner.
    raw = '{"k": "a\\"b{c}"}'
    assert _slice_first_json("prefix " + raw) == raw


def test_slice_first_json_unbalanced_returns_input():
    text = 'noise {"a": 1 no close'
    assert _slice_first_json(text) == text


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
    assert out["questions"] == [{"question": "Why?", "topic": "t", "resolution": "answer_remote"}]


def test_tag_pair_filters_bad_questions(monkeypatch):
    payload = (
        '{"topics": "", "intent": "", "type": "", "semantic_handle": "",'
        '"questions": ['
        '{"question": "", "resolution": "ignore"},'  # empty -> dropped
        '{"question": "Keep me", "resolution": "weird"},'  # bad res -> ignore
        '"not-a-dict"'
        "]}"
    )
    _patch_client(monkeypatch, payload)
    out = tag_pair("u", "a", project_id=None)
    assert out["questions"] == [{"question": "Keep me", "topic": "", "resolution": "ignore"}]


def test_tag_pair_missing_semantic_handle_is_empty(monkeypatch):
    _patch_client(monkeypatch, '{"topics": "x", "intent": "y", "type": "z", "questions": []}')
    out = tag_pair("u", "a", project_id=None)
    assert out["semantic_handle"] == ""


def test_tag_pair_strips_code_fences(monkeypatch):
    _patch_client(
        monkeypatch,
        '```json\n{"topics":"t","intent":"","type":"","semantic_handle":"h","questions":[]}\n```',
    )
    out = tag_pair("u", "a", project_id=None)
    assert out["topics"] == "t"
    assert out["semantic_handle"] == "h"


def test_tag_pair_non_json_returns_none(monkeypatch):
    _patch_client(monkeypatch, "I cannot comply, here is prose with no json object")
    assert tag_pair("u", "a", project_id=None) is None


# --- _build_tagger_prompt -----------------------------------------------------


def test_build_tagger_prompt_structure_no_previous():
    prompt = _build_tagger_prompt("the user message", "the assistant reply", None, _settings())
    assert "------CURRENT TURN------" in prompt
    assert "------USER------" in prompt
    assert "------ASSISTANT------" in prompt
    assert "the user message" in prompt
    assert "the assistant reply" in prompt
    # No previous pair -> previous block uses the (none) markers.
    assert "(none)" in prompt


def test_build_tagger_prompt_includes_previous_turn():
    prev = "#route: DIRECT\nUser: hello\nAssistant: hi there"
    prompt = _build_tagger_prompt("now", "reply", prev, _settings())
    assert "PREVIOUS TURN" in prompt
    assert "hello" in prompt


# --- _parse_tagger_response ---------------------------------------------------


def test_parse_tagger_response_plain_json():
    assert _parse_tagger_response('{"a": 1}') == {"a": 1}


def test_parse_tagger_response_strips_code_fences():
    assert _parse_tagger_response('```json\n{"a": 2}\n```') == {"a": 2}


def test_parse_tagger_response_slices_surrounding_noise():
    assert _parse_tagger_response('blah {"a": 3} trailing') == {"a": 3}


def test_parse_tagger_response_non_json_is_none():
    assert _parse_tagger_response("not json at all") is None


def test_parse_tagger_response_non_dict_is_none():
    assert _parse_tagger_response("[1, 2, 3]") is None


# --- _extract_tagger_fields ---------------------------------------------------


def test_extract_tagger_fields_normalizes_and_validates():
    data = {
        "topics": "a, b",
        "intent": "explain",
        "type": "technical",
        "semantic_handle": "the thing",
        "questions": [
            {"question": "Why?", "topic": "t", "resolution": "answer_remote"},
            {"question": "", "resolution": "ignore"},  # empty -> dropped
            {"question": "Keep", "resolution": "weird"},  # bad res -> ignore
            "not-a-dict",  # skipped
        ],
    }
    out = _extract_tagger_fields(data)
    assert out["topics"] == "a, b"
    assert out["intent"] == "explain"
    assert out["type"] == "technical"
    assert out["semantic_handle"] == "the thing"
    assert out["questions"] == [
        {"question": "Why?", "topic": "t", "resolution": "answer_remote"},
        {"question": "Keep", "topic": "", "resolution": "ignore"},
    ]


def test_extract_tagger_fields_missing_semantic_handle_is_empty():
    out = _extract_tagger_fields({"topics": "x", "intent": "y", "type": "z", "questions": []})
    assert out["semantic_handle"] == ""
    assert out["questions"] == []


def test_extract_tagger_fields_coerces_non_string_semantic_handle():
    out = _extract_tagger_fields({"semantic_handle": 123})
    assert out["semantic_handle"] == "123"


# --- _tagger_usage_from_response ----------------------------------------------


def test_tagger_usage_from_response_maps_fields():
    resp = _fake_response("{}")
    usage = _tagger_usage_from_response(resp)
    assert usage["purpose"] == "tagger"
    assert usage["model"] == "gpt-mini"
    assert usage["total_tokens_reported"] == 2
    assert usage["usage_is_estimate"] is True
    assert "extra_usage" not in usage


def test_tagger_usage_from_response_includes_extra_usage():
    usage_ns = SimpleNamespace(
        prompt_tokens_reported=3,
        completion_tokens_reported=4,
        total_tokens_reported=7,
        usage_is_estimate=False,
        extra_usage={"cached": 1},
    )
    resp = SimpleNamespace(text="{}", model="m", usage=usage_ns)
    usage = _tagger_usage_from_response(resp)
    assert usage["extra_usage"] == {"cached": 1}
    assert usage["usage_is_estimate"] is False


# --- debug dump helpers -------------------------------------------------------


def _debug_settings():
    return SimpleNamespace(builder_model="gpt-builder", tagger_model="gpt-mini")


def test_write_tagger_success_debug_writes_when_project_id(monkeypatch):
    writes = []
    monkeypatch.setattr(
        tagger, "write_debug_file", lambda pid, name, body: writes.append((pid, name, body))
    )
    _write_tagger_success_debug("p1", _debug_settings(), "the user prompt", "the raw response")
    assert len(writes) == 1
    pid, name, body = writes[0]
    assert pid == "p1" and name.startswith("prompts/") and name.endswith("_tagger.txt")
    assert "success: true" in body and "the raw response" in body


def test_write_tagger_success_debug_noop_without_project_id(monkeypatch):
    writes = []
    monkeypatch.setattr(tagger, "write_debug_file", lambda *a, **k: writes.append(a))
    _write_tagger_success_debug("", _debug_settings(), "u", "r")
    assert writes == []


def test_write_tagger_success_debug_logs_on_write_failure(monkeypatch, caplog):
    monkeypatch.setattr(
        tagger, "write_debug_file", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    )
    _write_tagger_success_debug("p1", _debug_settings(), "u", "r")
    assert any("Failed writing debug tagger prompt dump" in r.message for r in caplog.records)


def test_write_tagger_failure_debug_writes_when_project_id(monkeypatch):
    monkeypatch.setattr(tagger, "get_settings", lambda: _debug_settings())
    writes = []
    monkeypatch.setattr(
        tagger, "write_debug_file", lambda pid, name, body: writes.append((pid, name, body))
    )
    _write_tagger_failure_debug("p1", "u text", "a text", "prev text", ValueError("boom"))
    assert len(writes) == 1
    _, name, body = writes[0]
    assert name.startswith("prompts/")
    assert "success: false" in body and "error: boom" in body and "u text" in body


def test_write_tagger_failure_debug_noop_without_project_id(monkeypatch):
    monkeypatch.setattr(tagger, "get_settings", lambda: _debug_settings())
    writes = []
    monkeypatch.setattr(tagger, "write_debug_file", lambda *a, **k: writes.append(a))
    _write_tagger_failure_debug(None, "u", "a", None, ValueError("x"))
    assert writes == []


def test_write_tagger_failure_debug_logs_on_write_failure(monkeypatch, caplog):
    monkeypatch.setattr(tagger, "get_settings", lambda: _debug_settings())
    monkeypatch.setattr(
        tagger, "write_debug_file", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    )
    _write_tagger_failure_debug("p1", "u", "a", None, ValueError("x"))
    assert any("Failed writing debug failure dump" in r.message for r in caplog.records)


# --- tag_pair instrumentation / debug / error finalize ------------------------


class _FakeInstr:
    def __init__(self, *, inv_id="inv-1", end_raises=False):
        self.inv_id = inv_id
        self.end_raises = end_raises
        self.ended = []

    def start_invocation(self, **kwargs):
        return self.inv_id

    def end_invocation(self, invocation_id, **kwargs):
        if self.end_raises:
            raise RuntimeError("end_invocation failed")
        self.ended.append((invocation_id, kwargs))


def _full_settings():
    return SimpleNamespace(
        tagger_model="gpt-mini",
        builder_model="gpt-builder",
        builder_max_tokens=256,
        tagger_current_response_middle_cut_percent=50,
        tagger_previous_response_middle_cut_percent=75,
        tagger_min_response_length_for_chop=600,
    )


def test_tag_pair_writes_success_debug_with_project_id(monkeypatch):
    monkeypatch.setattr(tagger, "get_settings", lambda: _full_settings())
    monkeypatch.setattr(tagger, "get_instrumentation", lambda: _FakeInstr())
    _patch_client(
        monkeypatch, '{"topics":"t","intent":"","type":"","semantic_handle":"h","questions":[]}'
    )
    writes = []
    monkeypatch.setattr(tagger, "write_debug_file", lambda pid, name, body: writes.append(name))
    out = tag_pair("u", "a", project_id="p1")
    assert out["topics"] == "t"
    # Success debug body executed (project_id truthy).
    assert writes and writes[0].startswith("prompts/")


def test_tag_pair_summary_log_failure_is_contained(monkeypatch, caplog):
    monkeypatch.setattr(tagger, "get_settings", lambda: _full_settings())
    instr = _FakeInstr()
    monkeypatch.setattr(tagger, "get_instrumentation", lambda: instr)
    _patch_client(
        monkeypatch, '{"topics":"t","intent":"","type":"","semantic_handle":"h","questions":[]}'
    )

    def _boom(*a, **k):
        raise RuntimeError("log boom")

    monkeypatch.setattr(tagger.logger, "info", _boom)
    out = tag_pair("u", "a", project_id=None)
    # The summary-log failure is swallowed; tagging still succeeds and finalizes.
    assert out["topics"] == "t"
    assert instr.ended  # end_invocation still ran
    assert any("Failed writing tagger summary log" in r.message for r in caplog.records)


def test_tag_pair_error_finalizes_invocation(monkeypatch):
    monkeypatch.setattr(tagger, "get_settings", lambda: _full_settings())
    instr = _FakeInstr()
    monkeypatch.setattr(tagger, "get_instrumentation", lambda: instr)
    # Non-JSON output -> ValueError -> error path; invocation_id is truthy so the
    # finalize branch runs end_invocation with the captured usage/timing.
    _patch_client(monkeypatch, "no json here")
    assert tag_pair("u", "a", project_id=None) is None
    assert instr.ended and instr.ended[0][0] == "inv-1"


def test_tag_pair_error_finalize_failure_is_contained(monkeypatch, caplog):
    monkeypatch.setattr(tagger, "get_settings", lambda: _full_settings())
    monkeypatch.setattr(tagger, "get_instrumentation", lambda: _FakeInstr(end_raises=True))
    _patch_client(monkeypatch, "no json here")
    assert tag_pair("u", "a", project_id=None) is None
    assert any("Failed finalizing invocation after error" in r.message for r in caplog.records)
