"""add shared plan

Revision ID: 04835d646d06
Revises: 5c1f0e7a9b3d
Create Date: 2026-10-21 15:28:11.469685

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '04835d646d06'
down_revision: Union[str, Sequence[str], None] = '5c1f0e7a9b3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('shared_plan',
    sa.Column('id', sa.String(length=16), nullable=False),
    sa.Column('city_id', sa.String(), nullable=False),
    sa.Column('lang', sa.String(length=2), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('plan', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['city_id'], ['city.id'], name=op.f('fk_shared_plan_city_id_city')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_shared_plan')),
    sa.UniqueConstraint('content_hash', name=op.f('uq_shared_plan_content_hash'))
    )
    op.create_index(op.f('ix_shared_plan_created_at'), 'shared_plan', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_shared_plan_created_at'), table_name='shared_plan')
    op.drop_table('shared_plan')
