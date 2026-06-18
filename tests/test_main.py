"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for main FastAPI application.
"""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import patch

import app.main as main
import pytest
from app.main import _build_run_config, _collect_git_metadata, app
from fastapi import HTTPException
from fastapi.testclient import TestClient

client = TestClient(app)


# --- shared fakes -------------------------------------------------------------


class _FakeExec:
    """Stand-in for the object returned by Session.exec()."""

    def __init__(self, first=None, all_=None):
        self._first = first
        self._all = all_ or []

    def first(self):
        return self._first

    def all(self):
        return list(self._all)


class _FakeSession:
    """Context-manager session whose exec() returns a preset _FakeExec."""

    def __init__(self, *, first=None, all_=None):
        self._exec = _FakeExec(first=first, all_=all_)
        self.added = []
        self.committed = False

    def exec(self, *_args, **_kwargs):
        return self._exec

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _fake_settings():
    return SimpleNamespace(
        model_name="main-model",
        builder_model="builder-model",
        tagger_model="tagger-model",
        model_max_tokens=4096,
        base_top_k=8,
        retrieval_multiplier=3.0,
        embedding_model="embed-model",
        chunk_size=1000,
        chunk_overlap=100,
        enable_scheduler=True,
        sleep_cycle_hour=3,
        sleep_cycle_minute=30,
        verify_rag=True,
        force_rag_rebuild_on_startup=False,
        enable_dream=True,
        instrumentation_enabled=True,
        instrumentation_mode="full",
        instrumentation_run_id=None,
        instrumentation_runs_dir="/tmp/runs",
        instrumentation_prompt_tol_abs_tokens=50,
        instrumentation_prompt_tol_pct=0.1,
    )


def _fake_route_policy():
    return {
        "OTHER": SimpleNamespace(
            retrieval_multiplier=2.0,
            max_keep=5,
            min_score=0.4,
            expansion_max_before=1,
            expansion_max_after=2,
        )
    }


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
@patch("app.api.chat.validate_active_llm_key", return_value=True)
def test_chat_stream_contract(_mock_validate_active_llm_key, mock_get_llm_client):
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


# --- _build_run_config --------------------------------------------------------


def test_build_run_config_snapshot_shape():
    cfg = _build_run_config(_fake_settings(), _fake_route_policy(), "abc123", True)
    snap = cfg["config_snapshot"]
    assert snap["models_configured"] == {
        "provider": "openai",
        "main_model": "gpt-5.5",
        "builder_model": "gpt-5-mini",
        "tagger_model": "gpt-5-mini",
        "dream_model": "gpt-5.5",
    }
    assert snap["retrieval_static"]["base_top_k"] == 8
    assert snap["retrieval_static"]["embedding_model"] == "embed-model"
    assert snap["maintenance"]["sleep_cycle_hour"] == 3
    assert snap["maintenance"]["dream_enabled"] is True
    assert snap["instrumentation"]["mode"] == "full"
    assert snap["git_commit"] == "abc123"
    assert snap["git_dirty"] is True


def test_build_run_config_route_policy_snapshot():
    cfg = _build_run_config(_fake_settings(), _fake_route_policy(), "x", False)
    rp = cfg["config_snapshot"]["route_policy"]["OTHER"]
    assert rp["retrieval_multiplier"] == 2.0
    assert rp["max_keep"] == 5
    assert rp["min_score"] == 0.4
    assert rp["expansion"] == {"max_before": 1, "max_after": 2}


# --- _collect_git_metadata ----------------------------------------------------


def test_collect_git_metadata_success(monkeypatch):
    def _fake_run(cmd, **_kwargs):
        if "rev-parse" in cmd:
            return SimpleNamespace(returncode=0, stdout="deadbeef\n")
        return SimpleNamespace(returncode=0, stdout=" M file.py\n")

    monkeypatch.setattr(main.subprocess, "run", _fake_run)
    commit, dirty = _collect_git_metadata()
    assert commit == "deadbeef"
    assert dirty is True


def test_collect_git_metadata_clean_tree(monkeypatch):
    def _fake_run(cmd, **_kwargs):
        if "rev-parse" in cmd:
            return SimpleNamespace(returncode=0, stdout="cafe\n")
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(main.subprocess, "run", _fake_run)
    commit, dirty = _collect_git_metadata()
    assert commit == "cafe"
    assert dirty is False


def test_collect_git_metadata_defaults_on_error(monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("git not available")

    monkeypatch.setattr(main.subprocess, "run", _boom)
    commit, dirty = _collect_git_metadata()
    assert commit == "unknown"
    assert dirty is False


# --- _ensure_default_project --------------------------------------------------


def test_ensure_default_project_noop_when_present(monkeypatch):
    session = _FakeSession(first=SimpleNamespace(id="existing"))
    monkeypatch.setattr(main, "get_session", lambda: session)
    main._ensure_default_project()
    assert session.added == []
    assert session.committed is False


def test_ensure_default_project_seeds_when_absent(monkeypatch):
    session = _FakeSession(first=None)
    monkeypatch.setattr(main, "get_session", lambda: session)
    main._ensure_default_project()
    assert len(session.added) == 1
    assert session.added[0].name == "Main"
    assert session.committed is True


def test_ensure_default_project_logs_on_failure(monkeypatch, caplog):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(main, "get_session", _boom)
    with caplog.at_level(logging.WARNING, logger="syx"):
        main._ensure_default_project()
    assert any("Failed to ensure default 'Main'" in r.message for r in caplog.records)


# --- _init_factory_clients ----------------------------------------------------


def test_init_factory_clients_happy(monkeypatch, caplog):
    monkeypatch.setattr(main, "get_llm_client", lambda: None)
    monkeypatch.setattr(main, "get_llm_client_mini", lambda: None)
    monkeypatch.setattr(main, "get_embedding_client", lambda: None)
    with caplog.at_level(logging.INFO, logger="syx"):
        main._init_factory_clients()
    assert any("Factory clients initialized at startup" in r.message for r in caplog.records)


def test_init_factory_clients_llm_failure_tolerated(monkeypatch, caplog):
    def _boom():
        raise RuntimeError("llm down")

    monkeypatch.setattr(main, "get_llm_client", _boom)
    monkeypatch.setattr(main, "get_llm_client_mini", lambda: None)
    monkeypatch.setattr(main, "get_embedding_client", lambda: None)
    with caplog.at_level(logging.INFO, logger="syx"):
        main._init_factory_clients()
    msgs = " ".join(r.message for r in caplog.records)
    assert "LLM factory startup initialization failed" in msgs
    assert "Factory clients initialized at startup" in msgs


def test_init_factory_clients_embedding_failure_non_st_tolerated(monkeypatch, caplog):
    monkeypatch.setattr(main, "get_llm_client", lambda: None)
    monkeypatch.setattr(main, "get_llm_client_mini", lambda: None)

    def _boom():
        raise RuntimeError("embed down")

    monkeypatch.setattr(main, "get_embedding_client", _boom)
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(embedding_provider="openai"))
    with caplog.at_level(logging.WARNING, logger="syx"):
        main._init_factory_clients()
    assert any(
        "Embedding factory startup initialization failed" in r.message for r in caplog.records
    )


def test_init_factory_clients_embedding_failure_st_is_fatal(monkeypatch):
    monkeypatch.setattr(main, "get_llm_client", lambda: None)
    monkeypatch.setattr(main, "get_llm_client_mini", lambda: None)

    def _boom():
        raise RuntimeError("st down")

    monkeypatch.setattr(main, "get_embedding_client", _boom)
    monkeypatch.setattr(
        main, "get_settings", lambda: SimpleNamespace(embedding_provider="sentence_transformers")
    )
    with pytest.raises(RuntimeError):
        main._init_factory_clients()


# --- _init_instrumentation ----------------------------------------------------


def test_init_instrumentation_happy_logs_run_id(monkeypatch, caplog):
    monkeypatch.setattr(main, "_collect_git_metadata", lambda: ("abc", False))
    monkeypatch.setattr(main, "_build_run_config", lambda *_a, **_k: {})
    monkeypatch.setattr(main, "load_and_validate_route_policy", lambda: {})
    monkeypatch.setattr(
        main,
        "init_instrumentation",
        lambda *_a, **_k: SimpleNamespace(start_run=lambda config: "run-123"),
    )
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(instrumentation_mode="full"))
    with caplog.at_level(logging.INFO, logger="syx"):
        main._init_instrumentation()
    assert any("Initialized run_id=run-123" in r.message for r in caplog.records)


def test_init_instrumentation_no_run_id_skips_log(monkeypatch, caplog):
    monkeypatch.setattr(main, "_collect_git_metadata", lambda: ("abc", False))
    monkeypatch.setattr(main, "_build_run_config", lambda *_a, **_k: {})
    monkeypatch.setattr(main, "load_and_validate_route_policy", lambda: {})
    monkeypatch.setattr(
        main, "init_instrumentation", lambda *_a, **_k: SimpleNamespace(start_run=lambda config: "")
    )
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(instrumentation_mode="full"))
    with caplog.at_level(logging.INFO, logger="syx"):
        main._init_instrumentation()
    assert not any("Initialized run_id" in r.message for r in caplog.records)


def test_init_instrumentation_failure_tolerated(monkeypatch, caplog):
    def _boom(*_a, **_k):
        raise RuntimeError("instr down")

    monkeypatch.setattr(main, "_collect_git_metadata", lambda: ("abc", False))
    monkeypatch.setattr(main, "init_instrumentation", _boom)
    with caplog.at_level(logging.WARNING, logger="syx"):
        main._init_instrumentation()
    assert any("Failed to initialize instrumentation" in r.message for r in caplog.records)


# --- small lock/backfill helpers ----------------------------------------------


def test_clear_startup_lock_happy(monkeypatch, caplog):
    monkeypatch.setattr(main, "release_lock", lambda: None)
    with caplog.at_level(logging.INFO, logger="syx"):
        main._clear_startup_lock()
    assert any("Cleared any existing lock on startup" in r.message for r in caplog.records)


def test_clear_startup_lock_failure(monkeypatch, caplog):
    monkeypatch.setattr(main, "release_lock", lambda: (_ for _ in ()).throw(OSError("x")))
    with caplog.at_level(logging.WARNING, logger="syx"):
        main._clear_startup_lock()
    assert any("Failed clearing startup lock" in r.message for r in caplog.records)


def test_backfill_project_defaults_happy_and_failure(monkeypatch, caplog):
    monkeypatch.setattr(main, "backfill_all_projects", lambda: None)
    main._backfill_project_defaults()  # no exception

    monkeypatch.setattr(
        main, "backfill_all_projects", lambda: (_ for _ in ()).throw(RuntimeError("b"))
    )
    with caplog.at_level(logging.WARNING, logger="syx"):
        main._backfill_project_defaults()
    assert any("Backfill defaults failed" in r.message for r in caplog.records)


def test_init_sleep_lock_from_disk_happy_and_failure(monkeypatch, caplog):
    monkeypatch.setattr(main, "init_from_disk", lambda: None)
    main._init_sleep_lock_from_disk()

    monkeypatch.setattr(main, "init_from_disk", lambda: (_ for _ in ()).throw(OSError("d")))
    with caplog.at_level(logging.WARNING, logger="syx"):
        main._init_sleep_lock_from_disk()
    assert any("Failed to init lock from disk" in r.message for r in caplog.records)


# --- _seed_main_user_profile --------------------------------------------------


def test_seed_main_user_profile_noop_when_no_main(monkeypatch):
    monkeypatch.setattr(main, "get_session", lambda: _FakeSession(first=None))
    copied = []
    monkeypatch.setattr(main.shutil, "copy", lambda *a: copied.append(a))
    main._seed_main_user_profile()
    assert copied == []


def test_seed_main_user_profile_copies_and_rebuilds(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(main, "get_session", lambda: _FakeSession(first=SimpleNamespace(id="p1")))
    monkeypatch.setattr(main, "settings", SimpleNamespace(memory_root=str(tmp_path)))
    copied = []
    monkeypatch.setattr(main.shutil, "copy", lambda src, dst: copied.append((src, dst)))
    rebuilt = []
    monkeypatch.setattr(main, "rebuild_faiss_index", lambda pid: rebuilt.append(pid))
    with caplog.at_level(logging.INFO, logger="syx"):
        main._seed_main_user_profile()
    assert len(copied) == 1
    assert rebuilt == ["p1"]
    assert any("RAG rebuilt for project p1" in r.message for r in caplog.records)


def test_seed_main_user_profile_skips_copy_when_dst_exists(monkeypatch, tmp_path):
    pid = "p1"
    dst_dir = tmp_path / pid / "uploads"
    dst_dir.mkdir(parents=True)
    (dst_dir / "USER_PROFILE.txt").write_text("already here", encoding="utf-8")

    monkeypatch.setattr(main, "get_session", lambda: _FakeSession(first=SimpleNamespace(id=pid)))
    monkeypatch.setattr(main, "settings", SimpleNamespace(memory_root=str(tmp_path)))
    copied = []
    monkeypatch.setattr(main.shutil, "copy", lambda *a: copied.append(a))
    main._seed_main_user_profile()
    assert copied == []


def test_seed_main_user_profile_warns_when_default_missing(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(main, "get_session", lambda: _FakeSession(first=SimpleNamespace(id="p1")))
    monkeypatch.setattr(main, "settings", SimpleNamespace(memory_root=str(tmp_path)))

    real_isfile = main.os.path.isfile
    monkeypatch.setattr(
        main.os.path,
        "isfile",
        lambda p: False if p.endswith("USER_PROFILE.txt") else real_isfile(p),
    )
    with caplog.at_level(logging.WARNING, logger="syx"):
        main._seed_main_user_profile()
    assert any("USER_PROFILE.txt not found" in r.message for r in caplog.records)


def test_seed_main_user_profile_rebuild_failure_logged(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(main, "get_session", lambda: _FakeSession(first=SimpleNamespace(id="p1")))
    monkeypatch.setattr(main, "settings", SimpleNamespace(memory_root=str(tmp_path)))
    monkeypatch.setattr(main.shutil, "copy", lambda src, dst: None)
    monkeypatch.setattr(
        main, "rebuild_faiss_index", lambda pid: (_ for _ in ()).throw(RuntimeError("rag"))
    )
    with caplog.at_level(logging.WARNING, logger="syx"):
        main._seed_main_user_profile()
    assert any("RAG rebuild failed for project p1" in r.message for r in caplog.records)


def test_seed_main_user_profile_outer_failure_logged(monkeypatch, caplog):
    monkeypatch.setattr(main, "get_session", lambda: (_ for _ in ()).throw(RuntimeError("db")))
    with caplog.at_level(logging.WARNING, logger="syx"):
        main._seed_main_user_profile()
    assert any("Main seed failed" in r.message for r in caplog.records)


# --- _startup_rag_rebuild_sweep -----------------------------------------------


def test_startup_rag_rebuild_sweep_disabled(monkeypatch, caplog):
    monkeypatch.setattr(
        main, "get_settings", lambda: SimpleNamespace(force_rag_rebuild_on_startup=False)
    )
    with caplog.at_level(logging.INFO, logger="syx"):
        main._startup_rag_rebuild_sweep()
    assert any("skipping full RAG rebuild" in r.message for r in caplog.records)


def test_startup_rag_rebuild_sweep_rebuilds_each_project(monkeypatch, caplog):
    monkeypatch.setattr(
        main, "get_settings", lambda: SimpleNamespace(force_rag_rebuild_on_startup=True)
    )
    monkeypatch.setattr(
        main,
        "get_session",
        lambda: _FakeSession(all_=[SimpleNamespace(id="p1"), SimpleNamespace(id="p2")]),
    )
    rebuilt = []
    monkeypatch.setattr(main, "rebuild_faiss_index", lambda pid: rebuilt.append(pid))
    with caplog.at_level(logging.INFO, logger="syx"):
        main._startup_rag_rebuild_sweep()
    assert rebuilt == ["p1", "p2"]


def test_startup_rag_rebuild_sweep_per_project_failure_isolated(monkeypatch, caplog):
    monkeypatch.setattr(
        main, "get_settings", lambda: SimpleNamespace(force_rag_rebuild_on_startup=True)
    )
    monkeypatch.setattr(main, "get_session", lambda: _FakeSession(all_=[SimpleNamespace(id="p1")]))
    monkeypatch.setattr(
        main, "rebuild_faiss_index", lambda pid: (_ for _ in ()).throw(RuntimeError("rag"))
    )
    with caplog.at_level(logging.WARNING, logger="syx"):
        main._startup_rag_rebuild_sweep()
    assert any("Startup RAG rebuild failed for project p1" in r.message for r in caplog.records)


def test_startup_rag_rebuild_sweep_outer_failure_logged(monkeypatch, caplog):
    monkeypatch.setattr(
        main, "get_settings", lambda: (_ for _ in ()).throw(RuntimeError("settings"))
    )
    with caplog.at_level(logging.WARNING, logger="syx"):
        main._startup_rag_rebuild_sweep()
    assert any("Startup RAG rebuild sweep failed" in r.message for r in caplog.records)


# --- _start_sleep_scheduler ---------------------------------------------------


class _FakeScheduler:
    def __init__(self, *_a, **_k):
        self.jobs = []
        self.started = False

    def add_job(self, func, **kwargs):
        self.jobs.append((func, kwargs))

    def start(self):
        self.started = True


def test_start_sleep_scheduler_enabled(monkeypatch, caplog):
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(enable_scheduler=True, sleep_cycle_hour=3, sleep_cycle_minute=30),
    )
    created = {}

    def _factory(*a, **k):
        sched = _FakeScheduler()
        created["sched"] = sched
        return sched

    monkeypatch.setattr(main, "BackgroundScheduler", _factory)
    monkeypatch.setattr(main, "CronTrigger", lambda **k: ("cron", k))
    with caplog.at_level(logging.INFO, logger="syx"):
        main._start_sleep_scheduler()
    assert created["sched"].started is True
    assert any("Sleep scheduler started" in r.message for r in caplog.records)


def test_start_sleep_scheduler_disabled(monkeypatch):
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(enable_scheduler=False))
    called = []
    monkeypatch.setattr(main, "BackgroundScheduler", lambda *a, **k: called.append(True))
    main._start_sleep_scheduler()
    assert called == []


def test_start_sleep_scheduler_failure_logged(monkeypatch, caplog):
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(enable_scheduler=True, sleep_cycle_hour=3, sleep_cycle_minute=30),
    )
    monkeypatch.setattr(
        main, "BackgroundScheduler", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sched"))
    )
    with caplog.at_level(logging.WARNING, logger="syx"):
        main._start_sleep_scheduler()
    assert any("Failed to start scheduler" in r.message for r in caplog.records)


# --- lifespan orchestration ---------------------------------------------------


def test_lifespan_runs_startup_steps_and_finalizes(monkeypatch):
    calls = []
    step_names = [
        "_ensure_default_project",
        "_init_factory_clients",
        "_init_instrumentation",
        "_clear_startup_lock",
        "_backfill_project_defaults",
        "_init_sleep_lock_from_disk",
        "_seed_main_user_profile",
        "_startup_rag_rebuild_sweep",
        "_start_sleep_scheduler",
    ]
    for name in step_names:
        monkeypatch.setattr(main, name, lambda n=name: calls.append(n))
    monkeypatch.setattr(main, "init_db", lambda: calls.append("init_db"))
    monkeypatch.setattr(
        main,
        "get_instrumentation",
        lambda: SimpleNamespace(end_run=lambda summary: calls.append(("end_run", summary))),
    )

    async def _run():
        async with main.lifespan(main.app):
            calls.append("yield")

    asyncio.run(_run())

    assert calls[0] == "init_db"
    assert calls[1] == "_ensure_default_project"
    assert "yield" in calls
    assert any(isinstance(c, tuple) and c[0] == "end_run" for c in calls)


def test_lifespan_shutdown_finalize_failure_logged(monkeypatch, caplog):
    for name in [
        "_ensure_default_project",
        "_init_factory_clients",
        "_init_instrumentation",
        "_clear_startup_lock",
        "_backfill_project_defaults",
        "_init_sleep_lock_from_disk",
        "_seed_main_user_profile",
        "_startup_rag_rebuild_sweep",
        "_start_sleep_scheduler",
    ]:
        monkeypatch.setattr(main, name, lambda: None)
    monkeypatch.setattr(main, "init_db", lambda: None)
    monkeypatch.setattr(
        main,
        "get_instrumentation",
        lambda: SimpleNamespace(end_run=lambda summary: (_ for _ in ()).throw(RuntimeError("end"))),
    )

    async def _run():
        async with main.lifespan(main.app):
            pass

    with caplog.at_level(logging.WARNING, logger="syx"):
        asyncio.run(_run())
    assert any("Failed to finalize instrumentation run" in r.message for r in caplog.records)


# --- sleep_guard middleware ---------------------------------------------------


def test_sleep_guard_blocks_mutating_request_while_sleeping(monkeypatch):
    monkeypatch.setattr(main, "is_sleeping", lambda: True)
    resp = client.post("/some/non-allowlisted/path")
    assert resp.status_code == 423
    assert "sleeping" in resp.json()["error"].lower()


def test_sleep_guard_allows_get_while_sleeping(monkeypatch):
    monkeypatch.setattr(main, "is_sleeping", lambda: True)
    resp = client.get("/health")
    assert resp.status_code == 200


def test_sleep_guard_allowlist_passes_through(monkeypatch):
    monkeypatch.setattr(main, "is_sleeping", lambda: True)
    resp = client.post("/sleep/unlock")
    assert resp.status_code != 423


def test_sleep_guard_state_check_failure_proceeds(monkeypatch, caplog):
    monkeypatch.setattr(main, "is_sleeping", lambda: (_ for _ in ()).throw(RuntimeError("state")))
    with caplog.at_level(logging.WARNING, logger="syx"):
        resp = client.post("/some/non-allowlisted/path")
    assert resp.status_code != 423
    assert any("sleep_guard state check failed" in r.message for r in caplog.records)


# --- _schedule_entrypoint -----------------------------------------------------


def test_schedule_entrypoint_starts_cycle_when_not_sleeping(monkeypatch, caplog):
    monkeypatch.setattr(main, "clear_stale_lock", lambda: True)
    monkeypatch.setattr(main, "is_sleeping", lambda: False)
    started = []
    monkeypatch.setattr(main, "start_sleep_cycle_async", lambda: started.append(True))
    with caplog.at_level(logging.INFO, logger="syx"):
        main._schedule_entrypoint()
    assert started == [True]
    assert any("Cleared stale lock before scheduled run" in r.message for r in caplog.records)


def test_schedule_entrypoint_clear_stale_lock_failure_then_starts(monkeypatch):
    monkeypatch.setattr(
        main, "clear_stale_lock", lambda: (_ for _ in ()).throw(RuntimeError("stale"))
    )
    monkeypatch.setattr(main, "is_sleeping", lambda: False)
    started = []
    monkeypatch.setattr(main, "start_sleep_cycle_async", lambda: started.append(True))
    main._schedule_entrypoint()
    assert started == [True]


def test_schedule_entrypoint_skips_when_already_sleeping(monkeypatch, caplog):
    monkeypatch.setattr(main, "clear_stale_lock", lambda: False)
    monkeypatch.setattr(main, "is_sleeping", lambda: True)
    started = []
    monkeypatch.setattr(main, "start_sleep_cycle_async", lambda: started.append(True))
    with caplog.at_level(logging.INFO, logger="syx"):
        main._schedule_entrypoint()
    assert started == []
    assert any("Already running, skipping" in r.message for r in caplog.records)


def test_schedule_entrypoint_outer_failure_logged(monkeypatch, caplog):
    monkeypatch.setattr(main, "clear_stale_lock", lambda: False)
    monkeypatch.setattr(main, "is_sleeping", lambda: (_ for _ in ()).throw(RuntimeError("state")))
    with caplog.at_level(logging.WARNING, logger="syx"):
        main._schedule_entrypoint()
    assert any("Schedule entrypoint failed" in r.message for r in caplog.records)


# --- root / serve_react_app / health_check ------------------------------------


def test_root_serves_index_when_build_present(monkeypatch):
    monkeypatch.setattr(main.os.path, "exists", lambda p: True)
    monkeypatch.setattr(main, "FileResponse", lambda p: {"file": p})
    result = asyncio.run(main.root())
    assert isinstance(result, dict) and result.get("file", "").endswith("index.html")


def test_root_returns_api_info_when_not_built(monkeypatch):
    monkeypatch.setattr(main.os.path, "exists", lambda p: False)
    result = asyncio.run(main.root())
    assert result["message"].startswith("Syx AGI Chatbot API")
    assert result["docs"] == "/api/docs"


@pytest.mark.parametrize("path", ["api/foo", "docs", "redoc"])
def test_serve_react_app_404_for_api_routes(path):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.serve_react_app(path))
    assert exc.value.status_code == 404


def test_serve_react_app_serves_index_when_present(monkeypatch):
    monkeypatch.setattr(main.os.path, "exists", lambda p: True)
    monkeypatch.setattr(main, "FileResponse", lambda p: {"file": p})
    result = asyncio.run(main.serve_react_app("dashboard"))
    assert isinstance(result, dict) and result.get("file", "").endswith("index.html")


def test_serve_react_app_json_when_not_built(monkeypatch):
    monkeypatch.setattr(main.os.path, "exists", lambda p: False)
    result = asyncio.run(main.serve_react_app("dashboard"))
    assert result["error"] == "Frontend not built"
    assert result["path"] == "dashboard"


def test_health_check_unhealthy_on_exception(monkeypatch):
    monkeypatch.setattr(
        main, "active_llm_key_status", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    result = asyncio.run(main.health_check())
    assert result.status == "unhealthy"
    assert "error" in result.dependencies


def test_health_check_degraded_when_provider_key_missing(monkeypatch):
    from app.core import llm_service

    monkeypatch.setattr(
        main,
        "active_llm_key_status",
        lambda: {
            "provider": "anthropic",
            "setting": "ANTHROPIC_API_KEY",
            "dependency": "anthropic",
            "status": "missing",
        },
    )
    monkeypatch.setattr(llm_service, "get_llm_health", lambda: {"status": "unhealthy"})

    result = asyncio.run(main.health_check())

    assert result.status == "degraded"
    assert result.dependencies == {"anthropic": "missing", "llm": "unhealthy"}


# --- LoggingRedirect ----------------------------------------------------------


class _RecLogger:
    def __init__(self):
        self.calls = []

    def log(self, level, msg):
        self.calls.append(("log", level, msg))

    def info(self, msg):
        self.calls.append(("info", msg))


def test_logging_redirect_drops_blank():
    rec = _RecLogger()
    main.LoggingRedirect(rec, logging.WARNING).write("   \n")
    assert rec.calls == []


def test_logging_redirect_filters_in_progress_weight_loading():
    rec = _RecLogger()
    main.LoggingRedirect(rec, logging.WARNING).write("Loading weights: 50%|####  |")
    assert rec.calls == []


def test_logging_redirect_demotes_completed_weight_loading_to_info():
    rec = _RecLogger()
    main.LoggingRedirect(rec, logging.WARNING).write("Loading weights: 100%|#####| done")
    assert rec.calls and rec.calls[0][0] == "info"


def test_logging_redirect_forwards_normal_line_at_level():
    rec = _RecLogger()
    main.LoggingRedirect(rec, logging.WARNING).write("a real warning")
    assert rec.calls == [("log", logging.WARNING, "a real warning")]


def test_logging_redirect_flush_is_noop():
    assert main.LoggingRedirect(_RecLogger(), logging.INFO).flush() is None


# --- _flush_and_close_log_handlers --------------------------------------------


class _BoomHandler(logging.Handler):
    def __init__(self, *, fail_flush=False, fail_close=False):
        super().__init__()
        self.fail_flush = fail_flush
        self.fail_close = fail_close
        self.flushed = False
        self.closed_ = False

    def emit(self, record):  # pragma: no cover - records are not asserted
        pass

    def flush(self):
        if self.fail_flush:
            raise OSError("flush boom")
        self.flushed = True

    def close(self):
        if self.fail_close:
            raise OSError("close boom")
        self.closed_ = True
        super().close()


@pytest.fixture
def _isolated_root_handlers():
    root = logging.getLogger()
    saved = list(root.handlers)
    try:
        yield root
    finally:
        root.handlers = saved


def test_flush_and_close_log_handlers_happy(_isolated_root_handlers):
    handler = _BoomHandler()
    _isolated_root_handlers.handlers = [handler]
    main._flush_and_close_log_handlers()
    assert handler.flushed is True
    assert handler.closed_ is True


def test_flush_and_close_log_handlers_logs_flush_and_close_failures(_isolated_root_handlers):
    handler = _BoomHandler(fail_flush=True, fail_close=True)
    _isolated_root_handlers.handlers = [handler]
    # Should not raise despite both flush and close failing.
    main._flush_and_close_log_handlers()


# --- run_server ---------------------------------------------------------------


def _patch_run_server(monkeypatch, *, log_level, api_key_ok):
    import uvicorn

    monkeypatch.setattr(main, "validate_active_llm_key", lambda: api_key_ok)
    monkeypatch.setattr(
        main,
        "active_llm_key_status",
        lambda: {
            "provider": "openai",
            "setting": "OPENAI_API_KEY",
            "dependency": "openai",
            "status": "configured" if api_key_ok else "missing",
        },
    )
    monkeypatch.setattr(main, "settings", SimpleNamespace(host="127.0.0.1", port=8123))
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(log_level=log_level))
    flushed = []
    monkeypatch.setattr(main, "_flush_and_close_log_handlers", lambda: flushed.append(True))
    runs = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: runs.append(kwargs))
    return runs, flushed


def test_run_server_non_debug_redirects_and_runs(monkeypatch):
    runs, flushed = _patch_run_server(monkeypatch, log_level="INFO", api_key_ok=False)
    main.run_server()
    assert len(runs) == 1
    assert runs[0]["log_level"] == "info"
    assert flushed == [True]


def test_run_server_debug_runs_without_redirect(monkeypatch):
    runs, flushed = _patch_run_server(monkeypatch, log_level="DEBUG", api_key_ok=True)
    main.run_server()
    assert len(runs) == 1
    assert runs[0]["log_level"] == "debug"
    assert flushed == [True]
