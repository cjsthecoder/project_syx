"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.sleep.worker.

Covers the start/skip branching of start_sleep_cycle_runner: the early
already-sleeping skip, the double-checked skip inside the lock, and the
happy-path thread start (joined so no daemon thread leaks).
"""
import threading

import app.sleep.worker as worker


def test_start_skips_when_already_sleeping(monkeypatch):
    monkeypatch.setattr(worker, "is_sleeping", lambda: True)
    called = []
    assert worker.start_sleep_cycle_runner(lambda: called.append("ran")) is False
    assert called == []


def test_start_skips_when_sleeping_after_lock(monkeypatch):
    # First check (outside lock) is False, second check (inside lock) is True.
    states = iter([False, True])
    monkeypatch.setattr(worker, "is_sleeping", lambda: next(states))
    called = []
    assert worker.start_sleep_cycle_runner(lambda: called.append("ran")) is False
    assert called == []


def test_start_launches_thread(monkeypatch):
    monkeypatch.setattr(worker, "is_sleeping", lambda: False)
    done = threading.Event()
    started = worker.start_sleep_cycle_runner(done.set)
    assert started is True
    assert done.wait(timeout=5.0)
    # Join the launched thread so it does not outlive the test.
    if worker._runner_thread is not None:
        worker._runner_thread.join(timeout=5.0)
