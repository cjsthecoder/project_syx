"""
Factory for provider-selected embedding client.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..core.config import get_settings
from .providers.local_provider import LocalEmbeddingProvider
from .providers.openai_provider import OpenAIEmbeddingProvider

logger = logging.getLogger(__name__)

_EMBEDDING_CLIENT: Optional[object] = None


def get_embedding_client() -> object:
    global _EMBEDDING_CLIENT
    if _EMBEDDING_CLIENT is not None:
        return _EMBEDDING_CLIENT

    settings = get_settings()
    provider = str(getattr(settings, "embedding_provider", "openai") or "openai").strip().lower()
    if provider == "openai":
        logger.info(
            "Creating embedding client provider=%s model=%s",
            "openai",
            str(getattr(settings, "embedding_model", "")),
        )
        _EMBEDDING_CLIENT = OpenAIEmbeddingProvider(api_key=settings.openai_api_key)
        logger.info(
            "Initialized embedding client provider=%s model=%s",
            "openai",
            str(getattr(settings, "embedding_model", "")),
        )
        return _EMBEDDING_CLIENT
    if provider == "local":
        logger.info(
            "Creating embedding client provider=%s model=%s (stub)",
            "local",
            str(getattr(settings, "embedding_model", "")),
        )
        _EMBEDDING_CLIENT = LocalEmbeddingProvider()
        logger.info("Initialized embedding client provider=%s (stub)", "local")
        return _EMBEDDING_CLIENT

    logger.warning("Unknown embedding provider '%s'; defaulting to openai", provider)
    logger.info(
        "Creating embedding client provider=%s model=%s",
        "openai",
        str(getattr(settings, "embedding_model", "")),
    )
    _EMBEDDING_CLIENT = OpenAIEmbeddingProvider(api_key=settings.openai_api_key)
    logger.info(
        "Initialized embedding client provider=%s model=%s",
        "openai",
        str(getattr(settings, "embedding_model", "")),
    )
    return _EMBEDDING_CLIENT


def reset_embedding_client() -> None:
    global _EMBEDDING_CLIENT
    _EMBEDDING_CLIENT = None
