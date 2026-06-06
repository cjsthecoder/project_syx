"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Models API endpoint - returns available chat models.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..core.config import get_settings


router = APIRouter()


@router.get("/models")
async def get_models() -> JSONResponse:
    settings = get_settings()
    return JSONResponse(status_code=200, content={"models": settings.available_models})


