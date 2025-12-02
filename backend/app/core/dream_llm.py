import logging
from typing import Optional
from openai import OpenAI
from .config import get_settings

logger = logging.getLogger(__name__)


def dream_llm_call(prompt: str, max_output_tokens: Optional[int] = None) -> str:
    """
    Thin wrapper over OpenAI Responses API for Dream.
    Returns the text content (string) of the response.
    """
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    max_tokens = int(max_output_tokens or settings.dream_max_tokens)
    try:
        resp = client.responses.create(
            model=settings.dream_model,
            input=prompt,
            temperature=settings.dream_temperature,
            max_output_tokens=max_tokens,
        )
        # New Responses API: text output is in output_text, or assemble from content parts
        text = getattr(resp, "output_text", None)
        if text:
            return text
        # Fallback: concatenate text parts
        out = []
        for item in getattr(resp, "output", []) or []:
            if getattr(item, "type", "") == "message":
                for c in getattr(item, "content", []) or []:
                    if getattr(c, "type", "") == "output_text":
                        out.append(getattr(c, "text", "") or "")
        return "".join(out)
    except Exception as e:
        logger.warning("[DREAM][WARN] LLM call failed: %s", e)
        return '{"answer": "Dream agent failed to generate a valid answer."}'


