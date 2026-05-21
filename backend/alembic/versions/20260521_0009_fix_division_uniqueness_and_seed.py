"""fix division uniqueness and league seed data

Revision ID: 20260521_0009
Revises: 20260521_0008
Create Date: 2026-05-21
"""

from alembic import op
import sqlalchemy as sa


revision = '20260521_0009'
down_revision = '20260521_0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('divisions_name_key', 'divisions', type_='unique')
    op.create_unique_constraint('uq_division_group_name', 'divisions', ['division_group', 'name'])

    op.execute("""
    UPDATE divisions
    SET required_field_layout_type='THIRTY_YARD_WIDTH'
    WHERE name='4th/5th' AND division_group IN ('COED', 'GIRLS')
    """)


def downgrade() -> None:
    op.drop_constraint('uq_division_group_name', 'divisions', type_='unique')
    op.create_unique_constraint('divisions_name_key', 'divisions', ['name'])
