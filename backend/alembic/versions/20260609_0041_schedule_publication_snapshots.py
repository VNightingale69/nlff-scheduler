"""schedule publication snapshots

Revision ID: 20260609_0041
Revises: 20260609_0040
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260609_0041'
down_revision = '20260609_0040'
branch_labels = None
depends_on = None


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if column.name not in {col['name'] for col in inspector.get_columns(table)}:
        op.add_column(table, column)


def _uuid_type():
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(36), 'sqlite')


def upgrade() -> None:
    _add_column_if_missing('seasons', sa.Column('schedule_published_at', sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing('seasons', sa.Column('schedule_published_by_user_id', _uuid_type(), nullable=True))
    _add_column_if_missing('seasons', sa.Column('schedule_unpublished_at', sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing('seasons', sa.Column('schedule_unpublished_by_user_id', _uuid_type(), nullable=True))
    _add_column_if_missing('seasons', sa.Column('schedule_unpublished_reason', sa.Text(), nullable=True))
    _add_column_if_missing('seasons', sa.Column('last_published_schedule_hash', sa.String(length=64), nullable=True))
    _add_column_if_missing('seasons', sa.Column('last_published_game_count', sa.Integer(), nullable=True))
    _add_column_if_missing('seasons', sa.Column('last_published_at', sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing('seasons', sa.Column('schedule_modified_after_publish', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    for column in [
        'schedule_modified_after_publish',
        'last_published_at',
        'last_published_game_count',
        'last_published_schedule_hash',
        'schedule_unpublished_reason',
        'schedule_unpublished_by_user_id',
        'schedule_unpublished_at',
        'schedule_published_by_user_id',
        'schedule_published_at',
    ]:
        try:
            op.drop_column('seasons', column)
        except Exception:
            pass
