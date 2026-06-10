"""field soft delete and missing assignment flags

Revision ID: 20260610_0043
Revises: 20260610_0042
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260610_0043'
down_revision = '20260610_0042'
branch_labels = None
depends_on = None


def _uuid_type():
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(36), 'sqlite')


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table in inspector.get_table_names() and column.name not in {col['name'] for col in inspector.get_columns(table)}:
        op.add_column(table, column)


def upgrade() -> None:
    _add_column_if_missing('fields', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing('fields', sa.Column('deleted_by_user_id', _uuid_type(), nullable=True))
    _add_column_if_missing('games', sa.Column('missing_field_assignment', sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing('games', sa.Column('needs_schedule_review', sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing('games', sa.Column('field_deleted_from_game', sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing('games', sa.Column('previous_field_id', _uuid_type(), nullable=True))
    _add_column_if_missing('games', sa.Column('previous_field_name', sa.String(length=120), nullable=True))
    _add_column_if_missing('games', sa.Column('field_deleted_at', sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing('games', sa.Column('field_assignment_status', sa.String(length=40), nullable=True))


def downgrade() -> None:
    for table, columns in {
        'games': ['field_assignment_status', 'field_deleted_at', 'previous_field_name', 'previous_field_id', 'field_deleted_from_game', 'needs_schedule_review', 'missing_field_assignment'],
        'fields': ['deleted_by_user_id', 'deleted_at'],
    }.items():
        for column in columns:
            try:
                op.drop_column(table, column)
            except Exception:
                pass
