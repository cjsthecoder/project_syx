"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Database setup for Syx (SQLModel + SQLite).
"""

import logging
import os
from contextlib import contextmanager
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

logger = logging.getLogger(__name__)


def _ensure_dir(path: str) -> None:
    """Create the parent directory of a file path if it does not exist.

    Args:
        path: Filesystem path whose containing directory should be ensured.
    """
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)


def get_engine():
    """Create the SQLModel engine for the configured SQLite database.

    Accepts either a raw ``sqlite`` URL or a filesystem path (whose parent
    directory is created if needed).

    Returns:
        A SQLAlchemy engine bound to the configured database.
    """
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
        from alembic import command
        from alembic.config import Config

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
    """Ensure the DB schema is up-to-date by running migrations to head."""
    _run_migrations()


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a database session scoped to the surrounding ``with`` block.

    Yields:
        An open SQLModel session that is closed on context exit.
    """
    with Session(engine) as session:
        yield session
