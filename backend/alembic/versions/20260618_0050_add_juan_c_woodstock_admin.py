"""add juan c woodstock community admin

Revision ID: 20260618_0050
Revises: 20260611_0049
Create Date: 2026-06-18
"""

from alembic import op


revision = '20260618_0050'
down_revision = '20260611_0049'
branch_labels = None
depends_on = None


JUAN_C_WOODSTOCK_ADMIN_SQL = """
    CREATE EXTENSION IF NOT EXISTS pgcrypto;

    INSERT INTO roles (id, name, description, is_active)
    VALUES (gen_random_uuid(), 'COMMUNITY_ADMIN', 'Community-scoped administrative access', true)
    ON CONFLICT (name) DO UPDATE
    SET description = EXCLUDED.description,
        is_active = true;

    UPDATE users
    SET email = lower(email)
    WHERE lower(email) = 'ju2carb@gmail.com';

    WITH seeded_user(full_name, email, temporary_password) AS (
        VALUES ('Juan C', 'ju2carb@gmail.com', 'Woodstock1')
    ), resolved AS (
        SELECT
            su.full_name,
            lower(su.email) AS email,
            su.temporary_password,
            o.id AS organization_id,
            r.id AS role_id
        FROM seeded_user su
        JOIN organizations o
          ON o.name = 'Woodstock'
         AND o.is_active IS TRUE
         AND o.deleted_at IS NULL
        JOIN roles r
          ON r.name = 'COMMUNITY_ADMIN'
         AND r.is_active IS TRUE
    )
    UPDATE users u
    SET full_name = resolved.full_name,
        password_hash = crypt(resolved.temporary_password, gen_salt('bf')),
        role_id = resolved.role_id,
        organization_id = resolved.organization_id,
        is_active = true
    FROM resolved
    WHERE lower(u.email) = resolved.email;

    WITH seeded_user(full_name, email, temporary_password) AS (
        VALUES ('Juan C', 'ju2carb@gmail.com', 'Woodstock1')
    ), resolved AS (
        SELECT
            su.full_name,
            lower(su.email) AS email,
            su.temporary_password,
            o.id AS organization_id,
            r.id AS role_id
        FROM seeded_user su
        JOIN organizations o
          ON o.name = 'Woodstock'
         AND o.is_active IS TRUE
         AND o.deleted_at IS NULL
        JOIN roles r
          ON r.name = 'COMMUNITY_ADMIN'
         AND r.is_active IS TRUE
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
    op.execute(JUAN_C_WOODSTOCK_ADMIN_SQL)


def downgrade() -> None:
    pass
