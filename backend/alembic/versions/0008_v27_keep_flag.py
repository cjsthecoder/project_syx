"""



Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.

"""

"""Add keep flag to ChatMessage (V2.7.7)

Revision ID: 0008
Revises: 0007
Create Date: 2025-11-06
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('chatmessage') as batch_op:
        batch_op.add_column(sa.Column('keep', sa.Boolean(), nullable=False, server_default=sa.false()))
    # Drop server_default to avoid locking it in for future inserts
    with op.batch_alter_table('chatmessage') as batch_op:
        batch_op.alter_column('keep', server_default=None)


def downgrade():
    with op.batch_alter_table('chatmessage') as batch_op:
        batch_op.drop_column('keep')


