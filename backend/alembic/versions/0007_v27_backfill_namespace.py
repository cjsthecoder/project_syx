"""



Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.

"""

"""v2.7 backfill namespace to 'other' for existing chat messages

Revision ID: 0007
Revises: 0006
Create Date: 2025-11-05
"""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    try:
        conn.execute(sa.text("UPDATE chatmessage SET namespace = 'other' WHERE namespace IS NULL"))
    except Exception:
        # Best-effort
        pass


def downgrade() -> None:
    # No-op for backfill
    pass


