"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import logging
import re
from datetime import datetime
from typing import Optional

from ..core.config import get_settings
from ..llm_model.factory import get_llm_client
from ..utils.debug_utils import write_debug_file
from ..utils.tokens import count_tokens

logger = logging.getLogger(__name__)


def _safe_purpose(value: Optional[str]) -> str:
    purpose = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "dream").strip())
    return purpose.strip("_") or "dream"


def _write_prompt_to_execute(
    *,
    project_id: Optional[str],
    prompt: str,
    purpose: Optional[str],
    model: str,
    max_output_tokens: int,
) -> None:
    if not project_id:
        return
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    filename = f"dreaming/{ts}_{_safe_purpose(purpose)}_prompt_to_execute.txt"
    body = (
        f"# timestamp: {ts}\n"
        f"# project_id: {project_id}\n"
        f"# dream_purpose: {_safe_purpose(purpose)}\n"
        f"# model: {model}\n"
        f"# prompt_tokens_estimate: {count_tokens(prompt or '')}\n"
        f"# max_output_tokens_requested: {max_output_tokens}\n"
        "\n"
        "====== SYSTEM ======\n"
        "(none)\n"
        "\n"
        "====== USER ======\n"
        f"{prompt or ''}"
        "\n"
    )
    write_debug_file(project_id, filename, body)


def _write_response_usage_debug(
    *,
    project_id: Optional[str],
    response_text: str,
    purpose: Optional[str],
    model: str,
    max_output_tokens: int,
    usage: object,
) -> None:
    if not project_id:
        return
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    usage_extra = getattr(usage, "extra_usage", None)
    body = (
        f"# timestamp: {ts}\n"
        f"# project_id: {project_id}\n"
        f"# dream_purpose: {_safe_purpose(purpose)}\n"
        f"# model: {model}\n"
        f"# max_output_tokens_requested: {max_output_tokens}\n"
        f"# prompt_tokens_reported: {getattr(usage, 'prompt_tokens_reported', 0)}\n"
        f"# completion_tokens_reported: {getattr(usage, 'completion_tokens_reported', 0)}\n"
        f"# total_tokens_reported: {getattr(usage, 'total_tokens_reported', 0)}\n"
        f"# usage_is_estimate: {str(bool(getattr(usage, 'usage_is_estimate', True))).lower()}\n"
        f"# response_tokens_estimate: {count_tokens(response_text or '')}\n"
        f"# extra_usage: {usage_extra if usage_extra is not None else ''}\n"
        "\n"
        "====== RESPONSE ======\n"
        f"{response_text or ''}"
        "\n"
    )
    filename = f"dreaming/{ts}_{_safe_purpose(purpose)}_response_usage.txt"
    write_debug_file(project_id, filename, body)


def dream_llm_call(
    prompt: str,
    max_output_tokens: Optional[int] = None,
    *,
    project_id: Optional[str] = None,
    purpose: Optional[str] = None,
) -> str:
    """
    Thin wrapper over OpenAI Responses API for Dream.
    Returns the text content (string) of the response.
    """
    settings = get_settings()
    max_tokens = int(max_output_tokens or settings.dream_max_tokens)
    model = str(settings.dream_model)
    _write_prompt_to_execute(
        project_id=project_id,
        prompt=prompt,
        purpose=purpose,
        model=model,
        max_output_tokens=max_tokens,
    )
    try:
        response = get_llm_client().generate_response(
            model=model,
            system_prompt=None,
            user_prompt=prompt,
            temperature=float(settings.dream_temperature),
            max_output_tokens=max_tokens,
        )
        _write_response_usage_debug(
            project_id=project_id,
            response_text=response.text,
            purpose=purpose,
            model=model,
            max_output_tokens=max_tokens,
            usage=response.usage,
        )
        return response.text
    except Exception as e:
        logger.warning("[DREAM][WARN] LLM call failed: %s", e)
        return '{"answer": "Dream agent failed to generate a valid answer."}'



