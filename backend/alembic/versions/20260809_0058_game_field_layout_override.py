"""Persist intentional per-timeslot field layout overrides.

Revision ID: 20260809_0058
Revises: 20260808_0057
"""
from alembic import op
import sqlalchemy as sa

revision = '20260809_0058'
down_revision = '20260808_0057'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('games', sa.Column('field_layout_type_override', sa.String(length=20), nullable=True))


def downgrade():
    op.drop_column('games', 'field_layout_type_override')
