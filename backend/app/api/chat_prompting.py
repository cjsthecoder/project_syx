from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from ..utils.debug_utils import write_debug_file
from ..utils.logging import get_route

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
    """Best-effort token estimate for debug headers."""
    try:
        import tiktoken  # type: ignore

        enc = tiktoken.get_encoding("cl100k_base")
        return int(len(enc.encode(text or "")))
    except Exception:
        return int(len((text or "").split()))


def estimate_message_tokens(messages: list) -> int:
    """Best-effort token estimate over structured message list."""
    try:
        text = "\n".join(str((m.get("content") or "")) for m in (messages or []) if isinstance(m, dict))
        return int(estimate_tokens(text))
    except (AttributeError, TypeError, ValueError):
        return 0


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
    """
    Write a prompt debug snapshot to memory/{project_id}/debug/prompts/.
    Safe/no-op when project_id is missing or debug files are disabled.
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
