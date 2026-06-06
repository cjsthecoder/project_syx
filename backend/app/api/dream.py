"""
Copyright (c) 2025-2026 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
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


