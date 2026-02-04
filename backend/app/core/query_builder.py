"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
from __future__ import annotations
"""
Query Builder / Router for V2.3.1.

Calls a lightweight LLM to produce routing + rewritten queries and caches results briefly.
"""

import time
import json
import logging
from typing import Dict, Any, Tuple, Optional
from datetime import datetime

from openai import OpenAI

from .config import get_settings
from ..utils.debug_utils import write_debug_file

logger = logging.getLogger(__name__)


_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}

_SYS_PROMPT = """You are a fast interaction-mode classifier for a RAG system.
Return strict JSON only. No prose.

Your task is to classify the user's message into exactly one route.

Schema:
{"route":"CHITCHAT|DIRECT|PROCEDURAL|EXPLORATORY|SYNTHESIS|OTHER"}

Definitions:

- CHITCHAT:
  Purely social, conversational, or meta commentary.
  Examples: greetings, jokes, reactions, acknowledgements, comments about the chat itself.
  No real-world task, question, or information need.

- DIRECT:
  A clear, specific question with a narrow target that can be answered directly.
  Examples: factual lookups, definitions, short answers, direct questions.
  Excludes requests that require summarization, aggregation, or synthesis of multiple ideas.

- PROCEDURAL:
  How-to questions, step-by-step guidance, implementation, configuration, or execution details.
  Examples: instructions, workflows, setup, usage, or troubleshooting.

- EXPLORATORY:
  Open-ended questions focused on understanding, comparison, or investigation.
  Examples: "why", "compare", "analyze", "what are the differences", "how does X relate to Y".

- SYNTHESIS:
  Requests that require combining, abstracting, or distilling information.
  Includes summaries, overviews, big-picture explanations, design or planning tasks,
  tradeoff analysis, or "help me think" requests.
  Examples: "summarize X", "give an overview of Y", "what is the core idea behind Z",
  architecture decisions, strategy, or evaluating options.

- OTHER:
  Fallback for unclear, mixed, or unexpected requests that do not fit the above routes.

Rules:
- Choose CHITCHAT only if the message is purely social or conversational.
- Any real-world task, question, or intellectual request is NOT CHITCHAT.
- Choose exactly one route.
- Do not include any fields other than "route".
- Do not explain your choice.
- Do not rewrite or summarize the user input.
"""


class _BuilderPromptDumper:
    def dump(
        self,
        *,
        project_id: str,
        user_text: str,
        system_prompt: str,
        user_prompt: str,
        raw_response: str,
        data: Optional[Dict[str, Any]],
        model: Optional[str],
    ) -> None:
        """
        Write a builder debug snapshot to memory/{project_id}/debug/prompts/.
        Uses the same timestamp format as the chat prompt dump.
        """
        if not project_id:
            return
        ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        fname = f"{ts}_query.txt"
        try:
            pretty = json.dumps(data or {}, indent=2, sort_keys=True, ensure_ascii=False)
        except Exception:
            pretty = "{}"
        body = (
            f"# timestamp: {ts}\n"
            f"# project_id: {project_id}\n"
            + (f"# model: {model}\n" if model else "")
            + "\n"
            "====== USER_TEXT (passed into build_query) ======\n"
            + (user_text or "")
            + "\n"
            "====== BUILDER PROMPT (SYSTEM) ======\n"
            + (system_prompt or "")
            + "\n\n====== BUILDER PROMPT (USER) ======\n"
            + (user_prompt or "")
            + "\n\n====== BUILDER RESPONSE (raw) ======\n"
            + (raw_response or "")
            + "\n\n====== BUILDER DATA (parsed JSON) ======\n"
            + pretty
            + "\n"
        )
        write_debug_file(project_id, f"prompts/{fname}", body)


_PROMPT_DUMPER = _BuilderPromptDumper()


def _responses_text(resp: Any) -> str:
    """
    Extract text content from an OpenAI Responses API response.
    Mirrors the extraction logic used in dream/llm.py.
    """
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


def _cache_key(project_id: str, history_summary: str, user_text: str) -> str:
    from hashlib import sha256
    h = sha256()
    h.update(project_id.encode("utf-8", errors="ignore"))
    h.update(b"\n\n")
    h.update(history_summary.encode("utf-8", errors="ignore"))
    h.update(b"\n\n")
    h.update(user_text.encode("utf-8", errors="ignore"))
    return h.hexdigest()


