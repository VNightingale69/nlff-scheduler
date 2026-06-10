"""single elimination tournament builder

Revision ID: 20260610_0044
Revises: 20260610_0043
Create Date: 2026-06-10 00:44:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260610_0044'
down_revision = '20260610_0043'
branch_labels = None
depends_on = None


def _uuid():
    return postgresql.UUID(as_uuid=True)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    game_columns = {c['name'] for c in inspector.get_columns('games')}
    if 'game_type' not in game_columns:
        op.add_column('games', sa.Column('game_type', sa.String(length=30), nullable=False, server_default='REGULAR_SEASON'))
        op.alter_column('games', 'game_type', server_default=None)

    op.create_table('tournaments',
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('season_id', _uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('type', sa.String(length=40), nullable=False, server_default='SINGLE_ELIMINATION'),
        sa.Column('status', sa.String(length=40), nullable=False, server_default='DRAFT'),
        sa.Column('is_published', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_by_user_id', _uuid(), nullable=True),
        sa.Column('unpublished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('unpublished_by_user_id', _uuid(), nullable=True),
        sa.Column('created_by_user_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['published_by_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['season_id'], ['seasons.id']),
        sa.ForeignKeyConstraint(['unpublished_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_tournaments_season_id', 'tournaments', ['season_id'])
    op.create_table('tournament_divisions',
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('tournament_id', _uuid(), nullable=False),
        sa.Column('division_id', _uuid(), nullable=False),
        sa.Column('status', sa.String(length=40), nullable=False, server_default='SEEDED'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['division_id'], ['divisions.id']),
        sa.ForeignKeyConstraint(['tournament_id'], ['tournaments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tournament_id', 'division_id', name='uq_tournament_division'))
    op.create_index('ix_tournament_divisions_tournament_id', 'tournament_divisions', ['tournament_id'])
    op.create_table('tournament_teams',
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('tournament_division_id', _uuid(), nullable=False),
        sa.Column('team_id', _uuid(), nullable=False),
        sa.Column('seed', sa.Integer(), nullable=False),
        sa.Column('included', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('seed_source', sa.String(length=40), nullable=False, server_default='RESULTS_STANDINGS'),
        sa.Column('original_standings_rank', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id']),
        sa.ForeignKeyConstraint(['tournament_division_id'], ['tournament_divisions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tournament_division_id', 'seed', name='uq_tournament_team_seed'),
        sa.UniqueConstraint('tournament_division_id', 'team_id', name='uq_tournament_team'))
    op.create_index('ix_tournament_teams_division_id', 'tournament_teams', ['tournament_division_id'])
    op.create_table('tournament_games',
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('tournament_division_id', _uuid(), nullable=False),
        sa.Column('round_number', sa.Integer(), nullable=False),
        sa.Column('round_name', sa.String(length=80), nullable=False),
        sa.Column('game_number', sa.Integer(), nullable=False),
        sa.Column('team_1_id', _uuid(), nullable=True),
        sa.Column('team_2_id', _uuid(), nullable=True),
        sa.Column('team_1_seed', sa.Integer(), nullable=True),
        sa.Column('team_2_seed', sa.Integer(), nullable=True),
        sa.Column('team_1_source_game_id', _uuid(), nullable=True),
        sa.Column('team_2_source_game_id', _uuid(), nullable=True),
        sa.Column('winner_team_id', _uuid(), nullable=True),
        sa.Column('loser_team_id', _uuid(), nullable=True),
        sa.Column('game_date', sa.Date(), nullable=True),
        sa.Column('kickoff_time', sa.Time(), nullable=True),
        sa.Column('host_location_id', _uuid(), nullable=True),
        sa.Column('field_id', _uuid(), nullable=True),
        sa.Column('status', sa.String(length=40), nullable=False, server_default='WAITING_FOR_TEAMS'),
        sa.Column('home_score', sa.Integer(), nullable=True),
        sa.Column('away_score', sa.Integer(), nullable=True),
        sa.Column('home_forfeit', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('away_forfeit', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('score_status', sa.String(length=30), nullable=False, server_default='MISSING'),
        sa.Column('is_published', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('needs_review', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['field_id'], ['fields.id']),
        sa.ForeignKeyConstraint(['host_location_id'], ['host_locations.id']),
        sa.ForeignKeyConstraint(['loser_team_id'], ['teams.id']),
        sa.ForeignKeyConstraint(['team_1_id'], ['teams.id']),
        sa.ForeignKeyConstraint(['team_1_source_game_id'], ['tournament_games.id']),
        sa.ForeignKeyConstraint(['team_2_id'], ['teams.id']),
        sa.ForeignKeyConstraint(['team_2_source_game_id'], ['tournament_games.id']),
        sa.ForeignKeyConstraint(['tournament_division_id'], ['tournament_divisions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['winner_team_id'], ['teams.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tournament_division_id', 'game_number', name='uq_tournament_game_number'))
    op.create_index('ix_tournament_games_division_round', 'tournament_games', ['tournament_division_id', 'round_number'])


def downgrade():
    op.drop_index('ix_tournament_games_division_round', table_name='tournament_games')
    op.drop_table('tournament_games')
    op.drop_index('ix_tournament_teams_division_id', table_name='tournament_teams')
    op.drop_table('tournament_teams')
    op.drop_index('ix_tournament_divisions_tournament_id', table_name='tournament_divisions')
    op.drop_table('tournament_divisions')
    op.drop_index('ix_tournaments_season_id', table_name='tournaments')
    op.drop_table('tournaments')
    op.drop_column('games', 'game_type')
