"""store canonical week publication payloads

Revision ID: 20260820_0075
Revises: 20260820_0074
"""
from alembic import op
import sqlalchemy as sa

revision = '20260820_0075'
down_revision = '20260820_0074'
branch_labels = None
depends_on = None


def upgrade():
    # Do not fabricate a historical snapshot from current rows. Legacy hashes
    # remain explicitly recognizable by publication_hash_version=1.
    op.add_column('weeks', sa.Column('last_published_schedule_payload', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('weeks', 'last_published_schedule_payload')
