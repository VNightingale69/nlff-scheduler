"""add season schedule status

Revision ID: 20260527_0015
Revises: 20260526_0014
Create Date: 2026-05-27
"""
from alembic import op
import sqlalchemy as sa

revision = '20260527_0015'
down_revision = '20260526_0014'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('seasons', sa.Column('schedule_status', sa.String(length=20), nullable=False, server_default='draft'))
    op.execute("UPDATE seasons SET schedule_status='draft' WHERE schedule_status IS NULL")
    op.alter_column('seasons', 'schedule_status', server_default=None)

def downgrade() -> None:
    op.drop_column('seasons', 'schedule_status')
