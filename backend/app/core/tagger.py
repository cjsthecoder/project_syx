"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import logging
import json
import time
from typing import Dict, Optional, Any, List
from datetime import datetime

from .config import get_settings
from .tracking import get_instrumentation
from ..utils.debug_utils import write_debug_file
from openai import OpenAI

logger = logging.getLogger(__name__)

_SYS_PROMPT = """You are a memory tagging system.

You are a memory tagging system.

Your task is to extract compact, durable metadata for later retrieval.
Tag the CURRENT TURN only.

Use PREVIOUS TURN content only as supporting context to interpret the CURRENT TURN correctly.
Do not tag the PREVIOUS TURN as if it were the current exchange.
The goal is to help future searches reliably find the CURRENT TURN and its most durable meaning.

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

Open questions:
- Identify only high-value unresolved questions from this exchange.
- Extract question candidates from the ASSISTANT response text only.
- Do NOT extract questions from USER prompt text, even if the user asks a direct question.
- Do NOT extract routine brainstorming branches, minor follow-up ideas, casual suggestions, or low-stakes uncertainty.
- Only include a question if it is likely to matter later for research, design quality, major decisions, or long-term project direction.
- Prefer zero questions over weak questions.

Inclusion standard:
- Include a question only if at least one of these is true:
  - answering it would likely require outside research or verification
  - answering it would materially improve a major design, story, or project decision
  - it represents a genuinely important unresolved dependency or blocker
- Exclude questions that are:
  - already effectively resolved in the same exchange
  - simple next-step ideas
  - optional creative variations
  - minor style or wording choices
  - speculative branches that do not clearly matter

Question handling:
- Include explicit ASSISTANT-side questions ending with '?' only if they remain genuinely unresolved and important.
- Include implicit unresolved questions only when they are clearly important and durable, such as:
  - major unresolved design choices
  - critical pending decisions
  - research questions that need evidence
  - blockers or dependencies that affect later work

Resolution values:
- `remind_user` when a real user decision is required and it is important enough to revisit
- `answer_local` when it is important and can likely be answered from project/local context
- `answer_remote` when it is important and likely requires external research

Limits:
- It is valid and preferred to return an empty `questions` array.
- Do not emit weak, resolved, or low-value questions.

Return STRICT JSON only. No prose. No markdown fences.

Schema:
{
  "topics": "",
  "intent": "",
  "type": "",
  "semantic_handle": "",
  "questions": [
    {
      "question": "<exact or naturally rewritten question>",
      "topic": "<topic title where the question originated>",
      "resolution": "<remind_user | answer_local | answer_remote>"
    }
  ]
}

Rules:
- Always include all keys shown in the schema.
- Use "" (empty string) for unknown values. Do not output null.
- `questions` MUST be an array (use [] when no candidates).
- `resolution` MUST be one of: ignore, remind_user, answer_local, answer_remote.
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


def _safe_percent(value: Any, default: int, name: str) -> int:
    try:
        coerced = int(float(value))
    except Exception:
        logger.warning("[TAGGER] invalid %s=%r; using default=%s", name, value, default)
        return int(default)
    if coerced < 10 or coerced > 90:
        logger.warning("[TAGGER] out-of-range %s=%s; expected 10-90, using default=%s", name, coerced, default)
        return int(default)
    return coerced


def _safe_min_len(value: Any, default: int, name: str) -> int:
    try:
        coerced = int(float(value))
    except Exception:
        logger.warning("[TAGGER] invalid %s=%r; using default=%s", name, value, default)
        return int(default)
    if coerced <= 0:
        logger.warning("[TAGGER] non-positive %s=%s; using default=%s", name, coerced, default)
        return int(default)
    return coerced


def _middle_cut_assistant_text(text: str, cut_percent: int, min_length_for_chop: int) -> str:
    """
    Remove a percentage from the center while preserving at least 100 chars on both ends.
    """
    raw = str(text or "")
    n = len(raw)
    if n <= int(min_length_for_chop):
        return raw
    cut = int((n * int(cut_percent)) / 100)
    if cut <= 0 or cut >= n:
        return raw
    keep_total = n - cut
    left = keep_total // 2
    right = keep_total - left
    min_side = 100
    if left < min_side or right < min_side:
        left = min_side
        right = min_side
    if (left + right) >= n:
        return raw
    start = left
    end = n - right
    return raw[:start] + "\n...[middle omitted for tagging]...\n" + raw[end:]


def _extract_prev_tag_value(text: str, key: str) -> str:
    import re

    m = re.search(rf"(?m)^#{re.escape(key)}:\s*(.*)$", text or "")
    return (m.group(1).strip() if m else "")


def _build_previous_turn_block(previous_pair_text: Optional[str], prev_cut_percent: int, min_length_for_chop: int) -> str:
    """
    Build canonical PREVIOUS TURN block from stored previous_pair_text.
    """
    import re

    p = str(previous_pair_text or "")
    route = _extract_prev_tag_value(p, "route")
    keep = _extract_prev_tag_value(p, "keep")
    topics = _extract_prev_tag_value(p, "topics")
    intent = _extract_prev_tag_value(p, "intent")
    tag_type = _extract_prev_tag_value(p, "type")
    semantic_handle = _extract_prev_tag_value(p, "semantic_handle")

    prev_user = ""
    prev_assistant = ""
    m = re.search(r"\nUser:\s*(.*?)\nAssistant:\s*(.*)$", p, flags=re.DOTALL)
    if m:
        prev_user = (m.group(1) or "").strip()
        prev_assistant = (m.group(2) or "").strip()
    else:
        m2 = re.search(r"User:\s*(.*?)\nAssistant:\s*(.*)$", p, flags=re.DOTALL)
        if m2:
            prev_user = (m2.group(1) or "").strip()
            prev_assistant = (m2.group(2) or "").strip()

    prev_assistant = _middle_cut_assistant_text(
        prev_assistant,
        cut_percent=int(prev_cut_percent),
        min_length_for_chop=int(min_length_for_chop),
    ).strip()

    tags_lines = []
    if route:
        tags_lines.append(f"#route: {route}")
    if keep:
        tags_lines.append(f"#keep: {keep}")
    if topics:
        tags_lines.append(f"#topics: {topics}")
    if intent:
        tags_lines.append(f"#intent: {intent}")
    if tag_type:
        tags_lines.append(f"#type: {tag_type}")
    if semantic_handle:
        tags_lines.append(f"#semantic_handle: {semantic_handle}")
    tags_block = "\n".join(tags_lines).strip() if tags_lines else "(none)"

    prev_user_block = prev_user if prev_user else "(none)"
    prev_asst_block = prev_assistant if prev_assistant else "(none)"

    return (
        "------PREVIOUS TURN------\n"
        "------PREVIOUS TAGS------\n"
        f"{tags_block}\n\n"
        "------USER------\n"
        f"{prev_user_block}\n\n"
        "------ASSISTANT------\n"
        f"{prev_asst_block}\n"
    )


def tag_pair(
    user_text: str,
    assistant_text: str,
    previous_pair_text: Optional[str] = None,
    *,
    project_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Generate tag metadata (#topics, #intent, #type, #semantic_handle, #questions)
    using the builder model.

    Return value:
    - None on failure
    - On success:
      {
        "topics": str,
        "intent": str,
        "type": str,
        "semantic_handle": str,
        "questions": [{"question": str, "topic": str, "resolution": str}, ...],
      }
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
        current_cut_pct = _safe_percent(
            getattr(settings, "tagger_current_response_middle_cut_percent", 50),
            default=50,
            name="TAGGER_CURRENT_RESPONSE_MIDDLE_CUT_PERCENT",
        )
        previous_cut_pct = _safe_percent(
            getattr(settings, "tagger_previous_response_middle_cut_percent", 75),
            default=75,
            name="TAGGER_PREVIOUS_RESPONSE_MIDDLE_CUT_PERCENT",
        )
        min_length_for_chop = _safe_min_len(
            getattr(settings, "tagger_min_response_length_for_chop", 600),
            default=600,
            name="TAGGER_MIN_RESPONSE_LENGTH_FOR_CHOP",
        )
        assistant_for_prompt = _middle_cut_assistant_text(
            assistant_text,
            cut_percent=int(current_cut_pct),
            min_length_for_chop=int(min_length_for_chop),
        )
        previous_block = _build_previous_turn_block(
            previous_pair_text,
            prev_cut_percent=int(previous_cut_pct),
            min_length_for_chop=int(min_length_for_chop),
        )
        user_prompt = (
            f"{previous_block.rstrip()}\n\n"
            "------CURRENT TURN------\n"
            "------USER------\n"
            f"{user_text}\n\n"
            "------ASSISTANT------\n"
            f"{assistant_for_prompt}\n"
        )

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
            extra_usage: Dict[str, Any] = {}
            if u is not None:
                for k in ("input_token_details", "output_token_details", "reasoning_tokens", "cached_tokens"):
                    try:
                        v = getattr(u, k, None)
                        if v is not None:
                            extra_usage[k] = v
                    except Exception:
                        pass
            if total_tok > 0:
                usage = {
                    "purpose": "tagger",
                    "model": settings.builder_model,
                    "prompt_tokens_reported": prompt_tok,
                    "completion_tokens_reported": completion_tok,
                    "total_tokens_reported": total_tok,
                    "usage_is_estimate": False,
                }
                if extra_usage:
                    usage["extra_usage"] = extra_usage
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
        questions: List[Dict[str, str]] = []
        allowed_resolutions = {"ignore", "remind_user", "answer_local", "answer_remote"}
        raw_questions = data.get("questions")
        if isinstance(raw_questions, list):
            for item in raw_questions:
                if not isinstance(item, dict):
                    continue
                q_text = str(item.get("question", "") or "").strip()
                q_topic = str(item.get("topic", "") or "").strip()
                q_resolution = str(item.get("resolution", "") or "").strip().lower()
                if not q_text:
                    continue
                if q_resolution not in allowed_resolutions:
                    q_resolution = "ignore"
                questions.append(
                    {
                        "question": q_text,
                        "topic": q_topic,
                        "resolution": q_resolution,
                    }
                )

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
                    "====== TAGGER PROMPT (SYSTEM) ======\n"
                    + (_SYS_PROMPT or "")
                    + "\n\n====== TAGGER PROMPT (USER) ======\n"
                    + (user_prompt or "")
                    + "\n\n====== TAGGER RESPONSE ======\n"
                    + (raw or "")
                    + "\n"
                )
                write_debug_file(project_id, f"prompts/{fname}", body)
        except Exception:
            pass

        # Log trimmed for brevity
        try:
            logger.info(
                "[TAGGER] topics=%s intent=%s type=%s semantic_handle=%s questions_count=%s",
                (topics or "")[:120],
                (intent or "")[:120],
                (tag_type or "")[:120],
                (semantic_handle or "")[:120] if isinstance(semantic_handle, str) else "None",
                int(len(questions)),
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
            "questions": questions,
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


