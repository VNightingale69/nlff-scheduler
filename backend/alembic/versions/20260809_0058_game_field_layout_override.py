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
    # field_layout_type_override was used by the application before it was
    # represented in Alembic.  Some deployed databases therefore already have
    # that column.  Make this repair migration safe for both pristine and
    # schema-drifted databases rather than failing with DuplicateColumn and
    # leaving the new relationship absent.
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('timeslot_field_configurations'):
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

    inspector = sa.inspect(op.get_bind())
    indexes = inspector.get_indexes('timeslot_field_configurations')
    has_lookup_index = any(
        index['name'] == 'ix_timeslot_field_configuration_lookup'
        or index.get('column_names') == ['host_location_id', 'configuration_date', 'kickoff_time']
        for index in indexes
    )
    if not has_lookup_index:
        op.create_index('ix_timeslot_field_configuration_lookup', 'timeslot_field_configurations', ['host_location_id', 'configuration_date', 'kickoff_time'])

    game_columns = {column['name'] for column in inspector.get_columns('games')}
    if 'field_layout_type_override' not in game_columns:
        op.add_column('games', sa.Column('field_layout_type_override', sa.String(length=20), nullable=True))
    if 'timeslot_configuration_id' not in game_columns:
        op.add_column('games', sa.Column('timeslot_configuration_id', sa.Uuid(), nullable=True))

    inspector = sa.inspect(op.get_bind())
    foreign_keys = inspector.get_foreign_keys('games')
    has_timeslot_foreign_key = any(
        foreign_key['name'] == 'fk_games_timeslot_configuration'
        or (
            foreign_key.get('constrained_columns') == ['timeslot_configuration_id']
            and foreign_key.get('referred_table') == 'timeslot_field_configurations'
            and foreign_key.get('referred_columns') == ['id']
        )
        for foreign_key in foreign_keys
    )
    if not has_timeslot_foreign_key:
        op.create_foreign_key('fk_games_timeslot_configuration', 'games', 'timeslot_field_configurations', ['timeslot_configuration_id'], ['id'])


def downgrade():
    op.drop_constraint('fk_games_timeslot_configuration', 'games', type_='foreignkey')
    op.drop_column('games', 'timeslot_configuration_id')
    op.drop_column('games', 'field_layout_type_override')
    op.drop_index('ix_timeslot_field_configuration_lookup', table_name='timeslot_field_configurations')
    op.drop_table('timeslot_field_configurations')
