"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for provider-scoped LLM model registry resolution.
"""

import json

import pytest
from app.llm_model import registry


def test_openai_registry_resolves_provider_scoped_defaults(settings_override):
    settings_override(llm_provider="openai")
    resolved = registry.resolve_runtime_llm_models()
    assert resolved.selection_value == "openai/gpt-5.5"
    assert resolved.main_model == "gpt-5.5"
    assert resolved.mini_model == "gpt-5-mini"
    assert resolved.builder_model == "gpt-5-mini"
    assert resolved.tagger_model == "gpt-5-mini"
    assert resolved.dream_model == "gpt-5.5"


def test_provider_qualified_selection_sets_main_model(settings_override):
    settings_override(llm_provider="openai")
    resolved = registry.resolve_runtime_llm_models("openai/gpt-5-mini")
    assert resolved.selection_value == "openai/gpt-5-mini"
    assert resolved.main_model == "gpt-5-mini"
    assert resolved.builder_model == "gpt-5-mini"


def test_bare_model_selection_is_migration_compatible_for_active_provider(settings_override):
    settings_override(llm_provider="openai")
    resolved = registry.resolve_runtime_llm_models("gpt-5-mini")
    assert resolved.selection_value == "openai/gpt-5-mini"


def test_selection_rejects_model_from_wrong_provider(settings_override):
    settings_override(llm_provider="openai")
    with pytest.raises(registry.LLMModelRegistryError, match="not selectable"):
        registry.resolve_runtime_llm_models("openai/claude-sonnet")


def test_anthropic_registry_resolves_provider_scoped_defaults(settings_override):
    settings_override(llm_provider="anthropic")
    resolved = registry.resolve_runtime_llm_models()
    assert resolved.selection_value == "anthropic/claude-sonnet-4-6"
    assert resolved.main_model == "claude-sonnet-4-6"
    assert resolved.mini_model == "claude-haiku-4-5-20251001"
    assert resolved.builder_model == "claude-haiku-4-5-20251001"
    assert resolved.tagger_model == "claude-haiku-4-5-20251001"
    assert resolved.dream_model == "claude-sonnet-4-6"


def test_anthropic_frontier_model_selection(settings_override):
    settings_override(llm_provider="anthropic")
    resolved = registry.resolve_runtime_llm_models("anthropic/claude-opus-4-8")
    assert resolved.selection_value == "anthropic/claude-opus-4-8"
    assert resolved.main_model == "claude-opus-4-8"
    assert resolved.builder_model == "claude-haiku-4-5-20251001"


def test_malformed_registry_file_fails_clearly(tmp_path):
    registry_path = tmp_path / "llm_models.json"
    registry_path.write_text("{bad json", encoding="utf-8")
    registry.load_llm_model_registry.cache_clear()
    with pytest.raises(registry.LLMModelRegistryError, match="malformed JSON"):
        registry.load_llm_model_registry(str(registry_path))


def test_registry_rejects_invalid_role_model(tmp_path):
    registry_path = tmp_path / "llm_models.json"
    registry_path.write_text(
        json.dumps(
            {
                "providers": {
                    "openai": {
                        "label": "OpenAI",
                        "factory_provider": "openai",
                        "default_model": "gpt-5.5",
                        "models": [{"id": "gpt-5.5"}],
                        "roles": {
                            "mini": "gpt-5-mini",
                            "builder": "gpt-5.5",
                            "tagger": "gpt-5.5",
                            "dream": "gpt-5.5",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    registry.load_llm_model_registry.cache_clear()
    with pytest.raises(registry.LLMModelRegistryError, match="non-selectable role"):
        registry.load_llm_model_registry(str(registry_path))
