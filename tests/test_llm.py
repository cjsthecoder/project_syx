"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Tests for LLM integration.
"""

import pytest
from unittest.mock import patch, MagicMock
from app.core.llm import LLMProvider, get_llm_provider, generate_chat_response, generate_text_response
from app.llm_model.base import LLMResponse, LLMUsage


@pytest.fixture
def mock_openai_key():
    """Mock OpenAI API key for testing."""
    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key-123"}):
        yield


def test_llm_provider_initialization(mock_openai_key):
    """Test LLM provider initialization."""
    with patch("app.core.llm.validate_openai_key", return_value=True):
        provider = LLMProvider()
        assert provider is not None


def test_llm_provider_without_key():
    """Test LLM provider without API key."""
    with patch("app.core.llm.validate_openai_key", return_value=False):
        with pytest.raises(ValueError, match="OpenAI API key"):
            LLMProvider()


@patch("app.core.llm.get_llm_client")
def test_generate_response(mock_get_client, mock_openai_key):
    """Test response generation."""
    mock_client = MagicMock()
    mock_client.generate_chat.return_value = LLMResponse(
        text="Hello! How can I help you?",
        model="gpt-5.4",
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


@patch("app.core.llm.get_llm_client")
def test_generate_response_with_history(mock_get_client, mock_openai_key):
    """Test response generation with conversation history."""
    mock_client = MagicMock()
    mock_client.generate_chat.return_value = LLMResponse(
        text="I remember our previous conversation!",
        model="gpt-5.4",
        usage=LLMUsage(
            prompt_tokens_reported=20,
            completion_tokens_reported=10,
            total_tokens_reported=30,
            usage_is_estimate=False,
        ),
    )
    mock_get_client.return_value = mock_client
    
    # Test with conversation history
    history = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"}
    ]
    
    result = generate_chat_response("What did I say before?", history)
    
    assert result["success"] is True
    assert "I remember our previous conversation!" in result["response"]


@patch("app.core.llm.get_llm_client")
def test_llm_error_handling(mock_get_client, mock_openai_key):
    """Test LLM error handling."""
    mock_client = MagicMock()
    mock_client.generate_chat.side_effect = Exception("API Error")
    mock_get_client.return_value = mock_client
    
    result = generate_chat_response("Hello")
    
    assert result["success"] is False
    assert "error" in result
    assert "API Error" in result["response"]


@patch("app.core.llm.get_llm_client")
def test_generate_text_response(mock_get_client, mock_openai_key):
    """Test Responses API generation through core LLM helper."""
    mock_client = MagicMock()
    mock_client.generate_response.return_value = LLMResponse(
        text='{"answer": "ok"}',
        model="gpt-5.4",
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
        override_model="gpt-5.4",
        temperature_override=1.0,
        max_output_tokens=256,
        purpose="dream:test",
    )

    assert result.text == '{"answer": "ok"}'
    assert result.usage.total_tokens_reported == 13
    mock_client.generate_response.assert_called_once()


def test_get_llm_provider_singleton(mock_openai_key):
    """Test that get_llm_provider returns a singleton."""
    with patch("app.core.llm.validate_openai_key", return_value=True):
        provider1 = get_llm_provider()
        provider2 = get_llm_provider()
        assert provider1 is provider2
