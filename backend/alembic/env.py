"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Alembic migration environment for the Syx backend.

Configures offline and online migration runs against the application's SQLModel
metadata and database engine.
"""
import os
import sys

from alembic import context

sys.path.append(os.path.dirname(os.path.abspath(__file__)) + "/..")

from app.core.database import get_engine
from app.core.db_models import SQLModel

config = context.config

# Do not call Alembic's fileConfig so logs propagate to our app's logging setup

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = get_engine()

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
