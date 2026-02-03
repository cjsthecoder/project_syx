"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""Add tags_meta_json + semantic_handle to ChatMessage (V3.x)

Revision ID: 0009
Revises: 0008
Create Date: 2026-02-02
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("chatmessage") as batch_op:
        batch_op.add_column(sa.Column("tags_meta_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("semantic_handle", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("chatmessage") as batch_op:
        batch_op.drop_column("semantic_handle")
        batch_op.drop_column("tags_meta_json")

