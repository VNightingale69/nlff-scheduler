"""repair community admin organization aliases

Revision ID: 20260531_0029
Revises: 20260531_0028
Create Date: 2026-05-31
"""

from alembic import op


revision = '20260531_0029'
down_revision = '20260531_0028'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        WITH organization_aliases(short_name, full_name) AS (
            VALUES
              ('Antioch', 'Antioch Vikings'),
              ('Johnsburg', 'Johnsburg Skyhawks'),
              ('Westosha', 'Westosha Falcons')
        )
        UPDATE organizations short_org
        SET name = oa.full_name,
            is_active = true
        FROM organization_aliases oa
        WHERE short_org.name = oa.short_name
          AND NOT EXISTS (
              SELECT 1 FROM organizations full_org WHERE full_org.name = oa.full_name
          );

        WITH organization_aliases(short_name, full_name) AS (
            VALUES
              ('Antioch', 'Antioch Vikings'),
              ('Johnsburg', 'Johnsburg Skyhawks'),
              ('Westosha', 'Westosha Falcons')
        )
        INSERT INTO organizations (id, name, is_active)
        SELECT gen_random_uuid(), oa.full_name, true
        FROM organization_aliases oa
        WHERE NOT EXISTS (SELECT 1 FROM organizations o WHERE o.name = oa.full_name)
          AND EXISTS (SELECT 1 FROM organizations o WHERE o.name = oa.short_name)
        ON CONFLICT (name) DO NOTHING;

        WITH organization_aliases(short_name, full_name) AS (
            VALUES
              ('Antioch', 'Antioch Vikings'),
              ('Johnsburg', 'Johnsburg Skyhawks'),
              ('Westosha', 'Westosha Falcons')
        ), organization_map AS (
            SELECT short_org.id AS short_id, full_org.id AS full_id
            FROM organization_aliases oa
            JOIN organizations short_org ON short_org.name = oa.short_name
            JOIN organizations full_org ON full_org.name = oa.full_name
        )
        UPDATE users u
        SET organization_id = om.full_id
        FROM organization_map om
        WHERE u.organization_id = om.short_id;

        WITH organization_aliases(short_name, full_name) AS (
            VALUES
              ('Antioch', 'Antioch Vikings'),
              ('Johnsburg', 'Johnsburg Skyhawks'),
              ('Westosha', 'Westosha Falcons')
        ), organization_map AS (
            SELECT short_org.id AS short_id, full_org.id AS full_id
            FROM organization_aliases oa
            JOIN organizations short_org ON short_org.name = oa.short_name
            JOIN organizations full_org ON full_org.name = oa.full_name
        )
        UPDATE teams t
        SET organization_id = om.full_id
        FROM organization_map om
        WHERE t.organization_id = om.short_id;

        WITH organization_aliases(short_name, full_name) AS (
            VALUES
              ('Antioch', 'Antioch Vikings'),
              ('Johnsburg', 'Johnsburg Skyhawks'),
              ('Westosha', 'Westosha Falcons')
        ), organization_map AS (
            SELECT short_org.id AS short_id, full_org.id AS full_id
            FROM organization_aliases oa
            JOIN organizations short_org ON short_org.name = oa.short_name
            JOIN organizations full_org ON full_org.name = oa.full_name
        )
        DELETE FROM organization_division_participations odp
        USING organization_map om
        WHERE odp.organization_id = om.short_id
          AND EXISTS (
              SELECT 1
              FROM organization_division_participations target_odp
              WHERE target_odp.organization_id = om.full_id
                AND target_odp.division_id = odp.division_id
          );

        WITH organization_aliases(short_name, full_name) AS (
            VALUES
              ('Antioch', 'Antioch Vikings'),
              ('Johnsburg', 'Johnsburg Skyhawks'),
              ('Westosha', 'Westosha Falcons')
        ), organization_map AS (
            SELECT short_org.id AS short_id, full_org.id AS full_id
            FROM organization_aliases oa
            JOIN organizations short_org ON short_org.name = oa.short_name
            JOIN organizations full_org ON full_org.name = oa.full_name
        )
        UPDATE organization_division_participations odp
        SET organization_id = om.full_id
        FROM organization_map om
        WHERE odp.organization_id = om.short_id;

        WITH organization_aliases(short_name, full_name) AS (
            VALUES
              ('Antioch', 'Antioch Vikings'),
              ('Johnsburg', 'Johnsburg Skyhawks'),
              ('Westosha', 'Westosha Falcons')
        ), organization_map AS (
            SELECT short_org.id AS short_id, full_org.id AS full_id
            FROM organization_aliases oa
            JOIN organizations short_org ON short_org.name = oa.short_name
            JOIN organizations full_org ON full_org.name = oa.full_name
        )
        UPDATE host_locations hl
        SET organization_id = om.full_id
        FROM organization_map om
        WHERE hl.organization_id = om.short_id
          AND NOT EXISTS (
              SELECT 1
              FROM host_locations target_hl
              WHERE target_hl.organization_id = om.full_id
                AND target_hl.name = hl.name
          );

        WITH organization_aliases(short_name, full_name) AS (
            VALUES
              ('Antioch', 'Antioch Vikings'),
              ('Johnsburg', 'Johnsburg Skyhawks'),
              ('Westosha', 'Westosha Falcons')
        ), organization_map AS (
            SELECT short_org.id AS short_id, full_org.id AS full_id
            FROM organization_aliases oa
            JOIN organizations short_org ON short_org.name = oa.short_name
            JOIN organizations full_org ON full_org.name = oa.full_name
        )
        UPDATE hosting_availabilities ha
        SET organization_id = om.full_id
        FROM organization_map om
        WHERE ha.organization_id = om.short_id;

        WITH organization_aliases(short_name, full_name) AS (
            VALUES
              ('Antioch', 'Antioch Vikings'),
              ('Johnsburg', 'Johnsburg Skyhawks'),
              ('Westosha', 'Westosha Falcons')
        ), full_organizations AS (
            SELECT o.id
            FROM organization_aliases oa
            JOIN organizations o ON o.name = oa.full_name
        )
        UPDATE hosting_availabilities ha
        SET organization_id = hl.organization_id
        FROM host_locations hl
        JOIN full_organizations fo ON fo.id = hl.organization_id
        WHERE ha.host_location_id = hl.id
          AND (ha.organization_id IS NULL OR ha.organization_id <> hl.organization_id);

        WITH organization_aliases(short_name, full_name) AS (
            VALUES
              ('Antioch', 'Antioch Vikings'),
              ('Johnsburg', 'Johnsburg Skyhawks'),
              ('Westosha', 'Westosha Falcons')
        ), organization_map AS (
            SELECT short_org.id AS short_id, full_org.id AS full_id
            FROM organization_aliases oa
            JOIN organizations short_org ON short_org.name = oa.short_name
            JOIN organizations full_org ON full_org.name = oa.full_name
        )
        UPDATE host_plan_selections hps
        SET community_id = om.full_id
        FROM organization_map om
        WHERE hps.community_id = om.short_id;

        WITH organization_aliases(short_name, full_name) AS (
            VALUES
              ('Antioch', 'Antioch Vikings'),
              ('Johnsburg', 'Johnsburg Skyhawks'),
              ('Westosha', 'Westosha Falcons')
        )
        DELETE FROM organizations short_org
        USING organization_aliases oa
        WHERE short_org.name = oa.short_name
          AND NOT EXISTS (SELECT 1 FROM users u WHERE u.organization_id = short_org.id)
          AND NOT EXISTS (SELECT 1 FROM teams t WHERE t.organization_id = short_org.id)
          AND NOT EXISTS (SELECT 1 FROM host_locations hl WHERE hl.organization_id = short_org.id)
          AND NOT EXISTS (SELECT 1 FROM hosting_availabilities ha WHERE ha.organization_id = short_org.id)
          AND NOT EXISTS (
              SELECT 1
              FROM organization_division_participations odp
              WHERE odp.organization_id = short_org.id
          )
          AND NOT EXISTS (SELECT 1 FROM host_plan_selections hps WHERE hps.community_id = short_org.id);
    """)


def downgrade() -> None:
    pass
