"""host location level scheduling

Revision ID: 20260529_0016
Revises: 20260527_0015
Create Date: 2026-05-29 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260529_0016'
down_revision = '20260527_0015'
branch_labels = None
depends_on = None


def _uuid_type():
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    host_columns = {c['name'] for c in inspector.get_columns('host_locations')}
    if 'surface_type' not in host_columns:
        op.add_column('host_locations', sa.Column('surface_type', sa.String(length=40), nullable=False, server_default='OTHER'))
        op.alter_column('host_locations', 'surface_type', server_default=None)
    if 'notes' not in host_columns:
        op.add_column('host_locations', sa.Column('notes', sa.Text(), nullable=True))

    if 'host_location_configurations' not in inspector.get_table_names():
        op.create_table(
            'host_location_configurations',
            sa.Column('id', _uuid_type(), nullable=False),
            sa.Column('host_location_id', _uuid_type(), nullable=False),
            sa.Column('configuration_name', sa.String(length=80), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(['host_location_id'], ['host_locations.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('host_location_id', 'configuration_name', name='uq_host_location_configuration_name'),
        )

    availability_columns = {c['name'] for c in inspector.get_columns('hosting_availabilities')}
    if 'organization_id' not in availability_columns:
        op.add_column('hosting_availabilities', sa.Column('organization_id', _uuid_type(), nullable=True))
        op.create_foreign_key(None, 'hosting_availabilities', 'organizations', ['organization_id'], ['id'])
    if 'host_location_id' not in availability_columns:
        op.add_column('hosting_availabilities', sa.Column('host_location_id', _uuid_type(), nullable=True))
        op.create_foreign_key(None, 'hosting_availabilities', 'host_locations', ['host_location_id'], ['id'])
    if 'selected_configuration_id' not in availability_columns:
        op.add_column('hosting_availabilities', sa.Column('selected_configuration_id', _uuid_type(), nullable=True))
        op.create_foreign_key(None, 'hosting_availabilities', 'host_location_configurations', ['selected_configuration_id'], ['id'])
    if 'notes' not in availability_columns:
        op.add_column('hosting_availabilities', sa.Column('notes', sa.Text(), nullable=True))

    game_columns = {c['name'] for c in inspector.get_columns('games')}
    if 'host_location_id' not in game_columns:
        op.add_column('games', sa.Column('host_location_id', _uuid_type(), nullable=True))
        op.create_foreign_key(None, 'games', 'host_locations', ['host_location_id'], ['id'])
    if 'field_instance_id' not in game_columns:
        op.add_column('games', sa.Column('field_instance_id', _uuid_type(), nullable=True))
        op.create_foreign_key(None, 'games', 'field_instances', ['field_instance_id'], ['id'])


def downgrade() -> None:
    pass
