"""add host location primary metadata

Revision ID: 20260603_0034
Revises: 20260602_0033
Create Date: 2026-06-03 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '20260603_0034'
down_revision = '20260602_0033'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('host_locations', sa.Column('is_primary', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('host_locations', 'is_primary', server_default=None)


def downgrade() -> None:
    op.drop_column('host_locations', 'is_primary')
