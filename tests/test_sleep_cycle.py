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

from types import SimpleNamespace

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


def test_worker_runs_full_pipeline_and_releases(monkeypatch):
    # Drive the orchestrator with every stage faked so we exercise the flush ->
    # backfill -> per-project pipeline -> release ordering without real I/O.
    order = []
    monkeypatch.setattr(cycle, "engage_lock", lambda: order.append("engage"))
    monkeypatch.setattr(cycle, "release_lock", lambda: order.append("release"))
    monkeypatch.setattr(cycle, "_flush_active_pairs", lambda stats: order.append("flush"))
    monkeypatch.setattr(cycle, "_backfill_daily_md", lambda rows, stats: order.append("backfill"))
    monkeypatch.setattr(
        cycle, "_run_project_summary_pipeline", lambda p, stats: order.append(f"pipe:{p.id}")
    )

    class _S:
        def __enter__(self):
            return self

        def __exit__(self, *e):
            return False

        def exec(self, _q):
            return SimpleNamespace(all=lambda: [SimpleNamespace(id="pA"), SimpleNamespace(id="pB")])

    monkeypatch.setattr(cycle, "get_session", lambda: _S())

    cycle._sleep_cycle_worker()

    assert order == ["engage", "flush", "backfill", "pipe:pA", "pipe:pB", "release"]


def test_worker_project_query_failure_uses_empty_rows(monkeypatch):
    monkeypatch.setattr(cycle, "engage_lock", lambda: None)
    monkeypatch.setattr(cycle, "release_lock", lambda: None)
    monkeypatch.setattr(cycle, "_flush_active_pairs", lambda stats: None)
    backfilled = []
    monkeypatch.setattr(cycle, "_backfill_daily_md", lambda rows, stats: backfilled.append(rows))
    monkeypatch.setattr(
        cycle, "get_session", lambda: (_ for _ in ()).throw(RuntimeError("db boom"))
    )
    cycle._sleep_cycle_worker()
    assert backfilled == [[]]  # query failed -> empty rows


def test_worker_fatal_failure_still_releases(monkeypatch, caplog):
    monkeypatch.setattr(cycle, "engage_lock", lambda: None)
    released = []
    monkeypatch.setattr(cycle, "release_lock", lambda: released.append(True))
    monkeypatch.setattr(
        cycle, "_flush_active_pairs", lambda stats: (_ for _ in ()).throw(RuntimeError("fatal"))
    )
    cycle._sleep_cycle_worker()
    assert released == [True]
    assert any("[SLEEP][ERROR]" in r.message for r in caplog.records)


def test_worker_release_failure_logged(monkeypatch, caplog):
    monkeypatch.setattr(cycle, "engage_lock", lambda: None)
    monkeypatch.setattr(cycle, "_flush_active_pairs", lambda stats: None)
    monkeypatch.setattr(cycle, "_backfill_daily_md", lambda rows, stats: None)
    monkeypatch.setattr(
        cycle, "get_session", lambda: (_ for _ in ()).throw(RuntimeError("db boom"))
    )
    monkeypatch.setattr(
        cycle, "release_lock", lambda: (_ for _ in ()).throw(RuntimeError("release boom"))
    )
    cycle._sleep_cycle_worker()
    assert any("finalize failed" in r.message for r in caplog.records)


def test_start_sleep_cycle_async_delegates(monkeypatch):
    captured = {}

    def _runner(worker):
        captured["worker"] = worker
        return True

    monkeypatch.setattr(cycle, "start_sleep_cycle_runner", _runner)
    assert cycle.start_sleep_cycle_async() is True
    assert captured["worker"] is cycle._sleep_cycle_worker


# --- endpoint error / remaining branches ----------------------------------


def test_sleep_cycle_endpoint_error_path(client, monkeypatch):
    monkeypatch.setattr(
        cycle, "get_memory_manager", lambda: (_ for _ in ()).throw(RuntimeError("mem boom"))
    )
    resp = client.post("/sleep_cycle", json={"project_id": "p1"})
    # handle_memory_error maps to 507 Insufficient Storage.
    assert resp.status_code == 507


