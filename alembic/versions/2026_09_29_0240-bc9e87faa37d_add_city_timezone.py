"""add city timezone

Revision ID: bc9e87faa37d
Revises: 7f7326cabac4
Create Date: 2026-09-29 02:40:57.033360

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bc9e87faa37d'
down_revision: Union[str, Sequence[str], None] = '7f7326cabac4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('city', sa.Column('timezone', sa.String(length=64), server_default='UTC', nullable=False))
    # Backfill the cities that already exist; the ingestion script sets it for new ones.
    op.execute("UPDATE city SET timezone = 'Europe/Paris' WHERE id = 'paris'")
    op.execute("UPDATE city SET timezone = 'Europe/Istanbul' WHERE id = 'istanbul'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('city', 'timezone')
