"""Add turf wave scheduling metadata

Revision ID: 20260529_0021
Revises: 20260529_0020
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '20260529_0021'
down_revision = '20260529_0020'
branch_labels = None
depends_on = None


def _uuid_type():
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(36), 'sqlite')


def upgrade():
    op.create_table(
        'turf_waves',
        sa.Column('id', _uuid_type(), nullable=False),
        sa.Column('host_location_id', _uuid_type(), nullable=False),
        sa.Column('hosting_availability_id', _uuid_type(), nullable=False),
        sa.Column('week_id', _uuid_type(), nullable=True),
        sa.Column('host_date', sa.Date(), nullable=False),
        sa.Column('sequence_number', sa.Integer(), nullable=False),
        sa.Column('wave_intent', sa.String(length=40), nullable=False),
        sa.Column('preferred_layout_code', sa.String(length=80), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('transition_before_minutes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('transition_after_minutes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['host_location_id'], ['host_locations.id']),
        sa.ForeignKeyConstraint(['hosting_availability_id'], ['hosting_availabilities.id']),
        sa.ForeignKeyConstraint(['week_id'], ['weeks.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('hosting_availability_id', 'sequence_number', name='uq_turf_wave_availability_sequence'),
    )
    op.create_index('ix_turf_waves_host_date', 'turf_waves', ['host_location_id', 'host_date'])
    op.add_column('game_slots', sa.Column('turf_wave_id', _uuid_type(), nullable=True))
    op.create_foreign_key('fk_game_slots_turf_wave_id_turf_waves', 'game_slots', 'turf_waves', ['turf_wave_id'], ['id'])


def downgrade():
    op.drop_constraint('fk_game_slots_turf_wave_id_turf_waves', 'game_slots', type_='foreignkey')
    op.drop_column('game_slots', 'turf_wave_id')
    op.drop_index('ix_turf_waves_host_date', table_name='turf_waves')
    op.drop_table('turf_waves')
