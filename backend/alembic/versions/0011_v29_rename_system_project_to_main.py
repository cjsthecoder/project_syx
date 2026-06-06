"""
Copyright (c) 2025-2026 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""Rename system project 'Continuum' to 'Main'

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-06
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # Only rename if a 'Main' project does not already exist, to avoid violating
    # the case-insensitive name uniqueness rule.
    existing_main = conn.execute(
        sa.text("SELECT id FROM project WHERE lower(name) = 'main'")
    ).fetchone()
    if existing_main is None:
        conn.execute(
            sa.text("UPDATE project SET name = 'Main' WHERE lower(name) = 'continuum'")
        )


def downgrade() -> None:
    conn = op.get_bind()
    existing_continuum = conn.execute(
        sa.text("SELECT id FROM project WHERE lower(name) = 'continuum'")
    ).fetchone()
    if existing_continuum is None:
        conn.execute(
            sa.text("UPDATE project SET name = 'Continuum' WHERE lower(name) = 'main'")
        )
