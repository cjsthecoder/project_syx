"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.core.state (sleep lock + in-process sleeping flag).

The module keeps process-global state and a module-level lock path, so each
test points ``_LOCK_PATH`` at a temp file and resets the sleeping flag via an
autouse fixture to stay isolated.
"""

import os

import pytest
from app.core import state


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_LOCK_PATH", str(tmp_path / "locks" / "sleep.lock"))
    monkeypatch.setattr(state, "_sleeping", False)
    monkeypatch.setattr(state, "_since_ts", None)
    yield


def test_lock_path_returns_module_path():
    assert state.lock_path() == state._LOCK_PATH


def test_set_sleeping_toggles_and_tracks_since():
    assert state.is_sleeping() is False
    assert state.since() is None

    state.set_sleeping(True)
    assert state.is_sleeping() is True
    first_since = state.since()
    assert first_since is not None

    # Redundant engage is idempotent: since() is not reset.
    state.set_sleeping(True)
    assert state.since() == first_since

    state.set_sleeping(False)
    assert state.is_sleeping() is False
    assert state.since() is None

    # Redundant release is a no-op.
    state.set_sleeping(False)
    assert state.is_sleeping() is False


def test_engage_lock_writes_file_and_marks_sleeping():
    state.engage_lock()
    assert os.path.exists(state._LOCK_PATH)
    assert state.is_sleeping() is True


def test_release_lock_removes_file_and_clears_state():
    state.engage_lock()
    state.release_lock()
    assert not os.path.exists(state._LOCK_PATH)
    assert state.is_sleeping() is False


def test_release_lock_logs_on_remove_failure(monkeypatch, caplog):
    state.engage_lock()
    monkeypatch.setattr(state.os, "remove", lambda _p: (_ for _ in ()).throw(OSError("denied")))
    state.release_lock()
    assert any("release_lock failed" in r.message for r in caplog.records)
    assert state.is_sleeping() is False  # state still cleared despite remove failure


def test_init_from_disk_restores_sleeping_when_lock_exists():
    os.makedirs(os.path.dirname(state._LOCK_PATH), exist_ok=True)
    with open(state._LOCK_PATH, "w", encoding="utf-8") as handle:
        handle.write("123")
    state.init_from_disk()
    assert state.is_sleeping() is True


def test_init_from_disk_noop_without_lock():
    state.init_from_disk()
    assert state.is_sleeping() is False


def test_clear_stale_lock_removes_old_lock(monkeypatch):
    state.engage_lock()
    # Force the lock to look ancient.
    monkeypatch.setattr(state.os.path, "getmtime", lambda _p: 0.0)
    assert state.clear_stale_lock(max_age_seconds=60) is True
    assert not os.path.exists(state._LOCK_PATH)
    assert state.is_sleeping() is False


def test_clear_stale_lock_keeps_fresh_lock():
    state.engage_lock()
    assert state.clear_stale_lock(max_age_seconds=10_000) is False
    assert os.path.exists(state._LOCK_PATH)


def test_clear_stale_lock_no_lock_returns_false():
    assert state.clear_stale_lock() is False


def test_clear_stale_lock_logs_on_error(monkeypatch, caplog):
    state.engage_lock()
    monkeypatch.setattr(
        state.os.path, "getmtime", lambda _p: (_ for _ in ()).throw(OSError("stat failed"))
    )
    assert state.clear_stale_lock(max_age_seconds=1) is False
    assert any("clear_stale_lock failed" in r.message for r in caplog.records)
