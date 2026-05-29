"""host date layout controls

Revision ID: 20260529_0018
Revises: 20260529_0017
Create Date: 2026-05-29 13:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '20260529_0018'
down_revision = '20260529_0017'
branch_labels = None
depends_on = None


def _add_bool_if_missing(inspector, table_name: str, column_name: str, default: bool) -> None:
    columns = {c['name'] for c in inspector.get_columns(table_name)}
    if column_name not in columns:
        op.add_column(table_name, sa.Column(column_name, sa.Boolean(), nullable=False, server_default=sa.true() if default else sa.false()))
        op.alter_column(table_name, column_name, server_default=None)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'hosting_availabilities' not in inspector.get_table_names():
        return
    _add_bool_if_missing(inspector, 'hosting_availabilities', 'auto_select_turf_layout', True)
    inspector = sa.inspect(bind)
    _add_bool_if_missing(inspector, 'hosting_availabilities', 'lock_selected_layout', False)
    inspector = sa.inspect(bind)
    _add_bool_if_missing(inspector, 'hosting_availabilities', 'allow_turf_layout_changes', False)
    inspector = sa.inspect(bind)
    _add_bool_if_missing(inspector, 'hosting_availabilities', 'admin_override_incompatible_field_size', False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'hosting_availabilities' not in inspector.get_table_names():
        return
    columns = {c['name'] for c in inspector.get_columns('hosting_availabilities')}
    for column_name in ('admin_override_incompatible_field_size', 'allow_turf_layout_changes', 'lock_selected_layout', 'auto_select_turf_layout'):
        if column_name in columns:
            op.drop_column('hosting_availabilities', column_name)
