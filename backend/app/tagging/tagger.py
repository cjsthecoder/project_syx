"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Memory tagging model for chat exchanges.

This module calls the tagger LLM to extract topics, intent, type, a semantic
handle, and open questions for a chat pair, returning normalized metadata.
"""
import logging
import json
import time
from typing import Dict, Optional, Any, List
from datetime import datetime

from ..core.config import get_settings
from ..llm_model.factory import get_llm_client_mini
from ..tracking import get_instrumentation
from ..utils.debug_utils import write_debug_file

logger = logging.getLogger(__name__)

_SYS_PROMPT = """You are a memory tagging system.

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
- `ignore` when a question should not enter the Dream question pipeline
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
      "resolution": "<ignore | answer_local | answer_remote>"
    }
  ]
}

Rules:
- Always include all keys shown in the schema.
- Use "" (empty string) for unknown values. Do not output null.
- `questions` MUST be an array (use [] when no candidates).
- `resolution` MUST be one of: ignore, answer_local, answer_remote.
"""


def _slice_first_json(text: str) -> str:
    """Best-effort extraction of the first balanced JSON object from text.

    Scans for the first top-level ``{`` and returns the substring through its
    matching ``}``, tracking string literals and escapes so braces inside
    strings are ignored.

    Args:
        text: Raw model output that may wrap a JSON object in extra prose.

    Returns:
        The first balanced ``{...}`` slice, or the original ``text`` unchanged
        if no balanced object is found.
    """
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
    """Validate a configured percentage, falling back when out of bounds.

    Logs a warning and returns ``default`` when ``value`` is non-numeric or
    falls outside the accepted 10-90 range.

    Args:
        value: Raw configured value to coerce to a percent.
        default: Fallback percent used when validation fails.
        name: Setting name used only for log context.

    Returns:
        The validated percent in [10, 90], or ``default``.
    """
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
    """Validate a configured minimum length, falling back when invalid.

    Logs a warning and returns ``default`` when ``value`` is non-numeric or not
    positive.

    Args:
        value: Raw configured value to coerce to a length.
        default: Fallback length used when validation fails.
        name: Setting name used only for log context.

    Returns:
        The validated positive length, or ``default``.
    """
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
    """Remove a percentage from the center while preserving both ends.

    Used to shrink long assistant responses before tagging while keeping the
    opening and closing context. Text at or below ``min_length_for_chop`` is
    returned unchanged, and at least 100 characters are preserved on each side.

    Args:
        text: Assistant text to condense; ``None`` is treated as empty.
        cut_percent: Approximate share of the middle (as a percent) to remove.
        min_length_for_chop: Minimum length below which no trimming occurs.

    Returns:
        The trimmed text with an elision marker inserted, or the original text
        when trimming is not warranted.
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
    """Read a single ``#key: value`` tag line from stored previous-turn text.

    Args:
        text: Stored previous-pair text containing ``#key: value`` lines.
        key: Tag name to look up (without the leading ``#`` or trailing ``:``).

    Returns:
        The stripped value for ``key``, or an empty string if not present.
    """
    import re

    m = re.search(rf"(?m)^#{re.escape(key)}:\s*(.*)$", text or "")
    return (m.group(1).strip() if m else "")


