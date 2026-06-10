"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""Unit tests for the local agent-memory search router."""

from types import SimpleNamespace

import pytest
from app.agent_interface import router as agent_router
from app.agent_interface.models import AgentMemorySearchResponse, AgentMemorySnippet
from app.agent_interface.parser import SnippetParseError
from app.security.agent_tokens import AgentAuthorizationResult
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Mount only the agent-interface router for endpoint contract tests."""
    app = FastAPI()
    app.include_router(agent_router.router)
    return TestClient(app)


def _project(project_id: str = "p1"):
    return SimpleNamespace(id=project_id)


def _search_response(*, model: str | None = None) -> AgentMemorySearchResponse:
    return AgentMemorySearchResponse(
        project_name="Project Syx",
        project_id="p1",
        category="SYNTHESIS",
        query="memory search",
        model=model,
        snippet_count=1,
        bounded_result_count=0,
        unbounded_result_count=1,
        snippets=[
            AgentMemorySnippet(
                snippet_number=1,
                result_mode="unbounded_chunk_group",
                text="retrieved memory",
            )
        ],
    )


def _patch_ready(monkeypatch, *, auth=None, sleeping=False, retrieved=None):
    monkeypatch.setattr(agent_router, "resolve_project_name", lambda _name: _project())
    monkeypatch.setattr(
        agent_router,
        "authorize_agent_token",
        lambda _project_id, _token: auth or AgentAuthorizationResult(authorized=True),
    )
    monkeypatch.setattr(agent_router, "is_sleeping", lambda: sleeping)
    monkeypatch.setattr(
        agent_router,
        "retrieve_agent_memory",
        retrieved
        or (lambda **_kwargs: (_search_response(model=_kwargs.get("model")), "raw ctx", [])),
    )


def test_agent_memory_search_requires_agent_token(client, caplog):
    # Missing token is rejected before project lookup or retrieval.
    response = client.post(
        "/agent/memory/search",
        json={"project_name": "Project Syx", "query": "memory search"},
    )

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized", "message": "Missing agent token."}
    assert any("missing agent_token" in record.message for record in caplog.records)


def test_agent_memory_search_requires_project_name(client):
    response = client.post(
        "/agent/memory/search",
        json={"agent_token": "tok", "project_name": " ", "query": "memory search"},
    )

    assert response.status_code == 400
    assert response.json()["message"] == "project_name is required."


def test_agent_memory_search_requires_query(client):
    response = client.post(
        "/agent/memory/search",
        json={"agent_token": "tok", "project_name": "Project Syx", "query": ""},
    )

    assert response.status_code == 400
    assert response.json()["message"] == "query is required."


def test_agent_memory_search_unknown_project(client, monkeypatch):
    monkeypatch.setattr(agent_router, "resolve_project_name", lambda _name: None)

    response = client.post(
        "/agent/memory/search",
        json={"agent_token": "tok", "project_name": "Missing", "query": "memory search"},
    )

    assert response.status_code == 404
    assert response.json()["error"] == "project_not_found"
    assert response.json()["project_name"] == "Missing"


def test_agent_memory_search_forbidden_token(client, monkeypatch):
    _patch_ready(
        monkeypatch,
        auth=AgentAuthorizationResult(
            authorized=False,
            forbidden=True,
            message="not allowed",
        ),
    )

    response = client.post(
        "/agent/memory/search",
        json={"agent_token": "tok", "project_name": "Project Syx", "query": "memory search"},
    )

    assert response.status_code == 403
    assert response.json()["message"] == "not allowed"


def test_agent_memory_search_unauthorized_token(client, monkeypatch):
    _patch_ready(
        monkeypatch,
        auth=AgentAuthorizationResult(authorized=False, message="bad token"),
    )

    response = client.post(
        "/agent/memory/search",
        json={"agent_token": "tok", "project_name": "Project Syx", "query": "memory search"},
    )

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized", "message": "bad token"}


def test_agent_memory_search_sleep_lock(client, monkeypatch):
    _patch_ready(monkeypatch, sleeping=True)

    response = client.post(
        "/agent/memory/search",
        json={"agent_token": "tok", "project_name": "Project Syx", "query": "memory search"},
    )

    assert response.status_code == 423
    body = response.json()
    assert body["error"] == "memory_locked"
    assert body["project_id"] == "p1"
    assert body["retryable"] is True


def test_agent_memory_search_success_writes_debug(client, monkeypatch):
    debug_calls = []
    _patch_ready(monkeypatch)
    monkeypatch.setattr(
        agent_router,
        "write_agent_debug_files",
        lambda **kwargs: debug_calls.append(kwargs),
    )

    response = client.post(
        "/agent/memory/search",
        json={
            "agent_token": "tok",
            "project_name": "Project Syx",
            "query": "memory search",
            "category": "synthesis",
            "model": " model-x ",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "model-x"
    assert body["snippet_count"] == 1
    assert debug_calls[0]["raw_context"] == "raw ctx"
    assert debug_calls[0]["response_payload"]["snippets"][0]["text"] == "retrieved memory"


def test_agent_memory_search_snippet_parse_error_writes_debug(client, monkeypatch, caplog):
    def _raise_parse(**_kwargs):
        raise SnippetParseError("bad block", raw_context="raw bad context")

    debug_calls = []
    _patch_ready(monkeypatch, retrieved=_raise_parse)
    monkeypatch.setattr(
        agent_router,
        "write_agent_debug_files",
        lambda **kwargs: debug_calls.append(kwargs),
    )

    response = client.post(
        "/agent/memory/search",
        json={"agent_token": "tok", "project_name": "Project Syx", "query": "memory search"},
    )

    assert response.status_code == 500
    assert response.json()["error"] == "snippet_parse_failed"
    assert debug_calls[0]["raw_context"] == "raw bad context"
    assert debug_calls[0]["error_payload"]["retryable"] is False
    assert any("snippet parse failed" in record.message for record in caplog.records)


def test_agent_memory_search_generic_failure(client, monkeypatch, caplog):
    def _raise_generic(**_kwargs):
        raise RuntimeError("retrieval down")

    _patch_ready(monkeypatch, retrieved=_raise_generic)

    response = client.post(
        "/agent/memory/search",
        json={"agent_token": "tok", "project_name": "Project Syx", "query": "memory search"},
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": "agent_memory_search_failed",
        "message": "Agent memory search failed.",
    }
    assert any("retrieval down" in record.message for record in caplog.records)


def test_optional_str_normalizes_values():
    assert agent_router._optional_str(None) is None
    assert agent_router._optional_str("  ") is None
    assert agent_router._optional_str(" model-x ") == "model-x"
    assert agent_router._optional_str(123) == "123"
