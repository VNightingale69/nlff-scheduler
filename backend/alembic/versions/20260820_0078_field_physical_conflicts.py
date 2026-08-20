"""add explicit canonical physical field conflicts

Revision ID: 20260820_0078
Revises: 20260820_0077
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260820_0078'
down_revision = '20260820_0077'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'field_physical_conflicts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('host_location_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('host_locations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('field_a_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('fields.id', ondelete='CASCADE'), nullable=False),
        sa.Column('field_b_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('fields.id', ondelete='CASCADE'), nullable=False),
        sa.Column('reason', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('field_a_id <> field_b_id', name='ck_field_physical_conflict_distinct'),
        sa.UniqueConstraint('host_location_id', 'field_a_id', 'field_b_id', name='uq_field_physical_conflict_pair'),
    )
    op.create_index('ix_field_physical_conflicts_host', 'field_physical_conflicts', ['host_location_id'])


def downgrade():
    op.drop_index('ix_field_physical_conflicts_host', table_name='field_physical_conflicts')
    op.drop_table('field_physical_conflicts')
