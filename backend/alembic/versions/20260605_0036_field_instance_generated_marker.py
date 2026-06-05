"""add generated marker to field instances

Revision ID: 20260605_0036
Revises: 20260604_0035, 20260604_0027
Create Date: 2026-06-05
"""

from alembic import op
import sqlalchemy as sa


revision = '20260605_0036'
down_revision = ('20260604_0035', '20260604_0027')
branch_labels = None
depends_on = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(column['name'] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_column(inspector, 'field_instances', 'is_generated'):
        op.add_column(
            'field_instances',
            sa.Column('is_generated', sa.Boolean(), nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_column(inspector, 'field_instances', 'is_generated'):
        op.drop_column('field_instances', 'is_generated')
