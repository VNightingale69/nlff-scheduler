"""ensure organization_division_participations table exists with required columns

Revision ID: 20260521_0008
Revises: 20260521_0007
Create Date: 2026-05-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '20260521_0008'
down_revision = '20260521_0007'
branch_labels = None
depends_on = None

TABLE_NAME = 'organization_division_participations'


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


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
            sa.UniqueConstraint('organization_id', 'division_id', name='uq_org_division_participation'),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, TABLE_NAME):
        op.drop_table(TABLE_NAME)
