"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Models API endpoint - returns provider-qualified selectable chat models.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..llm_model.registry import get_active_llm_models, selectable_model_values

router = APIRouter()


@router.get("/models")
async def get_models() -> JSONResponse:
    """Return selectable provider/model values and the default selection.

    Returns:
        JSON object ``{"models": [...], "default": "<provider>/<model>"}``.
        The response shape is preserved for the frontend, while values carry
        provider identity.
    """
    active = get_active_llm_models()
    return JSONResponse(
        status_code=200,
        content={"models": selectable_model_values(), "default": active.selection_value},
    )
