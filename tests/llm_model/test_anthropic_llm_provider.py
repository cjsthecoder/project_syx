"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.llm_model.providers.anthropic_provider.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import app.llm_model.providers.anthropic_provider as provider_mod
from app.llm_model.providers.anthropic_provider import (
    AnthropicLLMProvider,
    _as_mapping,
    _content_text,
    _split_messages,
    _usage_from_message,
)


def _provider(mock_anthropic):
    return AnthropicLLMProvider(api_key="sk-ant", default_model="claude-default", timeout_s=12.0)


def _message(text="ok"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=2, output_tokens=3),
    )


def test_as_mapping_uses_model_dump():
    obj = SimpleNamespace(model_dump=lambda mode="python": {"x": 2})
    assert _as_mapping(obj) == {"x": 2}


def test_content_text_collects_text_blocks_only():
    content = [
        SimpleNamespace(type="text", text="hello "),
        SimpleNamespace(type="tool_use", text="ignored"),
        {"type": "text", "text": "world"},
    ]
    assert _content_text(content) == "hello world"


def test_usage_from_message_preserves_server_tool_use():
    usage = SimpleNamespace(
        input_tokens=10,
        output_tokens=5,
        server_tool_use=SimpleNamespace(web_search_requests=1),
    )
    out = _usage_from_message(usage)
    assert out.prompt_tokens_reported == 10
    assert out.completion_tokens_reported == 5
    assert out.total_tokens_reported == 15
    assert "server_tool_use" in (out.extra_usage or {})


def test_split_messages_moves_system_content_to_system_parameter():
    system, messages = _split_messages(
        [
            {"role": "system", "content": "sys 1"},
            {"role": "user", "content": "hello"},
            {"role": "tool", "content": "ignored"},
            {"role": "system", "content": "sys 2"},
        ]
    )
    assert system == "sys 1\n\nsys 2"
    assert messages == [{"role": "user", "content": "hello"}]


def test_generate_chat_calls_anthropic_messages_api():
    mock_anthropic = MagicMock()
    client = mock_anthropic.return_value
    client.messages.create.return_value = _message("chat ok")

    with patch.object(provider_mod, "Anthropic", mock_anthropic):
        provider = _provider(mock_anthropic)
        response = provider.generate_chat(
            messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
            ],
            model="claude-sonnet-4-6",
            temperature=2.0,
            max_completion_tokens=64,
        )

    mock_anthropic.assert_called_once_with(api_key="sk-ant", timeout=12.0)
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["system"] == "sys"
    assert kwargs["messages"] == [{"role": "user", "content": "hi"}]
    assert kwargs["temperature"] == 1.0
    assert kwargs["max_tokens"] == 64
    assert response.text == "chat ok"


def test_generate_response_prompts_json_when_required():
    mock_anthropic = MagicMock()
    client = mock_anthropic.return_value
    client.messages.create.return_value = _message('{"ok": true}')

    with patch.object(provider_mod, "Anthropic", mock_anthropic):
        provider = _provider(mock_anthropic)
        response = provider.generate_response(
            model=None,
            system_prompt="sys",
            user_prompt="return json",
            max_output_tokens=32,
            reasoning_effort="low",
            require_json_object=True,
            temperature=0.5,
        )

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["system"] == "sys"
    assert kwargs["thinking"] == {"type": "adaptive", "effort": "low"}
    assert "Return only a valid JSON object" in kwargs["messages"][0]["content"]
    assert response.text == '{"ok": true}'


def test_generate_response_research_enables_anthropic_web_search_tool():
    mock_anthropic = MagicMock()
    client = mock_anthropic.return_value
    client.messages.create.return_value = _message("research ok")

    with patch.object(provider_mod, "Anthropic", mock_anthropic):
        provider = _provider(mock_anthropic)
        response = provider.generate_response_research(
            model="claude-sonnet-4-6",
            system_prompt=None,
            user_prompt="research this",
            max_output_tokens=32,
        )

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["tools"] == [{"type": "web_search_20250305", "name": "web_search"}]
    assert response.text == "research ok"


def test_stream_chat_yields_text_and_final_usage():
    mock_anthropic = MagicMock()
    client = mock_anthropic.return_value
    client.messages.create.return_value = iter(
        [
            SimpleNamespace(
                type="message_start",
                message=SimpleNamespace(usage=SimpleNamespace(input_tokens=7, output_tokens=0)),
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(text="Hel"),
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(text="lo"),
            ),
            SimpleNamespace(
                type="message_delta",
                usage=SimpleNamespace(input_tokens=0, output_tokens=4),
            ),
        ]
    )

    with patch.object(provider_mod, "Anthropic", mock_anthropic):
        provider = _provider(mock_anthropic)
        out = list(provider.stream_chat(messages=[{"role": "user", "content": "hi"}]))

    assert [text for text, usage in out if usage is None] == ["Hel", "lo"]
    usages = [usage for text, usage in out if usage is not None]
    assert usages and usages[0].completion_tokens_reported == 4
    assert usages[0].prompt_tokens_reported == 7


def test_temperature_retry_drops_temperature():
    mock_anthropic = MagicMock()
    client = mock_anthropic.return_value
    client.messages.create.side_effect = [Exception("temperature unsupported"), _message("ok")]

    with patch.object(provider_mod, "Anthropic", mock_anthropic):
        provider = _provider(mock_anthropic)
        response = provider.generate_chat(
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.4,
        )

    assert response.text == "ok"
    assert "temperature" not in client.messages.create.call_args_list[1].kwargs
