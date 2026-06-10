"""community logo upload metadata

Revision ID: 20260610_0045
Revises: 20260610_0044
Create Date: 2026-06-10 00:45:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260610_0045'
down_revision = '20260610_0044'
branch_labels = None
depends_on = None


def _uuid():
    return postgresql.UUID(as_uuid=True)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column['name'] for column in inspector.get_columns('organizations')}
    additions = [
        ('logo_url', sa.Column('logo_url', sa.String(length=500), nullable=True)),
        ('logo_filename', sa.Column('logo_filename', sa.String(length=255), nullable=True)),
        ('logo_content_type', sa.Column('logo_content_type', sa.String(length=100), nullable=True)),
        ('logo_file_size', sa.Column('logo_file_size', sa.Integer(), nullable=True)),
        ('logo_width', sa.Column('logo_width', sa.Integer(), nullable=True)),
        ('logo_height', sa.Column('logo_height', sa.Integer(), nullable=True)),
        ('logo_uploaded_at', sa.Column('logo_uploaded_at', sa.DateTime(timezone=True), nullable=True)),
        ('logo_uploaded_by_user_id', sa.Column('logo_uploaded_by_user_id', _uuid(), nullable=True)),
    ]
    for name, column in additions:
        if name not in columns:
            op.add_column('organizations', column)

    foreign_keys = {fk['name'] for fk in inspector.get_foreign_keys('organizations')}
    if 'fk_organizations_logo_uploaded_by_user_id_users' not in foreign_keys:
        op.create_foreign_key(
            'fk_organizations_logo_uploaded_by_user_id_users',
            'organizations',
            'users',
            ['logo_uploaded_by_user_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    foreign_keys = {fk['name'] for fk in inspector.get_foreign_keys('organizations')}
    if 'fk_organizations_logo_uploaded_by_user_id_users' in foreign_keys:
        op.drop_constraint('fk_organizations_logo_uploaded_by_user_id_users', 'organizations', type_='foreignkey')
    columns = {column['name'] for column in inspector.get_columns('organizations')}
    for name in [
        'logo_uploaded_by_user_id',
        'logo_uploaded_at',
        'logo_height',
        'logo_width',
        'logo_file_size',
        'logo_content_type',
        'logo_filename',
        'logo_url',
    ]:
        if name in columns:
            op.drop_column('organizations', name)
