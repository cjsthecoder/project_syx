"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Sleep-cycle lock and in-process state management.

This module tracks whether a sleep cycle is active and manages the on-disk sleep
lock file, including engaging, releasing, restoring from disk, and clearing stale locks.
"""
import os
import time
from typing import Optional
import logging

from .config import get_settings

logger = logging.getLogger(__name__)

_sleeping: bool = False
_since_ts: Optional[float] = None
_LOCK_PATH = os.path.join(get_settings().lock_dir, "sleep.lock")


def lock_path() -> str:
    """Return the absolute path of the on-disk sleep lock file.

    Returns:
        The configured sleep lock file path.
    """
    return _LOCK_PATH


def is_sleeping() -> bool:
    """Return whether a sleep cycle is currently active in this process.

    Returns:
        True while a sleep cycle is engaged; False otherwise.
    """
    return _sleeping


def since() -> Optional[float]:
    """Return the epoch start time of the active sleep cycle, or None.

    Returns:
        The Unix timestamp when the current sleep cycle began, or None when not
        sleeping.
    """
    return _since_ts


def set_sleeping(on: bool) -> None:
    """Toggle in-process sleep state, tracking the start timestamp.

    Transitions are idempotent: redundant calls do not reset ``since()``.

    Args:
        on: True to engage the sleeping state, False to clear it.
    """
    global _sleeping, _since_ts
    if on and not _sleeping:
        _sleeping = True
        _since_ts = time.time()
    elif (not on) and _sleeping:
        _sleeping = False
        _since_ts = None


def engage_lock() -> None:
    """Write the sleep lock file and mark the process as sleeping."""
    os.makedirs(os.path.dirname(_LOCK_PATH), exist_ok=True)
    with open(_LOCK_PATH, "w", encoding="utf-8") as f:
        f.write(str(int(time.time())))
    set_sleeping(True)


def release_lock() -> None:
    """Remove the sleep lock file and clear the sleeping state."""
    try:
        if os.path.exists(_LOCK_PATH):
            os.remove(_LOCK_PATH)
    except OSError as exc:
        logger.warning("state.release_lock failed lock_path=%s detail=%s", _LOCK_PATH, exc)
    set_sleeping(False)


def init_from_disk() -> None:
    """Restore sleeping state from a lock file left by a prior process."""
    if os.path.exists(_LOCK_PATH):
        set_sleeping(True)


def clear_stale_lock(max_age_seconds: int = 2 * 60 * 60) -> bool:
    """Remove a stale lock file if it's older than ``max_age_seconds``.

    Args:
        max_age_seconds: Maximum lock-file age before it is considered stale;
            defaults to two hours.

    Returns:
        True if a stale lock was found and cleared; False otherwise.
    """
    try:
        if os.path.exists(_LOCK_PATH):
            mtime = os.path.getmtime(_LOCK_PATH)
            if (time.time() - mtime) > max_age_seconds:
                try:
                    os.remove(_LOCK_PATH)
                finally:
                    set_sleeping(False)
                return True
    except OSError as exc:
        logger.warning("state.clear_stale_lock failed lock_path=%s detail=%s", _LOCK_PATH, exc)
    return False

