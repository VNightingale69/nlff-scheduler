"""grass field capacity forecast

Revision ID: 20260529_0021
Revises: 20260529_0020
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa


revision = '20260529_0021'
down_revision = '20260529_0020'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('host_locations', sa.Column('field_area_name', sa.String(length=120), nullable=True))
    op.add_column('host_locations', sa.Column('setup_constraints', sa.Text(), nullable=True))
    op.add_column('host_locations', sa.Column('max_small_fields', sa.Integer(), server_default='0', nullable=False))
    op.add_column('host_locations', sa.Column('max_medium_fields', sa.Integer(), server_default='0', nullable=False))
    op.add_column('host_locations', sa.Column('max_large_fields', sa.Integer(), server_default='0', nullable=False))
    op.add_column('host_locations', sa.Column('max_total_fields', sa.Integer(), server_default='0', nullable=False))
    op.add_column('host_locations', sa.Column('can_support_small', sa.Boolean(), server_default=sa.text('true'), nullable=False))
    op.add_column('host_locations', sa.Column('can_support_medium', sa.Boolean(), server_default=sa.text('true'), nullable=False))
    op.add_column('host_locations', sa.Column('can_support_large', sa.Boolean(), server_default=sa.text('true'), nullable=False))


def downgrade() -> None:
    op.drop_column('host_locations', 'can_support_large')
    op.drop_column('host_locations', 'can_support_medium')
    op.drop_column('host_locations', 'can_support_small')
    op.drop_column('host_locations', 'max_total_fields')
    op.drop_column('host_locations', 'max_large_fields')
    op.drop_column('host_locations', 'max_medium_fields')
    op.drop_column('host_locations', 'max_small_fields')
    op.drop_column('host_locations', 'setup_constraints')
    op.drop_column('host_locations', 'field_area_name')
