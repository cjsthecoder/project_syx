"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""FastAPI router for local agent memory search."""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..core.state import is_sleeping
from ..security.agent_tokens import authorize_agent_token
from .parser import SnippetParseError
from .retrieval import (
    normalize_category,
    resolve_project_name,
    retrieve_agent_memory,
    write_agent_debug_files,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/agent/memory/search")
async def agent_memory_search(payload: Dict[str, Any]) -> JSONResponse:
    """Serve the read-only agent memory search endpoint.

    This is the external agent-memory interface boundary. It validates the
    request, authorizes the agent token, refuses retrieval while sleep holds
    the memory lock, and returns structured snippets. Retrieval never mutates
    project memory.

    Args:
        payload: Raw JSON request body containing ``agent_token``,
            ``project_name``, ``query``, and optional ``category``/``model``.

    Returns:
        A ``JSONResponse``. ``200`` with the structured snippet payload on
        success; ``400``/``401``/``403``/``404`` for validation or
        authorization failures; ``423`` when sleep is running; ``500`` when
        retrieval or snippet parsing fails.
    """
    request_payload = dict(payload or {})
    project_name = str(request_payload.get("project_name") or "")
    query = str(request_payload.get("query") or "")
    category = normalize_category(request_payload.get("category"))
    model = _optional_str(request_payload.get("model"))

    if "agent_token" not in request_payload:
        logger.warning("agent_memory_search missing agent_token field project_name=%s", project_name)
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "message": "Missing agent token."},
        )
    if not project_name.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "message": "project_name is required."},
        )
    if not query.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "message": "query is required."},
        )

    project = resolve_project_name(project_name)
    if project is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "project_not_found",
                "message": "No project exists with the requested project_name.",
                "project_name": project_name,
            },
        )

    auth = authorize_agent_token(project.id, str(request_payload.get("agent_token") or ""))
    if not auth.authorized:
        if auth.forbidden:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "forbidden",
                    "message": auth.message or "Agent token does not have access to the requested project.",
                    "project_name": project_name,
                },
            )
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "message": auth.message or "Missing or invalid agent token."},
        )

    if is_sleeping():
        return JSONResponse(
            status_code=423,
            content={
                "error": "memory_locked",
                "message": "Project memory is currently unavailable because sleep is running. Retry after sleep completes.",
                "project_id": project.id,
                "project_name": project_name,
                "retryable": True,
            },
        )

    raw_context = ""
    try:
        response, raw_context, parser_warnings = retrieve_agent_memory(
            project_name=project_name,
            project_id=project.id,
            query=query,
            category=category,
            model=model,
        )
        response_payload = response.to_response_dict()
        write_agent_debug_files(
            project_id=project.id,
            request_payload=request_payload,
            raw_context=raw_context,
            response_payload=response_payload,
            parser_warnings=parser_warnings,
        )
        return JSONResponse(status_code=200, content=response_payload)
    except SnippetParseError as exc:
        raw_context = getattr(exc, "raw_context", raw_context)
        logger.warning(
            "agent_memory_search snippet parse failed; project_id=%s detail=%s",
            project.id,
            exc,
        )
        error_payload = {
            "error": "snippet_parse_failed",
            "message": "Agent memory search retrieved context but could not convert it to structured snippets.",
            "retryable": False,
        }
        write_agent_debug_files(
            project_id=project.id,
            request_payload=request_payload,
            raw_context=raw_context,
            response_payload={},
            parser_warnings=[str(exc)],
            error_payload=error_payload,
        )
        return JSONResponse(status_code=500, content=error_payload)
    except Exception as exc:
        logger.exception("agent_memory_search failed; project_id=%s detail=%s", project.id, exc)
        return JSONResponse(
            status_code=500,
            content={"error": "agent_memory_search_failed", "message": "Agent memory search failed."},
        )


def _optional_str(value: Any) -> Optional[str]:
    """Coerce a raw request value into a trimmed optional string.

    Args:
        value: Arbitrary value taken from the request payload.

    Returns:
        The stripped string, or ``None`` when the value is ``None`` or blank.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None
