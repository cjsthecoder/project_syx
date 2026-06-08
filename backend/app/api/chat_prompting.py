"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Prompt construction and debugging helpers for the Syx chat API.

Defines the RAG system prompt, token estimation helpers, and a debug snapshot
writer that dumps the full assembled prompt to a project's debug directory.
"""
import logging
from datetime import datetime
from typing import Optional

from ..utils.debug_utils import write_debug_file
from ..utils.logging import get_route
from ..utils.tokens import count_message_content_tokens, count_tokens

logger = logging.getLogger(__name__)

RAG_SYSTEM_PROMPT = """Each retrieved snippet includes a similarity score in the range [0.0-1.0].
The similarity score reflects semantic closeness to the query, not factual correctness.

Guidance for use:
- Higher scores indicate stronger semantic relevance to the current query.
- Prefer high-scoring snippets when making factual claims or direct assertions.
- Lower-scoring snippets may be used for background, framing, or creative inspiration.
- Do not treat lower-scoring snippets as authoritative unless supported by higher-scoring context.

When multiple snippets conflict:
- Favor information from higher-scoring snippets.
- If only lower-scoring snippets are available, respond cautiously and note uncertainty.

Output constraint:
- Do NOT include similarity scores, snippet numbers, filenames, page numbers, routes, or other retrieval
metadata in your response unless the user explicitly asks for them.
- Use scores only to guide which retrieved text to rely on.
"""


def estimate_tokens(text: str) -> int:
    """Best-effort token estimate for debug headers.

    Args:
        text: Text to count tokens for; ``None`` is treated as empty.

    Returns:
        Estimated token count for the text.
    """
    return int(count_tokens(text or ""))


def estimate_message_tokens(messages: list) -> int:
    """Best-effort token estimate over a structured message list.

    Args:
        messages: List of role/content message dicts; ``None`` is treated as
            empty.

    Returns:
        Estimated token count across the messages' content.
    """
    return int(count_message_content_tokens(messages or []))


def dump_prompt_debug(
    *,
    project_id: Optional[str],
    base_system_prompt: Optional[str],
    assistant_hint: Optional[str],
    rag_system_prompt: Optional[str],
    conversation_history: Optional[list[dict]],
    user_prompt: Optional[str],
    model: Optional[str],
    msgs: Optional[list] = None,
) -> None:
    """Write a prompt debug snapshot to ``memory/{project_id}/debug/prompts/``.

    Assembles the full prompt (system, assistant hint, RAG context,
    conversation history, and user prompt) with a metadata header into a
    timestamped file. Safe/no-op when ``project_id`` is missing or debug files
    are disabled.

    Args:
        project_id: Project whose debug directory receives the snapshot;
            ``None`` makes the call a no-op.
        base_system_prompt: Base system prompt text.
        assistant_hint: Assistant personality/preferences hint text.
        rag_system_prompt: Injected RAG context text, if any.
        conversation_history: Prior turns as role/content message dicts.
        user_prompt: Current user message.
        model: Resolved model id, recorded in the header.
        msgs: Reserved for future exact-payload debug variants; currently
            unused.
    """
    if not project_id:
        return
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    fname = f"{ts}_prompt_to_execute.txt"
    route = None
    try:
        route = get_route()
    except Exception as exc:
        logger.debug("chat.prompt_debug failed reading route; detail=%s", exc)
        route = None
    rag_used = bool(rag_system_prompt)
    _ = msgs  # Reserved for future exact-payload debug variants.

    # Build conversation history section
    hist_lines: list[str] = []
    if conversation_history:
        for m in conversation_history:
            role = (m.get("role") or "").lower()
            content = (m.get("content") or "")
            if role == "user":
                hist_lines.append("USER:")
                hist_lines.append(content)
                hist_lines.append("")
            elif role == "assistant":
                hist_lines.append("ASSISTANT:")
                hist_lines.append(content)
                hist_lines.append("")
            else:
                hist_lines.append(f"{role.upper()}:")
                hist_lines.append(content)
                hist_lines.append("")
    hist_text = "\n".join(hist_lines).rstrip() + ("\n" if hist_lines else "")

    body = (
        f"# timestamp: {ts}\n"
        + (f"# project_id: {project_id}\n" if project_id else "")
        + (f"# route: {route}\n" if route else "")
        + f"# rag: {str(bool(rag_used)).lower()}\n"
        + (f"# model: {model}\n" if model else "")
    )
    # Estimate tokens over the whole formatted dump (best-effort).
    payload_preview = (
        "====== SYSTEM ======\n"
        + (base_system_prompt or "")
        + "\n\n====== ASSISTANT_HINT ======\n"
        + (assistant_hint or "")
        + "\n\n====== (RAG CONTEXT) ======\n"
        + (rag_system_prompt or "")
        + "\n\n====== CONVERSATION HISTORY ======\n"
        + hist_text
        + "\n====== USER PROMPT ======\n"
        + (user_prompt or "")
        + "\n"
    )
    body += f"# total_tokens_estimate: {estimate_tokens(body + payload_preview)}\n\n"
    body += payload_preview

    write_debug_file(project_id, f"prompts/{fname}", body)
