"""physical field area support

Revision ID: 20260520_0003
Revises: 20260520_0002
Create Date: 2026-05-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260520_0003'
down_revision = '20260520_0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'physical_field_areas',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('host_location_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('field_space_type', sa.String(length=80), nullable=False),
        sa.Column('supports_dynamic_configuration', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['host_location_id'], ['host_locations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('host_location_id', 'name', name='uq_field_area_location_name'),
    )
    op.create_table(
        'field_configuration_options',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('physical_field_area_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('thirty_yard_capacity', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('fifty_three_yard_capacity', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['physical_field_area_id'], ['physical_field_areas.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('physical_field_area_id', 'name', name='uq_field_config_option_area_name'),
    )
    op.add_column('fields', sa.Column('physical_field_area_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('fields', sa.Column('notes', sa.Text(), nullable=True))
    op.create_foreign_key(None, 'fields', 'physical_field_areas', ['physical_field_area_id'], ['id'])

    op.add_column('hosting_availabilities', sa.Column('physical_field_area_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('hosting_availabilities', sa.Column('field_configuration_option_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('hosting_availabilities', sa.Column('layout_type', sa.String(length=100), nullable=True))
    op.add_column('hosting_availabilities', sa.Column('slot_index', sa.Integer(), nullable=True))
    op.alter_column('hosting_availabilities', 'field_id', nullable=True)
    op.create_foreign_key(None, 'hosting_availabilities', 'physical_field_areas', ['physical_field_area_id'], ['id'])
    op.create_foreign_key(None, 'hosting_availabilities', 'field_configuration_options', ['field_configuration_option_id'], ['id'])
    op.drop_constraint('uq_field_availability_slot', 'hosting_availabilities', type_='unique')
    op.create_unique_constraint('uq_field_availability_slot', 'hosting_availabilities', ['field_id', 'physical_field_area_id', 'available_date', 'start_time', 'end_time', 'layout_type', 'slot_index'])

def downgrade() -> None:
    op.drop_constraint('uq_field_availability_slot', 'hosting_availabilities', type_='unique')
    op.create_unique_constraint('uq_field_availability_slot', 'hosting_availabilities', ['field_id', 'available_date', 'start_time', 'end_time'])
    op.drop_constraint(None, 'hosting_availabilities', type_='foreignkey')
    op.drop_constraint(None, 'hosting_availabilities', type_='foreignkey')
    op.alter_column('hosting_availabilities', 'field_id', nullable=False)
    op.drop_column('hosting_availabilities', 'slot_index')
    op.drop_column('hosting_availabilities', 'layout_type')
    op.drop_column('hosting_availabilities', 'field_configuration_option_id')
    op.drop_column('hosting_availabilities', 'physical_field_area_id')

    op.drop_constraint(None, 'fields', type_='foreignkey')
    op.drop_column('fields', 'notes')
    op.drop_column('fields', 'physical_field_area_id')
    op.drop_table('field_configuration_options')
    op.drop_table('physical_field_areas')
