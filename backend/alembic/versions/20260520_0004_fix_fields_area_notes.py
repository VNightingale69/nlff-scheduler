"""ensure fields physical area and notes columns exist

Revision ID: 20260520_0004
Revises: 20260520_0003
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '20260520_0004'
down_revision = '20260520_0003'
branch_labels = None
depends_on = None

_FIELDS_TABLE = 'fields'
_PHYSICAL_AREAS_TABLE = 'physical_field_areas'
_FIELDS_AREA_COLUMN = 'physical_field_area_id'
_FIELDS_NOTES_COLUMN = 'notes'
_FIELDS_AREA_FK = 'fk_fields_physical_field_area_id'


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {column['name'] for column in inspector.get_columns(table_name)}


def _has_fk(inspector: sa.Inspector, table_name: str, constrained_columns: list[str], referred_table: str) -> bool:
    for fk in inspector.get_foreign_keys(table_name):
        if fk.get('referred_table') == referred_table and fk.get('constrained_columns') == constrained_columns:
            return True
    return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _FIELDS_TABLE):
        return

    existing_columns = _column_names(inspector, _FIELDS_TABLE)

    if _FIELDS_AREA_COLUMN not in existing_columns:
        op.add_column(_FIELDS_TABLE, sa.Column(_FIELDS_AREA_COLUMN, postgresql.UUID(as_uuid=True), nullable=True))

    if _FIELDS_NOTES_COLUMN not in existing_columns:
        op.add_column(_FIELDS_TABLE, sa.Column(_FIELDS_NOTES_COLUMN, sa.Text(), nullable=True))

    inspector = sa.inspect(bind)
    if _has_table(inspector, _PHYSICAL_AREAS_TABLE) and not _has_fk(
        inspector,
        _FIELDS_TABLE,
        [_FIELDS_AREA_COLUMN],
        _PHYSICAL_AREAS_TABLE,
    ):
        op.create_foreign_key(
            _FIELDS_AREA_FK,
            _FIELDS_TABLE,
            _PHYSICAL_AREAS_TABLE,
            [_FIELDS_AREA_COLUMN],
            ['id'],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _FIELDS_TABLE):
        return

    fk_names = {
        fk.get('name')
        for fk in inspector.get_foreign_keys(_FIELDS_TABLE)
        if fk.get('referred_table') == _PHYSICAL_AREAS_TABLE and fk.get('constrained_columns') == [_FIELDS_AREA_COLUMN]
    }
    for fk_name in fk_names:
        if fk_name:
            op.drop_constraint(fk_name, _FIELDS_TABLE, type_='foreignkey')

    columns = _column_names(sa.inspect(bind), _FIELDS_TABLE)
    if _FIELDS_NOTES_COLUMN in columns:
        op.drop_column(_FIELDS_TABLE, _FIELDS_NOTES_COLUMN)
    if _FIELDS_AREA_COLUMN in columns:
        op.drop_column(_FIELDS_TABLE, _FIELDS_AREA_COLUMN)
