"""initial schema

Revision ID: 20260518_0001
Revises: 
Create Date: 2026-05-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '20260518_0001'
down_revision = None
branch_labels = None
depends_on = None


def _uuid_col():
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', _uuid_col(), primary_key=True, nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('email'),
    )

    for name, cols in [
        ('roles', [('name', 100), ('description', None)]),
        ('organizations', [('name', 255)]),
    ]:
        columns = [sa.Column('id', _uuid_col(), primary_key=True, nullable=False)]
        if name == 'roles':
            columns += [
                sa.Column('name', sa.String(100), nullable=False),
                sa.Column('description', sa.Text(), nullable=True),
            ]
        if name == 'organizations':
            columns += [sa.Column('name', sa.String(255), nullable=False)]
        columns += [
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        ]
        op.create_table(name, *columns, sa.UniqueConstraint('name'))

    op.create_table('divisions', sa.Column('id', _uuid_col(), primary_key=True), sa.Column('name', sa.String(120), nullable=False), sa.Column('required_field_layout_type', sa.String(100), nullable=False), sa.Column('min_age', sa.Integer()), sa.Column('max_age', sa.Integer()), sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint('name'))

    op.create_table('host_locations', sa.Column('id', _uuid_col(), primary_key=True), sa.Column('organization_id', _uuid_col(), sa.ForeignKey('organizations.id'), nullable=False), sa.Column('name', sa.String(255), nullable=False), sa.Column('address', sa.String(255)), sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint('organization_id', 'name', name='uq_host_location_org_name'))
    op.create_table('fields', sa.Column('id', _uuid_col(), primary_key=True), sa.Column('host_location_id', _uuid_col(), sa.ForeignKey('host_locations.id'), nullable=False), sa.Column('name', sa.String(120), nullable=False), sa.Column('layout_type', sa.String(100), nullable=False), sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint('host_location_id', 'name', name='uq_field_location_name'))
    op.create_table('teams', sa.Column('id', _uuid_col(), primary_key=True), sa.Column('organization_id', _uuid_col(), sa.ForeignKey('organizations.id'), nullable=False), sa.Column('division_id', _uuid_col(), sa.ForeignKey('divisions.id'), nullable=False), sa.Column('name', sa.String(255), nullable=False), sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint('organization_id', 'division_id', 'name', name='uq_team_org_div_name'))
    op.create_table('seasons', sa.Column('id', _uuid_col(), primary_key=True), sa.Column('name', sa.String(120), nullable=False), sa.Column('start_date', sa.Date(), nullable=False), sa.Column('end_date', sa.Date(), nullable=False), sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint('name'))
    op.create_table('weeks', sa.Column('id', _uuid_col(), primary_key=True), sa.Column('season_id', _uuid_col(), sa.ForeignKey('seasons.id'), nullable=False), sa.Column('week_number', sa.Integer(), nullable=False), sa.Column('start_date', sa.Date(), nullable=False), sa.Column('end_date', sa.Date(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint('season_id', 'week_number', name='uq_week_season_number'))
    op.create_table('hosting_availabilities', sa.Column('id', _uuid_col(), primary_key=True), sa.Column('field_id', _uuid_col(), sa.ForeignKey('fields.id'), nullable=False), sa.Column('available_date', sa.Date(), nullable=False), sa.Column('start_time', sa.Time(), nullable=False), sa.Column('end_time', sa.Time(), nullable=False), sa.Column('is_available', sa.Boolean(), nullable=False, server_default=sa.text('true')), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint('field_id', 'available_date', 'start_time', 'end_time', name='uq_field_availability_slot'))
    op.create_table('game_statuses', sa.Column('id', _uuid_col(), primary_key=True), sa.Column('code', sa.String(50), nullable=False), sa.Column('label', sa.String(100), nullable=False), sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint('code'), sa.UniqueConstraint('label'))
    op.create_table('games', sa.Column('id', _uuid_col(), primary_key=True), sa.Column('season_id', _uuid_col(), sa.ForeignKey('seasons.id'), nullable=False), sa.Column('week_id', _uuid_col(), sa.ForeignKey('weeks.id'), nullable=False), sa.Column('home_team_id', _uuid_col(), sa.ForeignKey('teams.id'), nullable=False), sa.Column('away_team_id', _uuid_col(), sa.ForeignKey('teams.id'), nullable=False), sa.Column('field_id', _uuid_col(), sa.ForeignKey('fields.id'), nullable=False), sa.Column('game_status_id', _uuid_col(), sa.ForeignKey('game_statuses.id'), nullable=False), sa.Column('game_date', sa.Date(), nullable=False), sa.Column('kickoff_time', sa.Time(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))

    op.execute("""
        INSERT INTO divisions (id, name, required_field_layout_type, min_age, max_age, is_active)
        VALUES
          (gen_random_uuid(), 'K-1', 'small-sided', 5, 7, true),
          (gen_random_uuid(), '2-3', 'mid-sided', 7, 9, true),
          (gen_random_uuid(), '4-5', 'standard', 9, 11, true),
          (gen_random_uuid(), '6-8', 'full', 11, 14, true)
    """)


def downgrade() -> None:
    for table in ['games', 'game_statuses', 'hosting_availabilities', 'weeks', 'seasons', 'teams', 'fields', 'host_locations', 'divisions', 'organizations', 'roles', 'users']:
        op.drop_table(table)
