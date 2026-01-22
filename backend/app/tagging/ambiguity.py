"""
Roll-off ambiguity classifier (DELTA-A.2).

This module performs a semantic ambiguity check on a rolled-off user/assistant pair.
It returns:
  - ambiguous: bool
  - reason: short string

On any failure, callers should treat ambiguous=False.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Tuple

from openai import OpenAI

from ..core.config import get_settings

logger = logging.getLogger(__name__)

_PROMPT = """You are an ambiguity classifier for conversational memory.

Your task is to determine whether the CURRENT conversation pair
(RESPONSE to USER MESSAGE) depends on the IMMEDIATELY PRECEDING
conversation pair to be correctly interpreted.

A pair is ambiguous ONLY if important meaning in the current user message
or assistant response cannot be understood WITHOUT the immediately prior
exchange.

Do NOT consider:
- General background knowledge
- Domain or story familiarity
- Named characters, places, or concepts introduced in this pair
- Earlier chapters, documents, or prior sessions

Do NOT assume access to anything except the current user message and
assistant response.

You must NOT attempt to resolve ambiguity.
You must NOT rewrite, summarize, or reinterpret content.
You must ONLY classify whether the immediately previous conversational turn
is required for correct interpretation.

Bias toward marking ambiguous ONLY when unresolved references clearly
depend on the immediately prior exchange.

CURRENT USER MESSAGE:
<<<USER_MESSAGE>>>

CURRENT ASSISTANT MESSAGE:
<<<ASSISTANT_MESSAGE>>>

Respond using EXACTLY the following format:

AMBIGUOUS: true | false
REASON: <one short sentence explaining why>
"""


def classify_ambiguity(user_text: str, assistant_text: str) -> Tuple[bool, str]:
    """
    Classify whether a rolled-off pair is ambiguous.

    Returns (ambiguous, reason). On any error, returns (False, reason).
    Always emits a debug log with AMBIGUOUS and REASON.
    """
    settings = get_settings()
    model = settings.ambiguity_model
    ambiguous = False
    reason = ""
    raw_preview = ""
    types = []
    incomplete = None
    try:
        msg = (
            _PROMPT.replace("<<<USER_MESSAGE>>>", user_text)
            .replace("<<<ASSISTANT_MESSAGE>>>", assistant_text)
            .strip()
            + "\n"
        )
        # Use OpenAI Responses API directly so we can omit unsupported sampling params
        # for GPT-5 family models (e.g., gpt-5-nano) while still getting textual output.
        client = OpenAI(api_key=settings.openai_api_key)
        # Note: some GPT-5 family models consume output tokens for reasoning by default.
        # Keep reasoning minimal and allocate enough output tokens for actual JSON text.
        try:
            r = client.responses.create(
                model=model,
                input=msg,
                max_output_tokens=512,
                reasoning={"effort": "minimal"},
            )
        except TypeError:
            # Older SDK / schema: fall back without reasoning parameter
            r = client.responses.create(
                model=model,
                input=msg,
                max_output_tokens=512,
            )

        # Extra debug context (helps explain "empty output" cases)
        try:
            output = getattr(r, "output", None) or []
            types = [getattr(it, "type", None) for it in (output or [])]
            incomplete = getattr(getattr(r, "incomplete_details", None), "reason", None)
        except Exception:
            logger.warning(
                "[AMBIGUITY_META_ERROR] Failed to read response metadata model=%s",
                model,
                exc_info=True,
            )

        raw = (getattr(r, "output_text", None) or "").strip()
        # Debug: log raw model output (truncated) before parsing and before final [AMBIGUITY] line
        try:
            raw_preview = (raw[:500] + ("…" if len(raw) > 500 else ""))
        except Exception:
            logger.warning(
                "[AMBIGUITY_RAW_PREVIEW_ERROR] Failed to build raw preview model=%s",
                model,
                exc_info=True,
            )
        if not raw:
            # Do not attempt to parse non-textual Responses objects. Treat as failure per DELTA-A.2.
            reason = "empty_output_text"
            ambiguous = False
        else:
            # Preferred parse: exact "AMBIGUOUS:" + "REASON:" lines (per ambiguity_prompt.txt)
            amb_match = re.search(r"(?im)^\s*AMBIGUOUS\s*:\s*(true|false)\s*$", raw)
            reason_match = re.search(r"(?im)^\s*REASON\s*:\s*(.+?)\s*$", raw)
            if amb_match:
                ambiguous = amb_match.group(1).lower() == "true"
                if reason_match:
                    reason = reason_match.group(1).strip()[:120]
                else:
                    reason = "missing_reason"
            else:
                # Back-compat: accept the previous JSON response format as fallback.
                try:
                    data = json.loads(raw)
                except Exception:
                    # Best-effort: try to extract JSON substring
                    start = raw.find("{")
                    end = raw.rfind("}")
                    if start >= 0 and end > start:
                        data = json.loads(raw[start : end + 1])
                    else:
                        raise
                ambiguous = bool(data.get("AMBIGUOUS", False))
                reason_val = data.get("REASON", "")
                reason = str(reason_val)[:120] if reason_val is not None else ""
    except Exception as e:
        ambiguous = False
        reason = f"classifier_error: {e}"
        logger.warning(
            "[AMBIGUITY_EXCEPTION] model=%s output_types=%s incomplete_reason=%s raw_preview=%r",
            model,
            types,
            incomplete,
            raw_preview,
            exc_info=True,
        )
    finally:
        # Required observability: always log boolean + reason.
        logger.debug("[AMBIGUITY] ambiguous=%s reason=%s model=%s", str(bool(ambiguous)).lower(), reason, model)
    return bool(ambiguous), reason

