"""grade based divisions

Revision ID: 20260520_0002
Revises: 20260518_0001
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa


revision = '20260520_0002'
down_revision = '20260518_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM divisions")
    op.execute("""
        INSERT INTO divisions (id, name, required_field_layout_type, is_active)
        VALUES
          (gen_random_uuid(), 'Kindergarten', 'THIRTY_YARD_WIDTH', true),
          (gen_random_uuid(), '1st Grade', 'THIRTY_YARD_WIDTH', true),
          (gen_random_uuid(), '2nd Grade', 'THIRTY_YARD_WIDTH', true),
          (gen_random_uuid(), '3rd Grade', 'THIRTY_YARD_WIDTH', true),
          (gen_random_uuid(), '4th Grade', 'FIFTY_THREE_YARD_WIDTH', true),
          (gen_random_uuid(), '5th Grade', 'FIFTY_THREE_YARD_WIDTH', true),
          (gen_random_uuid(), '6th Grade', 'FIFTY_THREE_YARD_WIDTH', true),
          (gen_random_uuid(), '7th Grade', 'FIFTY_THREE_YARD_WIDTH', true),
          (gen_random_uuid(), '8th Grade', 'FIFTY_THREE_YARD_WIDTH', true)
    """)
    op.drop_column('divisions', 'min_age')
    op.drop_column('divisions', 'max_age')


def downgrade() -> None:
    op.add_column('divisions', sa.Column('min_age', sa.Integer(), nullable=True))
    op.add_column('divisions', sa.Column('max_age', sa.Integer(), nullable=True))
