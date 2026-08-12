"""add generic supported field layouts and preserve existing field ids

Revision ID: 20260812_0062
Revises: 20260809_0061
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260812_0062'
down_revision = '20260809_0061'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('host_location_configurations', sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'))
    op.create_table(
        'field_configuration_members',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('field_configuration_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('host_location_configurations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('field_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('fields.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('field_configuration_id', 'field_id', name='uq_field_configuration_member'),
    )
    bind = op.get_bind()
    # Existing facilities retain the old "all active fields" behavior.
    bind.execute(sa.text("""
      INSERT INTO host_location_configurations
        (id, host_location_id, configuration_name, surface_type, space_used_yards, remaining_yards,
         large_field_count, medium_field_count, small_field_count, is_active, sort_order)
      SELECT gen_random_uuid(), h.id, 'Default Layout', COALESCE(h.surface_type,'GRASS_FIELD'), 0, 0,
             COUNT(f.id) FILTER (WHERE UPPER(f.layout_type)='LARGE'),
             COUNT(f.id) FILTER (WHERE UPPER(f.layout_type)='MEDIUM'),
             COUNT(f.id) FILTER (WHERE UPPER(f.layout_type)='SMALL'), TRUE, 0
      FROM host_locations h JOIN fields f ON f.host_location_id=h.id AND f.is_active=TRUE AND f.deleted_at IS NULL
      WHERE NOT EXISTS (SELECT 1 FROM host_location_configurations c WHERE c.host_location_id=h.id)
      GROUP BY h.id
    """))
    bind.execute(sa.text("""
      INSERT INTO field_configuration_members (id, field_configuration_id, field_id)
      SELECT gen_random_uuid(), c.id, f.id FROM host_location_configurations c
      JOIN fields f ON f.host_location_id=c.host_location_id AND f.is_active=TRUE AND f.deleted_at IS NULL
      WHERE c.configuration_name='Default Layout'
      ON CONFLICT DO NOTHING
    """))
    # Tim Osmond is data, not scheduler logic: replace its default membership with approved alternatives.
    hosts = bind.execute(sa.text("""SELECT h.id FROM host_locations h JOIN organizations o ON o.id=h.organization_id
      WHERE UPPER(TRIM(h.name))='TIM OSMOND SPORTS COMPLEX' AND UPPER(TRIM(o.name)) IN ('ANTIOCH','ANTIOCH VIKINGS')""")).scalars()
    layouts = [('4 Small', ['SMALL - 1','SMALL - 2','SMALL - 3','SMALL - 4']),
               ('2 Small + 1 Medium', ['SMALL - 1','SMALL - 2','MEDIUM - 1']),
               ('1 Large + 1 Medium', ['LARGE - 1','MEDIUM - 1'])]
    for host_id in hosts:
        bind.execute(sa.text("UPDATE host_location_configurations SET is_active=FALSE WHERE host_location_id=:h"), {'h': host_id})
        for order, (name, suffixes) in enumerate(layouts, 1):
            config_id = bind.execute(sa.text("""INSERT INTO host_location_configurations
              (id,host_location_id,configuration_name,surface_type,space_used_yards,remaining_yards,large_field_count,medium_field_count,small_field_count,is_active,sort_order)
              VALUES(gen_random_uuid(),:h,:n,'GRASS_FIELD',0,0,0,0,0,TRUE,:o)
              ON CONFLICT(host_location_id,configuration_name) DO UPDATE SET is_active=TRUE,sort_order=:o RETURNING id"""), {'h':host_id,'n':name,'o':order}).scalar_one()
            for suffix in suffixes:
                bind.execute(sa.text("""INSERT INTO field_configuration_members(id,field_configuration_id,field_id)
                  SELECT gen_random_uuid(),:c,f.id FROM fields f WHERE f.host_location_id=:h AND UPPER(f.name) LIKE '%' || :suffix
                  ON CONFLICT DO NOTHING"""), {'c':config_id,'h':host_id,'suffix':suffix})
        bind.execute(sa.text("""UPDATE host_location_configurations c SET
          small_field_count=(SELECT COUNT(*) FROM field_configuration_members m JOIN fields f ON f.id=m.field_id WHERE m.field_configuration_id=c.id AND UPPER(f.layout_type)='SMALL'),
          medium_field_count=(SELECT COUNT(*) FROM field_configuration_members m JOIN fields f ON f.id=m.field_id WHERE m.field_configuration_id=c.id AND UPPER(f.layout_type)='MEDIUM'),
          large_field_count=(SELECT COUNT(*) FROM field_configuration_members m JOIN fields f ON f.id=m.field_id WHERE m.field_configuration_id=c.id AND UPPER(f.layout_type)='LARGE')
          WHERE c.host_location_id=:h"""), {'h':host_id})


def downgrade():
    op.drop_table('field_configuration_members')
    op.drop_column('host_location_configurations', 'sort_order')
