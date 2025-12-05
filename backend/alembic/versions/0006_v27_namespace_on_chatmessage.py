"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""v2.7 add namespace to chat_message

Revision ID: 0006
Revises: 0005
Create Date: 2025-11-04
"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('chatmessage') as batch_op:
        batch_op.add_column(sa.Column('namespace', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('chatmessage') as batch_op:
        try:
            batch_op.drop_column('namespace')
        except Exception:
            pass


