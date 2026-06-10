"""team coach contact fields

Revision ID: 20260610_0042
Revises: 20260609_0041
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa

revision = '20260610_0042'
down_revision = '20260609_0041'
branch_labels = None
depends_on = None


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if column.name not in {col['name'] for col in inspector.get_columns(table)}:
        op.add_column(table, column)


def upgrade() -> None:
    _add_column_if_missing('teams', sa.Column('coach_name', sa.String(length=255), nullable=True))
    _add_column_if_missing('teams', sa.Column('coach_email', sa.String(length=255), nullable=True))


def downgrade() -> None:
    for column in ['coach_email', 'coach_name']:
        try:
            op.drop_column('teams', column)
        except Exception:
            pass
