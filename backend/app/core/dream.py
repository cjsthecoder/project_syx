import logging
import time
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Optional, List, Dict
import json
import re
import os
from filelock import FileLock

from .config import get_settings
from .dream_context import build_dream_context
from .dream_research import run_open_question_pipeline

logger = logging.getLogger(__name__)

_executor: Optional[ThreadPoolExecutor] = None
_context_cache: Dict[str, str] = {}

def _wait_for_dream_file(project_id: str, timeout: float = 5.0) -> bool:
    """Wait until questions.json exists, is unlocked, and size stabilizes or timeout expires."""
    base_dir = os.path.join("memory", project_id)
    questions_path = os.path.join(base_dir, "questions.json")
    lock_path = os.path.join(base_dir, "questions.lock")
    t0 = time.monotonic()
    last_size = -1
    while time.monotonic() - t0 < timeout:
        if (not os.path.exists(lock_path)) and os.path.isfile(questions_path):
            try:
                size = os.path.getsize(questions_path)
            except Exception:
                size = -1
            if size > 0 and size == last_size:
                return True  # unlocked and stable
            last_size = size
        time.sleep(0.05)
    return False


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
    Parse JSON block from [Open Questions] section.
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
    4.1.2: Submit the Open Questions processing task.
    - Extract questions array
    - Process each question sequentially
    - Write questions.json with minimal keys {question, topic, answer}
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
            parsed = _open_questions_agent(project_id, summary_text)
            questions = parsed.get("questions") if isinstance(parsed, dict) else []
            if not isinstance(questions, list):
                questions = []
            # Process sequentially
            outputs: List[Dict[str, str]] = []
            for item in questions:
                try:
                    q = (item or {}).get("question") or ""
                    topic = (item or {}).get("topic") or ""
                    resolution = (item or {}).get("resolution") or ""
                    if not q:
                        continue
                    out = run_open_question_pipeline(project_id, q, topic, resolution)
                    outputs.append(
                        {
                            "question": out.get("question") or q,
                            "topic": out.get("topic") or topic,
                            "answer": out.get("answer") or "Dream agent failed to generate a valid answer.",
                        }
                    )
                except Exception as qe:
                    logger.warning("[DREAM][WARN] project=%s per-question pipeline error: %s", project_id, qe)
            # Write questions.json with lock
            try:
                base_dir = os.path.join("memory", project_id)
                os.makedirs(base_dir, exist_ok=True)
                lock_path = os.path.join(base_dir, "questions.lock")
                questions_path = os.path.join(base_dir, "questions.json")
                with FileLock(lock_path):
                    with open(questions_path, "w", encoding="utf-8", newline="\n") as df:
                        df.write("{\n  \"questions\": [\n")
                        for i, ent in enumerate(outputs):
                            line = f'    {{ "question": {json.dumps(ent["question"])}, "topic": {json.dumps(ent["topic"])}, "answer": {json.dumps(ent["answer"])} }}'
                            if i < len(outputs) - 1:
                                line += ","
                            df.write(line + "\n")
                        df.write("  ]\n}\n")
            except Exception as we:
                logger.warning("[DREAM][WARN] project=%s failed writing questions.json: %s", project_id, we)
            # Build Dream Context Block (4.1.3.1) AFTER questions.json is written and unlocked
            try:
                _wait_for_dream_file(project_id, timeout=5.0)
                ctx = build_dream_context(project_id)
                _context_cache[project_id] = ctx
                # Write debug context file for inspection REMOVE in 4.1.3.2
                try:
                    base_dir = os.path.join("memory", project_id)
                    os.makedirs(base_dir, exist_ok=True)
                    debug_path = os.path.join(base_dir, "debug_context.txt")
                    with open(debug_path, "w", encoding="utf-8", newline="\n") as dbg:
                        dbg.write(ctx)
                    logger.info("[DREAM][CTX] Wrote debug context to %s", debug_path)
                except Exception as de:
                    logger.warning("[DREAM][CTX][WARN] Failed writing debug context: %s", de)
            except Exception as ce:
                logger.error("[DREAM][CTX][ERROR] project=%s %s", project_id, ce, exc_info=True)
            count = len(outputs)
            preview = json.dumps({"questions": outputs}, ensure_ascii=False)[:250]
            elapsed = time.monotonic() - t0
            logger.info("[DREAM] Completed project=%s duration=%.2fs count=%s preview=%s", project_id, elapsed, count, preview)
            logger.info("[DREAM] All agents complete for project=%s", project_id)
            # Best-effort cleanup
            try:
                if project_id in _context_cache:
                    del _context_cache[project_id]
            except Exception:
                pass
            return {"questions": outputs}
        except Exception as e:
            logger.error("[DREAM][ERROR] project=%s %s", project_id, e, exc_info=True)
            return {"questions": []}

    return _executor.submit(_task)


