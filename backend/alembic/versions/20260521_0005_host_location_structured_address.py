"""add structured address columns to host locations

Revision ID: 20260521_0005
Revises: 20260520_0004
Create Date: 2026-05-21
"""

from alembic import op
import sqlalchemy as sa


revision = '20260521_0005'
down_revision = '20260520_0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('host_locations', sa.Column('address_line1', sa.String(length=255), nullable=True))
    op.add_column('host_locations', sa.Column('address_line2', sa.String(length=255), nullable=True))
    op.add_column('host_locations', sa.Column('city', sa.String(length=120), nullable=True))
    op.add_column('host_locations', sa.Column('state', sa.String(length=80), nullable=True))
    op.add_column('host_locations', sa.Column('zip_code', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('host_locations', 'zip_code')
    op.drop_column('host_locations', 'state')
    op.drop_column('host_locations', 'city')
    op.drop_column('host_locations', 'address_line2')
    op.drop_column('host_locations', 'address_line1')
