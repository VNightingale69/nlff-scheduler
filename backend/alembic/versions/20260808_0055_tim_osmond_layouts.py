"""configure Tim Osmond Sports Complex approved physical layouts

Revision ID: 20260808_0055
Revises: 20260808_0054
"""
from alembic import op
import sqlalchemy as sa

revision = '20260808_0055'
down_revision = '20260808_0054'
branch_labels = None
depends_on = None

APPROVED = {
    'FOUR_SMALL': (0, 0, 4),
    'TWO_SMALL_ONE_MEDIUM': (0, 1, 2),
    'ONE_LARGE_ONE_MEDIUM': (1, 1, 0),
}


def upgrade():
    bind = op.get_bind()
    host_ids = [row[0] for row in bind.execute(sa.text(
        "SELECT h.id FROM host_locations h JOIN organizations o ON o.id = h.organization_id "
        "WHERE UPPER(TRIM(h.name)) = 'TIM OSMOND SPORTS COMPLEX' "
        "AND UPPER(TRIM(o.name)) IN ('ANTIOCH', 'ANTIOCH VIKINGS')"
    ))]
    for host_id in host_ids:
        # Existing availability rows remain attached to the same host; only its
        # physical-layout inventory changes from individual grass capacity.
        bind.execute(sa.text(
            "UPDATE host_locations SET surface_type='TURF_STADIUM' WHERE id=:host_id"
        ), {'host_id': host_id})
        rows = bind.execute(sa.text(
            "SELECT id, configuration_name FROM host_location_configurations WHERE host_location_id=:host_id"
        ), {'host_id': host_id}).all()
        by_code = {str(name).strip().upper().replace('-', '_').replace(' ', '_'): row_id for row_id, name in rows}
        obsolete_ids = [row_id for code, row_id in by_code.items() if code not in APPROVED]
        bind.execute(sa.text(
            "UPDATE host_location_configurations SET is_active=FALSE WHERE host_location_id=:host_id"
        ), {'host_id': host_id})
        if obsolete_ids:
            bind.execute(sa.text(
                "UPDATE hosting_availabilities SET selected_configuration_id=NULL, "
                "auto_select_turf_layout=TRUE, lock_selected_layout=FALSE "
                "WHERE host_location_id=:host_id AND selected_configuration_id IN "
                "(SELECT id FROM host_location_configurations WHERE host_location_id=:host_id AND is_active=FALSE)"
            ), {'host_id': host_id})
        for code, (large, medium, small) in APPROVED.items():
            if code in by_code:
                bind.execute(sa.text(
                    "UPDATE host_location_configurations SET surface_type='TURF_STADIUM', space_used_yards=120, "
                    "remaining_yards=0, large_field_count=:large, medium_field_count=:medium, "
                    "small_field_count=:small, is_active=TRUE WHERE id=:id"
                ), {'id': by_code[code], 'large': large, 'medium': medium, 'small': small})
            else:
                bind.execute(sa.text(
                    "INSERT INTO host_location_configurations (id, host_location_id, configuration_name, surface_type, "
                    "space_used_yards, remaining_yards, large_field_count, medium_field_count, small_field_count, is_active) "
                    "VALUES (gen_random_uuid(), :host_id, :code, 'TURF_STADIUM', 120, 0, :large, :medium, :small, TRUE)"
                ), {'host_id': host_id, 'code': code, 'large': large, 'medium': medium, 'small': small})


def downgrade():
    pass
