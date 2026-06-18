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
from .registry import (
    LLMModelRegistryError,
    RuntimeLLMModels,
    get_active_llm_models,
    reset_llm_model_registry_cache,
    set_active_llm_model_selection,
)

logger = logging.getLogger(__name__)

_MAIN_CLIENT: Optional[LLMClient] = None
_MINI_CLIENT: Optional[LLMClient] = None


def _provider_client(*, provider: str, default_model: str, timeout_s: float) -> LLMClient:
    """Construct a concrete provider client for a supported factory provider key.

    Provider SDK imports remain behind this factory/provider boundary. B.1.2
    ships with OpenAI only; B.1.3 adds Anthropic by registering another
    provider implementation here.
    """
    settings = get_settings()
    if provider == "openai":
        return OpenAILLMProvider(
            api_key=settings.openai_api_key,
            default_model=default_model,
            timeout_s=float(timeout_s),
        )
    raise LLMModelRegistryError(f"Unsupported LLM factory provider '{provider}'")


def _new_provider(*, models: RuntimeLLMModels, default_model: str, timeout_s: float) -> LLMClient:
    """Build a provider-agnostic LLM client for the resolved runtime model set.

    Args:
        models: Provider-scoped runtime model set resolved from the registry.
        default_model: Role-specific model used when a request does not specify one.
        timeout_s: Per-request timeout in seconds.

    Returns:
        A configured provider client satisfying ``LLMClient``.
    """
    logger.info(
        "Creating LLM provider instance provider=%s factory_provider=%s default_model=%s timeout_s=%.2f",
        models.provider_id,
        models.factory_provider,
        str(default_model),
        float(timeout_s),
    )
    return _provider_client(
        provider=models.factory_provider,
        default_model=default_model,
        timeout_s=float(timeout_s),
    )


def get_llm_client() -> LLMClient:
    """Return the cached main LLM client, creating it on first use.

    Uses the registry-resolved main chat model as the default model and
    ``LLM_REQUEST_TIMEOUT_S`` for the request timeout.

    Returns:
        The process-wide main provider-agnostic ``LLMClient`` instance.
    """
    global _MAIN_CLIENT
    if _MAIN_CLIENT is None:
        settings = get_settings()
        models = get_active_llm_models()
        default_model = models.main_model
        timeout_s = float(getattr(settings, "llm_request_timeout_s", 120.0) or 120.0)
        _MAIN_CLIENT = _new_provider(
            models=models,
            default_model=default_model,
            timeout_s=timeout_s,
        )
        logger.info(
            "Initialized main LLM client provider=%s model=%s timeout_s=%.2f",
            models.provider_id,
            default_model,
            timeout_s,
        )
    return _MAIN_CLIENT


def get_llm_client_mini() -> LLMClient:
    """Return the cached mini LLM client, creating it on first use.

    The mini client targets the smaller/faster model used for auxiliary tasks
    (e.g., tagging, builder). Defaults to the registry-resolved mini/helper
    role with the ``LLM_MINI_REQUEST_TIMEOUT_S`` timeout.

    Returns:
        The process-wide mini provider-agnostic ``LLMClient`` instance.
    """
    global _MINI_CLIENT
    if _MINI_CLIENT is None:
        settings = get_settings()
        models = get_active_llm_models()
        default_model = models.mini_model
        timeout_s = float(getattr(settings, "llm_mini_request_timeout_s", 30.0) or 30.0)
        _MINI_CLIENT = _new_provider(
            models=models,
            default_model=default_model,
            timeout_s=timeout_s,
        )
        logger.info(
            "Initialized mini LLM client provider=%s model=%s timeout_s=%.2f",
            models.provider_id,
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


def reset_llm_runtime_state() -> None:
    """Clear cached LLM clients and registry-resolved active model selection."""
    reset_llm_clients()
    reset_llm_model_registry_cache()


def select_llm_model_for_request(selection: Optional[str]) -> RuntimeLLMModels:
    """Resolve and activate the provider/model selection for a request.

    Args:
        selection: Optional provider-qualified model string. ``None`` resolves
            the startup/default provider selection from the registry.

    Returns:
        The active provider-scoped runtime model set.

    Raises:
        LLMModelRegistryError: If the selection or registry is invalid.
    """
    models, changed = set_active_llm_model_selection(selection)
    if changed:
        reset_llm_clients()
    return models
