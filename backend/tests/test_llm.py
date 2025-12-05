"""



Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.

"""

"""
Tests for LLM integration.
"""

import pytest
from unittest.mock import patch, MagicMock
from app.core.llm import LLMProvider, get_llm_provider, generate_chat_response


@pytest.fixture
def mock_openai_key():
    """Mock OpenAI API key for testing."""
    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key-123"}):
        yield


def test_llm_provider_initialization(mock_openai_key):
    """Test LLM provider initialization."""
    with patch("app.core.llm.ChatOpenAI") as mock_chat:
        mock_chat.return_value = MagicMock()
        provider = LLMProvider()
        assert provider is not None


def test_llm_provider_without_key():
    """Test LLM provider without API key."""
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="OpenAI API key"):
            LLMProvider()


@patch("app.core.llm.ChatOpenAI")
def test_generate_response(mock_chat, mock_openai_key):
    """Test response generation."""
    # Mock the LLM response
    mock_response = MagicMock()
    mock_response.content = "Hello! How can I help you?"
    mock_response.usage_metadata = {"total_tokens": 25}
    mock_chat.return_value.invoke.return_value = mock_response
    
    # Test response generation
    result = generate_chat_response("Hello, world!")
    
    assert result["success"] is True
    assert "Hello! How can I help you?" in result["response"]
    assert result["tokens_used"] == 25


@patch("app.core.llm.ChatOpenAI")
def test_generate_response_with_history(mock_chat, mock_openai_key):
    """Test response generation with conversation history."""
    # Mock the LLM response
    mock_response = MagicMock()
    mock_response.content = "I remember our previous conversation!"
    mock_response.usage_metadata = {"total_tokens": 30}
    mock_chat.return_value.invoke.return_value = mock_response
    
    # Test with conversation history
    history = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"}
    ]
    
    result = generate_chat_response("What did I say before?", history)
    
    assert result["success"] is True
    assert "I remember our previous conversation!" in result["response"]


@patch("app.core.llm.ChatOpenAI")
def test_llm_error_handling(mock_chat, mock_openai_key):
    """Test LLM error handling."""
    # Mock an error
    mock_chat.return_value.invoke.side_effect = Exception("API Error")
    
    result = generate_chat_response("Hello")
    
    assert result["success"] is False
    assert "error" in result
    assert "API Error" in result["response"]


def test_get_llm_provider_singleton(mock_openai_key):
    """Test that get_llm_provider returns a singleton."""
    with patch("app.core.llm.ChatOpenAI"):
        provider1 = get_llm_provider()
        provider2 = get_llm_provider()
        assert provider1 is provider2
