"""limit turf layouts to approved configuration codes

Revision ID: 20260604_0035
Revises: 20260603_0034
Create Date: 2026-06-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '20260604_0035'
down_revision = '20260603_0034'
branch_labels = None
depends_on = None

APPROVED_CONFIGS = {
    'THREE_SMALL': (100, 20, 0, 0, 3),
    'TWO_SMALL_ONE_MEDIUM': (120, 0, 0, 1, 2),
    'TWO_MEDIUM': (110, 10, 0, 2, 0),
    'ONE_SMALL_ONE_LARGE': (90, 30, 1, 0, 1),
}
ALIASES = {
    '3X30': 'THREE_SMALL',
    'ONE_MEDIUM_TWO_SMALL': 'TWO_SMALL_ONE_MEDIUM',
    'ONE_LARGE_ONE_SMALL': 'ONE_SMALL_ONE_LARGE',
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'host_location_configurations' not in inspector.get_table_names():
        return

    rows = bind.execute(sa.text(
        'SELECT id, host_location_id, configuration_name FROM host_location_configurations'
    )).mappings().all()
    names_by_host = {}
    for row in rows:
        names_by_host.setdefault(str(row['host_location_id']), set()).add(row['configuration_name'])

    for row in rows:
        config_name = row['configuration_name']
        approved_name = ALIASES.get(config_name)
        if not approved_name:
            continue
        if approved_name in names_by_host.get(str(row['host_location_id']), set()):
            op.execute(sa.text(
                'UPDATE host_location_configurations SET is_active = false WHERE id = :id'
            ).bindparams(id=row['id']))
        else:
            op.execute(sa.text(
                'UPDATE host_location_configurations SET configuration_name = :approved WHERE id = :id'
            ).bindparams(id=row['id'], approved=approved_name))
            names_by_host[str(row['host_location_id'])].add(approved_name)

    approved_names = tuple(APPROVED_CONFIGS.keys())
    op.execute(sa.text(
        'UPDATE host_location_configurations SET is_active = false WHERE configuration_name NOT IN :approved_names'
    ).bindparams(sa.bindparam('approved_names', expanding=True, value=approved_names)))

    for name, (used, remaining, large, medium, small) in APPROVED_CONFIGS.items():
        op.execute(sa.text(
            "UPDATE host_location_configurations SET surface_type = 'TURF_STADIUM', "
            'space_used_yards = :used, remaining_yards = :remaining, large_field_count = :large, '
            'medium_field_count = :medium, small_field_count = :small WHERE configuration_name = :name'
        ).bindparams(name=name, used=used, remaining=remaining, large=large, medium=medium, small=small))


def downgrade() -> None:
    pass
