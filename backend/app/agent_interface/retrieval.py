"""
Copyright (c) 2025-2026 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""Retrieval adapter for the A.4 agent memory search endpoint."""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlmodel import select

from ..core.config import compute_per_source_k, get_settings
from ..core.database import get_session
from ..core.db_models import Project
from ..core.route_policy import EXPECTED_ROUTES, get_route_policy
from ..rag.manager import merge_daily_and_main
from ..utils.debug_utils import write_debug_file
from .entry_expansion import expand_agent_memory_snippets
from .models import AgentMemorySearchResponse, AgentMemorySnippet
from .parser import SnippetParseError, parse_prompt_context_to_snippets

logger = logging.getLogger(__name__)


def resolve_project_name(project_name: str) -> Optional[Project]:
    wanted = str(project_name or "").strip().lower()
    if not wanted:
        return None
    with get_session() as session:
        rows = list(session.exec(select(Project)).all())
    matches = [project for project in rows if str(project.name or "").strip().lower() == wanted]
    if len(matches) > 1:
        logger.warning(
            "agent_memory_search duplicate project_name match; project_name=%s count=%s using_project_id=%s",
            project_name,
            len(matches),
            matches[0].id,
        )
    return matches[0] if matches else None


def normalize_category(category: Any) -> str:
    route = str(category or "OTHER").strip().upper() or "OTHER"
    allowed = {r for r in EXPECTED_ROUTES if r != "CHITCHAT"}
    return route if route in allowed else "OTHER"


def retrieve_agent_memory(
    *,
    project_name: str,
    project_id: str,
    query: str,
    category: str,
    model: Optional[str],
) -> tuple[AgentMemorySearchResponse, str, List[str]]:
    settings = get_settings()
    policy = get_route_policy(category or "OTHER")
    per_source_k = compute_per_source_k(int(settings.base_top_k), float(policy.retrieval_multiplier))
    max_keep = int(policy.max_keep)
    parser_warnings: List[str] = []

    if int(per_source_k) <= 0 or int(max_keep) <= 0:
        snippets: List[AgentMemorySnippet] = []
        raw_context = ""
    else:
        result = merge_daily_and_main(
            project_id=project_id,
            query=query,
            daily_enabled=_daily_enabled(project_id),
            max_keep=max_keep,
            route=category or "OTHER",
            per_source_k_override=int(per_source_k),
        )
        raw_context = str(result.get("context_text") or "")
        try:
            snippets = parse_prompt_context_to_snippets(raw_context)
        except SnippetParseError as exc:
            exc.raw_context = raw_context
            raise
        except Exception as exc:
            raise SnippetParseError(str(exc), raw_context=raw_context) from exc
        snippets = expand_agent_memory_snippets(project_id=project_id, snippets=snippets)

    response = _build_response(
        project_name=project_name,
        project_id=project_id,
        query=query,
        category=category,
        model=model,
        snippets=snippets,
    )
    return response, raw_context, parser_warnings


def write_agent_debug_files(
    *,
    project_id: str,
    request_payload: Dict[str, Any],
    raw_context: str,
    response_payload: Dict[str, Any],
    parser_warnings: Optional[List[str]] = None,
    error_payload: Optional[Dict[str, Any]] = None,
) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    query_body = {
        "timestamp": ts,
        "project_id": project_id,
        "request": request_payload,
        "raw_prompt_context": raw_context,
        "parser_warnings": parser_warnings or [],
    }
    response_body = {
        "timestamp": ts,
        "project_id": project_id,
        "response": response_payload,
        "error": error_payload,
        "parser_warnings": parser_warnings or [],
        "entry_expansion_summary": _entry_expansion_summary(response_payload),
    }
    write_debug_file(
        project_id,
        f"agent_interface/{ts}_agent_query.txt",
        json.dumps(query_body, ensure_ascii=False, indent=2),
    )
    write_debug_file(
        project_id,
        f"agent_interface/{ts}_agent_response.txt",
        json.dumps(response_body, ensure_ascii=False, indent=2),
    )


def _build_response(
    *,
    project_name: str,
    project_id: str,
    query: str,
    category: str,
    model: Optional[str],
    snippets: List[AgentMemorySnippet],
) -> AgentMemorySearchResponse:
    bounded = sum(1 for snip in snippets if snip.result_mode == "bounded_entry")
    unbounded = int(len(snippets) - bounded)
    return AgentMemorySearchResponse(
        project_name=project_name,
        project_id=project_id,
        category=category,
        query=query,
        model=model,
        snippet_count=len(snippets),
        bounded_result_count=bounded,
        unbounded_result_count=unbounded,
        snippets=snippets,
    )


def _daily_enabled(project_id: str) -> bool:
    try:
        with get_session() as session:
            project = session.get(Project, project_id)
            if project is not None:
                return bool(project.daily_rag_enabled)
    except Exception as exc:
        logger.warning(
            "agent_memory_search daily flag lookup failed; project_id=%s detail=%s",
            project_id,
            exc,
        )
    return True


def _entry_expansion_summary(response_payload: Dict[str, Any]) -> Dict[str, Any]:
    snippets = response_payload.get("snippets")
    if not isinstance(snippets, list):
        snippets = []
    bounded = [snip for snip in snippets if isinstance(snip, dict) and snip.get("result_mode") == "bounded_entry"]
    statuses: Dict[str, int] = {}
    methods: Dict[str, int] = {}
    memory_ids: List[str] = []
    truncated = 0
    for snip in snippets:
        if not isinstance(snip, dict):
            continue
        status = str(snip.get("entry_expansion_status") or "missing")
        method = str(snip.get("entry_expansion_method") or "missing")
        statuses[status] = statuses.get(status, 0) + 1
        methods[method] = methods.get(method, 0) + 1
        if snip.get("entry_expansion_truncated") is True:
            truncated += 1
        mid = snip.get("memory_id")
        if isinstance(mid, str) and mid.strip():
            memory_ids.append(mid)
    return {
        "bounded_snippets": int(len(bounded)),
        "expanded": int(statuses.get("expanded", 0)),
        "expanded_truncated": int(statuses.get("expanded_truncated", 0)),
        "fallback": int(statuses.get("fallback", 0)),
        "failed": int(statuses.get("failed", 0)),
        "truncated": int(truncated),
        "memory_ids": memory_ids,
        "statuses": statuses,
        "methods": methods,
    }
