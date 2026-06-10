"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for the pure helpers in app.core.query_builder.

The LLM-backed build_query path is intentionally excluded; these tests cover the
deterministic helpers it relies on: cache keying, route filtering, balanced-JSON
slicing, and contextual-turn formatting.
"""

import json
from types import SimpleNamespace

import pytest
from app.core import query_builder as QB
from app.core.query_builder import (
    _BuilderPromptDumper,
    _cache_key,
    _dump_builder_prompt,
    _filter_route_only,
    _parse_builder_response,
    _slice_first_json,
    build_query,
    format_contextual_turn,
)
from app.llm_model.base import LLMResponse, LLMUsage


def test_cache_key_is_stable_for_same_inputs():
    a = _cache_key("p1", "summary", "hello")
    b = _cache_key("p1", "summary", "hello")
    assert a == b


def test_cache_key_changes_with_any_field():
    base = _cache_key("p1", "summary", "hello")
    assert _cache_key("p2", "summary", "hello") != base
    assert _cache_key("p1", "other", "hello") != base
    assert _cache_key("p1", "summary", "hi") != base


def test_filter_route_only_normalizes_valid_route():
    assert _filter_route_only({"route": "chitchat"}) == {"route": "CHITCHAT"}
    assert _filter_route_only({"route": "  Direct "}) == {"route": "DIRECT"}


def test_filter_route_only_unknown_route_becomes_other():
    assert _filter_route_only({"route": "banana"}) == {"route": "OTHER"}


def test_filter_route_only_missing_route_becomes_other():
    assert _filter_route_only({}) == {"route": "OTHER"}


def test_filter_route_only_drops_extra_fields():
    out = _filter_route_only({"route": "SYNTHESIS", "extra": "x", "n": 1})
    assert out == {"route": "SYNTHESIS"}


def test_slice_first_json_simple_object():
    assert _slice_first_json('{"a": 1}') == '{"a": 1}'


def test_slice_first_json_strips_surrounding_prose():
    text = 'here you go: {"route": "DIRECT"} thanks!'
    assert _slice_first_json(text) == '{"route": "DIRECT"}'


def test_slice_first_json_handles_nested_objects():
    text = 'x {"a": {"b": 2}} y'
    assert _slice_first_json(text) == '{"a": {"b": 2}}'


def test_slice_first_json_ignores_braces_inside_strings():
    text = '{"a": "}{ not real"}'
    assert _slice_first_json(text) == '{"a": "}{ not real"}'


def test_slice_first_json_returns_first_object_only():
    text = '{"x": 1} and {"y": 2}'
    assert _slice_first_json(text) == '{"x": 1}'


def test_slice_first_json_no_object_returns_input():
    assert _slice_first_json("no json here") == "no json here"
    assert _slice_first_json("") == ""


def test_format_contextual_turn_base_only_without_meta():
    assert format_contextual_turn("hello", "") == "hello"
    assert format_contextual_turn("  hello  ", "") == "hello"


def test_format_contextual_turn_invalid_json_falls_back_to_base():
    assert format_contextual_turn("hello", "{not json") == "hello"


def test_format_contextual_turn_non_dict_meta_falls_back_to_base():
    assert format_contextual_turn("hello", "[1, 2, 3]") == "hello"


def test_format_contextual_turn_all_fields():
    meta = '{"semantic_handle": "ctx", "intent": "ask", "type": "q"}'
    out = format_contextual_turn("hello", meta)
    assert out == "hello Context: ctx. Intent: ask. Type: q"


def test_format_contextual_turn_partial_fields():
    meta = '{"semantic_handle": "ctx"}'
    assert format_contextual_turn("hello", meta) == "hello Context: ctx."


def test_format_contextual_turn_empty_base_has_no_leading_space():
    meta = '{"semantic_handle": "ctx"}'
    assert format_contextual_turn("", meta) == "Context: ctx."


def test_format_contextual_turn_ignores_non_string_fields():
    meta = '{"semantic_handle": 5, "intent": "ask"}'
    assert format_contextual_turn("hello", meta) == "hello Intent: ask."


def test_parse_builder_response_plain_json():
    assert _parse_builder_response('{"route": "DIRECT"}', "p1") == {"route": "DIRECT"}


def test_parse_builder_response_strips_code_fences():
    raw = '```json\n{"route": "SYNTHESIS"}\n```'
    assert _parse_builder_response(raw, "p1") == {"route": "SYNTHESIS"}


def test_parse_builder_response_strips_trailing_prose():
    raw = 'Sure: {"route": "CHITCHAT"} hope that helps'
    assert _parse_builder_response(raw, "p1") == {"route": "CHITCHAT"}


def test_parse_builder_response_skips_leading_garbage():
    raw = '}}garbage {"route": "OTHER"}'
    assert _parse_builder_response(raw, "p1") == {"route": "OTHER"}


def test_parse_builder_response_missing_route_raises():
    with pytest.raises(ValueError):
        _parse_builder_response('{"intent": "ask"}', "p1")


def test_parse_builder_response_non_dict_raises():
    with pytest.raises(ValueError):
        _parse_builder_response("[1, 2, 3]", "p1")


def test_parse_builder_response_unparseable_raises():
    with pytest.raises(json.JSONDecodeError):
        _parse_builder_response("not json at all", "p1")


def test_parse_builder_response_regex_fallback():
    # A stray leading quote confuses the balanced slicer so json.loads(clean)
    # fails, but the permissive regex still recovers the object.
    raw = '" {"route": "DIRECT"}'
    assert _parse_builder_response(raw, "p1") == {"route": "DIRECT"}


def test_filter_route_only_handles_non_dict():
    # A list has no .get -> the except branch yields the OTHER fallback.
    assert _filter_route_only([]) == {"route": "OTHER"}


def test_slice_first_json_handles_escaped_quotes():
    text = '{"a": "x\\"y"}'  # contains an escaped quote inside the string value
    assert _slice_first_json(text) == text


# --- _BuilderPromptDumper / _dump_builder_prompt --------------------------


def test_builder_prompt_dumper_noop_without_project(monkeypatch):
    writes = []
    monkeypatch.setattr(QB, "write_debug_file", lambda *a, **k: writes.append(a))
    _BuilderPromptDumper().dump(
        project_id="",
        user_text="u",
        system_prompt="s",
        user_prompt="up",
        raw_response="r",
        data={"route": "DIRECT"},
        model="m",
    )
    assert writes == []


def test_builder_prompt_dumper_writes_snapshot(monkeypatch):
    writes = []
    monkeypatch.setattr(
        QB, "write_debug_file", lambda pid, path, body: writes.append((pid, path, body))
    )
    _BuilderPromptDumper().dump(
        project_id="p1",
        user_text="u",
        system_prompt="s",
        user_prompt="up",
        raw_response="raw",
        data={"route": "DIRECT"},
        model="builder-x",
    )
    assert len(writes) == 1
    pid, path, body = writes[0]
    assert pid == "p1" and path.startswith("prompts/") and "builder-x" in body


def test_builder_prompt_dumper_handles_unserializable_data(monkeypatch):
    writes = []
    monkeypatch.setattr(QB, "write_debug_file", lambda pid, path, body: writes.append(body))
    _BuilderPromptDumper().dump(
        project_id="p1",
        user_text="u",
        system_prompt="s",
        user_prompt="up",
        raw_response="raw",
        data={"bad": object()},  # not JSON-serializable -> pretty falls back to "{}"
        model=None,
    )
    assert writes and "{}" in writes[0]


def test_dump_builder_prompt_logs_on_failure(monkeypatch, caplog):
    monkeypatch.setattr(
        QB._PROMPT_DUMPER, "dump", lambda **k: (_ for _ in ()).throw(RuntimeError("disk full"))
    )
    _dump_builder_prompt(
        project_id="p1", user_text="u", user_prompt="up", raw_response="r", data=None, model="m"
    )
    assert any("builder debug prompt dump failed" in r.message for r in caplog.records)


def test_dump_builder_prompt_failure_label_on_failure_path(monkeypatch, caplog):
    monkeypatch.setattr(
        QB._PROMPT_DUMPER, "dump", lambda **k: (_ for _ in ()).throw(RuntimeError("disk full"))
    )
    _dump_builder_prompt(
        project_id="p1",
        user_text="u",
        user_prompt="up",
        raw_response="r",
        data=None,
        model="m",
        failure=True,
    )
    assert any("builder failure-path prompt dump failed" in r.message for r in caplog.records)


# --- build_query -----------------------------------------------------------


class _FakeInstr:
    def __init__(self, inv_id="inv-1"):
        self.inv_id = inv_id
        self.ended = []

    def start_invocation(self, **kwargs):
        return self.inv_id

    def end_invocation(self, invocation_id, **kwargs):
        self.ended.append((invocation_id, kwargs))


def _builder_settings(builder_cache=False):
    return SimpleNamespace(
        builder_cache=builder_cache,
        builder_model="builder-mini",
        builder_max_tokens=64,
        log_preview_max_chars=40,
    )


def _route_response(route="DIRECT", extra_usage=None):
    return LLMResponse(
        text=json.dumps({"route": route}),
        model="builder-mini",
        usage=LLMUsage(
            prompt_tokens_reported=5,
            completion_tokens_reported=2,
            total_tokens_reported=7,
            usage_is_estimate=False,
            extra_usage=extra_usage,
        ),
    )


def _patch_build_query(monkeypatch, *, settings, client, instr):
    monkeypatch.setattr(QB, "get_settings", lambda: settings)
    monkeypatch.setattr(QB, "get_llm_client_mini", lambda: client)
    monkeypatch.setattr(QB, "get_instrumentation", lambda: instr)


def test_build_query_happy_path_no_cache(monkeypatch):
    QB._CACHE.clear()
    instr = _FakeInstr()
    client = SimpleNamespace(
        generate_response=lambda **k: _route_response("synthesis", extra_usage={"reasoning": 1})
    )
    _patch_build_query(monkeypatch, settings=_builder_settings(), client=client, instr=instr)
    out = build_query("p1", "history", "summarize the design")
    assert out == {"route": "SYNTHESIS"}
    assert instr.ended and instr.ended[0][1]["usage"]["extra_usage"] == {"reasoning": 1}


def test_build_query_populates_and_serves_cache(monkeypatch):
    QB._CACHE.clear()
    instr = _FakeInstr()
    calls = {"n": 0}

    def _gen(**kwargs):
        calls["n"] += 1
        return _route_response("DIRECT")

    client = SimpleNamespace(generate_response=_gen)
    _patch_build_query(
        monkeypatch, settings=_builder_settings(builder_cache=True), client=client, instr=instr
    )
    first = build_query("p1", "history", "what is x")
    second = build_query("p1", "history", "what is x")  # served from cache
    assert first == second == {"route": "DIRECT"}
    assert calls["n"] == 1  # second call did not re-invoke the classifier


def test_build_query_failure_returns_none(monkeypatch):
    QB._CACHE.clear()
    instr = _FakeInstr()
    client = SimpleNamespace(
        generate_response=lambda **k: (_ for _ in ()).throw(RuntimeError("mini down"))
    )
    _patch_build_query(monkeypatch, settings=_builder_settings(), client=client, instr=instr)
    assert build_query("p1", "history", "hello") is None
    assert instr.ended  # invocation still finalized on the failure path


def test_build_query_skips_end_when_no_invocation_id(monkeypatch):
    QB._CACHE.clear()
    instr = _FakeInstr(inv_id="")  # no invocation id -> end_invocation skipped
    client = SimpleNamespace(generate_response=lambda **k: _route_response("OTHER"))
    _patch_build_query(monkeypatch, settings=_builder_settings(), client=client, instr=instr)
    assert build_query("p1", "history", "hi") == {"route": "OTHER"}
    assert instr.ended == []
