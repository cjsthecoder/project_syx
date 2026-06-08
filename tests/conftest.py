"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Shared pytest fixtures for the Syx backend test suite.

Provides filesystem/settings isolation so tests do not read or mutate the real
per-project memory tree or the process-wide settings singleton.
"""

import os

# Route test logs to runtime/logs/tests/ with a 'test_' filename prefix. These
# must be set before app.core.config is imported, because the settings singleton
# (and setup_logging, which runs at app import time) read them eagerly.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("LOGS_DIR", os.path.join(_REPO_ROOT, "runtime", "logs", "tests"))
os.environ.setdefault("LOG_FILE_PREFIX", "test_")

import pytest

from app.core.config import get_settings


@pytest.fixture
def settings():
    """Return the process-wide settings singleton.

    Mutations should be made through monkeypatch (see ``settings_override``) so
    they are automatically reverted after each test.
    """
    return get_settings()


@pytest.fixture
def settings_override(monkeypatch):
    """Return a callable that overrides settings fields for the test's duration.

    Usage::

        def test_x(settings_override):
            settings_override(memory_root="/tmp/x", builder_cache=False)

    Each override is reverted automatically by monkeypatch teardown.
    """
    s = get_settings()

    def _override(**fields):
        for name, value in fields.items():
            if not hasattr(s, name):
                raise AttributeError(f"unknown settings field: {name}")
            monkeypatch.setattr(s, name, value)
        return s

    return _override


@pytest.fixture
def temp_memory_root(tmp_path, settings_override):
    """Point ``settings.memory_root`` at a fresh temp directory.

    Also clears the personality module's in-process caches before and after the
    test so cached prompt/personality reads from other tests cannot leak in.
    """
    from app.core import personality

    personality._PROMPT_CACHE.clear()
    personality._PERSONALITY_CACHE.clear()
    root = tmp_path / "memory"
    root.mkdir(parents=True, exist_ok=True)
    settings_override(memory_root=str(root))
    try:
        yield root
    finally:
        personality._PROMPT_CACHE.clear()
        personality._PERSONALITY_CACHE.clear()


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Swap the process-wide SQLModel engine for a fresh temp-file SQLite DB.

    ``get_session`` resolves ``database.engine`` at call time, so patching the
    module attribute redirects every DB consumer at once. Tables are created
    from the already-registered SQLModel metadata.
    """
    from sqlmodel import SQLModel, create_engine

    from app.core import database
    from app.core import db_models  # noqa: F401 — ensure tables are registered

    db_file = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)
    return engine


@pytest.fixture
def fresh_memory_manager(db):
    """Reset the global MemoryManager singleton so it binds to the temp DB.

    Depends on ``db`` so the manager loads history from the isolated engine.
    Construct the manager after applying any ``settings_override`` for limits.
    """
    from app.core import memory

    memory._memory_manager = None
    try:
        yield memory
    finally:
        memory._memory_manager = None


@pytest.fixture
def reset_projects_state():
    """Reset the projects router's in-memory current-project pointer."""
    from app.api import projects

    projects._current_project = None
    try:
        yield
    finally:
        projects._current_project = None
