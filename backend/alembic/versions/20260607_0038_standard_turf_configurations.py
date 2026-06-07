"""standard turf configuration rule set

Revision ID: 20260607_0038
Revises: 20260607_0037
Create Date: 2026-06-07
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa

revision = '20260607_0038'
down_revision = '20260607_0037'
branch_labels = None
depends_on = None

APPROVED_CONFIGS = {
    'THREE_SMALL': (100, 20, 0, 0, 3),
    'TWO_SMALL_ONE_MEDIUM': (120, 0, 0, 1, 2),
    'TWO_MEDIUM': (110, 10, 0, 2, 0),
    'ONE_SMALL_ONE_LARGE': (90, 30, 1, 0, 1),
    'ONE_LARGE': (70, 50, 1, 0, 0),
}
APPROVED_NAMES_SQL = "'THREE_SMALL', 'TWO_SMALL_ONE_MEDIUM', 'TWO_MEDIUM', 'ONE_SMALL_ONE_LARGE', 'ONE_LARGE'"


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
            op.execute(sa.text(
                'UPDATE host_location_configurations SET is_active = FALSE '
                f"WHERE UPPER(REPLACE(REPLACE(configuration_name, '-', '_'), ' ', '_')) NOT IN ({APPROVED_NAMES_SQL})"
            ))
        if {'host_location_id', 'configuration_name', 'is_active'}.issubset(cols) and 'host_locations' in tables:
            host_cols = _columns(bind, 'host_locations')
            if {'id', 'surface_type', 'is_active'}.issubset(host_cols):
                turf_host_ids = [row[0] for row in bind.execute(sa.text(
                    "SELECT id FROM host_locations WHERE is_active = TRUE AND surface_type = 'TURF_STADIUM'"
                )).all()]
                existing_pairs = {
                    (str(row[0]), row[1]) for row in bind.execute(sa.text(
                        "SELECT host_location_id, configuration_name FROM host_location_configurations"
                    )).all()
                }
                for name, (used, remaining, large, medium, small) in APPROVED_CONFIGS.items():
                    for host_id in turf_host_ids:
                        if (str(host_id), name) not in existing_pairs:
                            op.execute(sa.text(
                                "INSERT INTO host_location_configurations "
                                "(id, host_location_id, configuration_name, surface_type, space_used_yards, remaining_yards, large_field_count, medium_field_count, small_field_count, is_active) "
                                "VALUES (:id, :host_id, :name, 'TURF_STADIUM', :used, :remaining, :large, :medium, :small, TRUE)"
                            ).bindparams(id=str(uuid.uuid4()), host_id=host_id, name=name, used=used, remaining=remaining, large=large, medium=medium, small=small))
                            existing_pairs.add((str(host_id), name))
                    op.execute(sa.text(
                        "UPDATE host_location_configurations SET surface_type = 'TURF_STADIUM', "
                        "space_used_yards = :used, remaining_yards = :remaining, large_field_count = :large, "
                        "medium_field_count = :medium, small_field_count = :small, is_active = TRUE "
                        "WHERE configuration_name = :name"
                    ).bindparams(name=name, used=used, remaining=remaining, large=large, medium=medium, small=small))

    if 'hosting_availabilities' in tables and 'host_location_configurations' in tables:
        availability_cols = _columns(bind, 'hosting_availabilities')
        if {'selected_configuration_id', 'auto_select_turf_layout', 'lock_selected_layout'}.issubset(availability_cols):
            op.execute(sa.text(
                "UPDATE hosting_availabilities "
                "SET selected_configuration_id = NULL, auto_select_turf_layout = TRUE, lock_selected_layout = FALSE "
                "WHERE selected_configuration_id IN ("
                "SELECT id FROM host_location_configurations "
                f"WHERE UPPER(REPLACE(REPLACE(configuration_name, '-', '_'), ' ', '_')) NOT IN ({APPROVED_NAMES_SQL}))"
            ))

    if 'turf_waves' in tables and 'preferred_layout_code' in _columns(bind, 'turf_waves'):
        op.execute(sa.text(
            "UPDATE turf_waves SET preferred_layout_code = 'INVALID_REQUIRES_REGENERATION' "
            f"WHERE UPPER(REPLACE(REPLACE(preferred_layout_code, '-', '_'), ' ', '_')) NOT IN ({APPROVED_NAMES_SQL})"
        ))


def downgrade() -> None:
    pass
