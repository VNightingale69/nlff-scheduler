"""ensure organization_division_participations table and indexes exist

Revision ID: 20260521_0007
Revises: 20260521_0006
Create Date: 2026-05-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '20260521_0007'
down_revision = '20260521_0006'
branch_labels = None
depends_on = None

TABLE_NAME = 'organization_division_participations'
ORG_INDEX = 'ix_org_division_participations_organization_id'
DIV_INDEX = 'ix_org_division_participations_division_id'
UNIQUE_NAME = 'uq_org_division_participation'


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {index['name'] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, TABLE_NAME):
        op.create_table(
            TABLE_NAME,
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('division_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('is_participating', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('team_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
            sa.ForeignKeyConstraint(['division_id'], ['divisions.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('organization_id', 'division_id', name=UNIQUE_NAME),
        )

    inspector = sa.inspect(bind)
    index_names = _index_names(inspector, TABLE_NAME)
    if ORG_INDEX not in index_names:
        op.create_index(ORG_INDEX, TABLE_NAME, ['organization_id'], unique=False)
    if DIV_INDEX not in index_names:
        op.create_index(DIV_INDEX, TABLE_NAME, ['division_id'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, TABLE_NAME):
        return

    index_names = _index_names(inspector, TABLE_NAME)
    if DIV_INDEX in index_names:
        op.drop_index(DIV_INDEX, table_name=TABLE_NAME)
    if ORG_INDEX in index_names:
        op.drop_index(ORG_INDEX, table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)
