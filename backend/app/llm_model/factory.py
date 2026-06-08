"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Factory functions for provider-selected LLM clients.
"""


import logging
from typing import Optional

from ..core.config import get_settings
from .providers.openai_provider import OpenAILLMProvider

logger = logging.getLogger(__name__)

_MAIN_CLIENT: Optional[OpenAILLMProvider] = None
_MINI_CLIENT: Optional[OpenAILLMProvider] = None


def _new_provider(*, default_model: str, timeout_s: float) -> OpenAILLMProvider:
    """Build an OpenAI LLM provider for the given default model and timeout.

    Only ``openai`` is currently supported; any other configured
    ``LLM_PROVIDER`` value is logged and falls back to OpenAI.

    Args:
        default_model: Model used when a request does not specify one.
        timeout_s: Per-request timeout in seconds.

    Returns:
        A configured ``OpenAILLMProvider`` instance.
    """
    settings = get_settings()
    provider = str(getattr(settings, "llm_provider", "openai") or "openai").strip().lower()
    if provider != "openai":
        logger.warning("Unsupported LLM provider '%s'; falling back to openai", provider)
    logger.info(
        "Creating LLM provider instance provider=%s default_model=%s timeout_s=%.2f",
        "openai",
        str(default_model),
        float(timeout_s),
    )
    return OpenAILLMProvider(
        api_key=settings.openai_api_key, default_model=default_model, timeout_s=float(timeout_s)
    )


def get_llm_client() -> OpenAILLMProvider:
    """Return the cached main LLM client, creating it on first use.

    Uses ``MODEL_NAME`` as the default model and ``LLM_REQUEST_TIMEOUT_S`` for
    the request timeout.

    Returns:
        The process-wide main ``OpenAILLMProvider`` instance.
    """
    global _MAIN_CLIENT
    if _MAIN_CLIENT is None:
        settings = get_settings()
        default_model = str(settings.model_name)
        timeout_s = float(getattr(settings, "llm_request_timeout_s", 120.0) or 120.0)
        _MAIN_CLIENT = _new_provider(default_model=default_model, timeout_s=timeout_s)
        logger.info(
            "Initialized main LLM client provider=%s model=%s timeout_s=%.2f",
            str(getattr(settings, "llm_provider", "openai") or "openai"),
            default_model,
            timeout_s,
        )
    return _MAIN_CLIENT


def get_llm_client_mini() -> OpenAILLMProvider:
    """Return the cached mini LLM client, creating it on first use.

    The mini client targets the smaller/faster model used for auxiliary tasks
    (e.g., tagging, builder). Defaults to ``LLM_MINI_MODEL`` (falling back to
    ``BUILDER_MODEL``) with the ``LLM_MINI_REQUEST_TIMEOUT_S`` timeout.

    Returns:
        The process-wide mini ``OpenAILLMProvider`` instance.
    """
    global _MINI_CLIENT
    if _MINI_CLIENT is None:
        settings = get_settings()
        default_model = str(getattr(settings, "llm_mini_model", settings.builder_model))
        timeout_s = float(getattr(settings, "llm_mini_request_timeout_s", 30.0) or 30.0)
        _MINI_CLIENT = _new_provider(default_model=default_model, timeout_s=timeout_s)
        logger.info(
            "Initialized mini LLM client provider=%s model=%s timeout_s=%.2f",
            str(getattr(settings, "llm_provider", "openai") or "openai"),
            default_model,
            timeout_s,
        )
    return _MINI_CLIENT


def reset_llm_clients() -> None:
    """Clear cached main and mini LLM clients so they rebuild on next use.

    Useful after configuration changes and in tests.
    """
    global _MAIN_CLIENT, _MINI_CLIENT
    _MAIN_CLIENT = None
    _MINI_CLIENT = None
