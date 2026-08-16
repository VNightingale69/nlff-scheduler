"""replace Antioch TOSC site layouts with independent physical areas

Revision ID: 20260816_0068
Revises: 20260814_0067
"""
from alembic import op
import sqlalchemy as sa

revision = '20260816_0068'
down_revision = '20260814_0067'
branch_labels = None
depends_on = None
AREAS = {
    'Football Field 1': [('1 Large + 1 Small', 1, 0, 1), ('2 Medium', 0, 2, 0), ('3 Small', 0, 0, 3)],
    'Football Field 2': [('1 Large + 1 Small', 1, 0, 1), ('2 Medium', 0, 2, 0), ('3 Small', 0, 0, 3)],
    'Soccer Field': [('1 Large + 1 Small', 1, 0, 1), ('2 Medium', 0, 2, 0), ('3 Small', 0, 0, 3),
                     ('1 Medium + 1 Small', 0, 1, 1), ('1 Large', 1, 0, 0)],
}


def upgrade():
    bind = op.get_bind()
    hosts = bind.execute(sa.text("""SELECT h.id FROM host_locations h JOIN organizations o ON o.id=h.organization_id
      WHERE UPPER(TRIM(h.name)) IN ('TIM OSMOND SPORTS COMPLEX','ANTIOCH - TIM OSMOND SPORTS COMPLEX','ANTIOCH - TOSC')
        AND UPPER(TRIM(o.name)) IN ('ANTIOCH','ANTIOCH VIKINGS')""")).scalars().all()
    for host_id in hosts:
        # Preserve referenced rows for historical schedules while excluding them
        # from all active supported-layout queries.
        bind.execute(sa.text("""UPDATE host_location_configurations SET is_active=FALSE, is_legacy=TRUE,
          updated_at=now() WHERE host_location_id=:host"""), {'host': host_id})
        bind.execute(sa.text("UPDATE host_locations SET surface_type='GRASS_FIELD', updated_at=now() WHERE id=:host"), {'host': host_id})
        for area_name, layouts in AREAS.items():
            notes = 'Approximately 120 yards × 75 yards' if area_name == 'Soccer Field' else 'Regulation football field'
            area_id = bind.execute(sa.text("""INSERT INTO physical_field_areas
              (id,host_location_id,name,field_space_type,supports_dynamic_configuration,notes,is_active,created_at,updated_at)
              VALUES(gen_random_uuid(),:host,:name,'FULL_SIZE_FIELD',TRUE,:notes,TRUE,now(),now())
              ON CONFLICT(host_location_id,name) DO UPDATE SET supports_dynamic_configuration=TRUE,notes=:notes,is_active=TRUE,updated_at=now()
              RETURNING id"""), {'host': host_id, 'name': area_name, 'notes': notes}).scalar_one()
            names = [layout[0] for layout in layouts]
            bind.execute(sa.text("""UPDATE field_configuration_options SET is_active=FALSE,updated_at=now()
              WHERE physical_field_area_id=:area AND name NOT IN :names""").bindparams(sa.bindparam('names', expanding=True)), {'area': area_id, 'names': names})
            for name, large, medium, small in layouts:
                bind.execute(sa.text("""INSERT INTO field_configuration_options
                  (id,physical_field_area_id,name,configuration_name,surface_type,space_used_yards,remaining_yards,
                   large_field_count,medium_field_count,small_field_count,thirty_yard_capacity,fifty_three_yard_capacity,is_active,created_at,updated_at)
                  VALUES(gen_random_uuid(),:area,:name,:name,'GRASS_FIELD',0,0,:large,:medium,:small,:small,:large,TRUE,now(),now())
                  ON CONFLICT(physical_field_area_id,name) DO UPDATE SET configuration_name=:name,surface_type='GRASS_FIELD',
                   large_field_count=:large,medium_field_count=:medium,small_field_count=:small,
                   thirty_yard_capacity=:small,fifty_three_yard_capacity=:large,is_active=TRUE,updated_at=now()"""),
                  {'area': area_id, 'name': name, 'large': large, 'medium': medium, 'small': small})


def downgrade():
    # Historical site layouts cannot be safely guessed/reactivated.
    pass
