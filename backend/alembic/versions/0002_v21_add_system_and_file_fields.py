"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""v2.1 add system flag and file metadata; seed Continuum

Revision ID: 0002
Revises: 0001
Create Date: 2025-10-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column
from sqlalchemy import String, Boolean, Integer, DateTime
import uuid
from datetime import datetime, timezone

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Project.system
    with op.batch_alter_table('project') as batch_op:
        batch_op.add_column(sa.Column('system', sa.Boolean(), nullable=False, server_default=sa.text('0')))
        # Drop legacy include_in_all if exists
        try:
            batch_op.drop_column('include_in_all')
        except Exception:
            pass
    # File metadata
    with op.batch_alter_table('file') as batch_op:
        batch_op.add_column(sa.Column('embedding_status', sa.String(), nullable=False, server_default='indexed'))
        batch_op.add_column(sa.Column('page_count', sa.Integer(), nullable=False, server_default='1'))
        batch_op.add_column(sa.Column('token_count', sa.Integer(), nullable=False, server_default='0'))

    # Seed Continuum if not present
    conn = op.get_bind()
    res = conn.execute(sa.text("SELECT id FROM project WHERE lower(name) = 'continuum'"))
    row = res.fetchone()
    if not row:
        conn.execute(
            sa.text(
                "INSERT INTO project (id, name, description, created_at, updated_at, system) VALUES (:id, :name, :desc, :ca, :ua, :sys)"
            ),
            {
                'id': str(uuid.uuid4()),
                'name': 'Continuum',
                'desc': 'The continuous memory stream where all thoughts, ideas, and context flow beyond individual projects.',
                'ca': datetime.now(timezone.utc),
                'ua': datetime.now(timezone.utc),
                'sys': True,
            }
        )


def downgrade() -> None:
    with op.batch_alter_table('file') as batch_op:
        try:
            batch_op.drop_column('token_count')
            batch_op.drop_column('page_count')
            batch_op.drop_column('embedding_status')
        except Exception:
            pass
    with op.batch_alter_table('project') as batch_op:
        try:
            batch_op.drop_column('system')
        except Exception:
            pass
