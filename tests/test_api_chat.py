"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Contract tests for the chat API router.

These cover request validation and the non-LLM endpoints (health, stats). The
full LLM chat pipeline is intentionally out of scope here; ``get_llm_health`` is
patched so health behavior is deterministic and offline.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import chat as chat_module


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(chat_module.router)
    return TestClient(app)


def test_chat_rejects_empty_message(client):
    resp = client.post("/chat", json={"message": ""})
    assert resp.status_code == 422


def test_chat_rejects_missing_message(client):
    resp = client.post("/chat", json={"project_id": "p1"})
    assert resp.status_code == 422


def test_chat_health_healthy(client, monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "get_llm_health",
        lambda: {"status": "healthy", "model": "gpt-test"},
    )
    resp = client.get("/chat/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["service"] == "chat"
    assert body["model"] == "gpt-test"


def test_chat_health_unhealthy(client, monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "get_llm_health",
        lambda: {"status": "unhealthy", "error": "no key"},
    )
    resp = client.get("/chat/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unhealthy"
    assert body["service"] == "chat"


def test_chat_stats_shape(client):
    resp = client.get("/chat/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"conversations", "messages", "memory_mode", "features"}
    assert body["memory_mode"] == "persistent"
