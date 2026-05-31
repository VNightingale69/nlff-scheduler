"""add season link to game slots

Revision ID: 20260531_0027
Revises: 20260531_0026
Create Date: 2026-05-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '20260531_0027'
down_revision = '20260531_0026'
branch_labels = None
depends_on = None


def _uuid_type():
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        return postgresql.UUID(as_uuid=True)
    return sa.String(length=36)


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return column_name in {column['name'] for column in inspector.get_columns(table_name)}


def _has_fk(inspector, table_name: str, constraint_name: str) -> bool:
    return constraint_name in {fk.get('name') for fk in inspector.get_foreign_keys(table_name)}


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return index_name in {index.get('name') for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_column(inspector, 'game_slots', 'season_id'):
        op.add_column('game_slots', sa.Column('season_id', _uuid_type(), nullable=True))
    inspector = sa.inspect(bind)
    if bind.dialect.name != 'sqlite' and not _has_fk(inspector, 'game_slots', 'fk_game_slots_season_id_seasons'):
        op.create_foreign_key('fk_game_slots_season_id_seasons', 'game_slots', 'seasons', ['season_id'], ['id'])
    inspector = sa.inspect(bind)
    if not _has_index(inspector, 'game_slots', 'ix_game_slots_season_week_date'):
        op.create_index('ix_game_slots_season_week_date', 'game_slots', ['season_id', 'week_id', 'slot_date'])
    if bind.dialect.name == 'postgresql':
        op.execute(
            """
            UPDATE game_slots
            SET season_id = weeks.season_id
            FROM weeks
            WHERE game_slots.week_id = weeks.id
              AND game_slots.season_id IS NULL
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_index(inspector, 'game_slots', 'ix_game_slots_season_week_date'):
        op.drop_index('ix_game_slots_season_week_date', table_name='game_slots')
    inspector = sa.inspect(bind)
    if bind.dialect.name != 'sqlite' and _has_fk(inspector, 'game_slots', 'fk_game_slots_season_id_seasons'):
        op.drop_constraint('fk_game_slots_season_id_seasons', 'game_slots', type_='foreignkey')
    inspector = sa.inspect(bind)
    if _has_column(inspector, 'game_slots', 'season_id'):
        op.drop_column('game_slots', 'season_id')
