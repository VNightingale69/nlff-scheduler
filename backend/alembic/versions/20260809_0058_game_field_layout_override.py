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
    op.create_table(
        'timeslot_field_configurations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('host_location_id', sa.Uuid(), nullable=False),
        sa.Column('configuration_id', sa.Uuid(), nullable=False),
        sa.Column('configuration_date', sa.Date(), nullable=False),
        sa.Column('kickoff_time', sa.Time(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['configuration_id'], ['host_location_configurations.id']),
        sa.ForeignKeyConstraint(['host_location_id'], ['host_locations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('host_location_id', 'configuration_date', 'kickoff_time', name='uq_timeslot_field_configuration'),
    )
    op.create_index('ix_timeslot_field_configuration_lookup', 'timeslot_field_configurations', ['host_location_id', 'configuration_date', 'kickoff_time'])
    op.add_column('games', sa.Column('field_layout_type_override', sa.String(length=20), nullable=True))
    op.add_column('games', sa.Column('timeslot_configuration_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('fk_games_timeslot_configuration', 'games', 'timeslot_field_configurations', ['timeslot_configuration_id'], ['id'])


def downgrade():
    op.drop_constraint('fk_games_timeslot_configuration', 'games', type_='foreignkey')
    op.drop_column('games', 'timeslot_configuration_id')
    op.drop_column('games', 'field_layout_type_override')
    op.drop_index('ix_timeslot_field_configuration_lookup', table_name='timeslot_field_configurations')
    op.drop_table('timeslot_field_configurations')
