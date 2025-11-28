import logging
import time
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Optional
import json
import re

from .config import get_settings

logger = logging.getLogger(__name__)

_executor: Optional[ThreadPoolExecutor] = None


def init_dream_executor(max_workers: int) -> None:
    """Initialize the Dream executor if not already initialized."""
    global _executor
    if _executor is None and max_workers > 0:
        _executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="dream")
        logger.info("[DREAM] Executor initialized (max_workers=%s)", max_workers)


def shutdown_dream_executor() -> None:
    """Shutdown the Dream executor if initialized."""
    global _executor
    if _executor is not None:
        try:
            _executor.shutdown(wait=True, cancel_futures=True)
            logger.info("[DREAM] Executor shutdown complete")
        except Exception as e:
            logger.warning("[DREAM] Executor shutdown error: %s", e)
        finally:
            _executor = None


def _extract_json_from_open_questions(summary_text: str) -> Optional[str]:
    """
    Locate the [Open Questions] section and extract the first JSON object that follows.
    Returns the JSON text or None if not found/invalid.
    """
    try:
        # Find the [Open Questions] marker
        m = re.search(r"^\[Open Questions\][\s\S]*", summary_text, flags=re.MULTILINE)
        start_idx = m.start() if m else -1
        if start_idx < 0:
            return None
        # From marker onward, find first '{' and extract balanced braces
        tail = summary_text[start_idx:]
        brace_start = tail.find("{")
        if brace_start < 0:
            return None
        i = brace_start
        depth = 0
        for j, ch in enumerate(tail[brace_start:], start=brace_start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    json_str = tail[brace_start:j + 1]
                    # Validate it's JSON
                    json.loads(json_str)
                    return json_str
        return None
    except Exception:
        return None


def _open_questions_agent(project_id: str, summary_text: str) -> dict:
    """
    4.1.1 scope: Parse the JSON block from the [Open Questions] section.
    No file writes; return dict with count and preview for logging.
    """
    json_text = _extract_json_from_open_questions(summary_text or "")
    if not json_text:
        logger.warning("[DREAM][WARN] project=%s no valid JSON found in [Open Questions]", project_id)
        return {"questions": []}
    try:
        obj = json.loads(json_text)
        # Expect { "questions": [...] } per 4.1.1 format guidance
        lst = obj.get("questions")
        if not isinstance(lst, list):
            logger.warning("[DREAM][WARN] project=%s invalid JSON structure (no questions list)", project_id)
            return {"questions": []}
        # Just return parsed object; filtering already handled by formatter prompt
        return obj
    except Exception as e:
        logger.warning("[DREAM][WARN] project=%s invalid JSON payload: %s", project_id, e)
        return {"questions": []}


def submit_open_questions(project_id: str, summary_text: str) -> Future:
    """
    Submit the Open Questions extraction task to the executor and return a Future.
    Logs first 250 chars of payload on success.
    """
    settings = get_settings()
    if not settings.enable_dream:
        # Return a dummy completed future
        class _Dummy(Future):
            def __init__(self):
                super().__init__()
                self.set_result({"questions": []})
        return _Dummy()
    if _executor is None:
        raise RuntimeError("Dream executor not initialized")

    def _task():
        t0 = time.monotonic()
        logger.info("[DREAM] Start project=%s", project_id)
        try:
            result = _open_questions_agent(project_id, summary_text)
            preview = json.dumps(result, ensure_ascii=False)[:250]
            count = len(result.get("questions", [])) if isinstance(result.get("questions"), list) else 0
            elapsed = time.monotonic() - t0
            logger.info("[DREAM] Completed project=%s duration=%.2fs count=%s preview=%s", project_id, elapsed, count, preview)
            logger.info("[DREAM] All agents complete for project=%s", project_id)
            return result
        except Exception as e:
            logger.error("[DREAM][ERROR] project=%s %s", project_id, e, exc_info=True)
            return {"questions": []}

    return _executor.submit(_task)


