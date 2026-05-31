"""seed community administrator accounts

Revision ID: 20260531_0028
Revises: 20260531_0027
Create Date: 2026-05-31
"""

from alembic import op


revision = '20260531_0028'
down_revision = '20260531_0027'
branch_labels = None
depends_on = None


COMMUNITY_ADMIN_SEED_SQL = """
    CREATE EXTENSION IF NOT EXISTS pgcrypto;

    UPDATE roles SET name = 'LEAGUE_ADMIN', description = 'Global administrative access across all organizations', is_active = true
    WHERE name = 'league_admin' AND NOT EXISTS (SELECT 1 FROM roles WHERE name = 'LEAGUE_ADMIN');

    UPDATE roles SET name = 'COMMUNITY_ADMIN', description = 'Community-scoped administrative access', is_active = true
    WHERE name = 'community_scheduler' AND NOT EXISTS (SELECT 1 FROM roles WHERE name = 'COMMUNITY_ADMIN');

    INSERT INTO roles (id, name, description, is_active)
    VALUES
      (gen_random_uuid(), 'LEAGUE_ADMIN', 'Global administrative access across all organizations', true),
      (gen_random_uuid(), 'COMMUNITY_ADMIN', 'Community-scoped administrative access', true)
    ON CONFLICT (name) DO NOTHING;

    UPDATE users SET role_id = (SELECT id FROM roles WHERE name = 'LEAGUE_ADMIN' LIMIT 1)
    WHERE role_id IN (SELECT id FROM roles WHERE name = 'league_admin');
    UPDATE users SET role_id = (SELECT id FROM roles WHERE name = 'COMMUNITY_ADMIN' LIMIT 1)
    WHERE role_id IN (SELECT id FROM roles WHERE name = 'community_scheduler');
    UPDATE roles SET is_active = false WHERE name IN ('league_admin', 'community_scheduler');

    WITH organization_aliases(seed_name, organization_name) AS (
        VALUES
          ('Lake County Stallions', 'Lake County Stallions'),
          ('Cary', 'Cary'),
          ('Johnsburg', 'Johnsburg Skyhawks'),
          ('Woodstock', 'Woodstock'),
          ('Westosha', 'Westosha Falcons'),
          ('Antioch', 'Antioch Vikings'),
          ('Prairie Ridge', 'Prairie Ridge')
    )
    INSERT INTO organizations (id, name, is_active)
    SELECT gen_random_uuid(), organization_name, true FROM organization_aliases
    ON CONFLICT (name) DO NOTHING;

    UPDATE users SET email = lower(email)
    WHERE lower(email) IN (
      'aeschneider622@gmail.com',
      'lcstallionsflagfootball@gmail.com',
      'michaelwb01@yahoo.com',
      'harms827@gmail.com',
      'elostroscio@gmail.com',
      'kendzior.t@gmail.com',
      'ju2carb@gmail.com',
      'lar_nightingale@hotmail.com',
      'nicholasjstafford@gmail.com',
      'sdycha144@gmail.com'
    );

    WITH organization_aliases(seed_name, organization_name) AS (
        VALUES
          ('Lake County Stallions', 'Lake County Stallions'),
          ('Cary', 'Cary'),
          ('Johnsburg', 'Johnsburg Skyhawks'),
          ('Woodstock', 'Woodstock'),
          ('Westosha', 'Westosha Falcons'),
          ('Antioch', 'Antioch Vikings'),
          ('Prairie Ridge', 'Prairie Ridge')
    ), seeded_users(organization_name, full_name, email, temporary_password) AS (
        VALUES
          ('Lake County Stallions', 'Amy Schneider', 'aeschneider622@gmail.com', 'LakeCounty1'),
          ('Lake County Stallions', 'Katie Gandolf', 'lcstallionsflagfootball@gmail.com', 'LakeCounty2'),
          ('Lake County Stallions', 'Mike Schneider', 'michaelwb01@yahoo.com', 'LakeCounty3'),
          ('Cary', 'Brent Harmeier', 'harms827@gmail.com', 'Cary1'),
          ('Johnsburg', 'Eric Lostroscio', 'elostroscio@gmail.com', 'Johnsburg1'),
          ('Johnsburg', 'Tiffany Kendzior', 'kendzior.t@gmail.com', 'Johnsburg2'),
          ('Woodstock', 'Juan Cabajal', 'ju2carb@gmail.com', 'Woodstock1'),
          ('Westosha', 'Lisa Nightingale', 'lar_nightingale@hotmail.com', 'Westosha1'),
          ('Antioch', 'Nick Stafford', 'nicholasjstafford@gmail.com', 'Antioch1'),
          ('Prairie Ridge', 'Stephanie Dycha', 'sdycha144@gmail.com', 'PrairieRidge1')
    ), resolved AS (
        SELECT su.full_name, lower(su.email) AS email, su.temporary_password, o.id AS organization_id, r.id AS role_id
        FROM seeded_users su
        JOIN organization_aliases oa ON oa.seed_name = su.organization_name
        JOIN organizations o ON o.name = oa.organization_name
        JOIN roles r ON r.name = 'COMMUNITY_ADMIN'
    )
    INSERT INTO users (id, email, full_name, password_hash, role_id, organization_id, is_active)
    SELECT gen_random_uuid(), email, full_name, crypt(temporary_password, gen_salt('bf')), role_id, organization_id, true
    FROM resolved
    ON CONFLICT (email) DO UPDATE
    SET full_name = EXCLUDED.full_name,
        role_id = EXCLUDED.role_id,
        organization_id = EXCLUDED.organization_id,
        is_active = true;
"""


def upgrade() -> None:
    op.execute(COMMUNITY_ADMIN_SEED_SQL)


def downgrade() -> None:
    op.execute("""
        DELETE FROM users
        WHERE lower(email) IN (
          'aeschneider622@gmail.com',
          'lcstallionsflagfootball@gmail.com',
          'michaelwb01@yahoo.com',
          'harms827@gmail.com',
          'elostroscio@gmail.com',
          'kendzior.t@gmail.com',
          'ju2carb@gmail.com',
          'lar_nightingale@hotmail.com',
          'nicholasjstafford@gmail.com',
          'sdycha144@gmail.com'
        );
    """)
