"""week scoped schedule publication

Revision ID: 20260809_0059
Revises: 20260809_0058
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260809_0059'
down_revision = '20260809_0058'
branch_labels = None
depends_on = None

def _uuid():
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(36), 'sqlite')

def upgrade():
    op.add_column('weeks', sa.Column('publication_status', sa.String(20), nullable=False, server_default='UNPUBLISHED'))
    op.add_column('weeks', sa.Column('published_at', sa.DateTime(timezone=True)))
    op.add_column('weeks', sa.Column('published_by_user_id', _uuid()))
    op.add_column('weeks', sa.Column('unpublished_at', sa.DateTime(timezone=True)))
    op.add_column('weeks', sa.Column('last_published_schedule_hash', sa.String(64)))
    op.add_column('weeks', sa.Column('last_published_game_count', sa.Integer()))
    op.create_foreign_key('fk_weeks_published_by', 'weeks', 'users', ['published_by_user_id'], ['id'])
    # Preserve schedules published before week-scoped publication existed.
    op.execute("UPDATE weeks SET publication_status = 'PUBLISHED' WHERE season_id IN (SELECT id FROM seasons WHERE lower(schedule_status) IN ('published', 'saved'))")
    op.create_table('schedule_publication_events',
        sa.Column('id', _uuid(), primary_key=True),
        sa.Column('season_id', _uuid(), sa.ForeignKey('seasons.id'), nullable=False),
        sa.Column('week_ids', sa.Text(), nullable=False),
        sa.Column('action', sa.String(20), nullable=False),
        sa.Column('performed_by_user_id', _uuid(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('performed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('game_count', sa.Integer(), nullable=False, server_default='0'))

def downgrade():
    op.drop_table('schedule_publication_events')
    op.drop_constraint('fk_weeks_published_by', 'weeks', type_='foreignkey')
    for name in ('last_published_game_count','last_published_schedule_hash','unpublished_at','published_by_user_id','published_at','publication_status'):
        op.drop_column('weeks', name)
