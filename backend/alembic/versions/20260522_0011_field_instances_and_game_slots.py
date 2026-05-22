"""add field instances and generated game slots

Revision ID: 20260522_0011
Revises: 20260522_0010
Create Date: 2026-05-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '20260522_0011'
down_revision = '20260522_0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'field_instances',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('host_location_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('hosting_availability_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('instance_date', sa.Date(), nullable=False),
        sa.Column('field_name', sa.String(length=120), nullable=False),
        sa.Column('field_type', sa.String(length=10), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['host_location_id'], ['host_locations.id']),
        sa.ForeignKeyConstraint(['hosting_availability_id'], ['hosting_availabilities.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('hosting_availability_id', 'field_name', name='uq_field_instance_availability_name'),
    )

    op.create_table(
        'game_slots',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('field_instance_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('host_location_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('slot_date', sa.Date(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('field_type', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='OPEN'),
        sa.Column('assigned_game_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['assigned_game_id'], ['games.id']),
        sa.ForeignKeyConstraint(['field_instance_id'], ['field_instances.id']),
        sa.ForeignKeyConstraint(['host_location_id'], ['host_locations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('field_instance_id', 'start_time', 'end_time', name='uq_game_slot_instance_time'),
    )


def downgrade() -> None:
    op.drop_table('game_slots')
    op.drop_table('field_instances')
