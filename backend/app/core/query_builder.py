"""
Query Builder / Router for V2.3.1.

Calls a lightweight LLM to produce routing + rewritten queries and caches results briefly.
"""

from __future__ import annotations

import time
import json
import logging
from typing import Dict, Any, Tuple, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from .config import get_settings

logger = logging.getLogger(__name__)


_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def _cache_key(project_id: str, history_summary: str, user_text: str) -> str:
    from hashlib import sha256
    h = sha256()
    h.update(project_id.encode("utf-8", errors="ignore"))
    h.update(b"\n\n")
    h.update(history_summary.encode("utf-8", errors="ignore"))
    h.update(b"\n\n")
    h.update(user_text.encode("utf-8", errors="ignore"))
    return h.hexdigest()


def build_query(project_id: str, history_summary: str, user_text: str) -> Optional[Dict[str, Any]]:
    """Invoke builder LLM and return parsed JSON or None on failure."""
    settings = get_settings()
    if settings.builder_cache:
        key = _cache_key(project_id, history_summary, user_text)
        ent = _CACHE.get(key)
        if ent and (time.time() - ent[0]) < 600:  # 10 minutes TTL
            return ent[1]

    sys = (
        "You are a fast query builder and router for RAG. Return strict JSON only. No prose.\n\n"
        "Decide if retrieval is helpful:\n"
        "- CHITCHAT is only for small-talk, greetings, jokes, or meta comments about this chat itself (e.g., \"how are you\", \"haha\", \"thanks\", \"you're smart\").\n"
        "- Any question, idea, explanation, or reflection about real-world tasks, systems, tools, workflows, data, projects, or documents is NOT CHITCHAT. Treat those as technical and set rag=true.\n\n"
        "Schema: {\"route\":\"CHITCHAT|CODE|DOCS|OTHER\",\"rag\":true,\"standalone\":\"\",\"paraphrases\":[],\"hyde\":\"\",\"entities\":[],\"topics\":[],\"reason\":\"\",\"confidence\":0.0}\n\n"
        "Routing rules:\n"
        "- route=\"CHITCHAT\" → only if purely social or conversational.\n"
        "- route=\"CODE\" → when the question involves implementation, programming, APIs, configuration, or execution details (e.g., “how do we implement…”, “what function…”, “which parameter…”).\n"
        "- route=\"DOCS\" → when the question refers to explanations, conceptual understanding, features, or descriptive information (e.g., “how does this work”, “what does it mean”, “explain the process…”).\n"
        "- route=\"OTHER\" → anything factual or reasoning-based that doesn’t fit CODE or DOCS, including planning, design ideas, or general topics.\n"
        "- standalone must be a short, self-contained search query (≤ 200 chars).\n"
        "- Default to rag=true unless clearly small-talk.\n"
        "- Always include at least one topic. Topics describe the general area of knowledge\n"
        "(e.g., [\"vector search\", \"ANN tuning\", \"dynamic parameters\"]).\n"
         "- If the turn involves variables, configs, or API parameters, infer the broader topic\n"
        "they belong to (e.g., \"retrieval\", \"optimization\", \"search pipeline\").\n"
        "- Never leave topics empty."
    )
    user = f"Recent summary: {history_summary}\nTurn: {user_text}"

    try:
        llm = ChatOpenAI(
            openai_api_key=settings.openai_api_key,
            model_name=settings.builder_model,
            temperature=0.0,
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
        resp = llm.invoke([SystemMessage(content=sys), HumanMessage(content=user)])
        raw = getattr(resp, "content", "").strip()
        logger.debug("builder raw=%s", (raw[:cap] + ("…" if len(raw) > cap else "")))
        data = json.loads(raw)
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


