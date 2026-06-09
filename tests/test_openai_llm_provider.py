"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.llm_model.providers.openai_provider.

The pure envelope-normalization helpers (mapping coercion, int coercion, text
flattening, chat/responses usage parsing, responses output extraction) are
tested directly. The provider methods are exercised by faking the OpenAI SDK
client (``patch`` the module-level ``OpenAI`` symbol with a MagicMock), so no
network call is ever made; the temperature/input/text-format SDK fallbacks and
the streaming path are driven with crafted responses and raising side effects.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import app.llm_model.providers.openai_provider as provider_mod
from app.llm_model.providers.openai_provider import (
    OpenAILLMProvider,
    _as_mapping,
    _coerce_int,
    _extract_text_parts,
    _responses_output_text,
    _safe_usage_from_chat,
    _safe_usage_from_responses,
)

# --- _as_mapping --------------------------------------------------------------


def test_as_mapping_passthrough_dict():
    d = {"a": 1}
    assert _as_mapping(d) is d


def test_as_mapping_uses_model_dump():
    obj = SimpleNamespace(model_dump=lambda mode="python": {"x": 2})
    assert _as_mapping(obj) == {"x": 2}


def test_as_mapping_model_dump_non_dict_returns_empty():
    obj = SimpleNamespace(model_dump=lambda mode="python": [1, 2])
    assert _as_mapping(obj) == {}


def test_as_mapping_model_dump_raises_returns_empty(caplog):
    def _boom(mode="python"):
        raise RuntimeError("dump boom")

    obj = SimpleNamespace(model_dump=_boom)
    assert _as_mapping(obj) == {}


def test_as_mapping_no_model_dump_returns_empty():
    assert _as_mapping(object()) == {}


# --- _coerce_int --------------------------------------------------------------


def test_coerce_int_happy_and_falsy():
    assert _coerce_int(5) == 5
    assert _coerce_int(None) == 0
    assert _coerce_int(0) == 0


def test_coerce_int_invalid_uses_default():
    assert _coerce_int(object(), default=9) == 9
    assert _coerce_int("not-int", default=3) == 3


# --- _extract_text_parts ------------------------------------------------------


def test_extract_text_parts_bare_string():
    assert _extract_text_parts("hello") == "hello"


def test_extract_text_parts_non_string_non_list_empty():
    assert _extract_text_parts(123) == ""


def test_extract_text_parts_list_of_strings():
    assert _extract_text_parts(["a", "b"]) == "ab"


def test_extract_text_parts_list_with_text_dict_parts():
    value = [
        {"text": "plain"},
        {"text": {"value": "nested"}},
        {"type": "output_text", "text": "typed"},
        {"nothing": True},
    ]
    assert _extract_text_parts(value) == "plainnestedtyped"


# --- _safe_usage_from_chat ----------------------------------------------------


def test_safe_usage_from_chat_legacy_fields():
    usage = SimpleNamespace(prompt_tokens=3, completion_tokens=4, total_tokens=7)
    out = _safe_usage_from_chat(usage)
    assert (
        out.prompt_tokens_reported,
        out.completion_tokens_reported,
        out.total_tokens_reported,
    ) == (3, 4, 7)
    assert out.usage_is_estimate is False


def test_safe_usage_from_chat_input_output_fallback():
    # Legacy prompt/completion are zero -> fall back to input/output naming.
    usage = SimpleNamespace(
        prompt_tokens=0, completion_tokens=0, input_tokens=11, output_tokens=22, total_tokens=33
    )
    out = _safe_usage_from_chat(usage)
    assert out.prompt_tokens_reported == 11 and out.completion_tokens_reported == 22


def test_safe_usage_from_chat_parse_failure_returns_estimate():
    class _Bad:
        @property
        def prompt_tokens(self):
            raise RuntimeError("attr boom")

    out = _safe_usage_from_chat(_Bad())
    assert out.usage_is_estimate is True
    assert out.total_tokens_reported == 0


# --- _safe_usage_from_responses ----------------------------------------------


def test_safe_usage_from_responses_with_extra_detail():
    usage = SimpleNamespace(
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        reasoning_tokens=5,
        cached_tokens=2,
        input_token_details=None,
        output_token_details=None,
    )
    out = _safe_usage_from_responses(usage)
    assert out.prompt_tokens_reported == 10 and out.completion_tokens_reported == 20
    assert out.extra_usage == {"reasoning_tokens": 5, "cached_tokens": 2}


def test_safe_usage_from_responses_extra_field_access_skipped(caplog):
    # One extra field raises on attribute access -> skipped, others still read.
    class _Usage:
        input_tokens = 1
        output_tokens = 2
        total_tokens = 3

        @property
        def reasoning_tokens(self):
            raise RuntimeError("field boom")

    out = _safe_usage_from_responses(_Usage())
    assert out.prompt_tokens_reported == 1
    assert "reasoning_tokens" not in (out.extra_usage or {})


