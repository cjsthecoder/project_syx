"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.core.database.

Covers the directory helper, engine construction for both raw sqlite URLs and
filesystem paths, the Alembic migration runner (happy path and create_all
fallback), and the session context manager. Alembic and the module engine are
faked so no real migrations run and no real database file is touched.
"""

import os
from types import SimpleNamespace

from app.core import database
from sqlmodel import create_engine


def test_ensure_dir_creates_missing_directory(tmp_path):
    target = tmp_path / "nested" / "deeper" / "syx.db"
    database._ensure_dir(str(target))
    assert os.path.isdir(os.path.dirname(str(target)))


def test_get_engine_accepts_raw_sqlite_url(monkeypatch):
    monkeypatch.setattr(
        database, "get_settings", lambda: SimpleNamespace(db_path="sqlite:///:memory:")
    )
    engine = database.get_engine()
    assert str(engine.url).startswith("sqlite")


def test_get_engine_builds_url_from_path(monkeypatch, tmp_path):
    db_file = tmp_path / "data" / "app.db"
    monkeypatch.setattr(database, "get_settings", lambda: SimpleNamespace(db_path=str(db_file)))
    engine = database.get_engine()
    assert str(engine.url).startswith("sqlite:///")
    assert os.path.isdir(os.path.dirname(str(db_file)))  # parent dir created


def test_run_migrations_happy_path(monkeypatch):
    import alembic.command
    import alembic.config

    calls = {}

    class _FakeConfig:
        def __init__(self, ini):
            calls["ini"] = ini

        def set_main_option(self, key, value):
            calls[key] = value

    monkeypatch.setattr(alembic.config, "Config", _FakeConfig)
    monkeypatch.setattr(alembic.command, "upgrade", lambda cfg, rev: calls.setdefault("rev", rev))

    database._run_migrations()
    assert calls["rev"] == "head"
    assert "script_location" in calls


def test_run_migrations_falls_back_to_create_all(monkeypatch, caplog):
    import alembic.config

    def _boom(_ini):
        raise RuntimeError("alembic unavailable")

    monkeypatch.setattr(alembic.config, "Config", _boom)
    # Redirect create_all to a harmless in-memory engine.
    monkeypatch.setattr(database, "engine", create_engine("sqlite://"))

    database._run_migrations()
    assert any("_run_migrations failed" in r.message for r in caplog.records)


def test_init_db_invokes_migrations(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(database, "_run_migrations", lambda: called.__setitem__("n", 1))
    database.init_db()
    assert called["n"] == 1


def test_get_session_yields_open_session(monkeypatch):
    monkeypatch.setattr(database, "engine", create_engine("sqlite://"))
    with database.get_session() as session:
        assert session is not None
        # A trivial round-trip confirms the session is usable.
        from sqlalchemy import text

        assert session.exec(text("SELECT 1")).first()[0] == 1
