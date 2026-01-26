"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import logging
from typing import List, Optional

from .llm import get_llm_provider
from .config import get_settings

logger = logging.getLogger(__name__)

_PROMPT = """You are a memory tagging system.

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

Return ONLY the following metadata lines.
Do not include explanations or extra text.

#topics: <keywords>
#intent: <short phrase>
#type: <category>
"""


def tag_pair(user_text: str, assistant_text: str, previous_pair_text: Optional[str] = None) -> Optional[List[str]]:
    """
    Generate 3 tag lines (#topics, #intent, #type) using the builder model.
    Returns list of 3 strings in canonical order, or None on failure.
    """
    try:
        provider = get_llm_provider()
        settings = get_settings()
        context = (previous_pair_text + "\n\n") if previous_pair_text else ""
        msg = f"{_PROMPT}\n\n{context}USER: {user_text}\nASSISTANT: {assistant_text}\n"
        # Small, deterministic output
        resp = provider.generate_response(
            message=msg,
            override_model=settings.builder_model,
            temperature_override=0.0,
            completion_tokens_override=settings.builder_max_tokens,
        )
        if not resp or not isinstance(resp, dict) or not resp.get("success"):
            logger.warning("[TAGGER][WARN] failed: %s", (resp or {}).get("error") if isinstance(resp, dict) else "unknown")
            return None
        raw = resp.get("response") or ""
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        # Normalize and pick the first matching line per key
        out: List[str] = []
        for key in ("#topics:", "#intent:", "#type:"):
            found = next((ln for ln in lines if ln.lower().startswith(key)), None)
            out.append(found if found else f"{key} ")
        # Log trimmed for brevity
        try:
            tv = out[0][8:].strip() if len(out) > 0 else ""
            iv = out[1][8:].strip() if len(out) > 1 else ""
            ty = out[2][6:].strip() if len(out) > 2 else ""
            logger.info("[TAGGER] topics=%s intent=%s type=%s", tv[:120], iv[:120], ty[:120])
        except Exception:
            pass
        return out
    except Exception as e:
        logger.warning("[TAGGER][WARN] %s", e)
        return None


