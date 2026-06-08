"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Factory for provider-selected embedding client.
"""


import logging
from typing import Optional

from ..core.config import get_active_embedding_model, get_settings
from .providers.openai_provider import OpenAIEmbeddingProvider
from .providers.sentence_transformers_provider import SentenceTransformersEmbeddingProvider

logger = logging.getLogger(__name__)

_EMBEDDING_CLIENT: Optional[object] = None


def get_embedding_client() -> object:
    """Return the process-wide embedding client, creating it on first use.

    Selects the provider from ``EMBEDDING_PROVIDER`` (``openai`` or
    ``sentence_transformers``) and caches the resulting instance for reuse.
    Construction may load a local model or initialize a network-backed client.

    Returns:
        The cached embedding client implementing the ``EmbeddingClient`` protocol.

    Raises:
        RuntimeError: If the OpenAI provider is selected without ``OPENAI_API_KEY``,
            or if the configured provider name is unsupported.
    """
    global _EMBEDDING_CLIENT
    if _EMBEDDING_CLIENT is not None:
        return _EMBEDDING_CLIENT

    settings = get_settings()
    provider = str(getattr(settings, "embedding_provider", "openai") or "openai").strip().lower()
    active_model = get_active_embedding_model()
    if provider == "openai":
        if not str(settings.openai_api_key or "").strip():
            raise RuntimeError("EMBEDDING_PROVIDER=openai requires OPENAI_API_KEY to be set.")
        logger.info(
            "Creating embedding client provider=%s model=%s",
            "openai",
            active_model,
        )
        _EMBEDDING_CLIENT = OpenAIEmbeddingProvider(api_key=settings.openai_api_key)
        logger.info(
            "Initialized embedding client provider=%s model=%s",
            "openai",
            active_model,
        )
        return _EMBEDDING_CLIENT
    if provider == "sentence_transformers":
        logger.info(
            "Creating embedding client provider=%s model=%s",
            "sentence_transformers",
            active_model,
        )
        _EMBEDDING_CLIENT = SentenceTransformersEmbeddingProvider()
        logger.info(
            "Initialized embedding client provider=%s model=%s",
            "sentence_transformers",
            active_model,
        )
        return _EMBEDDING_CLIENT

    raise RuntimeError(
        f"Unknown embedding provider '{provider}'. "
        "Supported providers: openai, sentence_transformers."
    )


def reset_embedding_client() -> None:
    """Clear the cached embedding client so the next call rebuilds it.

    Useful after configuration changes (e.g., provider or model) and in tests.
    """
    global _EMBEDDING_CLIENT
    _EMBEDDING_CLIENT = None