def test_sleep_status_error_returns_500(client, monkeypatch):
    monkeypatch.setattr(cycle, "is_sleeping", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    resp = client.get("/sleep/status")
    assert resp.status_code == 500
    assert "error" in resp.json()


def test_sleep_status_sleeping_includes_since(client, monkeypatch):
    monkeypatch.setattr(cycle, "is_sleeping", lambda: True)
    monkeypatch.setattr(cycle, "since", lambda: 0)
    resp = client.get("/sleep/status")
    assert resp.status_code == 200
    assert resp.json()["since"] is not None


def test_sleep_start_not_started_returns_423(client, monkeypatch):
    monkeypatch.setattr(cycle, "is_sleeping", lambda: False)
    monkeypatch.setattr(cycle, "start_sleep_cycle_async", lambda: False)
    resp = client.post("/sleep/start")
    assert resp.status_code == 423


def test_sleep_start_error_returns_500(client, monkeypatch):
    monkeypatch.setattr(cycle, "is_sleeping", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    resp = client.post("/sleep/start")
    assert resp.status_code == 500


def test_sleep_unlock_happy(client, monkeypatch):
    monkeypatch.setattr(cycle, "release_lock", lambda: None)
    resp = client.post("/sleep/unlock")
    assert resp.status_code == 200 and resp.json()["status"] == "unlocked"


def test_sleep_unlock_error_returns_500(client, monkeypatch):
    monkeypatch.setattr(cycle, "release_lock", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    resp = client.post("/sleep/unlock")
    assert resp.status_code == 500


def test_sleep_cycle_status_happy(client, monkeypatch):
    monkeypatch.setattr(
        cycle, "get_memory_manager", lambda: SimpleNamespace(get_memory_stats=lambda: {"k": "v"})
    )
    resp = client.get("/sleep_cycle/status")
    assert resp.status_code == 200 and resp.json()["status"] == "stub"


def test_sleep_cycle_status_error_returns_500(client, monkeypatch):
    monkeypatch.setattr(
        cycle, "get_memory_manager", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    resp = client.get("/sleep_cycle/status")
    assert resp.status_code == 500


def test_manual_cleanup_happy(client, monkeypatch):
    monkeypatch.setattr(
        cycle,
        "get_memory_manager",
        lambda: SimpleNamespace(cleanup_old_memories=lambda **k: {"items_cleaned": 0}),
    )
    resp = client.post("/sleep_cycle/cleanup?project_id=p1&retention_days=15")
    assert resp.status_code == 200 and resp.json()["retention_days"] == 15


def test_manual_cleanup_error_path(client, monkeypatch):
    monkeypatch.setattr(
        cycle, "get_memory_manager", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    resp = client.post("/sleep_cycle/cleanup")
    assert resp.status_code == 507


def test_get_cleanup_schedule_happy(client):
    resp = client.get("/sleep_cycle/schedule")
    assert resp.status_code == 200 and resp.json()["status"] == "stub"


def test_get_cleanup_schedule_error_returns_500(client, monkeypatch):
    # The body only builds a static response; force the first JSONResponse to
    # raise so the error handler (which builds a second one) runs.
    real = cycle.JSONResponse

    def _raising(*args, **kwargs):
        if kwargs.get("status_code") == 200:
            raise RuntimeError("render boom")
        return real(*args, **kwargs)

    monkeypatch.setattr(cycle, "JSONResponse", _raising)
    resp = client.get("/sleep_cycle/schedule")
    assert resp.status_code == 500


def test_set_cleanup_schedule_happy(client):
    resp = client.post("/sleep_cycle/schedule?enabled=true&frequency=weekly")
    assert resp.status_code == 200
    assert resp.json()["requested_schedule"]["frequency"] == "weekly"


def test_set_cleanup_schedule_error_path(client, monkeypatch):
    monkeypatch.setattr(
        cycle.request_logger,
        "log_request",
        lambda **k: (_ for _ in ()).throw(RuntimeError("log boom")),
    )
    resp = client.post("/sleep_cycle/schedule")
    assert resp.status_code == 507


def test_sleep_cycle_health_error_returns_503(client, monkeypatch):
    monkeypatch.setattr(
        cycle, "get_memory_manager", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    resp = client.get("/sleep_cycle/health")
    assert resp.status_code == 503
