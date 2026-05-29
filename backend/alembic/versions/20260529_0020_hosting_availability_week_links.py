"""hosting availability week links

Revision ID: 20260529_0020
Revises: 20260529_0019
Create Date: 2026-05-29 15:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260529_0020'
down_revision = '20260529_0019'
branch_labels = None
depends_on = None


def _add_column_if_missing(inspector, table_name: str, column: sa.Column) -> None:
    columns = {c['name'] for c in inspector.get_columns(table_name)}
    if column.name not in columns:
        op.add_column(table_name, column)


def _create_index_if_missing(inspector, table_name: str, index_name: str, columns: list[str], unique: bool = False) -> None:
    indexes = {idx['name'] for idx in inspector.get_indexes(table_name)}
    if index_name not in indexes:
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if 'hosting_availabilities' not in tables:
        return

    _add_column_if_missing(inspector, 'hosting_availabilities', sa.Column('season_id', postgresql.UUID(as_uuid=True), nullable=True))
    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, 'hosting_availabilities', sa.Column('week_id', postgresql.UUID(as_uuid=True), nullable=True))
    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, 'hosting_availabilities', sa.Column('primary_game_date', sa.Date(), nullable=True))
    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, 'hosting_availabilities', sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()))

    op.execute('UPDATE hosting_availabilities SET primary_game_date = COALESCE(primary_game_date, available_date)')
    op.execute('UPDATE hosting_availabilities SET active = is_available WHERE active IS NULL')
    try:
        op.alter_column('hosting_availabilities', 'active', server_default=None)
    except Exception:
        pass

    inspector = sa.inspect(bind)
    if bind.dialect.name != 'sqlite':
        foreign_keys = {fk['name'] for fk in inspector.get_foreign_keys('hosting_availabilities')}
        if 'fk_hosting_availabilities_season_id' not in foreign_keys:
            op.create_foreign_key('fk_hosting_availabilities_season_id', 'hosting_availabilities', 'seasons', ['season_id'], ['id'])
        if 'fk_hosting_availabilities_week_id' not in foreign_keys:
            op.create_foreign_key('fk_hosting_availabilities_week_id', 'hosting_availabilities', 'weeks', ['week_id'], ['id'])

    inspector = sa.inspect(bind)
    _create_index_if_missing(inspector, 'hosting_availabilities', 'ix_hosting_availabilities_week_id', ['week_id'])
    inspector = sa.inspect(bind)
    _create_index_if_missing(inspector, 'hosting_availabilities', 'ix_hosting_availabilities_season_week_host', ['season_id', 'week_id', 'host_location_id'])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'hosting_availabilities' not in inspector.get_table_names():
        return
    indexes = {idx['name'] for idx in inspector.get_indexes('hosting_availabilities')}
    for index_name in ('ix_hosting_availabilities_season_week_host', 'ix_hosting_availabilities_week_id'):
        if index_name in indexes:
            op.drop_index(index_name, table_name='hosting_availabilities')
    columns = {c['name'] for c in inspector.get_columns('hosting_availabilities')}
    for column_name in ('active', 'primary_game_date', 'week_id', 'season_id'):
        if column_name in columns:
            op.drop_column('hosting_availabilities', column_name)
