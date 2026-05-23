"""make games.field_id nullable for generated-slot scheduling

Revision ID: 20260523_0012
Revises: 20260522_0011
Create Date: 2026-05-23
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260523_0012'
down_revision = '20260522_0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('games', 'field_id', existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    op.alter_column('games', 'field_id', existing_type=sa.UUID(), nullable=False)
