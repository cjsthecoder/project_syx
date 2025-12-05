"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
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
branch_labels = 'None'
depends_on = 'None'

def upgrade() -> None:
    # No-op migration retained for history; consolidates chain between 0002 and 0003
    pass

def downgrade() -> None:
    pass


