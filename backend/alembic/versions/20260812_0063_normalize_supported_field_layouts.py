"""normalize legacy supported layouts and activate canonical alternatives

Revision ID: 20260812_0063
Revises: 20260812_0062
"""
from alembic import op
import sqlalchemy as sa


revision = '20260812_0063'
down_revision = '20260812_0062'
branch_labels = None
depends_on = None


ALIASES = {
    'FOUR_SMALL': ('4 Small', ('SMALL - 1', 'SMALL - 2', 'SMALL - 3', 'SMALL - 4')),
    'TWO_SMALL_ONE_MEDIUM': ('2 Small + 1 Medium', ('SMALL - 1', 'SMALL - 2', 'MEDIUM - 1')),
    'ONE_LARGE_ONE_SMALL': ('1 Large + 1 Small', ('LARGE - 1', 'SMALL - 1')),
}


def _configuration(bind, host_id, name):
    return bind.execute(sa.text("""SELECT id FROM host_location_configurations
      WHERE host_location_id=:host AND configuration_name=:name"""), {'host': host_id, 'name': name}).scalar()


def _assign_current_fields(bind, config_id, host_id, suffixes):
    bind.execute(sa.text('DELETE FROM field_configuration_members WHERE field_configuration_id=:config'), {'config': config_id})
    for suffix in suffixes:
        bind.execute(sa.text("""INSERT INTO field_configuration_members(id, field_configuration_id, field_id)
          SELECT gen_random_uuid(), :config, f.id FROM fields f
          WHERE f.host_location_id=:host AND f.deleted_at IS NULL AND UPPER(TRIM(f.name)) LIKE '%' || :suffix
          ORDER BY f.created_at DESC LIMIT 1"""), {'config': config_id, 'host': host_id, 'suffix': suffix})


def upgrade():
    op.add_column('host_location_configurations', sa.Column('is_legacy', sa.Boolean(), nullable=False, server_default=sa.false()))
    bind = op.get_bind()
    hosts = bind.execute(sa.text("""SELECT DISTINCT host_location_id FROM host_location_configurations
      WHERE configuration_name IN ('FOUR_SMALL','TWO_SMALL_ONE_MEDIUM','ONE_LARGE_ONE_SMALL')""")).scalars().all()
    for host_id in hosts:
        for legacy_name, (friendly_name, suffixes) in ALIASES.items():
            legacy_id = _configuration(bind, host_id, legacy_name)
            canonical_id = _configuration(bind, host_id, friendly_name)
            if canonical_id is None and legacy_id is not None:
                # Preserve the legacy ID (and all historical foreign keys) when it can become canonical.
                bind.execute(sa.text("""UPDATE host_location_configurations SET configuration_name=:name,
                  is_active=TRUE, is_legacy=FALSE WHERE id=:id"""), {'name': friendly_name, 'id': legacy_id})
                canonical_id, legacy_id = legacy_id, None
            elif canonical_id is None:
                canonical_id = bind.execute(sa.text("""INSERT INTO host_location_configurations
                  (id,host_location_id,configuration_name,surface_type,space_used_yards,remaining_yards,
                   large_field_count,medium_field_count,small_field_count,is_active,is_legacy,sort_order)
                  SELECT gen_random_uuid(),:host,:name,COALESCE(surface_type,'GRASS_FIELD'),0,0,0,0,0,TRUE,FALSE,0
                  FROM host_locations WHERE id=:host RETURNING id"""), {'host': host_id, 'name': friendly_name}).scalar_one()
            bind.execute(sa.text("""UPDATE host_location_configurations SET is_active=TRUE,is_legacy=FALSE
              WHERE id=:id"""), {'id': canonical_id})
            _assign_current_fields(bind, canonical_id, host_id, suffixes)
            if legacy_id and legacy_id != canonical_id:
                bind.execute(sa.text("""UPDATE host_location_configurations SET is_active=FALSE,is_legacy=TRUE
                  WHERE id=:id"""), {'id': legacy_id})
        bind.execute(sa.text("""UPDATE host_location_configurations c SET
          small_field_count=(SELECT COUNT(*) FROM field_configuration_members m JOIN fields f ON f.id=m.field_id WHERE m.field_configuration_id=c.id AND UPPER(f.layout_type)='SMALL'),
          medium_field_count=(SELECT COUNT(*) FROM field_configuration_members m JOIN fields f ON f.id=m.field_id WHERE m.field_configuration_id=c.id AND UPPER(f.layout_type)='MEDIUM'),
          large_field_count=(SELECT COUNT(*) FROM field_configuration_members m JOIN fields f ON f.id=m.field_id WHERE m.field_configuration_id=c.id AND UPPER(f.layout_type)='LARGE')
          WHERE c.host_location_id=:host"""), {'host': host_id})


def downgrade():
    op.drop_column('host_location_configurations', 'is_legacy')
