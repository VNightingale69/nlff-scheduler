"""grass host capacity fields

Revision ID: 20260529_0022
Revises: 20260529_0021
Create Date: 2026-05-29 14:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '20260529_0022'
down_revision = '20260529_0021'
branch_labels = None
depends_on = None


def _add_int_if_missing(inspector, table_name: str, column_name: str) -> None:
    columns = {column['name'] for column in inspector.get_columns(table_name)}
    if column_name not in columns:
        op.add_column(table_name, sa.Column(column_name, sa.Integer(), nullable=False, server_default='0'))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'host_locations' not in inspector.get_table_names():
        return
    for column_name in ('max_small_fields', 'max_medium_fields', 'max_large_fields', 'max_total_fields'):
        _add_int_if_missing(inspector, 'host_locations', column_name)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'host_locations' not in inspector.get_table_names():
        return
    columns = {column['name'] for column in inspector.get_columns('host_locations')}
    for column_name in ('max_total_fields', 'max_large_fields', 'max_medium_fields', 'max_small_fields'):
        if column_name in columns:
            op.drop_column('host_locations', column_name)
