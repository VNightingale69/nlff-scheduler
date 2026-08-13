"""add safe user soft deletion

Revision ID: 20260813_0064
Revises: 20260812_0063
"""
from alembic import op
import sqlalchemy as sa

revision = '20260813_0064'
down_revision = '20260812_0063'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_users_active_not_deleted', 'users', ['is_active', 'deleted_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_users_active_not_deleted', table_name='users')
    op.drop_column('users', 'deleted_at')
