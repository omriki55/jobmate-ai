"""telegram_id to bigint

Revision ID: a1b2c3d4e5f6
Revises: d959250a50cb
Create Date: 2026-03-06 11:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str]] = 'd959250a50cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Alter telegram_id from INTEGER to BIGINT."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column(
            'telegram_id',
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )


def downgrade() -> None:
    """Revert telegram_id back to INTEGER."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column(
            'telegram_id',
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )
