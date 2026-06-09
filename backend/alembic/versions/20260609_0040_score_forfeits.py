"""score forfeits

Revision ID: 20260609_0040
Revises: 20260609_0039
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa

revision = '20260609_0040'
down_revision = '20260609_0039'
branch_labels = None
depends_on = None


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if column.name not in {col['name'] for col in inspector.get_columns(table)}:
        op.add_column(table, column)


def upgrade() -> None:
    _add_column_if_missing('game_scores', sa.Column('home_forfeit', sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing('game_scores', sa.Column('away_forfeit', sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing('score_submissions', sa.Column('home_forfeit', sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing('score_submissions', sa.Column('away_forfeit', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    for table, column in [
        ('score_submissions', 'away_forfeit'),
        ('score_submissions', 'home_forfeit'),
        ('game_scores', 'away_forfeit'),
        ('game_scores', 'home_forfeit'),
    ]:
        try:
            op.drop_column(table, column)
        except Exception:
            pass