def _build_previous_turn_block(previous_pair_text: Optional[str], prev_cut_percent: int, min_length_for_chop: int) -> str:
    """Build the canonical PREVIOUS TURN block from stored pair text.

    Parses prior tags (route, keep, topics, intent, type, semantic_handle) and
    the prior user/assistant messages out of ``previous_pair_text``, condenses
    the prior assistant message, and formats them into the structured block the
    tagger prompt expects.

    Args:
        previous_pair_text: Stored text of the prior turn; ``None`` yields an
            empty/placeholder block.
        prev_cut_percent: Middle-cut percent applied to the prior assistant text.
        min_length_for_chop: Minimum length below which the prior assistant text
            is left untrimmed.

    Returns:
        The formatted PREVIOUS TURN block, using ``(none)`` placeholders for any
        missing sections.
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


def _build_tagger_prompt(
    user_text: str,
    assistant_text: str,
    previous_pair_text: Optional[str],
    settings: Any,
) -> str:
    """Assemble the tagger user prompt for the current turn.

    Resolves the configured middle-cut percentages and chop threshold, applies
    the middle-cut to the assistant response, renders the previous-turn context
    block, and lays out the CURRENT TURN section.

    Args:
        user_text: The current turn's user message.
        assistant_text: The current turn's assistant response.
        previous_pair_text: Optional stored text of the prior turn for context.
        settings: Settings object providing the tagger cut/chop config.

    Returns:
        The fully assembled user prompt string.
    """
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
    return (
        f"{previous_block.rstrip()}\n\n"
        "------CURRENT TURN------\n"
        "------USER------\n"
        f"{user_text}\n\n"
        "------ASSISTANT------\n"
        f"{assistant_for_prompt}\n"
    )


def _parse_tagger_response(raw: str) -> Optional[Dict[str, Any]]:
    """Parse the tagger model's raw text into a JSON object.

    Strips Markdown code fences, isolates the first balanced JSON object, and
    decodes it. Returns ``None`` when decoding fails or the result is not a dict.

    Args:
        raw: Raw model output text.

    Returns:
        The decoded dict, or ``None`` when the output is not a JSON object.
    """
    clean = raw or ""
    if clean.startswith("```"):
        lines2 = [ln for ln in clean.splitlines() if not ln.strip().startswith("```")]
        clean = "\n".join(lines2).strip()
    clean = _slice_first_json(clean)
    try:
        data = json.loads(clean)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _extract_tagger_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize the tagger JSON object into the canonical metadata dict.

    Coerces ``topics``/``intent``/``type``/``semantic_handle`` to strings and
    validates each question's ``resolution`` against the allowed set (defaulting
    to ``ignore``), dropping empty questions and non-dict entries.

    Args:
        data: The decoded tagger JSON object.

    Returns:
        A dict with keys ``topics``, ``intent``, ``type``, ``semantic_handle``,
        and ``questions``.
    """
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
    allowed_resolutions = {"ignore", "answer_local", "answer_remote"}
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
    return {
        "topics": topics,
        "intent": intent,
        "type": tag_type,
        "semantic_handle": semantic_handle,
        "questions": questions,
    }


def _tagger_usage_from_response(response: Any) -> Dict[str, Any]:
    """Build the usage telemetry dict from a tagger LLM response.

    Args:
        response: The LLM response exposing ``model`` and a ``usage`` record.

    Returns:
        A usage dict including reported token counts and (when present) the
        provider ``extra_usage`` payload.
    """
    usage: Dict[str, Any] = {
        "purpose": "tagger",
        "model": response.model,
        "prompt_tokens_reported": int(response.usage.prompt_tokens_reported),
        "completion_tokens_reported": int(response.usage.completion_tokens_reported),
        "total_tokens_reported": int(response.usage.total_tokens_reported),
        "usage_is_estimate": bool(response.usage.usage_is_estimate),
    }
    if response.usage.extra_usage:
        usage["extra_usage"] = response.usage.extra_usage
    return usage


