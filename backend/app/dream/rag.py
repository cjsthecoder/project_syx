"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Dream-specific RAG retrieval adapter for the Sleep/Dream pipeline.

Wraps the route-policy-driven daily/main memory merge so dream agents can
retrieve context with a deterministic synthetic route, returning a normalized
result dict (with empty-result fallbacks on failure).
"""
import logging
from typing import Any, Dict

from sqlmodel import select

from ..core.config import compute_per_source_k, get_settings
from ..core.database import get_session
from ..core.db_models import Project
from ..core.route_policy import get_route_policy
from ..rag.manager import merge_daily_and_main

logger = logging.getLogger(__name__)


def _empty_result(*, route: str, per_source_k: int = 0, max_keep: int = 0, daily_enabled: bool = False) -> Dict[str, Any]:
    return {
        "context_text": "",
        "tokens_used": 0,
        "daily_texts": [],
        "main_texts": [],
        "main_hits": 0,
        "daily_hits": 0,
        "total_hits": 0,
        "ordered_candidates": 0,
        "selected_candidates": 0,
        "kept_candidates": 0,
        "expanded_unique_chunks_after_merge": 0,
        "route": route,
        "per_source_k": int(per_source_k),
        "max_keep": int(max_keep),
        "daily_enabled": bool(daily_enabled),
    }


def _daily_enabled(project_id: str) -> bool:
    """Return the project's daily-RAG flag, defaulting to True when lookup fails."""
    try:
        with get_session() as session:
            project = session.exec(select(Project).where(Project.id == project_id)).first()
            if project is not None:
                return bool(project.daily_rag_enabled)
    except Exception as exc:
        logger.debug("[DREAM][RAG] daily flag lookup failed project=%s detail=%s", project_id, exc)
    return True


def retrieve_dream_context(
    *,
    project_id: str,
    query: str,
    route: str = "EXPLORATORY",
    include_daily: bool = True,
) -> Dict[str, Any]:
    """
    Dream-specific retrieval adapter.

    Dream agents do not run the chat builder during sleep, so callers provide a
    deterministic synthetic route. Retrieval still goes through the same
    route-policy-driven merge/selection/expansion path used by chat.
    """
    resolved_route = (route or "OTHER").strip().upper() or "OTHER"
    try:
        settings = get_settings()
        policy = get_route_policy(resolved_route)
        per_source_k = compute_per_source_k(int(settings.base_top_k), float(policy.retrieval_multiplier))
        max_keep = int(policy.max_keep)
        daily_enabled = bool(include_daily) and _daily_enabled(project_id)

        if per_source_k <= 0 or max_keep <= 0:
            return _empty_result(
                route=resolved_route,
                per_source_k=per_source_k,
                max_keep=max_keep,
                daily_enabled=daily_enabled,
            )

        result = merge_daily_and_main(
            project_id=project_id,
            query=query,
            daily_enabled=daily_enabled,
            max_keep=max_keep,
            route=resolved_route,
            per_source_k_override=per_source_k,
        )
        result["route"] = resolved_route
        result["per_source_k"] = int(per_source_k)
        result["max_keep"] = int(max_keep)
        result["daily_enabled"] = bool(daily_enabled)
        return result
    except Exception as exc:
        logger.warning(
            "[DREAM][RAG] Expanded retrieval failed project=%s route=%s query=%r detail=%s",
            project_id,
            resolved_route,
            (query or "")[:120],
            exc,
            exc_info=True,
        )
        return _empty_result(route=resolved_route)
