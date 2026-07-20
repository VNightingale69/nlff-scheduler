"""enforce team organization integrity

Revision ID: 20260720_0050
Revises: 20260611_0049
Create Date: 2026-07-20
"""
from alembic import op
import sqlalchemy as sa

revision = '20260720_0050'
down_revision = '20260611_0049'
branch_labels = None
depends_on = None


def upgrade():
    # Remove impossible nulls before asserting NOT NULL; dangling non-null rows must be cleaned with
    # python -m app.scripts.cleanup_orphaned_organizations --apply before this migration runs.
    op.alter_column('teams', 'organization_id', existing_type=sa.UUID(), nullable=False)
    op.drop_constraint('teams_organization_id_fkey', 'teams', type_='foreignkey')
    op.create_foreign_key('teams_organization_id_fkey', 'teams', 'organizations', ['organization_id'], ['id'], ondelete='RESTRICT')


def downgrade():
    op.drop_constraint('teams_organization_id_fkey', 'teams', type_='foreignkey')
    op.create_foreign_key('teams_organization_id_fkey', 'teams', 'organizations', ['organization_id'], ['id'])