def _filter_route_only(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a minimal, route-only dict from a parsed classifier response."""
    try:
        route = (data.get("route") or "").strip()
    except Exception:
        route = ""
    ru = str(route or "").strip().upper()
    allowed = {"CHITCHAT", "DIRECT", "PROCEDURAL", "EXPLORATORY", "SYNTHESIS", "OTHER"}
    if ru not in allowed:
        ru = "OTHER"
    return {"route": ru}


def _slice_first_json(text: str) -> str:
    """
    Extract the first balanced JSON object from text, respecting quoted strings.
    If no complete object is found, return the original text unchanged.
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
        else:
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
                continue
    if start != -1 and end != -1:
        return text[start:end]
    return text


def format_contextual_turn(user_text: str, tags_meta_json: str) -> str:
    """
    Canonical contextual query string builder.

    Rules:
    - Start with the raw user prompt only.
    - Append Context/Intent/Type only if the corresponding fields exist (non-empty after strip).
    - Never emit empty labels, nulls, or defaults.

    Output format:
      <user_prompt> Context: <semantic_handle>. Intent: <intent>. Type: <type>
    (each segment is conditional; final punctuation matches the template above)
    """
    base = (user_text or "").strip()
    out = base
    meta: Optional[Dict[str, Any]] = None
    try:
        hs = (tags_meta_json or "").strip()
        if hs:
            meta = json.loads(hs)
    except Exception:
        meta = None
    if isinstance(meta, dict):
        sh = meta.get("semantic_handle", None)
        intent = meta.get("intent", None)
        typ = meta.get("type", None)
        if isinstance(sh, str) and sh.strip():
            out = (out + " " if out else "") + f"Context: {sh.strip()}."
        if isinstance(intent, str) and intent.strip():
            out = (out + " " if out else "") + f"Intent: {intent.strip()}."
        if isinstance(typ, str) and typ.strip():
            out = (out + " " if out else "") + f"Type: {typ.strip()}"
    return out


def build_query(project_id: str, history_summary: str, user_text: str) -> Optional[Dict[str, Any]]:
    """Invoke classifier LLM and return parsed JSON or None on failure."""
    settings = get_settings()
    if settings.builder_cache:
        key = _cache_key(project_id, history_summary, user_text)
        ent = _CACHE.get(key)
        if ent and (time.time() - ent[0]) < 600:  # 10 minutes TTL
            return ent[1]

    user = format_contextual_turn(user_text, history_summary)
    raw = ""
    data: Optional[Dict[str, Any]] = None

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        # Log the prompt for debug visibility (trimmed)
        settings = get_settings()
        cap = settings.log_preview_max_chars
        logger.debug(
            "builder prompt summary=%s turn=%s",
            (history_summary[:cap] + ("…" if len(history_summary) > cap else "")),
            (user_text[:cap] + ("…" if len(user_text) > cap else "")),
        )
        # Call OpenAI Responses API directly (bypass LangChain).
        # IMPORTANT: omit temperature for maximum model compatibility.
        try:
            resp = client.responses.create(
                model=settings.builder_model,
                input=[
                    {"role": "system", "content": _SYS_PROMPT},
                    {"role": "user", "content": user},
                ],
                # Guarantee a JSON text payload (avoid reasoning-only outputs).
                text={"format": {"type": "json_object"}},
                # Allow some reasoning, but keep it bounded.
                reasoning={"effort": "low"},
                max_output_tokens=int(settings.builder_max_tokens),
            )
        except Exception:
            # Fallback: some client versions/models may not accept message-list `input`.
            resp = client.responses.create(
                model=settings.builder_model,
                input=_SYS_PROMPT + "\n\n" + user,
                text={"format": {"type": "json_object"}},
                reasoning={"effort": "low"},
                max_output_tokens=int(settings.builder_max_tokens),
            )
        raw = _responses_text(resp)
        logger.debug("builder raw=%s", (raw[:cap] + ("…" if len(raw) > cap else "")))
        # Clean output to ensure strict JSON parsing
        clean = raw
        if clean.startswith("```"):
            lines = [ln for ln in clean.splitlines() if not ln.strip().startswith("```")]
            clean = "\n".join(lines).strip()
        # Slice out the first balanced JSON object to avoid trailing prose
        clean = _slice_first_json(clean)
        try:
            data = json.loads(clean)
        except json.JSONDecodeError as je:
            # Provide a concise diagnostic snippet near the error position
            try:
                pos = getattr(je, "pos", 0)
                snippet = clean[max(0, pos - 80) : pos + 80]
                logger.debug("builder json decode failed near pos=%s snippet=%r", pos, snippet)
            except Exception:
                pass
            import re
            m = re.search(r"\{[\s\S]*\}", clean)
            if not m:
                raise
            data = json.loads(m.group(0))
        # Basic shape validation
        if not isinstance(data, dict) or "route" not in data:
            raise ValueError("invalid builder json")
        # Debug dump (best-effort; no-op unless GENERATE_DEBUG_FILES=true)
        try:
            _PROMPT_DUMPER.dump(
                project_id=project_id,
                user_text=user_text,
                system_prompt=_SYS_PROMPT,
                user_prompt=user,
                raw_response=raw,
                data=data,
                model=settings.builder_model,
            )
        except Exception:
            pass
        data2 = _filter_route_only(data)
        if settings.builder_cache:
            _CACHE[key] = (time.time(), data2)
        logger.info("builder route=%s", data2.get("route"))
        return data2
    except Exception as e:
        # Debug dump failure case (best-effort)
        try:
            _PROMPT_DUMPER.dump(
                project_id=project_id,
                user_text=user_text,
                system_prompt=_SYS_PROMPT,
                user_prompt=user,
                raw_response=raw,
                data=(data if isinstance(data, dict) else None),
                model=getattr(settings, "builder_model", None),
            )
        except Exception:
            pass
        logger.warning(f"builder failed: {e}")
        return None


