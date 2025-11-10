"""v2.7 add forget flag to chat_message

Revision ID: 0005
Revises: 0004
Create Date: 2025-11-03
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('chatmessage') as batch_op:
        batch_op.add_column(sa.Column('forget', sa.Boolean(), nullable=False, server_default=sa.text('0')))


def downgrade() -> None:
    with op.batch_alter_table('chatmessage') as batch_op:
        try:
            batch_op.drop_column('forget')
        except Exception:
            pass


