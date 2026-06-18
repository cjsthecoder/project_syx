"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Provider-scoped LLM model registry and runtime model resolution.
"""

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping, Optional

from ..core.config import get_settings

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LLM_MODELS_PATH = os.path.abspath(
    os.path.join(_THIS_DIR, "..", "config", "llm_models.json")
)
_REQUIRED_ROLES = ("mini", "builder", "tagger", "dream")
_ACTIVE_MODELS: Optional["RuntimeLLMModels"] = None


class LLMModelRegistryError(RuntimeError):
    """Raised when the app-owned LLM model registry is invalid or unusable."""


@dataclass(frozen=True)
class LLMModelInfo:
    """Selectable model metadata from the provider registry.

    Attributes:
        id: Provider-native model id sent to the concrete LLM provider.
        label: Human-readable label shown by clients.
    """

    id: str
    label: str


@dataclass(frozen=True)
class LLMProviderModels:
    """Provider-owned model inventory and runtime role defaults.

    Attributes:
        provider_id: Stable provider id used in UI/backend selections.
        label: Human-readable provider label.
        factory_provider: Provider implementation key used by the factory.
        default_model: Default main chat model for this provider.
        models: Selectable main chat models.
        roles: Runtime role defaults for mini, builder, tagger, and Dream.
    """

    provider_id: str
    label: str
    factory_provider: str
    default_model: str
    models: tuple[LLMModelInfo, ...]
    roles: Mapping[str, str]


@dataclass(frozen=True)
class RuntimeLLMModels:
    """Resolved provider-scoped model set used by runtime LLM clients.

    Attributes:
        provider_id: Selected provider id.
        provider_label: Human-readable provider label.
        factory_provider: Provider implementation key used by the factory.
        selection_value: Provider-qualified main model selection, e.g. ``openai/gpt-5.5``.
        main_model: Provider-native main chat model id.
        mini_model: Provider-native mini/helper model id.
        builder_model: Provider-native query builder model id.
        tagger_model: Provider-native tagger model id.
        dream_model: Provider-native Dream model id.
    """

    provider_id: str
    provider_label: str
    factory_provider: str
    selection_value: str
    main_model: str
    mini_model: str
    builder_model: str
    tagger_model: str
    dream_model: str


@dataclass(frozen=True)
class LLMModelRegistry:
    """Validated app-owned registry of supported LLM providers and model sets.

    Attributes:
        providers: Mapping of provider id to provider-scoped model metadata.
    """

    providers: Mapping[str, LLMProviderModels]


def _coerce_non_empty_str(value: Any, *, field: str) -> str:
    """Return a stripped string or raise when a registry field is missing."""
    text = str(value or "").strip()
    if not text:
        raise LLMModelRegistryError(f"LLM model registry missing required field: {field}")
    return text


def _parse_model_entry(provider_id: str, raw: Any) -> LLMModelInfo:
    """Parse one model metadata entry from the registry."""
    if not isinstance(raw, dict):
        raise LLMModelRegistryError(
            f"LLM model registry provider '{provider_id}' has a non-object model entry"
        )
    model_id = _coerce_non_empty_str(raw.get("id"), field=f"{provider_id}.models[].id")
    label = str(raw.get("label") or model_id).strip() or model_id
    return LLMModelInfo(id=model_id, label=label)


def _parse_provider(provider_id: str, raw: Any) -> LLMProviderModels:
    """Parse and validate one provider entry from the registry."""
    if not isinstance(raw, dict):
        raise LLMModelRegistryError(
            f"LLM model registry provider '{provider_id}' must be an object"
        )

    label = _coerce_non_empty_str(raw.get("label"), field=f"{provider_id}.label")
    factory_provider = _coerce_non_empty_str(
        raw.get("factory_provider"),
        field=f"{provider_id}.factory_provider",
    )
    default_model = _coerce_non_empty_str(
        raw.get("default_model"),
        field=f"{provider_id}.default_model",
    )

    raw_models = raw.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise LLMModelRegistryError(
            f"LLM model registry provider '{provider_id}' must define non-empty models"
        )
    models = tuple(_parse_model_entry(provider_id, item) for item in raw_models)
    model_ids = {model.id for model in models}
    if default_model not in model_ids:
        raise LLMModelRegistryError(
            f"LLM model registry provider '{provider_id}' default_model '{default_model}' "
            "is not selectable"
        )

    raw_roles = raw.get("roles")
    if not isinstance(raw_roles, dict):
        raise LLMModelRegistryError(
            f"LLM model registry provider '{provider_id}' must define roles"
        )
    roles = {
        role: _coerce_non_empty_str(raw_roles.get(role), field=f"{provider_id}.roles.{role}")
        for role in _REQUIRED_ROLES
    }
    invalid_roles = {role: model for role, model in roles.items() if model not in model_ids}
    if invalid_roles:
        formatted = ", ".join(f"{role}={model}" for role, model in sorted(invalid_roles.items()))
        raise LLMModelRegistryError(
            f"LLM model registry provider '{provider_id}' has non-selectable role models: "
            f"{formatted}"
        )

    return LLMProviderModels(
        provider_id=provider_id,
        label=label,
        factory_provider=factory_provider,
        default_model=default_model,
        models=models,
        roles=roles,
    )


def _registry_path() -> str:
    """Return the configured LLM model registry path."""
    settings = get_settings()
    configured = str(getattr(settings, "llm_models_registry_path", "") or "").strip()
    return os.path.abspath(configured or DEFAULT_LLM_MODELS_PATH)


@lru_cache(maxsize=1)
def load_llm_model_registry(path: Optional[str] = None) -> LLMModelRegistry:
    """Load and validate the app-owned LLM model registry.

    Args:
        path: Optional registry path override used by tests.

    Returns:
        A validated ``LLMModelRegistry``.

    Raises:
        LLMModelRegistryError: If the registry file is missing, malformed, or invalid.
    """
    registry_path = os.path.abspath(path or _registry_path())
    try:
        with open(registry_path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError as exc:
        raise LLMModelRegistryError(f"LLM model registry not found at {registry_path}") from exc
    except json.JSONDecodeError as exc:
        raise LLMModelRegistryError(
            f"LLM model registry is malformed JSON at {registry_path}: {exc}"
        ) from exc

    if not isinstance(raw, dict) or not isinstance(raw.get("providers"), dict):
        raise LLMModelRegistryError("LLM model registry must define a providers object")
    providers = {
        str(provider_id).strip().lower(): _parse_provider(str(provider_id).strip().lower(), entry)
        for provider_id, entry in raw["providers"].items()
        if str(provider_id).strip()
    }
    if not providers:
        raise LLMModelRegistryError("LLM model registry must include at least one provider")
    return LLMModelRegistry(providers=providers)


def reset_llm_model_registry_cache() -> None:
    """Clear cached registry and active runtime model resolution."""
    global _ACTIVE_MODELS
    load_llm_model_registry.cache_clear()
    _ACTIVE_MODELS = None


def _provider_or_raise(registry: LLMModelRegistry, provider_id: str) -> LLMProviderModels:
    """Return a provider registry entry or raise a clear compatibility error."""
    provider = registry.providers.get(provider_id)
    if provider is None:
        raise LLMModelRegistryError(
            f"LLM provider '{provider_id}' is not defined in the model registry"
        )
    return provider


def _split_selection(
    selection: Optional[str], *, default_provider: str
) -> tuple[str, Optional[str]]:
    """Split a provider-qualified or legacy bare model selection."""
    text = str(selection or "").strip()
    if not text:
        return default_provider, None
    if "/" not in text:
        return default_provider, text

    provider_id, model_id = text.split("/", 1)
    provider_id = provider_id.strip().lower()
    model_id = model_id.strip()
    if not provider_id or not model_id:
        raise LLMModelRegistryError(
            f"Invalid LLM model selection '{selection}'; expected provider/model"
        )
    return provider_id, model_id


def provider_qualified_model(provider_id: str, model_id: str) -> str:
    """Return the provider-qualified model selection string used by the UI/API."""
    return f"{str(provider_id).strip().lower()}/{str(model_id).strip()}"


def resolve_runtime_llm_models(selection: Optional[str] = None) -> RuntimeLLMModels:
    """Resolve provider-scoped runtime models from a UI/API selection or defaults.

    Args:
        selection: Optional provider-qualified model string such as
            ``openai/gpt-5.5``. Bare model ids are accepted for the configured
            startup provider for migration compatibility.

    Returns:
        The coherent runtime model set for main, mini, builder, tagger, and Dream.

    Raises:
        LLMModelRegistryError: If provider/model compatibility validation fails.
    """
    settings = get_settings()
    registry = load_llm_model_registry()
    default_provider = str(getattr(settings, "llm_provider", "openai") or "openai").strip().lower()
    provider_id, selected_model = _split_selection(selection, default_provider=default_provider)
    provider = _provider_or_raise(registry, provider_id)
    model_id = selected_model or provider.default_model
    selectable = {model.id for model in provider.models}
    if model_id not in selectable:
        raise LLMModelRegistryError(
            f"LLM model '{model_id}' is not selectable for provider '{provider_id}'"
        )

    return RuntimeLLMModels(
        provider_id=provider.provider_id,
        provider_label=provider.label,
        factory_provider=provider.factory_provider,
        selection_value=provider_qualified_model(provider.provider_id, model_id),
        main_model=model_id,
        mini_model=provider.roles["mini"],
        builder_model=provider.roles["builder"],
        tagger_model=provider.roles["tagger"],
        dream_model=provider.roles["dream"],
    )


def get_active_llm_models() -> RuntimeLLMModels:
    """Return the active runtime model set, resolving startup defaults if needed."""
    global _ACTIVE_MODELS
    if _ACTIVE_MODELS is None:
        _ACTIVE_MODELS = resolve_runtime_llm_models()
    return _ACTIVE_MODELS


def set_active_llm_model_selection(selection: Optional[str]) -> tuple[RuntimeLLMModels, bool]:
    """Set the active runtime model selection.

    Args:
        selection: Optional provider-qualified model string. ``None`` resolves
            startup provider defaults from the registry.

    Returns:
        A tuple of ``(models, changed)`` where ``changed`` indicates whether the
        active provider/model set changed.
    """
    global _ACTIVE_MODELS
    models = resolve_runtime_llm_models(selection)
    changed = _ACTIVE_MODELS != models
    _ACTIVE_MODELS = models
    return models, changed


def selectable_model_values() -> list[str]:
    """Return provider-qualified selectable main model values for `/models`."""
    registry = load_llm_model_registry()
    values: list[str] = []
    for provider_id in sorted(registry.providers):
        provider = registry.providers[provider_id]
        values.extend(
            provider_qualified_model(provider.provider_id, model.id) for model in provider.models
        )
    return values
