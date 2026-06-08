"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
OpenAI embedding provider implementation.
"""


import logging
import random
import re
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI

from ...core.config import get_active_embedding_model, get_settings
from ..base import EmbedResult

logger = logging.getLogger(__name__)


class OpenAIEmbeddingProvider:
    """Embedding client backed by the OpenAI embeddings API.

    Wraps the OpenAI SDK and adds retry/backoff handling for transient errors,
    rate limiting (HTTP 429), and request timeouts.
    """

    def __init__(self, *, api_key: str) -> None:
        """Construct the provider and initialize the OpenAI SDK client.

        Args:
            api_key: OpenAI API key used to authenticate requests.
        """
        settings = get_settings()
        self._timeout_s = float(getattr(settings, "embedding_request_timeout_s", 45.0) or 45.0)
        self._client = OpenAI(api_key=api_key, timeout=self._timeout_s)

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        """Report whether an exception represents provider rate limiting.

        Args:
            exc: Exception raised by the OpenAI SDK call.

        Returns:
            True if the error looks like an HTTP 429 / rate-limit condition,
            based on the status code or message text.
        """
        try:
            status_code = getattr(exc, "status_code", None)
            if int(status_code or 0) == 429:
                return True
        except (TypeError, ValueError):
            pass
        msg = str(exc or "").lower()
        return ("rate limit" in msg) or ("too many requests" in msg) or ("429" in msg)

    @staticmethod
    def _extract_retry_after_seconds(exc: Exception) -> Optional[float]:
        """Extract the provider's suggested retry delay from an error.

        Looks first at a ``retry-after`` response header and falls back to
        parsing a "try again in Ns" hint from the message text.

        Args:
            exc: Exception raised by the OpenAI SDK call.

        Returns:
            The suggested wait in seconds, or ``None`` if no hint is present or
            it cannot be parsed.
        """
        try:
            response = getattr(exc, "response", None)
            headers = getattr(response, "headers", None)
            if isinstance(headers, Dict):
                retry_after = headers.get("retry-after")
                if retry_after is not None:
                    return float(retry_after)
            if headers is not None and hasattr(headers, "get"):
                retry_after = headers.get("retry-after")
                if retry_after is not None:
                    return float(retry_after)
        except (TypeError, ValueError) as header_exc:
            logger.debug("embedding provider retry-after header parse skipped detail=%s", header_exc)
        msg = str(exc or "")
        m = re.search(r"try again in\s*([0-9]+(?:\.[0-9]+)?)s", msg, flags=re.IGNORECASE)
        if not m:
            return None
        try:
            return float(m.group(1))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_timeout_error(exc: Exception) -> bool:
        """Report whether an exception represents a request timeout.

        Args:
            exc: Exception raised by the OpenAI SDK call.

        Returns:
            True if the error message indicates a timeout.
        """
        msg = str(exc or "").lower()
        return ("timed out" in msg) or ("timeout" in msg)

    def embed(
        self,
        texts: List[str],
        *,
        model: Optional[str] = None,
        retries: int = 2,
        rate_limit_retries: int = 10,
    ) -> EmbedResult:
        """Embed texts via the OpenAI API with retry and backoff.

        Issues a network request to OpenAI. Rate-limit errors honor the
        provider's ``retry-after`` hint when available; other transient errors
        use exponential backoff with jitter.

        Args:
            texts: Input strings to embed; non-string items are coerced to "".
            model: Optional model override; defaults to the active embedding model.
            retries: Maximum general (non-rate-limit) retry attempts.
            rate_limit_retries: Maximum rate-limit retry attempts.

        Returns:
            An ``EmbedResult`` with one vector per input text.

        Raises:
            RuntimeError: If the request still fails after exhausting all retries.
        """
        settings = get_settings()
        use_model = model or get_active_embedding_model()
        clean = [t if isinstance(t, str) else "" for t in (texts or [])]
        if not clean:
            return EmbedResult(vectors=[], model=str(use_model))

        last_err: Optional[Exception] = None
        general_attempt = 0
        rate_limit_attempt = 0
        while True:
            try:
                t0 = time.monotonic()
                resp = self._client.embeddings.create(
                    model=str(use_model),
                    input=clean,
                    timeout=self._timeout_s,
                )
                vectors: List[List[float]] = []
                data = getattr(resp, "data", None)
                if data is None:
                    dumped = getattr(resp, "model_dump", None)
                    if callable(dumped):
                        obj = dumped(mode="python")
                        if isinstance(obj, dict):
                            data = obj.get("data", [])
                for item in data or []:
                    vec = getattr(item, "embedding", None)
                    if vec is None and isinstance(item, dict):
                        vec = item.get("embedding")
                    if isinstance(vec, list):
                        vectors.append([float(x) for x in vec])
                dt = time.monotonic() - t0
                total_retry_attempts = int(general_attempt) + int(rate_limit_attempt)
                if total_retry_attempts > 0:
                    logger.warning(
                        "embedding provider recovered after retries=%s (general=%s, rate_limit=%s) in %.2fs",
                        int(total_retry_attempts),
                        int(general_attempt),
                        int(rate_limit_attempt),
                        dt,
                    )
                return EmbedResult(vectors=vectors, model=str(use_model))
            except Exception as exc:
                last_err = exc
                if self._is_timeout_error(exc):
                    logger.warning(
                        "embedding provider request timed out model=%s timeout_s=%.2f attempt_general=%s/%s attempt_rate_limit=%s/%s detail=%s",
                        str(use_model),
                        float(self._timeout_s),
                        int(general_attempt + 1),
                        int(retries),
                        int(rate_limit_attempt),
                        int(rate_limit_retries),
                        str(exc),
                    )
                if self._is_rate_limit_error(exc):
                    rate_limit_attempt += 1
                    retry_after_s = self._extract_retry_after_seconds(exc)
                    base_wait = retry_after_s if retry_after_s is not None else (0.6 * (2 ** min(rate_limit_attempt - 1, 5)))
                    wait_s = float(base_wait) + random.uniform(0.0, 0.25)
                    logger.warning(
                        "embedding provider throttled model=%s attempt=%s/%s wait_s=%.2f detail=%s",
                        str(use_model),
                        int(rate_limit_attempt),
                        int(rate_limit_retries),
                        float(wait_s),
                        str(exc),
                    )
                    if rate_limit_attempt > int(rate_limit_retries):
                        break
                    try:
                        time.sleep(wait_s)
                    except Exception as sleep_exc:
                        logger.info(
                            "embedding provider sleep interrupted during rate-limit backoff model=%s wait_s=%.2f detail=%s",
                            str(use_model),
                            float(wait_s),
                            sleep_exc,
                        )
                    continue

                general_attempt += 1
                if general_attempt > int(retries):
                    break
                try:
                    backoff_s = (0.4 * (2 ** (general_attempt - 1))) + random.uniform(0.0, 0.2)
                    time.sleep(backoff_s)
                except Exception as sleep_exc:
                    logger.info(
                        "embedding provider sleep interrupted during general backoff model=%s backoff_s=%.2f detail=%s",
                        str(use_model),
                        float(backoff_s),
                        sleep_exc,
                    )
        raise RuntimeError(
            "embedding provider failed after retries="
            f"{retries} and rate_limit_retries={rate_limit_retries}: {last_err}"
        )

    def embed_query(self, text: str, *, model: Optional[str] = None) -> List[float]:
        """Embed a single query string and return its vector (empty if none).

        Issues a network request via :meth:`embed`.

        Args:
            text: Query string to embed; ``None`` is treated as empty.
            model: Optional model override; defaults to the active embedding model.

        Returns:
            The embedding vector for ``text``, or an empty list when no vector
            is produced.
        """
        res = self.embed([text or ""], model=model)
        return res.vectors[0] if res.vectors else []
