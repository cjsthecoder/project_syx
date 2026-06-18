"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for LLM integration.
"""

from unittest.mock import MagicMock, patch

import pytest
from app.core import llm_service
from app.core.llm_service import (
    LLMProvider,
    _build_messages,
    generate_chat_response,
    generate_research_response,
    generate_text_response,
    get_llm_provider,
    reset_llm_provider,
)
from app.llm_model.base import LLMResponse, LLMUsage


class _FakeInstr:
    """Instrumentation stub that yields a real invocation id so the instrumented
    branches (start/end invocation, usage payloads) are actually exercised."""

    def __init__(self, *, inv_id="inv-1", end_raises=False):
        self.inv_id = inv_id
        self.end_raises = end_raises
        self.stages = []
        self.ended = []

    def record_stage(self, name, payload):
        self.stages.append((name, payload))

    def start_invocation(self, **kwargs):
        return self.inv_id

    def end_invocation(self, invocation_id, **kwargs):
        if self.end_raises:
            raise RuntimeError("end_invocation failed")
        self.ended.append((invocation_id, kwargs))


def _response_with_extra_usage(text="ok", model="gpt-5.5"):
    return LLMResponse(
        text=text,
        model=model,
        usage=LLMUsage(
            prompt_tokens_reported=10,
            completion_tokens_reported=5,
            total_tokens_reported=15,
            usage_is_estimate=False,
            extra_usage={"reasoning_tokens": 3},
        ),
    )


@pytest.fixture
def mock_openai_key():
    """Make the LLM provider construct without a real key.

    `validate_openai_key()` reads from the cached Settings object, not the live
    environment, so patching os.environ alone is not enough in a clean CI
    environment. Patch the validator directly and reset the provider singleton
    so the tests are hermetic regardless of whether a key is configured.
    """
    reset_llm_provider()
    with (
        patch.dict("os.environ", {"OPENAI_API_KEY": "test-key-123"}),
        patch("app.core.llm_service.validate_openai_key", return_value=True),
    ):
        yield
    reset_llm_provider()


def test_llm_provider_initialization(mock_openai_key):
    """Test LLM provider initialization."""
    with patch("app.core.llm_service.validate_openai_key", return_value=True):
        provider = LLMProvider()
        assert provider is not None


def test_llm_provider_without_key():
    """Test LLM provider without API key."""
    with patch("app.core.llm_service.validate_openai_key", return_value=False):
        with pytest.raises(ValueError, match="OpenAI API key"):
            LLMProvider()


@patch("app.core.llm_service.get_llm_client")
def test_generate_response(mock_get_client, mock_openai_key):
    """Test response generation."""
    mock_client = MagicMock()
    mock_client.generate_chat.return_value = LLMResponse(
        text="Hello! How can I help you?",
        model="gpt-5.5",
        usage=LLMUsage(
            prompt_tokens_reported=10,
            completion_tokens_reported=15,
            total_tokens_reported=25,
            usage_is_estimate=False,
        ),
    )
    mock_get_client.return_value = mock_client

    # Test response generation
    result = generate_chat_response("Hello, world!")

    assert result["success"] is True
    assert "Hello! How can I help you?" in result["response"]
    assert result["tokens_used"] == 25


@patch("app.core.llm_service.get_llm_client")
def test_generate_response_with_history(mock_get_client, mock_openai_key):
    """Test response generation with conversation history."""
    mock_client = MagicMock()
    mock_client.generate_chat.return_value = LLMResponse(
        text="I remember our previous conversation!",
        model="gpt-5.5",
        usage=LLMUsage(
            prompt_tokens_reported=20,
            completion_tokens_reported=10,
            total_tokens_reported=30,
            usage_is_estimate=False,
        ),
    )
    mock_get_client.return_value = mock_client

    # Test with conversation history
    history = [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi there!"}]

    result = generate_chat_response("What did I say before?", history)

    assert result["success"] is True
    assert "I remember our previous conversation!" in result["response"]


@patch("app.core.llm_service.get_llm_client")
def test_llm_error_handling(mock_get_client, mock_openai_key):
    """Test LLM error handling."""
    mock_client = MagicMock()
    mock_client.generate_chat.side_effect = Exception("API Error")
    mock_get_client.return_value = mock_client

    result = generate_chat_response("Hello")

    assert result["success"] is False
    assert "error" in result
    assert "API Error" in result["response"]


@patch("app.core.llm_service.get_llm_client")
def test_generate_text_response(mock_get_client, mock_openai_key):
    """Test Responses API generation through core LLM helper."""
    mock_client = MagicMock()
    mock_client.generate_response.return_value = LLMResponse(
        text='{"answer": "ok"}',
        model="gpt-5.5",
        usage=LLMUsage(
            prompt_tokens_reported=8,
            completion_tokens_reported=5,
            total_tokens_reported=13,
            usage_is_estimate=False,
        ),
    )
    mock_get_client.return_value = mock_client

    result = generate_text_response(
        "Summarize this",
        override_model="gpt-5.5",
        temperature_override=1.0,
        max_output_tokens=256,
        purpose="dream:test",
    )

    assert result.text == '{"answer": "ok"}'
    assert result.usage.total_tokens_reported == 13
    mock_client.generate_response.assert_called_once()


@patch("app.core.llm_service.get_llm_client")
def test_generate_research_response_uses_provider_research_boundary(
    mock_get_client, mock_openai_key
):
    """Test researched text generation through the provider-agnostic research method."""
    mock_client = MagicMock()
    mock_client.generate_response_research.return_value = LLMResponse(
        text="research blob",
        model="gpt-5.5",
        usage=LLMUsage(
            prompt_tokens_reported=8,
            completion_tokens_reported=5,
            total_tokens_reported=13,
            usage_is_estimate=False,
        ),
    )
    mock_get_client.return_value = mock_client

    result = generate_research_response(
        "Research this",
        override_model="gpt-5.5",
        temperature_override=1.0,
        max_output_tokens=256,
        purpose="dream:remote_research",
    )

    assert result.text == "research blob"
    mock_client.generate_response_research.assert_called_once()
    mock_client.generate_response.assert_not_called()


def test_get_llm_provider_singleton(mock_openai_key):
    """Test that get_llm_provider returns a singleton."""
    with patch("app.core.llm_service.validate_openai_key", return_value=True):
        provider1 = get_llm_provider()
        provider2 = get_llm_provider()
        assert provider1 is provider2


# --- _build_messages -------------------------------------------------------


def test_build_messages_full_order_and_role_filtering():
    messages = _build_messages(
        message="now",
        conversation_history=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "tool", "content": "ignored"},  # non-standard role dropped
        ],
        base_system_prompt="base",
        assistant_hint="hint",
        rag_system_prompt="rag ctx",
    )
    roles = [m["role"] for m in messages]
    assert roles == ["system", "assistant", "system", "user", "assistant", "user"]
    assert messages[0]["content"] == "base"
    assert messages[2]["content"] == "rag ctx"
    assert messages[-1]["content"] == "now"


# --- generate_response instrumented branches -------------------------------


def test_generate_response_records_full_instrumentation(mock_openai_key, monkeypatch):
    instr = _FakeInstr()
    monkeypatch.setattr(llm_service, "get_instrumentation", lambda: instr)
    client = MagicMock()
    client.generate_chat.return_value = _response_with_extra_usage()
    monkeypatch.setattr(llm_service, "get_llm_client", lambda: client)

    result = generate_chat_response("Hello", base_system_prompt="base", rag_system_prompt="ctx")
    assert result["success"] is True
    # The invocation was ended with a usage payload carrying extra_usage.
    assert instr.ended and instr.ended[0][1]["usage"]["extra_usage"] == {"reasoning_tokens": 3}


def test_generate_response_failure_finalizes_invocation(mock_openai_key, monkeypatch):
    instr = _FakeInstr()
    monkeypatch.setattr(llm_service, "get_instrumentation", lambda: instr)
    client = MagicMock()
    client.generate_chat.side_effect = RuntimeError("boom")
    monkeypatch.setattr(llm_service, "get_llm_client", lambda: client)

    result = generate_chat_response("Hello")
    assert result["success"] is False
    # The open invocation was still ended (with zeroed usage) on the failure path.
    assert instr.ended and instr.ended[0][1]["usage"]["total_tokens_reported"] == 0


def test_generate_response_finalize_error_is_logged(mock_openai_key, monkeypatch, caplog):
    instr = _FakeInstr(end_raises=True)
    monkeypatch.setattr(llm_service, "get_instrumentation", lambda: instr)
    client = MagicMock()
    client.generate_chat.side_effect = RuntimeError("boom")
    monkeypatch.setattr(llm_service, "get_llm_client", lambda: client)

    result = generate_chat_response("Hello")
    assert result["success"] is False
    assert any("failed ending invocation" in r.message for r in caplog.records)


# --- get_model_info / health_check ----------------------------------------


def test_get_model_info_shape(mock_openai_key):
    with patch("app.core.llm_service.validate_openai_key", return_value=True):
        info = LLMProvider().get_model_info()
    assert set(info.keys()) == {"model_name", "temperature", "max_tokens", "api_key_configured"}


def _empty_usage():
    return LLMUsage(
        prompt_tokens_reported=0,
        completion_tokens_reported=0,
        total_tokens_reported=0,
        usage_is_estimate=True,
    )


def test_health_check_healthy(mock_openai_key, monkeypatch):
    client = MagicMock()
    client.generate_chat.return_value = LLMResponse(
        text="pong", model="gpt-5.5", usage=_empty_usage()
    )
    monkeypatch.setattr(llm_service, "get_llm_client", lambda: client)
    with patch("app.core.llm_service.validate_openai_key", return_value=True):
        status = LLMProvider().health_check()
    assert status == {"status": "healthy", "model": "gpt-5.5"}


def test_health_check_no_response(mock_openai_key, monkeypatch):
    client = MagicMock()
    client.generate_chat.return_value = LLMResponse(
        text=None, model="gpt-5.5", usage=_empty_usage()
    )
    monkeypatch.setattr(llm_service, "get_llm_client", lambda: client)
    with patch("app.core.llm_service.validate_openai_key", return_value=True):
        status = LLMProvider().health_check()
    assert status["status"] == "unhealthy"
    assert status["error"] == "No response from model"


def test_get_llm_health_delegates_to_provider(mock_openai_key, monkeypatch):
    client = MagicMock()
    client.generate_chat.return_value = LLMResponse(
        text="pong", model="gpt-5.5", usage=_empty_usage()
    )
    monkeypatch.setattr(llm_service, "get_llm_client", lambda: client)
    with patch("app.core.llm_service.validate_openai_key", return_value=True):
        assert llm_service.get_llm_health()["status"] == "healthy"


def test_health_check_exception(mock_openai_key, monkeypatch):
    client = MagicMock()
    client.generate_chat.side_effect = RuntimeError("network down")
    monkeypatch.setattr(llm_service, "get_llm_client", lambda: client)
    with patch("app.core.llm_service.validate_openai_key", return_value=True):
        status = LLMProvider().health_check()
    assert status["status"] == "unhealthy"
    assert "network down" in status["error"]


# --- generate_text_response instrumented + failure -------------------------


def test_generate_text_response_records_instrumentation(mock_openai_key, monkeypatch):
    instr = _FakeInstr()
    monkeypatch.setattr(llm_service, "get_instrumentation", lambda: instr)
    client = MagicMock()
    client.generate_response.return_value = _response_with_extra_usage(text='{"ok": true}')
    monkeypatch.setattr(llm_service, "get_llm_client", lambda: client)

    result = generate_text_response("prompt", system_prompt="sys", purpose="dream:x")
    assert result.text == '{"ok": true}'
    assert instr.ended and instr.ended[0][1]["usage"]["extra_usage"] == {"reasoning_tokens": 3}


def test_generate_text_response_failure_finalizes_and_reraises(mock_openai_key, monkeypatch):
    instr = _FakeInstr()
    monkeypatch.setattr(llm_service, "get_instrumentation", lambda: instr)
    client = MagicMock()
    client.generate_response.side_effect = RuntimeError("text boom")
    monkeypatch.setattr(llm_service, "get_llm_client", lambda: client)

    with pytest.raises(RuntimeError, match="text boom"):
        generate_text_response("prompt", purpose="dream:x")
    assert instr.ended and instr.ended[0][1]["usage"]["total_tokens_reported"] == 0


def test_generate_text_response_finalize_error_is_logged(mock_openai_key, monkeypatch, caplog):
    instr = _FakeInstr(end_raises=True)
    monkeypatch.setattr(llm_service, "get_instrumentation", lambda: instr)
    client = MagicMock()
    client.generate_response.side_effect = RuntimeError("text boom")
    monkeypatch.setattr(llm_service, "get_llm_client", lambda: client)

    with pytest.raises(RuntimeError, match="text boom"):
        generate_text_response("prompt")
    assert any("failed ending invocation" in r.message for r in caplog.records)
