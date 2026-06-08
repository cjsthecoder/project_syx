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

import pytest

from app.core.query_builder import (
    _cache_key,
    _filter_route_only,
    _parse_builder_response,
    _slice_first_json,
    format_contextual_turn,
)


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
        _parse_builder_response('[1, 2, 3]', "p1")


def test_parse_builder_response_unparseable_raises():
    with pytest.raises(json.JSONDecodeError):
        _parse_builder_response("not json at all", "p1")
