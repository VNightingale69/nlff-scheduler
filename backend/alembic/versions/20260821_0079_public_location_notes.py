"""add public hosting location notes

Revision ID: 20260821_0079
Revises: 20260820_0078
"""
from alembic import op
import sqlalchemy as sa

revision = '20260821_0079'
down_revision = '20260820_0078'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('host_locations', sa.Column('public_location_notes', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('host_locations', 'public_location_notes')
