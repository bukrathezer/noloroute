"""add sight type and city price info

Revision ID: 556f25a152f1
Revises: bc9e87faa37d
Create Date: 2026-09-29 06:16:29.259730

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '556f25a152f1'
down_revision: Union[str, Sequence[str], None] = 'bc9e87faa37d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('poi', sa.Column('google_type', sa.String(length=64), nullable=True))
    op.add_column('city', sa.Column('price_basis', sa.String(length=20), nullable=True))
    op.add_column('city', sa.Column('prices_checked_on', sa.Date(), nullable=True))
    # Existing cities; re-running the ingestion script sets the same values (and POI types).
    op.execute("UPDATE city SET price_basis = 'adult', prices_checked_on = '2026-09-29' WHERE id = 'paris'")
    op.execute("UPDATE city SET price_basis = 'tr_citizen', prices_checked_on = '2026-09-29' WHERE id = 'istanbul'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('city', 'prices_checked_on')
    op.drop_column('city', 'price_basis')
    op.drop_column('poi', 'google_type')
