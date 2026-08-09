"""repair partially deployed timeslot configuration schema

Revision ID: 20260809_0060
Revises: 20260809_0059

The original 0058 migration was edited after release to tolerate a legacy
``games.field_layout_type_override`` column.  Editing an Alembic revision does
not repair a database on which that revision is already recorded, however.
This forward-only repair gives every deployed database a new revision to run.
It adds only missing, nullable game columns and never rewrites game rows.
"""
from alembic import op
import sqlalchemy as sa


revision = '20260809_0060'
down_revision = '20260809_0059'
branch_labels = None
depends_on = None


def _has_columns(inspector, table_name, expected):
    present = {column['name'] for column in inspector.get_columns(table_name)}
    return expected.issubset(present)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

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
    else:
        required = {'id', 'host_location_id', 'configuration_id', 'configuration_date', 'kickoff_time', 'created_at', 'updated_at'}
        if not _has_columns(sa.inspect(bind), 'timeslot_field_configurations', required):
            raise RuntimeError('timeslot_field_configurations exists but is incomplete; refusing an unsafe automatic repair')

    inspector = sa.inspect(bind)
    indexes = inspector.get_indexes('timeslot_field_configurations')
    if not any(index.get('name') == 'ix_timeslot_field_configuration_lookup' or
               index.get('column_names') == ['host_location_id', 'configuration_date', 'kickoff_time']
               for index in indexes):
        op.create_index('ix_timeslot_field_configuration_lookup', 'timeslot_field_configurations',
                        ['host_location_id', 'configuration_date', 'kickoff_time'])

    game_columns = {column['name'] for column in inspector.get_columns('games')}
    if 'field_layout_type_override' not in game_columns:
        op.add_column('games', sa.Column('field_layout_type_override', sa.String(length=20), nullable=True))
    if 'timeslot_configuration_id' not in game_columns:
        op.add_column('games', sa.Column('timeslot_configuration_id', sa.Uuid(), nullable=True))

    foreign_keys = sa.inspect(bind).get_foreign_keys('games')
    if not any(foreign_key.get('constrained_columns') == ['timeslot_configuration_id'] and
               foreign_key.get('referred_table') == 'timeslot_field_configurations'
               for foreign_key in foreign_keys):
        op.create_foreign_key('fk_games_timeslot_configuration', 'games',
                              'timeslot_field_configurations', ['timeslot_configuration_id'], ['id'])


def downgrade():
    # This is a repair revision: objects may belong to 0058 and must not be
    # removed merely by stepping back from 0060.
    pass
