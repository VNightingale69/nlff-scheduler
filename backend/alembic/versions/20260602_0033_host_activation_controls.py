"""host activation controls

Revision ID: 20260602_0033
Revises: 20260601_0032
Create Date: 2026-06-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '20260602_0033'
down_revision = '20260601_0032'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('host_locations', sa.Column('host_role', sa.String(length=40), nullable=True))
    op.add_column('host_locations', sa.Column('minimum_games_to_activate_overflow_host', sa.Integer(), nullable=False, server_default='2'))
    op.add_column('host_locations', sa.Column('preferred_minimum_games_per_active_host', sa.Integer(), nullable=False, server_default='2'))
    op.add_column('host_locations', sa.Column('maximum_games_per_host_per_date', sa.Integer(), nullable=True))
    op.add_column('host_locations', sa.Column('overflow_activation_allowed', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.alter_column('host_locations', 'minimum_games_to_activate_overflow_host', server_default=None)
    op.alter_column('host_locations', 'preferred_minimum_games_per_active_host', server_default=None)
    op.alter_column('host_locations', 'overflow_activation_allowed', server_default=None)


def downgrade() -> None:
    op.drop_column('host_locations', 'overflow_activation_allowed')
    op.drop_column('host_locations', 'maximum_games_per_host_per_date')
    op.drop_column('host_locations', 'preferred_minimum_games_per_active_host')
    op.drop_column('host_locations', 'minimum_games_to_activate_overflow_host')
    op.drop_column('host_locations', 'host_role')
