"""replace Johnsburg facility layouts with their physical field configurations

Revision ID: 20260808_0056
Revises: 20260808_0055
"""
from alembic import op
import sqlalchemy as sa

revision = '20260808_0056'
down_revision = '20260808_0055'
branch_labels = None
depends_on = None


FACILITIES = {
    'JOHNSBURG STADIUM': ('ONE_LARGE_ONE_MEDIUM', 1, 1, 0, 2),
    'HILLER PARK': ('FOUR_SMALL', 0, 0, 4, 4),
    'HILLER STADIUM': ('TWO_MEDIUM', 0, 2, 0, 2),
}


def upgrade():
    bind = op.get_bind()
    hosts = bind.execute(sa.text(
        "SELECT h.id, UPPER(TRIM(h.name)) AS location_name "
        "FROM host_locations h JOIN organizations o ON o.id = h.organization_id "
        "WHERE UPPER(TRIM(o.name)) IN ('JOHNSBURG', 'JOHNSBURG SKYHAWKS') "
        "AND UPPER(TRIM(h.name)) IN ('JOHNSBURG STADIUM', 'HILLER PARK', 'HILLER STADIUM')"
    )).all()

    for host_id, location_name in hosts:
        code, large, medium, small, total = FACILITIES[location_name]
        bind.execute(sa.text(
            "UPDATE host_locations SET surface_type='TURF_STADIUM', max_large_fields=:large, "
            "max_medium_fields=:medium, max_small_fields=:small, max_total_fields=:total WHERE id=:host_id"
        ), {'host_id': host_id, 'large': large, 'medium': medium, 'small': small, 'total': total})

        rows = bind.execute(sa.text(
            "SELECT id, configuration_name FROM host_location_configurations "
            "WHERE host_location_id=:host_id ORDER BY created_at, id"
        ), {'host_id': host_id}).all()
        matching = [
            row_id for row_id, name in rows
            if str(name or '').strip().upper().replace('-', '_').replace(' ', '_') == code
        ]
        exact = [row_id for row_id, name in rows if str(name or '').strip().upper() == code]
        canonical_id = exact[0] if exact else (matching[0] if matching else None)

        # Keep child rows for historical references, but only the one current
        # physical layout remains active. Existing host/date/game rows survive.
        bind.execute(sa.text(
            "UPDATE host_location_configurations SET is_active=FALSE WHERE host_location_id=:host_id"
        ), {'host_id': host_id})
        if canonical_id is None:
            canonical_id = bind.execute(sa.text(
                "INSERT INTO host_location_configurations "
                "(id, host_location_id, configuration_name, surface_type, space_used_yards, remaining_yards, "
                "large_field_count, medium_field_count, small_field_count, is_active) "
                "VALUES (gen_random_uuid(), :host_id, :code, 'TURF_STADIUM', 120, 0, :large, :medium, :small, TRUE) "
                "RETURNING id"
            ), {'host_id': host_id, 'code': code, 'large': large, 'medium': medium, 'small': small}).scalar_one()
        else:
            bind.execute(sa.text(
                "UPDATE host_location_configurations SET configuration_name=:code, surface_type='TURF_STADIUM', "
                "space_used_yards=120, remaining_yards=0, large_field_count=:large, medium_field_count=:medium, "
                "small_field_count=:small, is_active=TRUE WHERE id=:id"
            ), {'id': canonical_id, 'code': code, 'large': large, 'medium': medium, 'small': small})

        bind.execute(sa.text(
            "UPDATE hosting_availabilities SET selected_configuration_id=NULL, auto_select_turf_layout=TRUE, "
            "lock_selected_layout=FALSE WHERE host_location_id=:host_id AND selected_configuration_id IS NOT NULL "
            "AND selected_configuration_id<>:canonical_id"
        ), {'host_id': host_id, 'canonical_id': canonical_id})


def downgrade():
    # Previous layouts cannot be reconstructed safely without inventing data.
    pass
