"""Cleanup unapproved turf configuration values

Revision ID: 20260604_0027
Revises: 20260531_0026
Create Date: 2026-06-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '20260604_0027'
down_revision = '20260531_0026'
branch_labels = None
depends_on = None

APPROVED_CODES = ('THREE_SMALL', 'TWO_SMALL_ONE_MEDIUM', 'TWO_MEDIUM', 'ONE_SMALL_ONE_LARGE')


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    return {column['name'] for column in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)

    if 'host_location_configurations' in tables:
        cols = _columns(bind, 'host_location_configurations')
        if {'configuration_name', 'is_active'}.issubset(cols):
            op.execute(
                sa.text(
                    "UPDATE host_location_configurations "
                    "SET is_active = FALSE "
                    "WHERE UPPER(REPLACE(REPLACE(configuration_name, '-', '_'), ' ', '_')) NOT IN ('THREE_SMALL', 'TWO_SMALL_ONE_MEDIUM', 'TWO_MEDIUM', 'ONE_SMALL_ONE_LARGE')"
                )
            )

    if 'hosting_availabilities' in tables and 'host_location_configurations' in tables:
        availability_cols = _columns(bind, 'hosting_availabilities')
        if {'selected_configuration_id', 'auto_select_turf_layout', 'lock_selected_layout'}.issubset(availability_cols):
            op.execute(
                sa.text(
                    "UPDATE hosting_availabilities "
                    "SET selected_configuration_id = NULL, auto_select_turf_layout = TRUE, lock_selected_layout = FALSE "
                    "WHERE selected_configuration_id IN ("
                    "SELECT id FROM host_location_configurations "
                    "WHERE UPPER(REPLACE(REPLACE(configuration_name, '-', '_'), ' ', '_')) NOT IN ('THREE_SMALL', 'TWO_SMALL_ONE_MEDIUM', 'TWO_MEDIUM', 'ONE_SMALL_ONE_LARGE'))"
                )
            )

    if 'turf_waves' in tables:
        cols = _columns(bind, 'turf_waves')
        if {'preferred_layout_code'}.issubset(cols):
            op.execute(
                sa.text(
                    "UPDATE turf_waves "
                    "SET preferred_layout_code = 'INVALID_REQUIRES_REGENERATION' "
                    "WHERE UPPER(REPLACE(REPLACE(preferred_layout_code, '-', '_'), ' ', '_')) NOT IN ('THREE_SMALL', 'TWO_SMALL_ONE_MEDIUM', 'TWO_MEDIUM', 'ONE_SMALL_ONE_LARGE')"
                )
            )

    if 'field_configuration_options' in tables:
        cols = _columns(bind, 'field_configuration_options')
        if {'surface_type', 'configuration_name', 'is_active'}.issubset(cols):
            op.execute(
                sa.text(
                    "UPDATE field_configuration_options "
                    "SET is_active = FALSE "
                    "WHERE surface_type = 'TURF_STADIUM' "
                    "AND UPPER(REPLACE(REPLACE(configuration_name, '-', '_'), ' ', '_')) NOT IN ('THREE_SMALL', 'TWO_SMALL_ONE_MEDIUM', 'TWO_MEDIUM', 'ONE_SMALL_ONE_LARGE')"
                )
            )


def downgrade() -> None:
    pass
