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


def upgrade():
    bind = op.get_bind()
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
        bind.execute(sa.text("""UPDATE hosting_availability SET active=FALSE,is_available=FALSE,updated_at=now()
          WHERE field_id IN :ids""").bindparams(ids), {'ids': field_ids})
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
