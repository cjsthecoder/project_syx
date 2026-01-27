"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

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

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from .config import get_settings

logger = logging.getLogger(__name__)


_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}

_SYS_PROMPT = """You are a fast query builder and router for RAG. Return strict JSON only. No prose.

Decide if retrieval is helpful:
- CHITCHAT is only for small-talk, greetings, jokes, or meta comments about this chat itself (e.g., "how are you", "haha", "thanks", "you're smart").
- Any question, idea, explanation, or reflection about real-world tasks, systems, tools, workflows, data, projects, or documents is NOT CHITCHAT. Treat those as technical and set rag=true.

Schema: {"route":"CHITCHAT|CODE|DOCS|OTHER","rag":true,"standalone":"","paraphrases":[],"hyde":"","entities":[],"topics":[],"reason":"","confidence":0.0}

Routing rules:
- route="CHITCHAT" → only if purely social or conversational.
- route="CODE" → when the question involves implementation, programming, APIs, configuration, or execution details (e.g., "how do we implement…", "what function…", "which parameter…").
- route="DOCS" → when the question refers to explanations, conceptual understanding, features, or descriptive information (e.g., "how does this work", "what does it mean", "explain the process…").
- route="OTHER" → anything factual or reasoning-based that doesn’t fit CODE or DOCS, including planning, design ideas, or general topics.
- standalone must be a short, self-contained search query (≤ 200 chars).
- standalone should be optimized for semantic retrieval, not conversation.
- Remove pronouns, deixis, and conversational phrasing.
- Prefer explicit nouns, named entities, and concrete concepts.
- Default to rag=true unless clearly small-talk.
- Always include at least one topic. Topics describe the general area of knowledge (e.g., ["vector search", "ANN tuning", "dynamic parameters"]).
- Topics describe the broad domain of knowledge.
- standalone should be a concrete query that could plausibly retrieve stored memories.
- If the turn involves variables, configs, or API parameters, infer the broader topic they belong to (e.g., "retrieval", "optimization", "search pipeline").
- Never leave topics empty."""


def _cache_key(project_id: str, history_summary: str, user_text: str) -> str:
    from hashlib import sha256
    h = sha256()
    h.update(project_id.encode("utf-8", errors="ignore"))
    h.update(b"\n\n")
    h.update(history_summary.encode("utf-8", errors="ignore"))
    h.update(b"\n\n")
    h.update(user_text.encode("utf-8", errors="ignore"))
    return h.hexdigest()


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


def build_query(project_id: str, history_summary: str, user_text: str) -> Optional[Dict[str, Any]]:
    """Invoke builder LLM and return parsed JSON or None on failure."""
    settings = get_settings()
    if settings.builder_cache:
        key = _cache_key(project_id, history_summary, user_text)
        ent = _CACHE.get(key)
        if ent and (time.time() - ent[0]) < 600:  # 10 minutes TTL
            return ent[1]

    user = f"Recent summary: {history_summary}\nTurn: {user_text}"

    try:
        llm = ChatOpenAI(
            api_key=settings.openai_api_key,
            model=settings.builder_model,
            temperature=1.0,
            model_kwargs={"max_completion_tokens": settings.builder_max_tokens},
            streaming=False,
        )
        # Log the prompt for debug visibility (trimmed)
        settings = get_settings()
        cap = settings.log_preview_max_chars
        logger.debug(
            "builder prompt summary=%s turn=%s",
            (history_summary[:cap] + ("…" if len(history_summary) > cap else "")),
            (user_text[:cap] + ("…" if len(user_text) > cap else "")),
        )
        resp = llm.invoke([SystemMessage(content=_SYS_PROMPT), HumanMessage(content=user)])
        raw = getattr(resp, "content", "").strip()
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
        if not isinstance(data, dict) or "route" not in data or "rag" not in data:
            raise ValueError("invalid builder json")
        if settings.builder_cache:
            _CACHE[key] = (time.time(), data)
        logger.info(
            "builder route=%s rag=%s conf=%s topics=%s standalone=%s",
            data.get("route"),
            data.get("rag"),
            data.get("confidence"),
            ",".join(map(str, data.get("topics", [])[:5])),
            (data.get("standalone", "")[:80] + ("…" if len(data.get("standalone", "")) > 80 else "")),
        )
        return data
    except Exception as e:
        logger.warning(f"builder failed: {e}")
        return None


