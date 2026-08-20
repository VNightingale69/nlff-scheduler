"""version week publication fingerprints

Revision ID: 20260820_0074
Revises: 20260818_0073
"""
from alembic import op
import sqlalchemy as sa

revision = '20260820_0074'
down_revision = '20260818_0073'
branch_labels = None
depends_on = None


def upgrade():
    # Existing hashes used the legacy serializer.  They remain comparable and
    # are upgraded naturally the next time an administrator republishes.
    op.add_column('weeks', sa.Column(
        'publication_hash_version', sa.Integer(), nullable=False, server_default='1'
    ))


def downgrade():
    op.drop_column('weeks', 'publication_hash_version')
