"""
Copyright (c) 2025-2026 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.llm_model.providers.openai_provider import OpenAILLMProvider


def test_generate_response_sets_client_and_request_timeout():
    mock_openai = MagicMock()
    mock_client = mock_openai.return_value
    mock_client.responses.create.return_value = SimpleNamespace(
        output_text='{"ok": true}',
        usage=SimpleNamespace(input_tokens=3, output_tokens=4, total_tokens=7),
    )

    with patch("app.llm_model.providers.openai_provider.OpenAI", mock_openai):
        provider = OpenAILLMProvider(api_key="test-key", default_model="gpt-5-mini", timeout_s=12.5)
        response = provider.generate_response(
            model=None,
            system_prompt="system",
            user_prompt="user",
            max_output_tokens=64,
            require_json_object=True,
        )

    mock_openai.assert_called_once_with(api_key="test-key", timeout=12.5)
    mock_client.responses.create.assert_called_once()
    assert mock_client.responses.create.call_args.kwargs["timeout"] == 12.5
    assert response.text == '{"ok": true}'


def test_generate_chat_sets_request_timeout():
    mock_openai = MagicMock()
    mock_client = mock_openai.return_value
    mock_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=4, total_tokens=7),
    )

    with patch("app.llm_model.providers.openai_provider.OpenAI", mock_openai):
        provider = OpenAILLMProvider(api_key="test-key", default_model="gpt-5.5", timeout_s=22.0)
        response = provider.generate_chat(messages=[{"role": "user", "content": "hi"}])

    mock_client.chat.completions.create.assert_called_once()
    assert mock_client.chat.completions.create.call_args.kwargs["timeout"] == 22.0
    assert response.text == "hello"
