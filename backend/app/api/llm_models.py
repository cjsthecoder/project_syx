"""



Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.

"""

"""
Models API endpoint - returns available chat models (V2).
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..core.config import get_settings


router = APIRouter()


@router.get("/models")
async def get_models() -> JSONResponse:
    settings = get_settings()
    return JSONResponse(status_code=200, content={"models": settings.available_models})


