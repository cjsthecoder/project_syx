"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import logging
import json
import time
from typing import Dict, Optional, Any
from datetime import datetime

from .config import get_settings
from .tracking import get_instrumentation
from ..utils.debug_utils import write_debug_file
from openai import OpenAI

logger = logging.getLogger(__name__)

_SYS_PROMPT = """You are a memory tagging system.

Your task is to extract compact, durable metadata for later retrieval.
The goal is to help future searches reliably find this exchange.

Use ONLY the content provided.
Do NOT invent information.
Do NOT infer long term meaning beyond what is explicit.

Prefer tags that:
- Would plausibly be used as search queries later
- Represent concrete concepts, entities, or themes
- Are stable over time

If present, extract:
- Proper names (people, organizations, projects, locations, technologies)
- Clearly stated topics or subject matter
- The user’s intent in asking the question
- The general category of the exchange

Guidelines:
- Use 3 to 7 topics maximum
- Topics should be lowercase, comma separated keywords
- Include proper names exactly as written
- Do not include filler words or generic terms
- Avoid one off or throwaway details

Intent should describe the purpose of the exchange, for example:
- explore story ideas
- ask for explanation
- design a system
- evaluate consequences
- clarify a concept

Type should be one or two broad categories such as:
technical, story, design, system, research, planning, meta

Semantic handle:
- A short, human readable noun phrase that names what this exchange is about
- Should be understandable without surrounding conversation
- Should avoid pronouns like this, that, it, we
- Should not be a full sentence
- Prefer 5 to 12 words
- Do not include commentary or explanation

Return STRICT JSON only. No prose. No markdown fences.

Schema:
{"topics":"","intent":"","type":"","semantic_handle":""}

Rules:
- Always include all keys shown in the schema.
- Use "" (empty string) for unknown values. Do not output null.
"""


def _responses_text(resp: Any) -> str:
    """Extract text content from an OpenAI Responses API response."""
    try:
        text = getattr(resp, "output_text", None)
        if isinstance(text, str) and text:
            return text
    except Exception:
        pass
    out: list[str] = []
    try:
        for item in getattr(resp, "output", []) or []:
            if getattr(item, "type", "") == "message":
                for c in getattr(item, "content", []) or []:
                    if getattr(c, "type", "") == "output_text":
                        out.append(getattr(c, "text", "") or "")
    except Exception:
        pass
    return "".join(out).strip()


def _slice_first_json(text: str) -> str:
    """Best-effort extraction of the first balanced JSON object from text."""
    if not text:
        return text
    in_string = False
    string_quote = ""
    escape_next = False
    depth = 0
    start = -1
    end = -1
    for i, ch in enumerate(text):
        if in_string:
            if escape_next:
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                continue
            if ch == string_quote:
                in_string = False
            continue
        if ch == '"' or ch == "'":
            in_string = True
            string_quote = ch
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
            continue
        if ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
    if start != -1 and end != -1:
        return text[start:end]
    return text


