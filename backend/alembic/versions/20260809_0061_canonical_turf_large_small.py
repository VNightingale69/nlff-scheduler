"""make one Large plus one Small the canonical Turf Stadium layout

Revision ID: 20260809_0061
Revises: 20260809_0060
"""
from alembic import op
import sqlalchemy as sa

revision = '20260809_0061'
down_revision = '20260809_0060'
branch_labels = None
depends_on = None

OLD_CODE = 'ONE_LARGE_ONE_MEDIUM'
NEW_CODE = 'ONE_LARGE_ONE_SMALL'


def _normalized_code_sql(column: str) -> str:
    return f"UPPER(REPLACE(REPLACE(TRIM({column}), '-', '_'), ' ', '_'))"


def upgrade():
    bind = op.get_bind()
    turf_hosts = [row[0] for row in bind.execute(sa.text(
        "SELECT id FROM host_locations WHERE surface_type='TURF_STADIUM'"
    ))]

    for host_id in turf_hosts:
        rows = bind.execute(sa.text(
            "SELECT id, configuration_name FROM host_location_configurations "
            "WHERE host_location_id=:host_id ORDER BY created_at, id"
        ), {'host_id': host_id}).all()
        by_code = {
            str(name or '').strip().upper().replace('-', '_').replace(' ', '_'): row_id
            for row_id, name in rows
        }
        canonical_id = by_code.get(NEW_CODE)
        old_id = by_code.get(OLD_CODE)

        # Prefer converting the former canonical row in place. This preserves
        # its ID and every saved timeslot/game relationship that points at it.
        if canonical_id is None and old_id is not None:
            canonical_id = old_id
            bind.execute(sa.text(
                "UPDATE host_location_configurations SET configuration_name=:new_code "
                "WHERE id=:id"
            ), {'new_code': NEW_CODE, 'id': canonical_id})
        elif canonical_id is None:
            canonical_id = bind.execute(sa.text(
                "INSERT INTO host_location_configurations "
                "(id, host_location_id, configuration_name, surface_type, space_used_yards, remaining_yards, "
                "large_field_count, medium_field_count, small_field_count, is_active) "
                "VALUES (gen_random_uuid(), :host_id, :new_code, 'TURF_STADIUM', 90, 30, 1, 0, 1, TRUE) "
                "RETURNING id"
            ), {'host_id': host_id, 'new_code': NEW_CODE}).scalar_one()

        # If both rows already existed, retain the new row and safely repoint
        # configuration FKs before deactivating the old row.
        if old_id is not None and old_id != canonical_id:
            bind.execute(sa.text(
                "UPDATE hosting_availabilities SET selected_configuration_id=:new_id "
                "WHERE selected_configuration_id=:old_id"
            ), {'new_id': canonical_id, 'old_id': old_id})
            bind.execute(sa.text(
                "UPDATE timeslot_field_configurations SET configuration_id=:new_id "
                "WHERE configuration_id=:old_id"
            ), {'new_id': canonical_id, 'old_id': old_id})

        bind.execute(sa.text(
            "UPDATE host_location_configurations SET is_active=FALSE WHERE host_location_id=:host_id"
        ), {'host_id': host_id})
        bind.execute(sa.text(
            "UPDATE host_location_configurations SET configuration_name=:new_code, surface_type='TURF_STADIUM', "
            "space_used_yards=90, remaining_yards=30, large_field_count=1, medium_field_count=0, "
            "small_field_count=1, is_active=TRUE WHERE id=:id"
        ), {'new_code': NEW_CODE, 'id': canonical_id})
        bind.execute(sa.text(
            "UPDATE host_locations SET max_large_fields=1, max_medium_fields=0, "
            "max_small_fields=1, max_total_fields=2 WHERE id=:host_id"
        ), {'host_id': host_id})
        bind.execute(sa.text(
            "UPDATE hosting_availabilities SET selected_configuration_id=:canonical_id, "
            "auto_select_turf_layout=TRUE, lock_selected_layout=FALSE "
            "WHERE host_location_id=:host_id"
        ), {'host_id': host_id, 'canonical_id': canonical_id})

    if not turf_hosts:
        return

    # Existing assignments are retained. Games on a position whose meaning
    # changes are explicitly queued for administrator review rather than being
    # silently treated as compatible with a Small field.
    bind.execute(sa.text(
        "UPDATE games g SET needs_schedule_review=TRUE, "
        "field_assignment_status='TURF_MEDIUM_MIGRATED_REVIEW_REQUIRED', "
        "internal_admin_notes=CASE WHEN COALESCE(g.internal_admin_notes, '')='' "
        "THEN 'Turf Stadium Medium field changed to Small; verify division compatibility.' "
        "ELSE g.internal_admin_notes || E'\\nTurf Stadium Medium field changed to Small; verify division compatibility.' END "
        "FROM field_instances fi JOIN host_locations h ON h.id=fi.host_location_id "
        "WHERE g.field_instance_id=fi.id AND h.surface_type='TURF_STADIUM' AND fi.field_type='MEDIUM'"
    ))
    bind.execute(sa.text(
        "UPDATE game_slots gs SET field_type='SMALL' FROM field_instances fi "
        "JOIN host_locations h ON h.id=fi.host_location_id "
        "WHERE gs.field_instance_id=fi.id AND h.surface_type='TURF_STADIUM' AND fi.field_type='MEDIUM'"
    ))
    bind.execute(sa.text(
        "UPDATE field_instances fi SET field_type='SMALL', field_name=CASE WHEN EXISTS ("
        "SELECT 1 FROM field_instances sibling WHERE sibling.hosting_availability_id=fi.hosting_availability_id "
        "AND sibling.id<>fi.id AND LOWER(sibling.field_name)=LOWER(REGEXP_REPLACE(fi.field_name, 'Medium Field( 1)?', 'Small Field', 'i'))"
        ") THEN REGEXP_REPLACE(fi.field_name, 'Medium', 'Small (migrated)', 'i') "
        "ELSE REGEXP_REPLACE(fi.field_name, 'Medium Field( 1)?', 'Small Field', 'i') END "
        "FROM host_locations h WHERE h.id=fi.host_location_id "
        "AND h.surface_type='TURF_STADIUM' AND fi.field_type='MEDIUM'"
    ))
    bind.execute(sa.text(
        "UPDATE fields f SET layout_type='SMALL', name=CASE WHEN EXISTS ("
        "SELECT 1 FROM fields sibling WHERE sibling.host_location_id=f.host_location_id AND sibling.id<>f.id "
        "AND LOWER(sibling.name)=LOWER(REGEXP_REPLACE(f.name, 'Medium Field( 1)?', 'Small Field', 'i'))"
        ") THEN REGEXP_REPLACE(f.name, 'Medium', 'Small (migrated)', 'i') "
        "ELSE REGEXP_REPLACE(f.name, 'Medium Field( 1)?', 'Small Field', 'i') END "
        "FROM host_locations h WHERE h.id=f.host_location_id "
        "AND h.surface_type='TURF_STADIUM' AND UPPER(f.layout_type)='MEDIUM'"
    ))
    bind.execute(sa.text(
        "UPDATE turf_waves SET preferred_layout_code=:new_code WHERE "
        + _normalized_code_sql('preferred_layout_code') + "=:old_code"
    ), {'new_code': NEW_CODE, 'old_code': OLD_CODE})


def downgrade():
    # Restoring Medium semantics could make post-upgrade Small assignments
    # incompatible, so this intentionally does not rewrite schedule data.
    pass
