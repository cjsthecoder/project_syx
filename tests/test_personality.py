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

import json
import os

import pytest
from app.core import personality
from app.core.personality import (
    _normalize_personality,
    _project_dir,
    _project_personality_path,
    _project_prompt_path,
    backfill_all_projects,
    ensure_directories,
    load_default_prompt_and_personality,
    load_project_personality,
    load_project_system_prompt,
    save_project_personality,
    save_project_system_prompt,
    seed_project_defaults,
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


# --- ensure_directories ----------------------------------------------------


def test_ensure_directories_logs_on_failure(monkeypatch, caplog):
    monkeypatch.setattr(
        personality.os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError("denied"))
    )
    ensure_directories("/some/path")  # must not raise
    assert any("ensure_directories failed" in r.message for r in caplog.records)


# --- load_default_prompt_and_personality ----------------------------------


def test_load_default_prompt_missing_file_returns_empty(
    temp_memory_root, settings_override, tmp_path
):
    settings_override(
        default_system_prompt_path=str(tmp_path / "absent_prompt.txt"),
        default_personality_prompt_path=str(tmp_path / "absent_pers.json"),
    )
    prompt, pers = load_default_prompt_and_personality()
    assert prompt == "" and pers == {}


def test_load_default_personality_non_dict_returns_empty(
    temp_memory_root, settings_override, tmp_path
):
    bad = tmp_path / "pers.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")  # valid JSON but not an object
    settings_override(
        default_system_prompt_path=str(tmp_path / "absent_prompt.txt"),
        default_personality_prompt_path=str(bad),
    )
    _, pers = load_default_prompt_and_personality()
    assert pers == {}


# --- seed_project_defaults -------------------------------------------------


def test_seed_logs_when_prompt_write_fails(temp_memory_root, caplog):
    pid = "seed-prompt-fail"
    os.makedirs(_project_dir(pid), exist_ok=True)
    # Make the prompt path a directory so open(..., "w") raises IsADirectoryError.
    os.mkdir(_project_prompt_path(pid))
    seed_project_defaults(pid)
    assert any("Failed writing project prompt" in r.message for r in caplog.records)


def test_seed_logs_when_personality_write_fails(temp_memory_root, caplog):
    pid = "seed-pers-fail"
    os.makedirs(_project_dir(pid), exist_ok=True)
    os.mkdir(_project_personality_path(pid))  # directory blocks the JSON write
    seed_project_defaults(pid)
    assert any("Failed writing project personality" in r.message for r in caplog.records)


# --- backfill_all_projects -------------------------------------------------


def test_backfill_seeds_existing_projects(db, temp_memory_root):
    from app.core.db_models import Project
    from sqlmodel import Session

    with Session(db) as session:
        session.add(Project(id="proj-bf", name="BF", description="", system=False))
        session.commit()
    backfill_all_projects()
    assert os.path.isfile(_project_prompt_path("proj-bf"))
    assert os.path.isfile(_project_personality_path("proj-bf"))


def test_backfill_logs_on_session_failure(monkeypatch, caplog):
    monkeypatch.setattr(
        personality, "get_session", lambda: (_ for _ in ()).throw(RuntimeError("db down"))
    )
    backfill_all_projects()  # must not raise
    assert any("Backfill failed" in r.message for r in caplog.records)


# --- load_project_system_prompt -------------------------------------------


def test_load_project_system_prompt_uses_cache(temp_memory_root):
    save_project_system_prompt("cache-p", "cached prompt")
    assert load_project_system_prompt("cache-p") == "cached prompt"
    # Second call returns the cached value without re-reading.
    assert load_project_system_prompt("cache-p") == "cached prompt"


def test_empty_project_prompt_file_falls_back_to_default(
    temp_memory_root, settings_override, tmp_path
):
    default_file = tmp_path / "default_prompt.txt"
    default_file.write_text("DEFAULT PROMPT", encoding="utf-8")
    settings_override(default_system_prompt_path=str(default_file))
    pid = "empty-prompt"
    os.makedirs(_project_dir(pid), exist_ok=True)
    # Existing-but-whitespace project file triggers the default fallback.
    with open(_project_prompt_path(pid), "w", encoding="utf-8") as handle:
        handle.write("   \n")
    assert load_project_system_prompt(pid) == "DEFAULT PROMPT"


def test_missing_project_prompt_with_empty_default(temp_memory_root, settings_override, tmp_path):
    settings_override(default_system_prompt_path=str(tmp_path / "absent.txt"))
    assert load_project_system_prompt("missing-prompt") == ""


# --- load_project_personality ---------------------------------------------


def test_load_project_personality_uses_cache(temp_memory_root):
    save_project_personality("cache-pers", {"tone": "playful"})
    first = load_project_personality("cache-pers")
    assert load_project_personality("cache-pers") is first  # cached object reused


def test_load_project_personality_invalid_json_falls_back(temp_memory_root):
    pid = "bad-pers"
    os.makedirs(_project_dir(pid), exist_ok=True)
    with open(_project_personality_path(pid), "w", encoding="utf-8") as handle:
        json.dump([1, 2, 3], handle)  # not a dict
    norm = load_project_personality(pid)
    assert set(norm.keys()) == {"tone", "verbosity", "format", "creativity", "domain_focus"}


def test_load_project_personality_missing_file_falls_back(temp_memory_root):
    norm = load_project_personality("no-pers-file")
    assert set(norm.keys()) == {"tone", "verbosity", "format", "creativity", "domain_focus"}
