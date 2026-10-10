"""add poi wikidata sitelinks

Revision ID: 2e8a5187f963
Revises: 88d681d002ad
Create Date: 2026-10-10 16:11:41.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2e8a5187f963'
down_revision: Union[str, Sequence[str], None] = '88d681d002ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('poi', sa.Column('wikidata_sitelinks', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('poi', 'wikidata_sitelinks')
