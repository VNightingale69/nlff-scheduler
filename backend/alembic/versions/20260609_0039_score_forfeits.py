"""add score forfeit support

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


def upgrade() -> None:
    op.add_column('game_scores', sa.Column('home_forfeit', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('game_scores', sa.Column('away_forfeit', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('game_scores', sa.Column('winner_team_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_game_scores_winner_team_id', 'game_scores', 'teams', ['winner_team_id'], ['id'])

    op.add_column('score_submissions', sa.Column('home_forfeit', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('score_submissions', sa.Column('away_forfeit', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('score_submissions', sa.Column('submitted_home_score_raw', sa.String(length=30), nullable=True))
    op.add_column('score_submissions', sa.Column('submitted_away_score_raw', sa.String(length=30), nullable=True))
    op.add_column('score_submissions', sa.Column('normalized_home_score_display', sa.String(length=30), nullable=True))
    op.add_column('score_submissions', sa.Column('normalized_away_score_display', sa.String(length=30), nullable=True))
    op.add_column('score_submissions', sa.Column('actor_role', sa.String(length=80), nullable=True))
    op.add_column('score_submissions', sa.Column('previous_status', sa.String(length=30), nullable=True))
    op.add_column('score_submissions', sa.Column('new_status', sa.String(length=30), nullable=True))
    op.add_column('score_submissions', sa.Column('normalization_note', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('score_submissions', 'normalization_note')
    op.drop_column('score_submissions', 'new_status')
    op.drop_column('score_submissions', 'previous_status')
    op.drop_column('score_submissions', 'actor_role')
    op.drop_column('score_submissions', 'normalized_away_score_display')
    op.drop_column('score_submissions', 'normalized_home_score_display')
    op.drop_column('score_submissions', 'submitted_away_score_raw')
    op.drop_column('score_submissions', 'submitted_home_score_raw')
    op.drop_column('score_submissions', 'away_forfeit')
    op.drop_column('score_submissions', 'home_forfeit')
    op.drop_constraint('fk_game_scores_winner_team_id', 'game_scores', type_='foreignkey')
    op.drop_column('game_scores', 'winner_team_id')
    op.drop_column('game_scores', 'away_forfeit')
    op.drop_column('game_scores', 'home_forfeit')
