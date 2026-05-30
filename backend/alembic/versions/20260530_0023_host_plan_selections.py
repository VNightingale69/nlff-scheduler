"""host plan selections

Revision ID: 20260530_0023
Revises: 20260529_0022
Create Date: 2026-05-30 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260530_0023'
down_revision = '20260529_0022'
branch_labels = None
depends_on = None


def _uuid_type():
    bind = op.get_bind()
    return postgresql.UUID(as_uuid=True) if bind.dialect.name == 'postgresql' else sa.String(length=36)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'host_plan_selections' in inspector.get_table_names():
        return
    uuid_type = _uuid_type()
    op.create_table(
        'host_plan_selections',
        sa.Column('id', uuid_type, primary_key=True, nullable=False),
        sa.Column('season_id', uuid_type, sa.ForeignKey('seasons.id'), nullable=False),
        sa.Column('week_id', uuid_type, sa.ForeignKey('weeks.id'), nullable=True),
        sa.Column('game_date', sa.Date(), nullable=False),
        sa.Column('community_id', uuid_type, sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('host_location_id', uuid_type, sa.ForeignKey('host_locations.id'), nullable=False),
        sa.Column('availability_id', uuid_type, sa.ForeignKey('hosting_availabilities.id'), nullable=True),
        sa.Column('status', sa.String(length=40), nullable=False, server_default='AVAILABLE'),
        sa.Column('locked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('season_id', 'game_date', 'host_location_id', name='uq_host_plan_selection_season_date_location'),
    )
    op.create_index('ix_host_plan_selections_week_status', 'host_plan_selections', ['week_id', 'status'])
    op.create_index('ix_host_plan_selections_date_status', 'host_plan_selections', ['season_id', 'game_date', 'status'])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'host_plan_selections' not in inspector.get_table_names():
        return
    op.drop_index('ix_host_plan_selections_date_status', table_name='host_plan_selections')
    op.drop_index('ix_host_plan_selections_week_status', table_name='host_plan_selections')
    op.drop_table('host_plan_selections')
