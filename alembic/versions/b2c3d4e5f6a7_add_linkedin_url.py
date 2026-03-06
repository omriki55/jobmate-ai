"""add linkedin_url to user_preferences

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-06 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str]] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add linkedin_url column to user_preferences."""
    with op.batch_alter_table('user_preferences', schema=None) as batch_op:
        batch_op.add_column(sa.Column('linkedin_url', sa.String(), nullable=True))


def downgrade() -> None:
    """Remove linkedin_url column from user_preferences."""
    with op.batch_alter_table('user_preferences', schema=None) as batch_op:
        batch_op.drop_column('linkedin_url')
