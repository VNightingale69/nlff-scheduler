"""auth enhancements

Revision ID: 20260519_0002
Revises: 20260518_0001
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260519_0002'
down_revision = '20260518_0001'
branch_labels = None
depends_on = None


def _uuid_col():
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column('users', sa.Column('password_hash', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('role_id', _uuid_col(), nullable=True))
    op.add_column('users', sa.Column('organization_id', _uuid_col(), nullable=True))
    op.create_foreign_key('fk_users_role_id', 'users', 'roles', ['role_id'], ['id'])
    op.create_foreign_key('fk_users_organization_id', 'users', 'organizations', ['organization_id'], ['id'])

    op.execute("""
        INSERT INTO roles (id, name, description, is_active)
        VALUES
          (gen_random_uuid(), 'league_admin', 'Global administrative access across all organizations', true),
          (gen_random_uuid(), 'community_scheduler', 'Organization-scoped scheduling access', true)
        ON CONFLICT (name) DO NOTHING;
    """)

    op.execute("""
        UPDATE users
        SET password_hash = '$2b$12$uQly8n8rE.2jScfQ5u5k8ecf9jksxJ7eaWgKThj8YC9QxV7umL6Jq',
            role_id = (SELECT id FROM roles WHERE name = 'league_admin' LIMIT 1)
        WHERE password_hash IS NULL;
    """)

    op.alter_column('users', 'password_hash', nullable=False)
    op.alter_column('users', 'role_id', nullable=False)


def downgrade() -> None:
    op.drop_constraint('fk_users_organization_id', 'users', type_='foreignkey')
    op.drop_constraint('fk_users_role_id', 'users', type_='foreignkey')
    op.drop_column('users', 'organization_id')
    op.drop_column('users', 'role_id')
    op.drop_column('users', 'password_hash')
