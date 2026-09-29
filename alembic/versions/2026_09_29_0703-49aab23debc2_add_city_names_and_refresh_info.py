"""add city names and refresh info

Revision ID: 49aab23debc2
Revises: 556f25a152f1
Create Date: 2026-09-29 07:03:57.517602

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '49aab23debc2'
down_revision: Union[str, Sequence[str], None] = '556f25a152f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('city', sa.Column('name_tr', sa.String(length=100), nullable=True))
    op.add_column('city', sa.Column('country_code', sa.String(length=2), nullable=True))
    op.add_column('city', sa.Column('refreshed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('city', sa.Column('last_ingest_requests', sa.Integer(), nullable=True))
    op.execute("UPDATE city SET name_tr = 'Paris', country_code = 'FR' WHERE id = 'paris'")
    op.execute("UPDATE city SET name_tr = 'İstanbul', country_code = 'TR' WHERE id = 'istanbul'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('city', 'last_ingest_requests')
    op.drop_column('city', 'refreshed_at')
    op.drop_column('city', 'country_code')
    op.drop_column('city', 'name_tr')
