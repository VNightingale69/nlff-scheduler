"""add team lifecycle eligibility fields

Revision ID: 20260729_0052
Revises: 20260720_0051
"""
from alembic import op
import sqlalchemy as sa


revision = '20260729_0052'
down_revision = '20260720_0051'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('teams', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('teams', sa.Column('superseded_by_team_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'teams_superseded_by_team_id_fkey', 'teams', 'teams',
        ['superseded_by_team_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index(
        'ix_teams_current_eligibility', 'teams',
        ['is_active', 'deleted_at', 'superseded_by_team_id'],
    )


def downgrade():
    op.drop_index('ix_teams_current_eligibility', table_name='teams')
    op.drop_constraint('teams_superseded_by_team_id_fkey', 'teams', type_='foreignkey')
    op.drop_column('teams', 'superseded_by_team_id')
    op.drop_column('teams', 'deleted_at')
