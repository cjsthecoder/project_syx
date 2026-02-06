"""
LLMClient: containment boundary for model interactions.

Public interface must be plain-data only (no vendor SDK types).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import List, Optional

from openai import OpenAI

from ..core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class EmbedResult:
    vectors: List[List[float]]
    model: str


class LLMClient:
    """
    OpenAI-backed LLMClient.

    Only plain-data crosses this boundary.
    """

    def __init__(self, *, api_key: str) -> None:
        self._client = OpenAI(api_key=api_key)

    def embed(self, texts: List[str], *, model: Optional[str] = None, retries: int = 2) -> EmbedResult:
        """
        Embed texts via OpenAI embeddings API.

        Returns raw (unnormalized) vectors; normalization belongs in vector layer.
        """
        settings = get_settings()
        use_model = model or settings.embedding_model
        clean = [t if isinstance(t, str) else "" for t in (texts or [])]
        if not clean:
            return EmbedResult(vectors=[], model=str(use_model))

        last_err: Optional[Exception] = None
        for attempt in range(int(retries) + 1):
            try:
                t0 = time.monotonic()
                resp = self._client.embeddings.create(model=str(use_model), input=clean)
                # OpenAI SDK returns resp.data items with .embedding list[float]
                vectors: List[List[float]] = []
                for item in getattr(resp, "data", []) or []:
                    vec = getattr(item, "embedding", None)
                    if isinstance(vec, list):
                        vectors.append([float(x) for x in vec])
                dt = time.monotonic() - t0
                if attempt > 0:
                    logger.warning("LLMClient.embed recovered after retries=%s in %.2fs", attempt, dt)
                return EmbedResult(vectors=vectors, model=str(use_model))
            except Exception as e:
                last_err = e
                if attempt >= int(retries):
                    break
                # Best-effort exponential backoff; keep small for interactive usage.
                try:
                    time.sleep(0.4 * (2**attempt))
                except Exception:
                    pass
        raise RuntimeError(f"LLMClient.embed failed after retries={retries}: {last_err}")

    def embed_query(self, text: str, *, model: Optional[str] = None) -> List[float]:
        res = self.embed([text or ""], model=model)
        return res.vectors[0] if res.vectors else []


_CLIENT: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Process-wide singleton."""
    global _CLIENT
    if _CLIENT is None:
        s = get_settings()
        _CLIENT = LLMClient(api_key=s.openai_api_key)
    return _CLIENT

