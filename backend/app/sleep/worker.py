from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from ..core.state import is_sleeping

logger = logging.getLogger(__name__)

_runner_lock = threading.Lock()
_runner_thread: Optional[threading.Thread] = None


def start_sleep_cycle_runner(worker: Callable[[], None]) -> bool:
    """
    Start a sleep cycle worker thread if not already sleeping.
    Returns True if started.
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
