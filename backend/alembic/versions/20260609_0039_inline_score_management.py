"""inline score management workflow

Revision ID: 20260609_0039
Revises: 20260607_0038
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260609_0039'
down_revision = '20260607_0038'
branch_labels = None
depends_on = None


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if column.name not in {col['name'] for col in inspector.get_columns(table)}:
        op.add_column(table, column)


def _create_index_if_missing(name: str, table: str, columns: list[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if name not in {idx['name'] for idx in inspector.get_indexes(table)}:
        op.create_index(name, table, columns)


def upgrade() -> None:
    _add_column_if_missing('game_scores', sa.Column('submitted_by_community_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id'), nullable=True))
    _add_column_if_missing('game_scores', sa.Column('is_published', sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing('game_scores', sa.Column('published_by_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True))
    _add_column_if_missing('game_scores', sa.Column('published_at', sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing('game_scores', sa.Column('unpublished_by_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True))
    _add_column_if_missing('game_scores', sa.Column('unpublished_at', sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing('game_scores', sa.Column('unpublished_reason', sa.Text(), nullable=True))
    _add_column_if_missing('game_scores', sa.Column('score_conflict', sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing('game_scores', sa.Column('confirmed_by_opponent', sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing('game_scores', sa.Column('flagged', sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing('game_scores', sa.Column('flag_reason', sa.Text(), nullable=True))
    _add_column_if_missing('game_scores', sa.Column('flagged_by_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True))
    _add_column_if_missing('game_scores', sa.Column('flagged_by_community_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id'), nullable=True))
    _add_column_if_missing('game_scores', sa.Column('flagged_at', sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing('game_scores', sa.Column('last_updated_by_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True))
    _add_column_if_missing('game_scores', sa.Column('last_updated_at', sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE game_scores SET score_status = 'MISSING' WHERE score_status IN ('SCHEDULED', 'SCORE_PENDING')")
    _create_index_if_missing('ix_game_scores_published', 'game_scores', ['is_published'])
    _create_index_if_missing('ix_game_scores_conflict', 'game_scores', ['score_conflict'])

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'score_history' not in inspector.get_table_names():
        op.create_table(
            'score_history',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('game_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('action', sa.String(length=50), nullable=False),
            sa.Column('previous_home_score', sa.Integer(), nullable=True),
            sa.Column('previous_away_score', sa.Integer(), nullable=True),
            sa.Column('new_home_score', sa.Integer(), nullable=True),
            sa.Column('new_away_score', sa.Integer(), nullable=True),
            sa.Column('previous_status', sa.String(length=30), nullable=True),
            sa.Column('new_status', sa.String(length=30), nullable=True),
            sa.Column('previous_is_published', sa.Boolean(), nullable=True),
            sa.Column('new_is_published', sa.Boolean(), nullable=True),
            sa.Column('actor_user_id', postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('actor_role', sa.String(length=100), nullable=True),
            sa.Column('actor_community_id', postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('reason', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(['actor_community_id'], ['organizations.id']),
            sa.ForeignKeyConstraint(['actor_user_id'], ['users.id']),
            sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
    _create_index_if_missing('ix_score_history_game_id', 'score_history', ['game_id'])
    _create_index_if_missing('ix_score_history_action', 'score_history', ['action'])
    _create_index_if_missing('ix_score_history_created_at', 'score_history', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_score_history_created_at', table_name='score_history')
    op.drop_index('ix_score_history_action', table_name='score_history')
    op.drop_index('ix_score_history_game_id', table_name='score_history')
    op.drop_table('score_history')
    op.drop_index('ix_game_scores_conflict', table_name='game_scores')
    op.drop_index('ix_game_scores_published', table_name='game_scores')
    for column in ['last_updated_at', 'last_updated_by_user_id', 'flagged_at', 'flagged_by_community_id', 'flagged_by_user_id', 'flag_reason', 'flagged', 'confirmed_by_opponent', 'score_conflict', 'unpublished_reason', 'unpublished_at', 'unpublished_by_user_id', 'published_at', 'published_by_user_id', 'is_published', 'submitted_by_community_id']:
        op.drop_column('game_scores', column)
