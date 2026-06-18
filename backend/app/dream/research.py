"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Remote research helpers for the Dream cycle.

Provides token counting/trimming utilities and a best-effort web-search-backed
research fetch used to enrich Dream reasoning.
"""
import logging

from ..core.config import get_settings
from ..core.llm_service import generate_research_response
from ..utils.tokens import count_tokens as _count_tokens
from ..utils.tokens import trim_to_tokens as _trim_to_tokens

logger = logging.getLogger(__name__)


def count_tokens(text: str) -> int:
    """Count tokens in ``text``, treating ``None`` as empty."""
    return int(_count_tokens(text or ""))


def trim_to_tokens(text: str, max_tokens: int) -> str:
    """Trim ``text`` to at most ``max_tokens`` tokens, treating ``None`` as empty."""
    return _trim_to_tokens(text or "", max_tokens)


def fetch_remote_research(query: str) -> str:
    """Fetch remote research through the provider-agnostic LLM boundary.

    Best-effort: LLM/tool failures are logged and return an empty string rather
    than raising.

    Args:
        query: Research subject; embedded into the web-research instruction prompt.

    Returns:
        Research text blob (may be long; caller is responsible for capping
        tokens), or an empty string on failure.
    """
    settings = get_settings()
    try:
        response = generate_research_response(
            f"Perform web research to gather concise factual context for: {query}",
            override_model=settings.dream_model,
            system_prompt=None,
            temperature_override=float(settings.dream_temperature),
            max_output_tokens=int(settings.dream_max_tokens),
            purpose="dream:remote_research",
        )
        return response.text
    except Exception as e:
        logger.warning("[DREAM][WARN] Remote research failed: %s", e)
        return ""
