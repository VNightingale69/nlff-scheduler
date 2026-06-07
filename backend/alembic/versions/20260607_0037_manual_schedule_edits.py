"""manual schedule edits

Revision ID: 20260607_0037
Revises: 20260605_0036
Create Date: 2026-06-07
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260607_0037'
down_revision = '20260605_0036'
branch_labels = None
depends_on = None


def _uuid_type():
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column('games', sa.Column('public_notes', sa.Text(), nullable=True))
    op.add_column('games', sa.Column('internal_admin_notes', sa.Text(), nullable=True))
    op.add_column('games', sa.Column('is_manual_edit', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('games', sa.Column('manual_edit_locked', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('games', sa.Column('manual_updated_by_user_id', _uuid_type(), nullable=True))
    op.add_column('games', sa.Column('manual_updated_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('games', sa.Column('original_game_snapshot', sa.Text(), nullable=True))
    op.create_foreign_key('fk_games_manual_updated_by_user_id_users', 'games', 'users', ['manual_updated_by_user_id'], ['id'])

    op.create_table(
        'schedule_change_logs',
        sa.Column('id', _uuid_type(), primary_key=True, default=uuid.uuid4),
        sa.Column('game_id', _uuid_type(), nullable=False),
        sa.Column('changed_by_user_id', _uuid_type(), nullable=False),
        sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('field_changed', sa.String(length=100), nullable=False),
        sa.Column('old_value', sa.Text(), nullable=True),
        sa.Column('new_value', sa.Text(), nullable=True),
        sa.Column('warning_override', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('warnings', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['changed_by_user_id'], ['users.id']),
    )
    op.create_index('ix_schedule_change_logs_game_id', 'schedule_change_logs', ['game_id'])
    op.create_index('ix_schedule_change_logs_changed_at', 'schedule_change_logs', ['changed_at'])

    bind = op.get_bind()
    existing = bind.execute(sa.text('SELECT id FROM game_statuses WHERE lower(code) = lower(:code) LIMIT 1'), {'code': 'RESCHEDULED'}).first()
    if existing:
        bind.execute(sa.text('UPDATE game_statuses SET code = :code, label = :label, is_active = true WHERE id = :id'), {'id': existing.id, 'code': 'RESCHEDULED', 'label': 'Rescheduled'})
    else:
        bind.execute(sa.text('INSERT INTO game_statuses (id, code, label, is_active) VALUES (:id, :code, :label, true)'), {'id': str(uuid.uuid4()), 'code': 'RESCHEDULED', 'label': 'Rescheduled'})


def downgrade() -> None:
    op.drop_index('ix_schedule_change_logs_changed_at', table_name='schedule_change_logs')
    op.drop_index('ix_schedule_change_logs_game_id', table_name='schedule_change_logs')
    op.drop_table('schedule_change_logs')
    op.drop_constraint('fk_games_manual_updated_by_user_id_users', 'games', type_='foreignkey')
    op.drop_column('games', 'original_game_snapshot')
    op.drop_column('games', 'manual_updated_at')
    op.drop_column('games', 'manual_updated_by_user_id')
    op.drop_column('games', 'manual_edit_locked')
    op.drop_column('games', 'is_manual_edit')
    op.drop_column('games', 'internal_admin_notes')
    op.drop_column('games', 'public_notes')
    op.execute("DELETE FROM game_statuses WHERE code = 'RESCHEDULED'")
