"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Tuple

from filelock import FileLock

from ..core.config import get_settings

logger = logging.getLogger(__name__)


def _normalize_question_key(question: str, topic: str) -> str:
    def _norm(text: str) -> str:
        lowered = str(text or "").strip().lower()
        lowered = re.sub(r"['\"`“”’]", "", lowered)
        lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
        return lowered.strip()

    return f"{_norm(question)}||{_norm(topic)}"


def consolidate_open_questions_artifact(project_id: str) -> Dict[str, Any]:
    """
    Deterministically consolidate open_questions.jsonl into canonical unresolved questions.

    Consolidation rules:
    - Stable dedupe key: normalized(question) + normalized(topic)
    - Collision policy: keep latest record by (ts, line_no)
    - Status resolution: drop records where final resolution == "ignore"
    """
    base_dir = os.path.join(get_settings().memory_root, project_id)
    src_path = os.path.join(base_dir, "open_questions.jsonl")
    out_path = os.path.join(base_dir, "open_questions_consolidated.json")
    state_dir = os.path.join(base_dir, "state")
    os.makedirs(state_dir, exist_ok=True)
    lock_path = os.path.join(state_dir, "open_questions.lock")
    legacy_lock_path = os.path.join(base_dir, "open_questions.lock")
    if os.path.isfile(legacy_lock_path) and not os.path.exists(lock_path):
        try:
            os.replace(legacy_lock_path, lock_path)
        except OSError as exc:
            logger.warning("[SLEEP][QUESTIONS] lock migration failed project=%s detail=%s", project_id, exc)
    consolidated: Dict[str, Any] = {"questions": []}
    if not os.path.isfile(src_path):
        try:
            with open(out_path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(consolidated, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning(
                "[SLEEP][QUESTIONS] Failed writing empty consolidated artifact project=%s path=%s detail=%s",
                project_id,
                out_path,
                exc,
            )
        return consolidated

    latest_by_key: Dict[str, Tuple[Tuple[str, int], Dict[str, Any]]] = {}
    kept = 0
    ignored = 0
    parsed = 0

    with FileLock(lock_path):
        try:
            with open(src_path, "r", encoding="utf-8") as f:
                for line_no, raw in enumerate(f, start=1):
                    raw = (raw or "").strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except Exception:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    question = str(obj.get("question", "") or "").strip()
                    topic = str(obj.get("topic", "") or "").strip()
                    resolution = str(obj.get("resolution", "") or "").strip().lower()
                    if not question:
                        continue
                    if resolution not in {"ignore", "answer_local", "answer_remote"}:
                        resolution = "ignore"
                    key = _normalize_question_key(question, topic)
                    if not key:
                        continue
                    parsed += 1
                    ts = str(obj.get("ts", "") or "")
                    rank = (ts, int(line_no))
                    cur = latest_by_key.get(key)
                    if (cur is None) or (rank >= cur[0]):
                        latest_by_key[key] = (
                            rank,
                            {
                                "question": question,
                                "topic": topic,
                                "resolution": resolution,
                                "project_id": project_id,
                                "namespace": str(obj.get("namespace", "") or ""),
                                "semantic_handle": str(obj.get("semantic_handle", "") or ""),
                                "pair_id": str(obj.get("pair_id", "") or ""),
                                "assistant_message_id": obj.get("assistant_message_id"),
                                "user_message_id": obj.get("user_message_id"),
                                "source_ts": ts,
                            },
                        )
        except Exception as e:
            logger.warning("[SLEEP][QUESTIONS] Failed reading open_questions.jsonl project=%s: %s", project_id, e)
            try:
                with open(out_path, "w", encoding="utf-8", newline="\n") as f:
                    json.dump(consolidated, f, ensure_ascii=False, indent=2)
            except Exception as exc:
                logger.warning(
                    "[SLEEP][QUESTIONS] Failed writing fallback consolidated artifact project=%s path=%s detail=%s",
                    project_id,
                    out_path,
                    exc,
                )
            return consolidated

        rows: List[Dict[str, Any]] = []
        for _key, (_rank, item) in latest_by_key.items():
            if str(item.get("resolution", "")).lower() == "ignore":
                ignored += 1
                continue
            kept += 1
            rows.append(item)
        rows.sort(
            key=lambda r: (
                str(r.get("source_ts", "") or ""),
                str(r.get("question", "") or "").lower(),
                str(r.get("topic", "") or "").lower(),
            )
        )
        consolidated = {"questions": rows}
        try:
            with open(out_path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(consolidated, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("[SLEEP][QUESTIONS] Failed writing consolidated artifact project=%s: %s", project_id, e)
    logger.info(
        "[SLEEP][QUESTIONS] project=%s parsed=%s deduped=%s kept=%s ignored=%s",
        project_id,
        int(parsed),
        int(len(latest_by_key)),
        int(kept),
        int(ignored),
    )
    return consolidated