def test_safe_usage_from_responses_parse_failure_returns_estimate():
    class _Bad:
        @property
        def input_tokens(self):
            raise RuntimeError("boom")

    out = _safe_usage_from_responses(_Bad())
    assert out.usage_is_estimate is True


# --- _responses_output_text ---------------------------------------------------


def test_responses_output_text_prefers_output_text():
    resp = SimpleNamespace(output_text="the answer")
    assert _responses_output_text(resp) == "the answer"


def test_responses_output_text_walks_structured_output():
    # No convenience output_text -> walk output -> message -> output_text parts.
    msg_item = {
        "type": "message",
        "content": [
            {"type": "output_text", "text": "hello "},
            {"type": "reasoning", "text": "ignored"},
            {"type": "output_text", "text": "world"},
        ],
    }
    other_item = {"type": "reasoning", "content": []}
    resp = SimpleNamespace(output_text=None, output=[other_item, msg_item])
    assert _responses_output_text(resp) == "hello world"


def test_responses_output_text_output_via_mapping_fallback():
    # The ``output`` attribute is absent -> read it from the mapping form.
    resp = SimpleNamespace(
        output_text=None,
        model_dump=lambda mode="python": {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "mapped"}]}]
        },
    )
    assert _responses_output_text(resp) == "mapped"


def test_responses_output_text_output_text_read_failure_falls_back(caplog):
    class _Resp:
        @property
        def output_text(self):
            raise RuntimeError("read boom")

        output = [{"type": "message", "content": [{"type": "output_text", "text": "fallback"}]}]

    assert _responses_output_text(_Resp()) == "fallback"
    assert any("failed reading output_text" in r.message for r in caplog.records)


def test_responses_output_text_iteration_failure_returns_empty(caplog):
    class _Resp:
        output_text = None

        @property
        def output(self):
            raise RuntimeError("iter boom")

    assert _responses_output_text(_Resp()) == ""
    assert any("failed iterating response output" in r.message for r in caplog.records)


# --- provider construction helper --------------------------------------------


def _provider(mock_openai):
    return OpenAILLMProvider(api_key="k", default_model="gpt-default", timeout_s=10.0)


# --- generate_chat ------------------------------------------------------------


def test_generate_chat_temperature_retry():
    mock_openai = MagicMock()
    client = mock_openai.return_value
    good = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )
    client.chat.completions.create.side_effect = [
        Exception("Unsupported value: 'temperature' is not supported"),
        good,
    ]
    with patch.object(provider_mod, "OpenAI", mock_openai):
        provider = _provider(mock_openai)
        resp = provider.generate_chat(
            messages=[{"role": "user", "content": "hi"}], temperature=0.5, max_completion_tokens=32
        )
    assert resp.text == "ok"
    assert client.chat.completions.create.call_count == 2
    # max_completion_tokens forwarded as an int.
    assert client.chat.completions.create.call_args_list[0].kwargs["max_completion_tokens"] == 32


def test_generate_chat_non_temperature_error_reraises():
    mock_openai = MagicMock()
    client = mock_openai.return_value
    client.chat.completions.create.side_effect = RuntimeError("server exploded")
    with patch.object(provider_mod, "OpenAI", mock_openai):
        provider = _provider(mock_openai)
        try:
            provider.generate_chat(messages=[{"role": "user", "content": "hi"}])
            raise AssertionError("expected RuntimeError")
        except RuntimeError as exc:
            assert "server exploded" in str(exc)


def test_generate_chat_content_via_mapping_fallback():
    # message.content is None -> _as_mapping(msg).get("content") used instead.
    mock_openai = MagicMock()
    client = mock_openai.return_value
    msg = SimpleNamespace(content=None, model_dump=lambda mode="python": {"content": "mapped"})
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=msg)],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )
    with patch.object(provider_mod, "OpenAI", mock_openai):
        provider = _provider(mock_openai)
        resp = provider.generate_chat(messages=[{"role": "user", "content": "hi"}])
    assert resp.text == "mapped"


def test_generate_chat_text_parse_failure_is_contained(caplog):
    # choices present but indexing the message raises -> warning, empty text.
    class _BadChoices(list):
        def __getitem__(self, i):
            raise RuntimeError("choice boom")

        def __bool__(self):
            return True

    mock_openai = MagicMock()
    client = mock_openai.return_value
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=_BadChoices(),
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )
    with patch.object(provider_mod, "OpenAI", mock_openai):
        provider = _provider(mock_openai)
        resp = provider.generate_chat(messages=[{"role": "user", "content": "hi"}])
    assert resp.text == ""
    assert any("chat text parse failed" in r.message for r in caplog.records)


# --- stream_chat --------------------------------------------------------------


def test_stream_chat_yields_text_and_usage():
    mock_openai = MagicMock()
    client = mock_openai.return_value
    chunks = [
        SimpleNamespace(
            usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(content="Hel"))]
        ),
        SimpleNamespace(usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(content="lo"))]),
        SimpleNamespace(usage=None, choices=[]),  # no choices -> skipped
        SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3), choices=[]
        ),
    ]
    client.chat.completions.create.return_value = iter(chunks)
    with patch.object(provider_mod, "OpenAI", mock_openai):
        provider = _provider(mock_openai)
        out = list(
            provider.stream_chat(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2,
                max_completion_tokens=16,
            )
        )
    texts = [t for t, u in out if u is None]
    usages = [u for t, u in out if u is not None]
    assert "".join(texts) == "Hello"
    assert usages and usages[0].total_tokens_reported == 3


