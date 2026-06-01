"""add score tracking tables

Revision ID: 20260601_0032
Revises: 20260601_0031
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260601_0032'
down_revision = '20260601_0031'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'game_scores',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('game_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('home_score', sa.Integer(), nullable=True),
        sa.Column('away_score', sa.Integer(), nullable=True),
        sa.Column('score_status', sa.String(length=30), nullable=False, server_default='SCHEDULED'),
        sa.Column('submitted_by_user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by_user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('league_admin_notes', sa.Text(), nullable=True),
        sa.Column('community_admin_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['approved_by_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['submitted_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('game_id'),
    )
    op.create_index('ix_game_scores_game_id', 'game_scores', ['game_id'])
    op.create_index('ix_game_scores_status', 'game_scores', ['score_status'])

    op.create_table(
        'score_submissions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('game_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('home_score', sa.Integer(), nullable=False),
        sa.Column('away_score', sa.Integer(), nullable=False),
        sa.Column('submitted_by_user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('submission_source_community_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('community_admin_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['submitted_by_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['submission_source_community_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_score_submissions_game_id', 'score_submissions', ['game_id'])
    op.create_index('ix_score_submissions_source_community', 'score_submissions', ['submission_source_community_id'])


def downgrade() -> None:
    op.drop_index('ix_score_submissions_source_community', table_name='score_submissions')
    op.drop_index('ix_score_submissions_game_id', table_name='score_submissions')
    op.drop_table('score_submissions')
    op.drop_index('ix_game_scores_status', table_name='game_scores')
    op.drop_index('ix_game_scores_game_id', table_name='game_scores')
    op.drop_table('game_scores')
