"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for app.sleep.cycle.

Covers the sleep router's contract endpoints, the start/lock branching (mocked),
and the worker's orchestration skeleton on an empty database (no projects), which
verifies the lock is always released via the finally block without any LLM,
embedding, or FAISS calls.
"""

import app.sleep.cycle as cycle
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(cycle.router)
    return TestClient(app)


def test_sleep_cycle_stub_endpoint(client):
    resp = client.post("/sleep_cycle", json={"project_id": "p1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["items_cleaned"] == 0
    assert "not yet implemented" in body["response"]


def test_sleep_status_shape(client):
    resp = client.get("/sleep/status")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"sleeping", "since", "lock_path"}
    assert isinstance(body["sleeping"], bool)


def test_sleep_start_when_idle(client, monkeypatch):
    monkeypatch.setattr(cycle, "is_sleeping", lambda: False)
    monkeypatch.setattr(cycle, "start_sleep_cycle_async", lambda: True)
    resp = client.post("/sleep/start")
    assert resp.status_code == 200
    assert resp.json()["status"] == "sleep cycle started"


def test_sleep_start_when_already_sleeping(client, monkeypatch):
    monkeypatch.setattr(cycle, "is_sleeping", lambda: True)
    resp = client.post("/sleep/start")
    assert resp.status_code == 423


def test_sleep_cycle_health(client):
    resp = client.get("/sleep_cycle/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "sleep_cycle"
    assert "features" in body


def test_worker_releases_lock_on_empty_db(db, monkeypatch):
    calls = {"engage": 0, "release": 0}
    monkeypatch.setattr(
        cycle, "engage_lock", lambda: calls.__setitem__("engage", calls["engage"] + 1)
    )
    monkeypatch.setattr(
        cycle, "release_lock", lambda: calls.__setitem__("release", calls["release"] + 1)
    )

    # Empty DB -> no projects -> worker should be a quick, side-effect-free no-op.
    cycle._sleep_cycle_worker()

    assert calls["engage"] == 1
    assert calls["release"] == 1
