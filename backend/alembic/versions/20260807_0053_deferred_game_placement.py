"""replace placeholder TBD inventory with deferred game placement

Revision ID: 20260807_0053
Revises: 20260729_0052
"""
from alembic import op
import sqlalchemy as sa

revision = '20260807_0053'
down_revision = '20260729_0052'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('weeks', sa.Column('host_assignment_pending', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('games', sa.Column('placement_status', sa.String(length=20), nullable=False, server_default='PLACED'))
    op.alter_column('games', 'kickoff_time', existing_type=sa.Time(), nullable=True)

    # Convert historical references before removing placeholder configuration. Team,
    # season, week, date and matchup columns are intentionally untouched.
    op.execute("""
        UPDATE games g SET
            host_location_id = NULL, field_id = NULL, field_instance_id = NULL,
            kickoff_time = NULL, placement_status = 'TBD'
        WHERE g.host_location_id IN (
            SELECT hl.id FROM host_locations hl JOIN organizations o ON o.id = hl.organization_id
            WHERE upper(trim(hl.name)) = 'TBD' OR upper(trim(o.name)) = 'TBD'
        ) OR g.field_id IN (
            SELECT f.id FROM fields f JOIN host_locations hl ON hl.id = f.host_location_id
            JOIN organizations o ON o.id = hl.organization_id
            WHERE upper(trim(f.name)) = 'TBD' OR upper(trim(hl.name)) = 'TBD' OR upper(trim(o.name)) = 'TBD'
        ) OR g.field_instance_id IN (
            SELECT fi.id FROM field_instances fi JOIN host_locations hl ON hl.id = fi.host_location_id
            JOIN organizations o ON o.id = hl.organization_id
            WHERE upper(trim(fi.field_name)) = 'TBD' OR upper(trim(hl.name)) = 'TBD' OR upper(trim(o.name)) = 'TBD'
        )
    """)
    op.execute("""
        UPDATE weeks w SET host_assignment_pending = true
        WHERE EXISTS (SELECT 1 FROM games g WHERE g.week_id = w.id AND g.placement_status = 'TBD')
    """)
    op.execute("""UPDATE tournament_games tg SET host_location_id=NULL, field_id=NULL
        WHERE host_location_id IN (SELECT hl.id FROM host_locations hl JOIN organizations o ON o.id=hl.organization_id WHERE upper(trim(hl.name))='TBD' OR upper(trim(o.name))='TBD')
        OR field_id IN (SELECT f.id FROM fields f JOIN host_locations hl ON hl.id=f.host_location_id JOIN organizations o ON o.id=hl.organization_id WHERE upper(trim(f.name))='TBD' OR upper(trim(hl.name))='TBD' OR upper(trim(o.name))='TBD')""")

    fake_hosts = "SELECT hl.id FROM host_locations hl JOIN organizations o ON o.id=hl.organization_id WHERE upper(trim(hl.name))='TBD' OR upper(trim(o.name))='TBD'"
    op.execute(f"DELETE FROM game_slots WHERE host_location_id IN ({fake_hosts})")
    op.execute(f"DELETE FROM turf_waves WHERE host_location_id IN ({fake_hosts})")
    op.execute(f"DELETE FROM field_instances WHERE host_location_id IN ({fake_hosts})")
    op.execute(f"DELETE FROM host_plan_selections WHERE host_location_id IN ({fake_hosts})")
    op.execute(f"DELETE FROM hosting_availabilities WHERE host_location_id IN ({fake_hosts})")
    op.execute("DELETE FROM field_configuration_options WHERE physical_field_area_id IN (SELECT p.id FROM physical_field_areas p WHERE p.host_location_id IN (" + fake_hosts + "))")
    op.execute(f"DELETE FROM fields WHERE host_location_id IN ({fake_hosts}) OR upper(trim(name))='TBD'")
    op.execute(f"DELETE FROM physical_field_areas WHERE host_location_id IN ({fake_hosts})")
    op.execute(f"DELETE FROM host_location_configurations WHERE host_location_id IN ({fake_hosts})")
    op.execute(f"DELETE FROM host_locations WHERE id IN ({fake_hosts})")
    # A placeholder organization is removed only after all fake inventory is gone.
    # It should never own teams/users; preserving those relationships is preferable
    # to deleting legitimate historical data if a mislabeled real org exists.
    op.execute("""DELETE FROM organizations o WHERE upper(trim(o.name))='TBD'
        AND NOT EXISTS (SELECT 1 FROM teams t WHERE t.organization_id=o.id)
        AND NOT EXISTS (SELECT 1 FROM users u WHERE u.organization_id=o.id)""")


def downgrade():
    # Fake inventory is deliberately not recreated; downgrade only restores schema.
    op.alter_column('games', 'kickoff_time', existing_type=sa.Time(), nullable=False)
    op.drop_column('games', 'placement_status')
    op.drop_column('weeks', 'host_assignment_pending')
