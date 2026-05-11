"""
Copyright (c) 2025-2026 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Dream-specific debug artifact writers.
"""

import re
from datetime import datetime
from typing import Optional

from ..utils.debug_utils import write_debug_file
from ..utils.tokens import count_tokens


def safe_dream_purpose(value: Optional[str]) -> str:
    purpose = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "dream").strip())
    return purpose.strip("_") or "dream"


def write_dream_prompt_to_execute(
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
    safe_purpose = safe_dream_purpose(purpose)
    body = (
        f"# timestamp: {ts}\n"
        f"# project_id: {project_id}\n"
        f"# dream_purpose: {safe_purpose}\n"
        f"# model: {model}\n"
        f"# max_output_tokens_requested: {max_output_tokens}\n"
        f"# total_tokens_estimate: {count_tokens(prompt or '')}\n"
        "\n"
        "====== SYSTEM ======\n"
        "(none)\n"
        "\n"
        "====== USER PROMPT ======\n"
        f"{prompt or ''}"
        "\n"
    )
    write_debug_file(project_id, f"dreaming/{ts}_{safe_purpose}_prompt_to_execute.txt", body)


def write_dream_response_usage_debug(
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
        f"# dream_purpose: {safe_dream_purpose(purpose)}\n"
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
    filename = f"dreaming/{ts}_{safe_dream_purpose(purpose)}_response_usage.txt"
    write_debug_file(project_id, filename, body)
