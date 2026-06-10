"""
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
    """Return the list of selectable chat models and the default selection.

    Returns:
        JSON object ``{"models": [...], "default": "<model_name>"}`` containing
        the configured whitelist of available model identifiers and the default
        model (``MODEL_NAME``) the UI should pre-select.
    """
    settings = get_settings()
    return JSONResponse(
        status_code=200,
        content={"models": settings.available_models, "default": settings.model_name},
    )
