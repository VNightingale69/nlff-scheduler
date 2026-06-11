"""soft delete organizations

Revision ID: 20260611_0049
Revises: 20260611_0048
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260611_0049'
down_revision = '20260611_0048'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('organizations', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('organizations', sa.Column('deleted_by_user_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_organizations_deleted_by_user_id_users', 'organizations', 'users', ['deleted_by_user_id'], ['id'])
    op.create_index('ix_organizations_active_not_deleted', 'organizations', ['is_active', 'deleted_at'])


def downgrade() -> None:
    op.drop_index('ix_organizations_active_not_deleted', table_name='organizations')
    op.drop_constraint('fk_organizations_deleted_by_user_id_users', 'organizations', type_='foreignkey')
    op.drop_column('organizations', 'deleted_by_user_id')
    op.drop_column('organizations', 'deleted_at')
