"""add persistent rulebook storage metadata

Revision ID: 20260611_0046
Revises: 20260610_0045
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa

revision = '20260611_0046'
down_revision = '20260610_0045'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('rulebooks', sa.Column('storage_path', sa.String(length=500), nullable=True))
    op.add_column('rulebooks', sa.Column('file_url', sa.String(length=500), nullable=True))
    op.execute("UPDATE rulebooks SET storage_path = 'rulebooks/' || stored_filename WHERE storage_path IS NULL")
    op.execute("UPDATE rulebooks SET file_url = '/api/rulebooks/' || id::text || '/view' WHERE file_url IS NULL")


def downgrade() -> None:
    op.drop_column('rulebooks', 'file_url')
    op.drop_column('rulebooks', 'storage_path')
