"""add poi turkish names and translated descriptions

Revision ID: 5c1f0e7a9b3d
Revises: 2e8a5187f963
Create Date: 2026-10-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c1f0e7a9b3d'
down_revision: Union[str, Sequence[str], None] = '2e8a5187f963'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('poi', sa.Column('name_tr', sa.String(), nullable=True))
    op.add_column('poi', sa.Column('description_translated', sa.String(length=2), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('poi', 'description_translated')
    op.drop_column('poi', 'name_tr')
