"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Contract tests for the small API routers (dream status, models) and the chat
prompt-debug helpers. These mount one router at a time and fake the only
boundaries (the request logger and the debug-file writer).
"""

import pytest
from app.api import chat_prompting as cp_module
from app.api import dream as dream_module
from app.api import llm_models as llm_models_module
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# /dream/status
# ---------------------------------------------------------------------------


@pytest.fixture
def dream_client():
    app = FastAPI()
    app.include_router(dream_module.router)
    return TestClient(app)


def test_dream_status_returns_no_dreams(dream_client):
    resp = dream_client.get("/dream/status")
    assert resp.status_code == 200
    assert resp.json() == {"has_dreams": False, "count": 0}


def test_dream_status_failure_returns_500(dream_client, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("logger down")

    monkeypatch.setattr(dream_module.request_logger, "log_request", boom)
    resp = dream_client.get("/dream/status")
    assert resp.status_code == 500
    assert "logger down" in resp.json()["error"]


# ---------------------------------------------------------------------------
# /models
# ---------------------------------------------------------------------------


@pytest.fixture
def models_client():
    app = FastAPI()
    app.include_router(llm_models_module.router)
    return TestClient(app)


def test_models_returns_whitelist(models_client):
    resp = models_client.get("/models")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["models"], list)
    assert isinstance(body["default"], str)
    assert body["default"] in body["models"]


# ---------------------------------------------------------------------------
# chat_prompting helpers
# ---------------------------------------------------------------------------


def test_estimate_tokens_handles_none():
    assert cp_module.estimate_tokens(None) == 0
    assert cp_module.estimate_tokens("hello world") > 0


def test_estimate_message_tokens_handles_none():
    assert cp_module.estimate_message_tokens(None) == 0
    assert cp_module.estimate_message_tokens([{"role": "user", "content": "hi"}]) >= 0


def test_dump_prompt_debug_noop_without_project(monkeypatch):
    called = []
    monkeypatch.setattr(cp_module, "write_debug_file", lambda *a, **k: called.append(a))
    cp_module.dump_prompt_debug(
        project_id=None,
        base_system_prompt="S",
        assistant_hint=None,
        rag_system_prompt=None,
        conversation_history=None,
        user_prompt="u",
        model="m",
    )
    assert called == []  # no project -> no write


def test_dump_prompt_debug_writes_all_sections(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        cp_module, "write_debug_file", lambda pid, path, body: captured.update(body=body)
    )
    cp_module.dump_prompt_debug(
        project_id="p1",
        base_system_prompt="SYS",
        assistant_hint="HINT",
        rag_system_prompt="RAG",
        conversation_history=[
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "system", "content": "sys-note"},  # exercises the "other role" branch
        ],
        user_prompt="now",
        model="gpt-test",
    )
    body = captured["body"]
    assert "USER:" in body and "ASSISTANT:" in body
    assert "SYSTEM:" in body  # non user/assistant role rendered uppercased
    assert "now" in body


def test_dump_prompt_debug_route_lookup_failure_logged(monkeypatch, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(cp_module, "write_debug_file", lambda *a, **k: None)

    def boom():
        raise RuntimeError("route ctx down")

    monkeypatch.setattr(cp_module, "get_route", boom)
    cp_module.dump_prompt_debug(
        project_id="p1",
        base_system_prompt="SYS",
        assistant_hint=None,
        rag_system_prompt=None,
        conversation_history=None,
        user_prompt="u",
        model="m",
    )
    assert any("failed reading route" in r.message for r in caplog.records)
