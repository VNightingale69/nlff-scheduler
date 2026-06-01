"""restore lake county community admin accounts

Revision ID: 20260601_0030
Revises: 20260531_0029
Create Date: 2026-06-01
"""

from alembic import op


revision = '20260601_0030'
down_revision = '20260531_0029'
branch_labels = None
depends_on = None


LAKE_COUNTY_ADMIN_SQL = """
    CREATE EXTENSION IF NOT EXISTS pgcrypto;

    INSERT INTO roles (id, name, description, is_active)
    VALUES (gen_random_uuid(), 'COMMUNITY_ADMIN', 'Community-scoped administrative access', true)
    ON CONFLICT (name) DO UPDATE
    SET description = EXCLUDED.description,
        is_active = true;

    INSERT INTO organizations (id, name, is_active)
    VALUES (gen_random_uuid(), 'Lake County Stallions', true)
    ON CONFLICT (name) DO UPDATE
    SET is_active = true;

    WITH seeded_users(full_name, email, temporary_password) AS (
        VALUES
          ('Amy Schneider', 'aeschneider622@gmail.com', 'LakeCounty1'),
          ('Katie Gandolf', 'lcstallionsflagfootball@gmail.com', 'LakeCounty2'),
          ('Mike Schneider', 'michaelwb01@yahoo.com', 'LakeCounty3')
    ), resolved AS (
        SELECT
            su.full_name,
            lower(su.email) AS email,
            su.temporary_password,
            o.id AS organization_id,
            r.id AS role_id
        FROM seeded_users su
        JOIN organizations o ON o.name = 'Lake County Stallions'
        JOIN roles r ON r.name = 'COMMUNITY_ADMIN'
    )
    UPDATE users u
    SET full_name = resolved.full_name,
        password_hash = crypt(resolved.temporary_password, gen_salt('bf')),
        role_id = resolved.role_id,
        organization_id = resolved.organization_id,
        is_active = true
    FROM resolved
    WHERE lower(u.email) = resolved.email;

    WITH seeded_users(full_name, email, temporary_password) AS (
        VALUES
          ('Amy Schneider', 'aeschneider622@gmail.com', 'LakeCounty1'),
          ('Katie Gandolf', 'lcstallionsflagfootball@gmail.com', 'LakeCounty2'),
          ('Mike Schneider', 'michaelwb01@yahoo.com', 'LakeCounty3')
    ), resolved AS (
        SELECT
            su.full_name,
            lower(su.email) AS email,
            su.temporary_password,
            o.id AS organization_id,
            r.id AS role_id
        FROM seeded_users su
        JOIN organizations o ON o.name = 'Lake County Stallions'
        JOIN roles r ON r.name = 'COMMUNITY_ADMIN'
    )
    INSERT INTO users (id, email, full_name, password_hash, role_id, organization_id, is_active)
    SELECT
        gen_random_uuid(),
        resolved.email,
        resolved.full_name,
        crypt(resolved.temporary_password, gen_salt('bf')),
        resolved.role_id,
        resolved.organization_id,
        true
    FROM resolved
    WHERE NOT EXISTS (
        SELECT 1
        FROM users u
        WHERE lower(u.email) = resolved.email
    );
"""


def upgrade() -> None:
    op.execute(LAKE_COUNTY_ADMIN_SQL)


def downgrade() -> None:
    pass
