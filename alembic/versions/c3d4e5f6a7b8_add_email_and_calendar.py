"""add email_address and calendar_url to user_preferences

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-06 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str]] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add email_address and calendar_url columns to user_preferences."""
    with op.batch_alter_table('user_preferences', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email_address', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('calendar_url', sa.String(), nullable=True))


def downgrade() -> None:
    """Remove email_address and calendar_url columns from user_preferences."""
    with op.batch_alter_table('user_preferences', schema=None) as batch_op:
        batch_op.drop_column('calendar_url')
        batch_op.drop_column('email_address')
