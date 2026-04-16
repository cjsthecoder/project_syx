"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Database setup for Syx (SQLModel + SQLite).
"""

import os
import logging
from contextlib import contextmanager
from typing import Iterator

from sqlmodel import SQLModel, Session, create_engine

from .config import get_settings
from .db_models import Project
from sqlmodel import select

logger = logging.getLogger(__name__)


def _ensure_dir(path: str) -> None:
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)


def get_engine():
    settings = get_settings()
    db_path = settings.db_path
    if db_path.startswith("sqlite"):
        url = db_path
    else:
        _ensure_dir(db_path)
        url = f"sqlite:///{db_path}"
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, echo=False, connect_args=connect_args)


engine = get_engine()


def _run_migrations() -> None:
    """Programmatically run Alembic upgrade head."""
    try:
        from alembic.config import Config
        from alembic import command
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/app
        alembic_ini = os.path.join(base_dir, "..", "alembic.ini")
        cfg = Config(alembic_ini)
        # Resolve script_location absolutely so migrations run correctly regardless of current working directory.
        cfg.set_main_option("script_location", os.path.join(base_dir, "..", "alembic"))
        command.upgrade(cfg, "head")
    except Exception as exc:
        logger.warning("database._run_migrations failed; falling back to create_all detail=%s", exc)
        # Fallback to create_all in dev if migrations cannot run
        from . import db_models  # noqa: F401 ensure models are imported
        SQLModel.metadata.create_all(engine)


def init_db() -> None:
    """Ensure DB schema up-to-date and seed legacy default if needed."""
    # Run migrations first to match current models
    _run_migrations()
    # Cleanup: remove legacy 'default' project if present
    try:
        with Session(engine) as session:
            legacy = session.exec(select(Project).where(Project.id == "default")).first()
            if legacy and not legacy.system:
                session.delete(legacy)
                session.commit()
    except Exception as exc:
        logger.warning("database.init_db failed removing legacy default project detail=%s", exc)


@contextmanager
def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


