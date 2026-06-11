"""store stable rulebook file keys instead of local paths

Revision ID: 20260611_0048
Revises: 20260611_0047
Create Date: 2026-06-11
"""
from alembic import op

revision = '20260611_0048'
down_revision = '20260611_0047'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE rulebooks SET storage_path = 'rulebooks/' || stored_filename WHERE storage_path IS NULL")
    op.execute("UPDATE rulebooks SET file_path = storage_path WHERE storage_path IS NOT NULL")


def downgrade() -> None:
    # Local filesystem paths cannot be reconstructed from stable storage keys.
    pass
