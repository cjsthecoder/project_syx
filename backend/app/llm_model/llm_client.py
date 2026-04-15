"""
LLMClient: containment boundary for model interactions.

Public interface must be plain-data only (no vendor SDK types).
"""

from __future__ import annotations

import logging
import random
import re
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

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        msg = str(exc or "").lower()
        return ("rate limit" in msg) or ("too many requests" in msg) or ("429" in msg)

    @staticmethod
    def _extract_retry_after_seconds(exc: Exception) -> Optional[float]:
        """
        Parse provider hints like "Please try again in 2.505s" from exception text.
        Returns None when no hint is present.
        """
        msg = str(exc or "")
        m = re.search(r"try again in\s*([0-9]+(?:\.[0-9]+)?)s", msg, flags=re.IGNORECASE)
        if not m:
            return None
        try:
            return float(m.group(1))
        except Exception:
            return None

    def embed(
        self,
        texts: List[str],
        *,
        model: Optional[str] = None,
        retries: int = 2,
        rate_limit_retries: int = 10,
    ) -> EmbedResult:
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
        general_attempt = 0
        rate_limit_attempt = 0
        while True:
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
                total_retry_attempts = int(general_attempt) + int(rate_limit_attempt)
                if total_retry_attempts > 0:
                    logger.warning(
                        "LLMClient.embed recovered after retries=%s (general=%s, rate_limit=%s) in %.2fs",
                        int(total_retry_attempts),
                        int(general_attempt),
                        int(rate_limit_attempt),
                        dt,
                    )
                return EmbedResult(vectors=vectors, model=str(use_model))
            except Exception as e:
                last_err = e
                if self._is_rate_limit_error(e):
                    rate_limit_attempt += 1
                    retry_after_s = self._extract_retry_after_seconds(e)
                    base_wait = retry_after_s if retry_after_s is not None else (0.6 * (2 ** min(rate_limit_attempt - 1, 5)))
                    wait_s = float(base_wait) + random.uniform(0.0, 0.25)
                    logger.warning(
                        "LLMClient.embed rate-limit/throttle model=%s attempt=%s/%s wait_s=%.2f detail=%s",
                        str(use_model),
                        int(rate_limit_attempt),
                        int(rate_limit_retries),
                        float(wait_s),
                        str(e),
                    )
                    if rate_limit_attempt > int(rate_limit_retries):
                        break
                    try:
                        time.sleep(wait_s)
                    except Exception as exc:
                        logger.info(
                            "LLMClient.embed sleep interrupted during rate-limit backoff; model=%s wait_s=%.2f detail=%s",
                            str(use_model),
                            float(wait_s),
                            str(exc),
                        )
                    continue

                general_attempt += 1
                if general_attempt > int(retries):
                    break
                # Best-effort exponential backoff; keep small for interactive usage.
                try:
                    backoff_s = (0.4 * (2 ** (general_attempt - 1))) + random.uniform(0.0, 0.2)
                    time.sleep(backoff_s)
                except Exception as exc:
                    logger.info(
                        "LLMClient.embed sleep interrupted during general backoff; model=%s backoff_s=%.2f detail=%s",
                        str(use_model),
                        float(backoff_s),
                        str(exc),
                    )
        raise RuntimeError(
            "LLMClient.embed failed after retries="
            f"{retries} and rate_limit_retries={rate_limit_retries}: {last_err}"
        )

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

