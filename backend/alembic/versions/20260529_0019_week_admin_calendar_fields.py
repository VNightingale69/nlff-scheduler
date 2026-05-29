"""week admin calendar fields

Revision ID: 20260529_0019
Revises: 20260529_0018
Create Date: 2026-05-29 14:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '20260529_0019'
down_revision = '20260529_0018'
branch_labels = None
depends_on = None


def _add_column_if_missing(inspector, table_name: str, column: sa.Column) -> None:
    columns = {c['name'] for c in inspector.get_columns(table_name)}
    if column.name not in columns:
        op.add_column(table_name, column)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'weeks' not in inspector.get_table_names():
        return

    _add_column_if_missing(inspector, 'weeks', sa.Column('label', sa.String(length=120), nullable=True))
    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, 'weeks', sa.Column('primary_game_date', sa.Date(), nullable=True))
    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, 'weeks', sa.Column('notes', sa.Text(), nullable=True))
    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, 'weeks', sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'))

    op.execute("UPDATE weeks SET primary_game_date = COALESCE(primary_game_date, start_date)")
    op.execute("UPDATE weeks SET status = 'draft' WHERE status IS NULL OR status = ''")
    op.alter_column('weeks', 'status', server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'weeks' not in inspector.get_table_names():
        return
    columns = {c['name'] for c in inspector.get_columns('weeks')}
    for column_name in ('status', 'notes', 'primary_game_date', 'label'):
        if column_name in columns:
            op.drop_column('weeks', column_name)