def tag_pair(
    user_text: str,
    assistant_text: str,
    previous_pair_text: Optional[str] = None,
    *,
    project_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Generate tag metadata (#topics, #intent, #type, #semantic_handle) using the builder model.

    Return value:
    - None on failure
    - On success: {"topics": str, "intent": str, "type": str, "semantic_handle": Optional[str]}
      where semantic_handle is None if the line is missing, or a string (possibly empty) if present.
    """
    try:
        settings = get_settings()
        instr = get_instrumentation()
        invocation_id = instr.start_invocation(
            purpose="tagger",
            model=settings.builder_model,
            meta={"project_id": project_id or ""},
        )
        t0 = time.perf_counter()
        usage: Dict[str, Any] = {
            "purpose": "tagger",
            "model": settings.builder_model,
            "prompt_tokens_reported": 0,
            "completion_tokens_reported": 0,
            "total_tokens_reported": 0,
            "usage_is_estimate": True,
        }
        context = (previous_pair_text + "\n\n") if previous_pair_text else ""
        user_prompt = f"{context}USER: {user_text}\nASSISTANT: {assistant_text}\n"

        client = OpenAI(api_key=settings.openai_api_key)
        raw = ""
        data: Optional[Dict[str, Any]] = None
        try:
            resp = client.responses.create(
                model=settings.builder_model,
                input=[
                    {"role": "system", "content": _SYS_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                # Guarantee a JSON text payload (avoid reasoning-only outputs).
                text={"format": {"type": "json_object"}},
                reasoning={"effort": "low"},
                max_output_tokens=int(settings.builder_max_tokens),
            )
        except Exception:
            resp = client.responses.create(
                model=settings.builder_model,
                input=_SYS_PROMPT + "\n\n" + user_prompt,
                text={"format": {"type": "json_object"}},
                reasoning={"effort": "low"},
                max_output_tokens=int(settings.builder_max_tokens),
            )
        try:
            u = getattr(resp, "usage", None)
            prompt_tok = int(getattr(u, "input_tokens", 0) or 0) if u is not None else 0
            completion_tok = int(getattr(u, "output_tokens", 0) or 0) if u is not None else 0
            total_tok = int(getattr(u, "total_tokens", 0) or (prompt_tok + completion_tok))
            if total_tok > 0:
                usage = {
                    "purpose": "tagger",
                    "model": settings.builder_model,
                    "prompt_tokens_reported": prompt_tok,
                    "completion_tokens_reported": completion_tok,
                    "total_tokens_reported": total_tok,
                    "usage_is_estimate": False,
                }
        except Exception:
            pass
        raw = _responses_text(resp)
        clean = raw
        if clean.startswith("```"):
            lines2 = [ln for ln in clean.splitlines() if not ln.strip().startswith("```")]
            clean = "\n".join(lines2).strip()
        clean = _slice_first_json(clean)
        try:
            data = json.loads(clean)
        except Exception:
            data = None
        if not isinstance(data, dict):
            raise ValueError("tagger returned non-json output")

        topics = str(data.get("topics", "") or "")
        intent = str(data.get("intent", "") or "")
        tag_type = str(data.get("type", "") or "")
        # semantic_handle may be missing only if the model violated schema; treat missing as None.
        semantic_handle = data.get("semantic_handle", None) if "semantic_handle" in data else None
        if semantic_handle is None:
            semantic_handle = ""
        if not isinstance(semantic_handle, str):
            semantic_handle = str(semantic_handle)

        # Debug dump (best-effort; no-op unless GENERATE_DEBUG_FILES=true)
        try:
            if project_id:
                ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
                fname = f"{ts}_tagger.txt"
                body = (
                    f"# timestamp: {ts}\n"
                    f"# project_id: {project_id}\n"
                    f"# model: {settings.builder_model}\n"
                    f"# success: true\n"
                    "\n"
                    "====== USER_TEXT ======\n"
                    + (user_text or "")
                    + "\n\n====== ASSISTANT_TEXT ======\n"
                    + (assistant_text or "")
                    + "\n\n====== PREVIOUS_PAIR_TEXT ======\n"
                    + (previous_pair_text or "")
                    + "\n\n====== TAGGER PROMPT (SYSTEM) ======\n"
                    + (_SYS_PROMPT or "")
                    + "\n\n====== TAGGER PROMPT (USER) ======\n"
                    + (user_prompt or "")
                    + "\n\n====== TAGGER RESPONSE (raw) ======\n"
                    + (raw or "")
                    + "\n\n====== TAGGER PARSED ======\n"
                    + f"topics: {topics}\n"
                    + f"intent: {intent}\n"
                    + f"type: {tag_type}\n"
                    + f"semantic_handle: {semantic_handle}\n"
                )
                write_debug_file(project_id, f"prompts/{fname}", body)
        except Exception:
            pass

        # Log trimmed for brevity
        try:
            logger.info(
                "[TAGGER] topics=%s intent=%s type=%s semantic_handle=%s",
                (topics or "")[:120],
                (intent or "")[:120],
                (tag_type or "")[:120],
                (semantic_handle or "")[:120] if isinstance(semantic_handle, str) else "None",
            )
        except Exception:
            pass
        instr.end_invocation(
            invocation_id,
            usage=usage,
            timing={"ttlt_ms": int((time.perf_counter() - t0) * 1000.0)},
        )

        return {
            "topics": topics,
            "intent": intent,
            "type": tag_type,
            "semantic_handle": semantic_handle,
        }
    except Exception as e:
        logger.warning("[TAGGER][WARN] %s", e)
        try:
            if "invocation_id" in locals() and invocation_id:
                get_instrumentation().end_invocation(
                    invocation_id,
                    usage=usage if "usage" in locals() else {
                        "purpose": "tagger",
                        "model": get_settings().builder_model,
                        "prompt_tokens_reported": 0,
                        "completion_tokens_reported": 0,
                        "total_tokens_reported": 0,
                        "usage_is_estimate": True,
                    },
                    timing={"ttlt_ms": int((time.perf_counter() - t0) * 1000.0)} if "t0" in locals() else {},
                )
        except Exception:
            pass
        # Debug dump on failure (best-effort)
        try:
            settings = get_settings()
            if project_id:
                ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
                fname = f"{ts}_tagger.txt"
                body = (
                    f"# timestamp: {ts}\n"
                    f"# project_id: {project_id}\n"
                    f"# model: {settings.builder_model}\n"
                    f"# success: false\n"
                    f"# error: {str(e)}\n"
                    "\n"
                    "====== USER_TEXT ======\n"
                    + (user_text or "")
                    + "\n\n====== ASSISTANT_TEXT ======\n"
                    + (assistant_text or "")
                    + "\n\n====== PREVIOUS_PAIR_TEXT ======\n"
                    + (previous_pair_text or "")
                    + "\n\n====== TAGGER PROMPT (SYSTEM) ======\n"
                    + (_SYS_PROMPT or "")
                    + "\n"
                )
                write_debug_file(project_id, f"prompts/{fname}", body)
        except Exception:
            pass
        return None


