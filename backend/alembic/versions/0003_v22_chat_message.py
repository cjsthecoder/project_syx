"""v2.2 add chatmessage table for persistent chat history

Revision ID: 0003
Revises: 0002
Create Date: 2025-10-09
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'chatmessage',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('project_id', sa.String(), sa.ForeignKey('project.id'), nullable=False, index=True),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('ix_chatmessage_project_created', 'chatmessage', ['project_id', 'created_at'])


def downgrade() -> None:
    try:
        op.drop_index('ix_chatmessage_project_created', table_name='chatmessage')
    except Exception:
        pass
    op.drop_table('chatmessage')


