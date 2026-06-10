"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.core.config.

Covers field validators, derived-config helpers, and model/key resolution.
"""

import pytest
from app.core.config import (
    Settings,
    compute_per_source_k,
    get_active_embedding_model,
    get_model_config,
    get_response_pruning_stage_config,
    validate_openai_key,
)
from pydantic import ValidationError


def test_tagger_percent_coerces_float_string_to_int():
    s = Settings(tagger_current_response_middle_cut_percent="62.5")
    assert s.tagger_current_response_middle_cut_percent == 62


def test_tagger_percent_accepts_plain_int():
    s = Settings(tagger_previous_response_middle_cut_percent=80)
    assert s.tagger_previous_response_middle_cut_percent == 80


def test_whitespace_mode_accepts_valid():
    for mode in ("off", "compact_prose", "preserve_code"):
        assert (
            Settings(response_pruning_whitespace_mode=mode).response_pruning_whitespace_mode == mode
        )


def test_whitespace_mode_rejects_invalid():
    with pytest.raises(ValidationError):
        Settings(response_pruning_whitespace_mode="bogus")


def test_compute_per_source_k_uses_ceil():
    assert compute_per_source_k(6, 2.0) == 12
    assert compute_per_source_k(6, 1.5) == 9
    assert compute_per_source_k(5, 1.1) == 6  # ceil(5.5)


def test_compute_per_source_k_zero_means_skip():
    assert compute_per_source_k(0, 2.0) == 0
    assert compute_per_source_k(6, 0.0) == 0


def test_compute_per_source_k_invalid_multiplier_falls_back_to_base():
    assert compute_per_source_k(6, float("nan")) == 6


def test_compute_per_source_k_invalid_multiplier_and_base_returns_zero():
    # Outer ceil() fails on a non-numeric multiplier, then the inner
    # int(base_top_k) also fails -> final fallback returns 0.
    assert compute_per_source_k("not-an-int", "not-a-float") == 0


def test_compute_per_source_k_invalid_multiplier_uses_base_fallback():
    assert compute_per_source_k(5, "not-a-float") == 5


def test_tagger_percent_coerces_bool_to_int():
    assert (
        Settings(tagger_min_response_length_for_chop=True).tagger_min_response_length_for_chop == 1
    )


def test_tagger_percent_coerces_float_to_int():
    assert (
        Settings(
            tagger_current_response_middle_cut_percent=62.5
        ).tagger_current_response_middle_cut_percent
        == 62
    )


def test_tagger_percent_blank_string_falls_through_to_validation_error():
    with pytest.raises(ValidationError):
        Settings(tagger_min_response_length_for_chop="   ")


def test_tagger_percent_non_numeric_string_falls_through_to_validation_error():
    with pytest.raises(ValidationError):
        Settings(tagger_min_response_length_for_chop="abc")


def test_tagger_percent_non_numeric_type_falls_through_to_validation_error():
    with pytest.raises(ValidationError):
        Settings(tagger_min_response_length_for_chop=[1, 2])


def test_get_active_embedding_model_openai(settings_override):
    settings_override(embedding_provider="openai", embedding_model="text-embedding-3-large")
    assert get_active_embedding_model() == "text-embedding-3-large"


def test_get_active_embedding_model_sentence_transformers(settings_override):
    settings_override(
        embedding_provider="sentence_transformers",
        sentence_transformers_model_id="BAAI/bge-m3",
    )
    assert get_active_embedding_model() == "BAAI/bge-m3"


def test_validate_openai_key(settings_override):
    settings_override(openai_api_key="")
    assert validate_openai_key() is False
    settings_override(openai_api_key="your-openai-api-key-here")
    assert validate_openai_key() is False
    settings_override(openai_api_key="sk-real-looking-key")
    assert validate_openai_key() is True


def test_get_model_config_shape(settings_override):
    settings_override(model_name="gpt-x", model_temperature=0.5, model_max_tokens=1234)
    cfg = get_model_config()
    assert cfg == {"model_name": "gpt-x", "temperature": 0.5, "max_tokens": 1234}


def test_get_response_pruning_stage_config_keys(settings_override):
    settings_override(response_pruning_enabled=False)
    cfg = get_response_pruning_stage_config()
    assert set(cfg.keys()) == {
        "enabled",
        "front_enabled",
        "end_enabled",
        "whitespace_enabled",
        "similarity_enabled",
    }
    assert cfg["enabled"] is False
    assert all(isinstance(v, bool) for v in cfg.values())
