"""
Factory functions for provider-selected LLM clients.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..core.config import get_settings
from .providers.openai_provider import OpenAILLMProvider

logger = logging.getLogger(__name__)

_MAIN_CLIENT: Optional[OpenAILLMProvider] = None
_MINI_CLIENT: Optional[OpenAILLMProvider] = None


def _new_provider(*, default_model: str) -> OpenAILLMProvider:
    settings = get_settings()
    provider = str(getattr(settings, "llm_provider", "openai") or "openai").strip().lower()
    if provider != "openai":
        logger.warning("Unsupported LLM provider '%s'; falling back to openai", provider)
    logger.info(
        "Creating LLM provider instance provider=%s default_model=%s",
        "openai",
        str(default_model),
    )
    return OpenAILLMProvider(api_key=settings.openai_api_key, default_model=default_model)


def get_llm_client() -> OpenAILLMProvider:
    global _MAIN_CLIENT
    if _MAIN_CLIENT is None:
        settings = get_settings()
        default_model = str(getattr(settings, "llm_main_model", settings.model_name))
        _MAIN_CLIENT = _new_provider(default_model=default_model)
        logger.info(
            "Initialized main LLM client provider=%s model=%s",
            str(getattr(settings, "llm_provider", "openai") or "openai"),
            default_model,
        )
    return _MAIN_CLIENT


def get_llm_client_mini() -> OpenAILLMProvider:
    global _MINI_CLIENT
    if _MINI_CLIENT is None:
        settings = get_settings()
        default_model = str(getattr(settings, "llm_mini_model", settings.builder_model))
        _MINI_CLIENT = _new_provider(default_model=default_model)
        logger.info(
            "Initialized mini LLM client provider=%s model=%s",
            str(getattr(settings, "llm_provider", "openai") or "openai"),
            default_model,
        )
    return _MINI_CLIENT


def reset_llm_clients() -> None:
    global _MAIN_CLIENT, _MINI_CLIENT
    _MAIN_CLIENT = None
    _MINI_CLIENT = None
