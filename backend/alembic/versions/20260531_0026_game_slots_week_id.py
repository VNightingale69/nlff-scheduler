"""add season week link to game slots

Revision ID: 20260531_0026
Revises: 20260530_0025
Create Date: 2026-05-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '20260531_0026'
down_revision = '20260530_0025'
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
    if not _has_column(inspector, 'game_slots', 'week_id'):
        op.add_column('game_slots', sa.Column('week_id', _uuid_type(), nullable=True))
    inspector = sa.inspect(bind)
    if bind.dialect.name != 'sqlite' and not _has_fk(inspector, 'game_slots', 'fk_game_slots_week_id_weeks'):
        op.create_foreign_key('fk_game_slots_week_id_weeks', 'game_slots', 'weeks', ['week_id'], ['id'])
    inspector = sa.inspect(bind)
    if not _has_index(inspector, 'game_slots', 'ix_game_slots_week_date'):
        op.create_index('ix_game_slots_week_date', 'game_slots', ['week_id', 'slot_date'])
    op.execute(
        """
        UPDATE game_slots
        SET week_id = weeks.id
        FROM field_instances
        JOIN hosting_availabilities ON hosting_availabilities.id = field_instances.hosting_availability_id
        JOIN weeks ON weeks.id = hosting_availabilities.week_id
        WHERE game_slots.field_instance_id = field_instances.id
          AND game_slots.week_id IS NULL
          AND game_slots.slot_date = weeks.primary_game_date
        """
    ) if bind.dialect.name == 'postgresql' else None


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_index(inspector, 'game_slots', 'ix_game_slots_week_date'):
        op.drop_index('ix_game_slots_week_date', table_name='game_slots')
    inspector = sa.inspect(bind)
    if bind.dialect.name != 'sqlite' and _has_fk(inspector, 'game_slots', 'fk_game_slots_week_id_weeks'):
        op.drop_constraint('fk_game_slots_week_id_weeks', 'game_slots', type_='foreignkey')
    inspector = sa.inspect(bind)
    if _has_column(inspector, 'game_slots', 'week_id'):
        op.drop_column('game_slots', 'week_id')
