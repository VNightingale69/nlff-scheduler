"""remove obsolete flat TOSC fields from active configuration

Revision ID: 20260816_0069
Revises: 20260816_0068

The field rows are retained only as soft-deleted FK tombstones.  Games are
detached after their display name is copied to previous_field_name, so active
configuration can never rediscover the obsolete identifiers.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260816_0069'
down_revision = '20260816_0068'
branch_labels = None
depends_on = None

LEGACY_NAMES = (
    'ANTIOCH TOSC LARGE - 1', 'ANTIOCH TOSC MEDIUM - 1',
    'ANTIOCH TOSC SMALL - 1', 'ANTIOCH TOSC SMALL - 2',
    'ANTIOCH TOSC SMALL - 3', 'ANTIOCH TOSC SMALL - 4',
)

REQUIRED_TABLE_COLUMNS = {
    'organizations': {'id', 'name'},
    'host_locations': {'id', 'organization_id', 'name'},
    'physical_field_areas': {'id', 'host_location_id', 'name', 'is_active'},
    'field_configuration_options': {'physical_field_area_id', 'is_active'},
    'fields': {'id', 'host_location_id', 'name', 'is_active', 'deleted_at'},
    'field_configuration_members': {'field_configuration_id', 'field_id'},
    'host_location_configurations': {'id', 'is_active', 'is_legacy'},
    'games': {'field_id', 'previous_field_id', 'previous_field_name'},
    # This plural table is the current HostingAvailability ORM source of truth.
    'hosting_availabilities': {'field_id', 'active', 'is_available'},
    'field_instances': {'id', 'host_location_id', 'field_name', 'is_active'},
    'game_slots': {'field_instance_id', 'assigned_game_id'},
}


def _validate_current_schema(inspector):
    """Fail loudly for drift in required current tables, not optional legacy data."""
    existing_tables = set(inspector.get_table_names())
    missing_tables = sorted(set(REQUIRED_TABLE_COLUMNS) - existing_tables)
    if missing_tables:
        raise RuntimeError(
            'TOSC field repair requires current-schema table(s): '
            + ', '.join(missing_tables)
        )
    for table, required_columns in REQUIRED_TABLE_COLUMNS.items():
        columns = {column['name'] for column in inspector.get_columns(table)}
        missing_columns = sorted(required_columns - columns)
        if missing_columns:
            raise RuntimeError(
                f'TOSC field repair requires {table} column(s): '
                + ', '.join(missing_columns)
            )
    return existing_tables


def _deactivate_availability_rows(bind, inspector, table_name, field_ids):
    """Deactivate field availability only when the named schema is compatible."""
    columns = {column['name'] for column in inspector.get_columns(table_name)}
    required = {'field_id', 'active', 'is_available'}
    if not required.issubset(columns):
        # hosting_availability is an optional pre-Alembic legacy table.  A table
        # with that name but another shape is not safe to guess or mutate.
        return
    updated_at = ',updated_at=now()' if 'updated_at' in columns else ''
    ids = sa.bindparam('availability_field_ids', expanding=True)
    bind.execute(sa.text(f"""UPDATE {table_name}
      SET active=FALSE,is_available=FALSE{updated_at}
      WHERE field_id IN :availability_field_ids""").bindparams(ids),
      {'availability_field_ids': field_ids})


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = _validate_current_schema(inspector)
    legacy = sa.bindparam('legacy_names', expanding=True)
    hosts = bind.execute(sa.text("""SELECT h.id FROM host_locations h JOIN organizations o ON o.id=h.organization_id
      WHERE UPPER(TRIM(h.name)) IN ('TIM OSMOND SPORTS COMPLEX','ANTIOCH - TIM OSMOND SPORTS COMPLEX','ANTIOCH - TOSC')
        AND UPPER(TRIM(o.name)) IN ('ANTIOCH','ANTIOCH VIKINGS')""")).scalars().all()
    for host_id in hosts:
        canonical_areas = sa.bindparam('canonical_areas', expanding=True)
        bind.execute(sa.text("""UPDATE field_configuration_options SET is_active=FALSE,updated_at=now()
          WHERE physical_field_area_id IN (SELECT id FROM physical_field_areas
            WHERE host_location_id=:host AND name NOT IN :canonical_areas)""").bindparams(canonical_areas),
          {'host': host_id, 'canonical_areas': ('Football Field 1', 'Football Field 2', 'Soccer Field')})
        bind.execute(sa.text("""UPDATE physical_field_areas SET is_active=FALSE,updated_at=now()
          WHERE host_location_id=:host AND name NOT IN :canonical_areas""").bindparams(canonical_areas),
          {'host': host_id, 'canonical_areas': ('Football Field 1', 'Football Field 2', 'Soccer Field')})
        field_ids = bind.execute(sa.text("""SELECT id FROM fields WHERE host_location_id=:host
          AND UPPER(TRIM(name)) IN :legacy_names""").bindparams(legacy),
          {'host': host_id, 'legacy_names': LEGACY_NAMES}).scalars().all()
        if not field_ids:
            continue
        ids = sa.bindparam('ids', expanding=True)
        # Remove site-wide layouts/memberships that made mutually exclusive
        # generated slots look like simultaneous physical resources.
        config_ids = bind.execute(sa.text("""SELECT DISTINCT field_configuration_id FROM field_configuration_members
          WHERE field_id IN :ids""").bindparams(ids), {'ids': field_ids}).scalars().all()
        bind.execute(sa.text("DELETE FROM field_configuration_members WHERE field_id IN :ids").bindparams(ids), {'ids': field_ids})
        if config_ids:
            cfgs = sa.bindparam('cfgs', expanding=True)
            bind.execute(sa.text("""UPDATE host_location_configurations SET is_active=FALSE,is_legacy=TRUE,updated_at=now()
              WHERE id IN :cfgs""").bindparams(cfgs), {'cfgs': config_ids})
        # Preserve historical presentation independently of the active Field.
        bind.execute(sa.text("""UPDATE games g SET previous_field_id=COALESCE(g.previous_field_id,g.field_id),
          previous_field_name=COALESCE(g.previous_field_name,f.name), field_id=NULL
          FROM fields f WHERE g.field_id=f.id AND f.id IN :ids""").bindparams(ids), {'ids': field_ids})
        _deactivate_availability_rows(
            bind, inspector, 'hosting_availabilities', field_ids
        )
        # Some pre-Alembic installations had a singular legacy table.  It is
        # not part of the application model and must never be assumed to exist.
        if 'hosting_availability' in existing_tables:
            _deactivate_availability_rows(
                bind, inspector, 'hosting_availability', field_ids
            )
        bind.execute(sa.text("""UPDATE field_instances SET is_active=FALSE,updated_at=now()
          WHERE host_location_id=:host AND field_name IN (SELECT name FROM fields WHERE id IN :ids)""").bindparams(ids),
          {'host': host_id, 'ids': field_ids})
        bind.execute(sa.text("""DELETE FROM game_slots WHERE assigned_game_id IS NULL AND field_instance_id IN
          (SELECT id FROM field_instances WHERE host_location_id=:host
            AND field_name IN (SELECT name FROM fields WHERE id IN :ids))""").bindparams(ids),
          {'host': host_id, 'ids': field_ids})
        bind.execute(sa.text("""UPDATE fields SET is_active=FALSE,deleted_at=COALESCE(deleted_at,now()),updated_at=now()
          WHERE id IN :ids""").bindparams(ids), {'ids': field_ids})


def downgrade():
    # Deliberately irreversible: reviving generated slots as physical fields
    # would reintroduce invalid scheduling capacity.
    pass
