"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""init

Consolidated baseline schema for the Syx backend. This single migration
creates the full current schema in one step. ``alembic upgrade head`` builds
everything from here.

Revision ID: 0001
Revises:
Create Date: 2026-06-08
"""
import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("system", sa.Boolean(), nullable=False),
        sa.Column("daily_rag_enabled", sa.Boolean(), nullable=False),
        sa.Column("last_semantic_handle", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_project_id"), "project", ["id"], unique=False)

    op.create_table(
        "chatmessage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("role", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("content", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("forget", sa.Boolean(), nullable=False),
        sa.Column("namespace", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("keep", sa.Boolean(), nullable=False),
        sa.Column("tags_meta_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("semantic_handle", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chatmessage_created_at"), "chatmessage", ["created_at"], unique=False)
    op.create_index(op.f("ix_chatmessage_project_id"), "chatmessage", ["project_id"], unique=False)

    op.create_table(
        "file",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("filename", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_type", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("embedding_status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_file_project_id"), "file", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_file_project_id"), table_name="file")
    op.drop_table("file")
    op.drop_index(op.f("ix_chatmessage_project_id"), table_name="chatmessage")
    op.drop_index(op.f("ix_chatmessage_created_at"), table_name="chatmessage")
    op.drop_table("chatmessage")
    op.drop_index(op.f("ix_project_id"), table_name="project")
    op.drop_table("project")