def _write_tagger_success_debug(
    project_id: str,
    settings: Any,
    user_prompt: str,
    raw: str,
) -> None:
    """Write the best-effort success debug dump for a tagger invocation.

    Args:
        project_id: Project id used to namespace the debug file.
        settings: Settings providing the builder/tagger model names.
        user_prompt: The assembled user prompt sent to the model.
        raw: The raw model response text.
    """
    try:
        if project_id:
            ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
            fname = f"{ts}_tagger.txt"
            body = (
                f"# timestamp: {ts}\n"
                f"# project_id: {project_id}\n"
                f"# model: {settings.builder_model}\n"
                f"# tagger_model: {settings.tagger_model}\n"
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
    except Exception as exc:
        logger.warning("[TAGGER] Failed writing debug tagger prompt dump project_id=%s: %s", project_id, exc)


def _write_tagger_failure_debug(
    project_id: Optional[str],
    user_text: str,
    assistant_text: str,
    previous_pair_text: Optional[str],
    error: Exception,
) -> None:
    """Write the best-effort failure debug dump for a tagger invocation.

    Args:
        project_id: Project id used to namespace the debug file.
        user_text: The current turn's user message.
        assistant_text: The current turn's assistant response.
        previous_pair_text: Optional prior-turn text.
        error: The exception that caused the failure.
    """
    try:
        settings = get_settings()
        if project_id:
            ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
            fname = f"{ts}_tagger.txt"
            body = (
                f"# timestamp: {ts}\n"
                f"# project_id: {project_id}\n"
                f"# model: {settings.builder_model}\n"
                f"# tagger_model: {settings.tagger_model}\n"
                f"# success: false\n"
                f"# error: {str(error)}\n"
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
    except Exception as exc:
        logger.warning("[TAGGER] Failed writing debug failure dump project_id=%s: %s", project_id, exc)


def tag_pair(
    user_text: str,
    assistant_text: str,
    previous_pair_text: Optional[str] = None,
    *,
    project_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Generate retrieval metadata for a chat turn via the tagger LLM.

    Calls the mini/tagger model to extract topics, intent, type, a semantic
    handle, and high-value open questions for the CURRENT turn, using the
    previous turn only as interpretive context. Performs network I/O and,
    when ``GENERATE_DEBUG_FILES`` is enabled, writes best-effort debug dumps.
    Instrumentation is recorded for both success and failure paths.

    Args:
        user_text: The current turn's user message.
        assistant_text: The current turn's assistant response.
        previous_pair_text: Optional stored text of the prior turn for context.
        project_id: Optional project identifier for instrumentation and debug dumps.

    Returns:
        On success, a dict with keys ``topics``, ``intent``, ``type``,
        ``semantic_handle`` (all ``str``) and ``questions`` (a list of
        ``{"question", "topic", "resolution"}`` dicts). Returns ``None`` if
        tagging fails or the model returns non-JSON output.
    """
    try:
        settings = get_settings()
        instr = get_instrumentation()
        invocation_id = instr.start_invocation(
            purpose="tagger",
            model=settings.tagger_model,
            meta={"project_id": project_id or ""},
        )
        t0 = time.perf_counter()
        usage: Dict[str, Any] = {
            "purpose": "tagger",
            "model": settings.tagger_model,
            "prompt_tokens_reported": 0,
            "completion_tokens_reported": 0,
            "total_tokens_reported": 0,
            "usage_is_estimate": True,
        }
        user_prompt = _build_tagger_prompt(user_text, assistant_text, previous_pair_text, settings)

        response = get_llm_client_mini().generate_response(
            model=settings.tagger_model,
            system_prompt=_SYS_PROMPT,
            user_prompt=user_prompt,
            max_output_tokens=int(settings.builder_max_tokens),
            reasoning_effort="low",
            require_json_object=True,
        )
        usage = _tagger_usage_from_response(response)
        raw = response.text
        data = _parse_tagger_response(raw)
        if data is None:
            raise ValueError("tagger returned non-json output")

        result = _extract_tagger_fields(data)

        # Debug dump (best-effort; no-op unless GENERATE_DEBUG_FILES=true)
        _write_tagger_success_debug(project_id, settings, user_prompt, raw)

        # Log trimmed for brevity
        try:
            semantic_handle = result["semantic_handle"]
            logger.info(
                "[TAGGER] topics=%s intent=%s type=%s semantic_handle=%s questions_count=%s",
                (result["topics"] or "")[:120],
                (result["intent"] or "")[:120],
                (result["type"] or "")[:120],
                (semantic_handle or "")[:120] if isinstance(semantic_handle, str) else "None",
                int(len(result["questions"])),
            )
        except Exception as exc:
            logger.warning("[TAGGER] Failed writing tagger summary log project_id=%s: %s", project_id, exc)
        instr.end_invocation(
            invocation_id,
            usage=usage,
            timing={"ttlt_ms": int((time.perf_counter() - t0) * 1000.0)},
        )

        return result
    except Exception as e:
        logger.warning("[TAGGER][WARN] %s", e)
        try:
            if "invocation_id" in locals() and invocation_id:
                get_instrumentation().end_invocation(
                    invocation_id,
                    usage=usage if "usage" in locals() else {
                        "purpose": "tagger",
                        "model": get_settings().tagger_model,
                        "prompt_tokens_reported": 0,
                        "completion_tokens_reported": 0,
                        "total_tokens_reported": 0,
                        "usage_is_estimate": True,
                    },
                    timing={"ttlt_ms": int((time.perf_counter() - t0) * 1000.0)} if "t0" in locals() else {},
                )
        except Exception as exc:
            logger.warning("[TAGGER] Failed finalizing invocation after error project_id=%s: %s", project_id, exc)
        # Debug dump on failure (best-effort)
        _write_tagger_failure_debug(project_id, user_text, assistant_text, previous_pair_text, e)
        return None


