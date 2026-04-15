"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import os
import time
from typing import Optional
import logging

logger = logging.getLogger(__name__)

_sleeping: bool = False
_since_ts: Optional[float] = None
_LOCK_PATH = os.path.join("runtime", "sleep.lock")


def lock_path() -> str:
    return _LOCK_PATH


def is_sleeping() -> bool:
    return _sleeping


def since() -> Optional[float]:
    return _since_ts


def set_sleeping(on: bool) -> None:
    global _sleeping, _since_ts
    if on and not _sleeping:
        _sleeping = True
        _since_ts = time.time()
    elif (not on) and _sleeping:
        _sleeping = False
        _since_ts = None


def engage_lock() -> None:
    os.makedirs(os.path.dirname(_LOCK_PATH), exist_ok=True)
    with open(_LOCK_PATH, "w", encoding="utf-8") as f:
        f.write(str(int(time.time())))
    set_sleeping(True)


def release_lock() -> None:
    try:
        if os.path.exists(_LOCK_PATH):
            os.remove(_LOCK_PATH)
    except OSError as exc:
        logger.warning("state.release_lock failed lock_path=%s detail=%s", _LOCK_PATH, exc)
    set_sleeping(False)


def init_from_disk() -> None:
    if os.path.exists(_LOCK_PATH):
        set_sleeping(True)


def clear_stale_lock(max_age_seconds: int = 2 * 60 * 60) -> bool:
    """
    Remove a stale lock file if it's older than max_age_seconds.
    Returns True if a stale lock was cleared.
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

