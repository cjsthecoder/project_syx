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


