"""add host location images

Revision ID: 20260821_0080
Revises: 20260821_0079
"""
from alembic import op
import sqlalchemy as sa

revision = '20260821_0080'
down_revision = '20260821_0079'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('host_locations', sa.Column('location_image_url', sa.String(500), nullable=True))
    op.add_column('host_locations', sa.Column('location_image_filename', sa.String(255), nullable=True))
    op.add_column('host_locations', sa.Column('location_image_storage_key', sa.String(500), nullable=True))
    op.add_column('host_locations', sa.Column('location_image_updated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('host_locations', 'location_image_updated_at')
    op.drop_column('host_locations', 'location_image_storage_key')
    op.drop_column('host_locations', 'location_image_filename')
    op.drop_column('host_locations', 'location_image_url')
