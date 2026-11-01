"""add google sign in

Revision ID: 8893db6fb8db
Revises: 6afc054c9528
Create Date: 2026-11-01 22:36:33.345895

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8893db6fb8db'
down_revision: Union[str, Sequence[str], None] = '6afc054c9528'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('user', sa.Column('google_sub', sa.String(), nullable=True))
    op.add_column('user', sa.Column('tokens_valid_after', sa.DateTime(timezone=True), nullable=True))
    op.alter_column('user', 'hashed_password',
               existing_type=sa.VARCHAR(),
               nullable=True)
    op.create_unique_constraint(op.f('uq_user_google_sub'), 'user', ['google_sub'])


def downgrade() -> None:
    """Downgrade schema."""
    # Fails while accounts without a password (Google only) exist: remove or reset them first.
    op.drop_constraint(op.f('uq_user_google_sub'), 'user', type_='unique')
    op.alter_column('user', 'hashed_password',
               existing_type=sa.VARCHAR(),
               nullable=False)
    op.drop_column('user', 'tokens_valid_after')
    op.drop_column('user', 'google_sub')
