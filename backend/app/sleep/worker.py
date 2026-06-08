"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Sleep-cycle worker thread launcher.

This module starts a background daemon thread to run a sleep-cycle worker,
skipping the start when a cycle is already in progress.
"""
import logging
import threading
from typing import Callable, Optional

from ..core.state import is_sleeping

logger = logging.getLogger(__name__)

_runner_lock = threading.Lock()
_runner_thread: Optional[threading.Thread] = None


def start_sleep_cycle_runner(worker: Callable[[], None]) -> bool:
    """Start a sleep cycle worker thread if not already sleeping.

    Guards against concurrent runs via an in-process lock plus the global
    sleeping flag; the worker runs on a daemon thread.

    Args:
        worker: Zero-argument callable executed on the background thread.

    Returns:
        True when a new thread was started, False when a cycle is already running.
    """
    if is_sleeping():
        logger.info("[SLEEP] Already running, skipping.")
        return False

    global _runner_thread
    with _runner_lock:
        if is_sleeping():
            logger.info("[SLEEP] Already running, skipping.")
            return False
        t = threading.Thread(target=worker, name="sleep-cycle", daemon=True)
        _runner_thread = t
        t.start()
        return True
