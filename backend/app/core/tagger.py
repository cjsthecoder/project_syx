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

_PROMPT = """Classify this exchange for memory tagging.
Return 1-3 metadata lines only in this format:
#topics: <keywords>
#intent: <purpose>
#type: <category such as technical, design, story, system, etc.>"""


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


