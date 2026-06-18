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
from .base import LLMClient
from .providers.openai_provider import OpenAILLMProvider

logger = logging.getLogger(__name__)

_DEFAULT_PROVIDER = "openai"
_MAIN_CLIENT: Optional[LLMClient] = None
_MINI_CLIENT: Optional[LLMClient] = None


def _configured_provider_key() -> str:
    """Return the supported provider key to instantiate for this process.

    B.1.1 keeps the existing OpenAI runtime path. Unsupported configured
    providers fall back explicitly to the default provider with a warning.
    """
    settings = get_settings()
    requested = str(getattr(settings, "llm_provider", _DEFAULT_PROVIDER) or _DEFAULT_PROVIDER)
    provider = requested.strip().lower()
    if provider == _DEFAULT_PROVIDER:
        return provider

    logger.warning(
        "Unsupported LLM provider '%s'; falling back to %s",
        provider,
        _DEFAULT_PROVIDER,
    )
    return _DEFAULT_PROVIDER


def _new_provider(*, provider: str, default_model: str, timeout_s: float) -> LLMClient:
    """Build a provider-agnostic LLM client for the configured provider.

    Args:
        provider: Supported provider key resolved from runtime configuration.
        default_model: Model used when a request does not specify one.
        timeout_s: Per-request timeout in seconds.

    Returns:
        A configured provider client satisfying ``LLMClient``.
    """
    settings = get_settings()
    logger.info(
        "Creating LLM provider instance provider=%s default_model=%s timeout_s=%.2f",
        provider,
        str(default_model),
        float(timeout_s),
    )
    return OpenAILLMProvider(
        api_key=settings.openai_api_key, default_model=default_model, timeout_s=float(timeout_s)
    )


def get_llm_client() -> LLMClient:
    """Return the cached main LLM client, creating it on first use.

    Uses ``MODEL_NAME`` as the default model and ``LLM_REQUEST_TIMEOUT_S`` for
    the request timeout.

    Returns:
        The process-wide main provider-agnostic ``LLMClient`` instance.
    """
    global _MAIN_CLIENT
    if _MAIN_CLIENT is None:
        settings = get_settings()
        default_model = str(settings.model_name)
        timeout_s = float(getattr(settings, "llm_request_timeout_s", 120.0) or 120.0)
        provider = _configured_provider_key()
        _MAIN_CLIENT = _new_provider(
            provider=provider,
            default_model=default_model,
            timeout_s=timeout_s,
        )
        logger.info(
            "Initialized main LLM client provider=%s model=%s timeout_s=%.2f",
            provider,
            default_model,
            timeout_s,
        )
    return _MAIN_CLIENT


def get_llm_client_mini() -> LLMClient:
    """Return the cached mini LLM client, creating it on first use.

    The mini client targets the smaller/faster model used for auxiliary tasks
    (e.g., tagging, builder). Defaults to ``LLM_MINI_MODEL`` (falling back to
    ``BUILDER_MODEL``) with the ``LLM_MINI_REQUEST_TIMEOUT_S`` timeout.

    Returns:
        The process-wide mini provider-agnostic ``LLMClient`` instance.
    """
    global _MINI_CLIENT
    if _MINI_CLIENT is None:
        settings = get_settings()
        default_model = str(getattr(settings, "llm_mini_model", settings.builder_model))
        timeout_s = float(getattr(settings, "llm_mini_request_timeout_s", 30.0) or 30.0)
        provider = _configured_provider_key()
        _MINI_CLIENT = _new_provider(
            provider=provider,
            default_model=default_model,
            timeout_s=timeout_s,
        )
        logger.info(
            "Initialized mini LLM client provider=%s model=%s timeout_s=%.2f",
            provider,
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
