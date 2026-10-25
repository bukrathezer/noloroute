"""add email verification

Revision ID: 6afc054c9528
Revises: 04835d646d06
Create Date: 2026-10-25 15:20:51.267218

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6afc054c9528'
down_revision: Union[str, Sequence[str], None] = '04835d646d06'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('email_code',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('email', sa.String(), nullable=False),
    sa.Column('purpose', sa.String(length=10), nullable=False),
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('pending_password_hash', sa.String(), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_code')),
    sa.UniqueConstraint('email', 'purpose', name=op.f('uq_email_code_email'))
    )
    op.create_index(op.f('ix_email_code_email'), 'email_code', ['email'], unique=False)
    op.add_column('user', sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user', 'email_verified_at')
    op.drop_index(op.f('ix_email_code_email'), table_name='email_code')
    op.drop_table('email_code')
