"""repair the user soft-delete schema

Revision ID: 20260813_0065
Revises: 20260813_0064

This forward-only repair also covers a database that was accidentally stamped at
0064 without applying the ``users.deleted_at`` DDL.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260813_0065'
down_revision = '20260813_0064'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column['name'] for column in inspector.get_columns('users')}
    if 'deleted_at' not in columns:
        op.add_column('users', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))

    indexes = {index['name'] for index in sa.inspect(bind).get_indexes('users')}
    if 'ix_users_active_not_deleted' not in indexes:
        op.create_index('ix_users_active_not_deleted', 'users', ['is_active', 'deleted_at'], unique=False)


def downgrade() -> None:
    # Revision 0064 owns the column and index. This repair intentionally has no
    # destructive downgrade so rolling back 0065 cannot remove deployed data.
    pass
