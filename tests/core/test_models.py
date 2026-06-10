"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for Pydantic models.
"""


from app.core.models import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    HealthResponse,
    ProjectRequest,
    ProjectResponse,
    RAGRequest,
    RAGResponse,
    SleepCycleRequest,
    SleepCycleResponse,
)


def test_chat_request():
    """Test ChatRequest model."""
    request = ChatRequest(
        message="Hello, world!", project_id="test_project", conversation_id="conv_123"
    )
    assert request.message == "Hello, world!"
    assert request.project_id == "test_project"
    assert request.conversation_id == "conv_123"


def test_chat_response():
    """Test ChatResponse model."""
    response = ChatResponse(
        response="Hello! How can I help you?",
        conversation_id="conv_123",
        model_used="gpt-5",
        tokens_used=25,
    )
    assert response.response == "Hello! How can I help you?"
    assert response.success is True
    assert response.tokens_used == 25


def test_rag_request():
    """Test RAGRequest model."""
    request = RAGRequest(
        query="What is machine learning?", project_id="test_project", max_results=5
    )
    assert request.query == "What is machine learning?"
    assert request.max_results == 5


def test_rag_response():
    """Test RAGResponse model."""
    response = RAGResponse(
        response="Machine learning is a subset of AI...",
        sources=[{"title": "ML Guide", "url": "https://example.com"}],
        confidence=0.95,
    )
    assert response.response == "Machine learning is a subset of AI..."
    assert len(response.sources) == 1
    assert response.confidence == 0.95


def test_project_request():
    """Test ProjectRequest model."""
    request = ProjectRequest(project_id="new_project", project_name="My New Project")
    assert request.project_id == "new_project"
    assert request.project_name == "My New Project"


def test_project_response():
    """Test ProjectResponse model."""
    response = ProjectResponse(
        response="Switched to project 'My Project'",
        current_project="project_123",
        available_projects=["default", "project_123"],
    )
    assert response.response == "Switched to project 'My Project'"
    assert response.current_project == "project_123"
    assert "project_123" in response.available_projects


def test_sleep_cycle_request():
    """Test SleepCycleRequest model."""
    request = SleepCycleRequest(project_id="test_project", force_cleanup=True)
    assert request.project_id == "test_project"
    assert request.force_cleanup is True


def test_sleep_cycle_response():
    """Test SleepCycleResponse model."""
    response = SleepCycleResponse(
        response="Memory cleanup completed",
        items_cleaned=150,
        memory_usage_before="2.5GB",
        memory_usage_after="1.8GB",
    )
    assert response.response == "Memory cleanup completed"
    assert response.items_cleaned == 150
    assert response.memory_usage_before == "2.5GB"


def test_error_response():
    """Test ErrorResponse model."""
    error = ErrorResponse(
        error="Test error message", error_code="TEST_ERROR", details={"field": "test_field"}
    )
    assert error.success is False
    assert error.error == "Test error message"
    assert error.error_code == "TEST_ERROR"


def test_health_response():
    """Test HealthResponse model."""
    health = HealthResponse(
        status="healthy", service="syx-api", version="1.0.0", dependencies={"openai": "connected"}
    )
    assert health.status == "healthy"
    assert health.service == "syx-api"
    assert "openai" in health.dependencies
