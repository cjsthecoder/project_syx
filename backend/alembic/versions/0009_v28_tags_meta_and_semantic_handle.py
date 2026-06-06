"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""Add tags_meta_json + semantic_handle to ChatMessage

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

