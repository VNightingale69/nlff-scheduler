"""repair supported field layout schema for partially migrated databases

Revision ID: 20260813_0066
Revises: 20260813_0065

The configuration API writes ``sort_order`` and ``is_legacy`` and then inserts
member rows in one transaction.  A deployment stamped past 0062/0063 without
that DDL therefore rolled the whole Add Configuration request back.  This
forward-only repair is intentionally additive and preserves all schedule data.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '20260813_0066'
down_revision = '20260813_0065'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column['name'] for column in inspector.get_columns('host_location_configurations')}
    if 'sort_order' not in columns:
        op.add_column('host_location_configurations', sa.Column('sort_order', sa.Integer(), nullable=False,
                                                                 server_default='0'))
    if 'is_legacy' not in columns:
        op.add_column('host_location_configurations', sa.Column('is_legacy', sa.Boolean(), nullable=False,
                                                                 server_default=sa.false()))

    if not sa.inspect(bind).has_table('field_configuration_members'):
        op.create_table(
            'field_configuration_members',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column('field_configuration_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('host_location_configurations.id', ondelete='CASCADE'), nullable=False),
            sa.Column('field_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('fields.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('field_configuration_id', 'field_id', name='uq_field_configuration_member'),
        )

    # The code is host-scoped.  Retain/create that composite constraint; never
    # create a global unique constraint on configuration_name.
    uniques = sa.inspect(bind).get_unique_constraints('host_location_configurations')
    if not any(set(item.get('column_names') or ()) == {'host_location_id', 'configuration_name'}
               for item in uniques):
        op.create_unique_constraint('uq_host_location_configuration_name', 'host_location_configurations',
                                    ['host_location_id', 'configuration_name'])


def downgrade() -> None:
    # Repair migrations must not remove member assignments or layout metadata.
    pass