def test_stream_chat_temperature_retry():
    mock_openai = MagicMock()
    client = mock_openai.return_value
    client.chat.completions.create.side_effect = [
        Exception("temperature not supported"),
        iter(
            [
                SimpleNamespace(
                    usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(content="x"))]
                )
            ]
        ),
    ]
    with patch.object(provider_mod, "OpenAI", mock_openai):
        provider = _provider(mock_openai)
        out = list(
            provider.stream_chat(messages=[{"role": "user", "content": "hi"}], temperature=0.9)
        )
    assert [t for t, u in out if u is None] == ["x"]
    assert client.chat.completions.create.call_count == 2


def test_stream_chat_non_temperature_error_reraises():
    mock_openai = MagicMock()
    client = mock_openai.return_value
    client.chat.completions.create.side_effect = RuntimeError("stream exploded")
    with patch.object(provider_mod, "OpenAI", mock_openai):
        provider = _provider(mock_openai)
        try:
            list(provider.stream_chat(messages=[{"role": "user", "content": "hi"}]))
            raise AssertionError("expected RuntimeError")
        except RuntimeError as exc:
            assert "stream exploded" in str(exc)


def test_stream_chat_chunk_parse_failure_is_contained(caplog):
    class _BadChunk:
        usage = None

        @property
        def choices(self):
            raise RuntimeError("chunk boom")

    mock_openai = MagicMock()
    client = mock_openai.return_value
    client.chat.completions.create.return_value = iter([_BadChunk()])
    with patch.object(provider_mod, "OpenAI", mock_openai):
        provider = _provider(mock_openai)
        out = list(provider.stream_chat(messages=[{"role": "user", "content": "hi"}]))
    assert out == []
    assert any("stream chunk parse failed" in r.message for r in caplog.records)


# --- generate_response (kwargs + SDK fallbacks) -------------------------------


def _ok_response(text="result"):
    return SimpleNamespace(
        output_text=text,
        usage=SimpleNamespace(input_tokens=1, output_tokens=2, total_tokens=3),
    )


def test_generate_response_sets_all_optional_kwargs():
    mock_openai = MagicMock()
    client = mock_openai.return_value
    client.responses.create.return_value = _ok_response()
    with patch.object(provider_mod, "OpenAI", mock_openai):
        provider = _provider(mock_openai)
        resp = provider.generate_response(
            model="m",
            system_prompt="sys",
            user_prompt="usr",
            max_output_tokens=64,
            reasoning_effort="low",
            require_json_object=True,
            tools=[{"type": "function"}],
            temperature=0.3,
        )
    kwargs = client.responses.create.call_args.kwargs
    assert kwargs["reasoning"] == {"effort": "low"}
    assert kwargs["tools"] == [{"type": "function"}]
    assert kwargs["text"] == {"format": {"type": "json_object"}}
    assert kwargs["temperature"] == 0.3
    assert resp.text == "result"


def test_generate_response_input_fallback_to_flat_string():
    mock_openai = MagicMock()
    client = mock_openai.return_value
    client.responses.create.side_effect = [
        Exception("Invalid 'input' value"),
        _ok_response("flat ok"),
    ]
    with patch.object(provider_mod, "OpenAI", mock_openai):
        provider = _provider(mock_openai)
        resp = provider.generate_response(model=None, system_prompt="sys", user_prompt="usr")
    second_kwargs = client.responses.create.call_args_list[1].kwargs
    assert second_kwargs["input"] == "sys\n\nusr"
    assert resp.text == "flat ok"


def test_generate_response_text_format_fallback():
    mock_openai = MagicMock()
    client = mock_openai.return_value
    client.responses.create.side_effect = [
        Exception("Unknown parameter: 'text.format'"),
        _ok_response("no json fmt"),
    ]
    with patch.object(provider_mod, "OpenAI", mock_openai):
        provider = _provider(mock_openai)
        resp = provider.generate_response(
            model=None, system_prompt="sys", user_prompt="usr", require_json_object=True
        )
    second_kwargs = client.responses.create.call_args_list[1].kwargs
    assert "text" not in second_kwargs
    assert resp.text == "no json fmt"


def test_generate_response_other_error_reraises():
    mock_openai = MagicMock()
    client = mock_openai.return_value
    client.responses.create.side_effect = RuntimeError("responses exploded")
    with patch.object(provider_mod, "OpenAI", mock_openai):
        provider = _provider(mock_openai)
        try:
            provider.generate_response(model=None, system_prompt=None, user_prompt="usr")
            raise AssertionError("expected RuntimeError")
        except RuntimeError as exc:
            assert "responses exploded" in str(exc)
