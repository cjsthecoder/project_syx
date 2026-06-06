"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Dream status API endpoint for the Syx AGI Chatbot Framework.

Exposes a stub /dream/status route that currently reports no available dreams
regardless of the dream feature flag.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from ..core.config import get_settings
from ..utils.logging import RequestLogger

router = APIRouter()
request_logger = RequestLogger("dream")


@router.get("/dream/status")
async def dream_status() -> JSONResponse:
    """Stub status for 4.1.1 - always returns no dreams yet."""
    try:
        request_logger.log_request(endpoint="/dream/status", method="GET")
        # 4.1.1: always return empty/no dreams, regardless of ENABLE_DREAM
        return JSONResponse(status_code=200, content={"has_dreams": False, "count": 0})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


