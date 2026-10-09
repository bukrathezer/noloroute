"""add poi wikipedia descriptions

Revision ID: 88d681d002ad
Revises: 49aab23debc2
Create Date: 2026-10-09 18:33:37.312266

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '88d681d002ad'
down_revision: Union[str, Sequence[str], None] = '49aab23debc2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('poi', sa.Column('wikidata_id', sa.String(length=16), nullable=True))
    op.add_column('poi', sa.Column('description_tr', sa.String(length=300), nullable=True))
    op.add_column('poi', sa.Column('description_en', sa.String(length=300), nullable=True))
    op.add_column('poi', sa.Column('wiki_checked_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('poi', 'wiki_checked_at')
    op.drop_column('poi', 'description_en')
    op.drop_column('poi', 'description_tr')
    op.drop_column('poi', 'wikidata_id')
