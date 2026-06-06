"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Tests for main FastAPI application.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root_endpoint():
    """Test root endpoint."""
    response = client.get("/")
    assert response.status_code == 200


def test_health_endpoint():
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data and isinstance(data["status"], str)
    assert "service" in data and isinstance(data["service"], str)
    assert "version" in data and isinstance(data["version"], str)
    assert "dependencies" in data and isinstance(data["dependencies"], dict)


def test_api_docs():
    """Test API documentation endpoint."""
    response = client.get("/api/docs")
    assert response.status_code == 200


def test_redoc():
    """Test ReDoc documentation endpoint."""
    response = client.get("/api/redoc")
    assert response.status_code == 200


@patch("app.api.chat.get_llm_client")
def test_chat_stream_contract(mock_get_llm_client):
    """Streaming endpoint returns plain text tokens and completion marker."""
    class _FakeClient:
        @staticmethod
        def stream_chat(**_kwargs):
            yield "Hello", None
            yield " world", None

    mock_get_llm_client.return_value = _FakeClient()
    response = client.post("/chat/stream", json={"message": "hi"})
    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("text/plain")
    body = response.text
    assert "Hello world" in body
    assert "::event: done" in body
