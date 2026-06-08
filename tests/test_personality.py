"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.core.personality.

Covers personality normalization (pure), size validation, and the per-project
save/load round-trip with cache invalidation, using an isolated memory root.
"""

import pytest
from app.core.personality import (
    _normalize_personality,
    load_default_prompt_and_personality,
    load_project_personality,
    load_project_system_prompt,
    save_project_personality,
    save_project_system_prompt,
)


def test_normalize_defaults_for_empty():
    norm = _normalize_personality({})
    assert norm == {
        "tone": "analytical",
        "verbosity": "concise",
        "format": "markdown",
        "creativity": 0.4,
        "domain_focus": [],
    }


def test_normalize_lowercases_and_strips_strings():
    norm = _normalize_personality({"tone": "  Friendly  ", "format": "TEXT"})
    assert norm["tone"] == "friendly"
    assert norm["format"] == "text"


def test_normalize_clamps_creativity():
    assert _normalize_personality({"creativity": 5})["creativity"] == 1.0
    assert _normalize_personality({"creativity": -1})["creativity"] == 0.0
    assert _normalize_personality({"creativity": "0.7"})["creativity"] == 0.7


def test_normalize_invalid_creativity_falls_back():
    assert _normalize_personality({"creativity": "abc"})["creativity"] == 0.4


def test_normalize_domain_focus_must_be_list():
    assert _normalize_personality({"domain_focus": "nope"})["domain_focus"] == []
    assert _normalize_personality({"domain_focus": ["a", "b"]})["domain_focus"] == [
        "a",
        "b",
    ]


def test_personality_save_load_round_trip(temp_memory_root):
    saved = save_project_personality("p1", {"tone": "Playful", "creativity": 0.9})
    assert saved["tone"] == "playful"
    loaded = load_project_personality("p1")
    assert loaded == saved


def test_personality_save_invalidates_cache(temp_memory_root):
    save_project_personality("p1", {"tone": "playful"})
    assert load_project_personality("p1")["tone"] == "playful"
    # Saving again must invalidate the cache so the next read sees the new value.
    save_project_personality("p1", {"tone": "formal"})
    assert load_project_personality("p1")["tone"] == "formal"


def test_system_prompt_save_load_round_trip(temp_memory_root):
    save_project_system_prompt("p1", "You are a helpful assistant.")
    assert load_project_system_prompt("p1") == "You are a helpful assistant."


def test_empty_project_prompt_falls_back_to_default(temp_memory_root):
    # No file written for this project -> load falls back to the default file.
    default_prompt, _ = load_default_prompt_and_personality()
    assert load_project_system_prompt("brand-new-project") == default_prompt


def test_system_prompt_size_limit_raises(temp_memory_root, settings_override):
    settings_override(system_prompt_max_bytes=10)
    with pytest.raises(ValueError):
        save_project_system_prompt("p1", "x" * 100)


def test_personality_size_limit_raises(temp_memory_root, settings_override):
    settings_override(personality_max_bytes=5)
    with pytest.raises(ValueError):
        save_project_personality("p1", {"domain_focus": ["a" * 100]})
