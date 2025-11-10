import os
import time
from typing import Optional

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
    except Exception:
        pass
    set_sleeping(False)


def init_from_disk() -> None:
    if os.path.exists(_LOCK_PATH):
        set_sleeping(True)

