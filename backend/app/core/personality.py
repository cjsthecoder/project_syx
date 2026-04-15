"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
from __future__ import annotations
"""
Project system prompt and personality management (V2.6).

Responsibilities:
- Load per-project `system_prompt.txt` and `personality.json` with caching
- Save updates and invalidate cache
- Seed defaults for new projects and backfill missing files for existing ones
"""

import json
import logging
import os
from typing import Any, Dict, Optional, Tuple

from .config import get_settings
from .database import get_session
from .db_models import Project

logger = logging.getLogger(__name__)

_PROMPT_CACHE: Dict[str, str] = {}
_PERSONALITY_CACHE: Dict[str, Dict[str, Any]] = {}

# Resolve repository root for robust relative-path handling
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))


def _project_dir(project_id: str) -> str:
    return os.path.join(get_settings().memory_root, project_id)


def _project_prompt_path(project_id: str) -> str:
    return os.path.join(_project_dir(project_id), "system_prompt.txt")


def _project_personality_path(project_id: str) -> str:
    return os.path.join(_project_dir(project_id), "personality.json")


def ensure_directories(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        logger.warning("[PROJECT] ensure_directories failed path=%s detail=%s", path, exc)


def load_default_prompt_and_personality() -> Tuple[str, Dict[str, Any]]:
    settings = get_settings()
    # Default prompt from file only
    try:
        path = settings.default_system_prompt_path
        exists = os.path.isfile(path)
        resolved_path = path
        if (not exists) and (not os.path.isabs(path)):
            alt = os.path.join(_REPO_ROOT, path)
            if os.path.isfile(alt):
                resolved_path = alt
                exists = True
                logger.debug("[PROJECT] Default system_prompt resolved via REPO_ROOT: %s", resolved_path)
        size = os.path.getsize(resolved_path) if exists else 0
        logger.debug(
            "[PROJECT] Default system_prompt path=%s exists=%s size_bytes=%s",
            resolved_path,
            exists,
            size,
        )
        with open(resolved_path, "r", encoding="utf-8") as f:
            default_prompt = f.read()
    except Exception:
        default_prompt = ""
        logger.debug("[PROJECT] Default system_prompt file missing; using empty prompt")
    # Default personality from file only
    try:
        ppath = settings.default_personality_prompt_path
        pexists = os.path.isfile(ppath)
        presolved = ppath
        if (not pexists) and (not os.path.isabs(ppath)):
            palt = os.path.join(_REPO_ROOT, ppath)
            if os.path.isfile(palt):
                presolved = palt
                pexists = True
                logger.debug("[PROJECT] Default personality resolved via REPO_ROOT: %s", presolved)
        psize = os.path.getsize(presolved) if pexists else 0
        logger.debug(
            "[PROJECT] Default personality path=%s exists=%s size_bytes=%s",
            presolved,
            pexists,
            psize,
        )
        with open(presolved, "r", encoding="utf-8") as f:
            obj = json.load(f)
            default_personality = obj if isinstance(obj, dict) else {}
            if not isinstance(obj, dict):
                logger.debug("[PROJECT] Default personality file invalid; using empty personality")
    except Exception:
        default_personality = {}
        logger.debug("[PROJECT] Default personality file missing; using empty personality")
    return default_prompt, default_personality


def seed_project_defaults(project_id: str) -> None:
    """Create per-project prompt/personality files if missing, using defaults.

    Called on project creation and during startup backfill.
    """
    ensure_directories(_project_dir(project_id))
    prompt_path = _project_prompt_path(project_id)
    pers_path = _project_personality_path(project_id)
    default_prompt, default_personality = load_default_prompt_and_personality()
    wrote_any = False
    if not os.path.isfile(prompt_path):
        try:
            with open(prompt_path, "w", encoding="utf-8") as f:
                f.write(default_prompt or "")
            wrote_any = True
        except OSError as exc:
            logger.warning("[PROJECT] Failed writing project prompt project_id=%s path=%s detail=%s", project_id, prompt_path, exc)
    if not os.path.isfile(pers_path):
        try:
            with open(pers_path, "w", encoding="utf-8") as f:
                json.dump(default_personality, f, ensure_ascii=False, indent=2)
            wrote_any = True
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("[PROJECT] Failed writing project personality project_id=%s path=%s detail=%s", project_id, pers_path, exc)
    if wrote_any:
        logger.debug("[PROJECT] Loaded system_prompt=system_prompt.txt personality=personality.json")


def backfill_all_projects() -> None:
    """Ensure all existing projects have default files present."""
    try:
        with get_session() as session:
            rows = session.query(Project).all()  # type: ignore[attr-defined]
            for p in rows or []:
                seed_project_defaults(p.id)
    except Exception as exc:
        # Non-fatal startup backfill path; request handling can continue.
        logger.warning("[PROJECT] Backfill failed for existing projects detail=%s", exc)


def _validate_sizes(prompt_text: Optional[str], personality_json: Optional[Dict[str, Any]]) -> None:
    settings = get_settings()
    if prompt_text is not None:
        if len(prompt_text.encode("utf-8")) > settings.system_prompt_max_bytes:
            raise ValueError("system_prompt exceeds size limit")
    if personality_json is not None:
        payload = json.dumps(personality_json, ensure_ascii=False)
        if len(payload.encode("utf-8")) > settings.personality_max_bytes:
            raise ValueError("personality exceeds size limit")


def _normalize_personality(p: Dict[str, Any]) -> Dict[str, Any]:
    tone = str(p.get("tone", "")).strip().lower() or "analytical"
    verbosity = str(p.get("verbosity", "")).strip().lower() or "concise"
    fmt = str(p.get("format", "")).strip().lower() or "markdown"
    creativity = p.get("creativity", 0.4)
    try:
        creativity = float(creativity)
    except Exception:
        creativity = 0.4
    if creativity < 0.0 or creativity > 1.0:
        creativity = max(0.0, min(1.0, creativity))
    domain_focus = p.get("domain_focus")
    if not isinstance(domain_focus, list):
        domain_focus = []
    return {
        "tone": tone,
        "verbosity": verbosity,
        "format": fmt,
        "creativity": creativity,
        "domain_focus": domain_focus,
    }


def load_project_system_prompt(project_id: str) -> str:
    cached = _PROMPT_CACHE.get(project_id)
    if cached is not None:
        return cached
    path = _project_prompt_path(project_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
            _validate_sizes(text, None)
            # If project file exists but is effectively empty, fall back to default file
            if not (text or "").strip():
                dtext, _ = load_default_prompt_and_personality()
                logger.debug(
                    "[PROJECT] Empty project system_prompt; using default (bytes=%s)",
                    len((dtext or "").encode("utf-8")),
                )
                _PROMPT_CACHE[project_id] = dtext
                return dtext
            _PROMPT_CACHE[project_id] = text
            logger.debug(
                "[PROJECT] Loaded project system_prompt path=%s bytes=%s",
                path,
                len(text.encode("utf-8")),
            )
            return text
    except Exception:
        # Fallback to default file content (may be empty)
        default_prompt, _ = load_default_prompt_and_personality()
        if not default_prompt:
            logger.debug("[PROJECT] Using default system prompt and personality (empty prompt)")
        _PROMPT_CACHE[project_id] = default_prompt
        return default_prompt


def load_project_personality(project_id: str) -> Dict[str, Any]:
    cached = _PERSONALITY_CACHE.get(project_id)
    if cached is not None:
        return cached
    path = _project_personality_path(project_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
            if not isinstance(obj, dict):
                raise ValueError("invalid personality json")
            norm = _normalize_personality(obj)
            _validate_sizes(None, norm)
            _PERSONALITY_CACHE[project_id] = norm
            logger.debug(
                "[PROJECT] Loaded project personality path=%s keys=%s",
                path,
                sorted(list(norm.keys())),
            )
            return norm
    except Exception:
        _, default_personality = load_default_prompt_and_personality()
        logger.debug("[PROJECT] Using default system prompt and personality (empty personality possible)")
        norm = _normalize_personality(default_personality)
        _PERSONALITY_CACHE[project_id] = norm
        return norm


def save_project_system_prompt(project_id: str, content: str) -> None:
    _validate_sizes(content, None)
    ensure_directories(_project_dir(project_id))
    path = _project_prompt_path(project_id)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content or "")
    _PROMPT_CACHE.pop(project_id, None)
    logger.debug(
        "[PROJECT] Saved project system_prompt path=%s bytes=%s",
        path,
        len((content or "").encode("utf-8")),
    )


def save_project_personality(project_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    norm = _normalize_personality(payload or {})
    _validate_sizes(None, norm)
    ensure_directories(_project_dir(project_id))
    path = _project_personality_path(project_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(norm, f, ensure_ascii=False, indent=2)
    _PERSONALITY_CACHE.pop(project_id, None)
    logger.debug(
        "[PROJECT] Saved project personality path=%s keys=%s",
        path,
        sorted(list(norm.keys())),
    )
    return norm


