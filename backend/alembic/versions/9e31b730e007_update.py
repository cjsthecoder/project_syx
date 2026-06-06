"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""update

Revision ID: 9e31b730e007
Revises: 0002
Create Date: 2025-10-07 17:39:20.225612

"""
from alembic import op
import sqlalchemy as sa

revision = '0002a'
down_revision = '0002'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # No-op migration retained for history; consolidates chain between 0002 and 0003
    pass

def downgrade() -> None:
    pass


