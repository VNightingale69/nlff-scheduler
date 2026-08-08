"""schedule import staging and audit

Revision ID: 20260808_0057
Revises: 20260808_0056
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision='20260808_0057'; down_revision='20260808_0056'; branch_labels=None; depends_on=None
def upgrade():
    op.create_table('schedule_imports', sa.Column('id',postgresql.UUID(as_uuid=True),primary_key=True), sa.Column('season_id',postgresql.UUID(as_uuid=True),sa.ForeignKey('seasons.id'),nullable=False), sa.Column('imported_by_user_id',postgresql.UUID(as_uuid=True),sa.ForeignKey('users.id'),nullable=False), sa.Column('imported_at',sa.DateTime(timezone=True),nullable=False), sa.Column('source_filename',sa.String(255),nullable=False), sa.Column('weeks_replaced',sa.Text(),nullable=False), sa.Column('existing_games_removed',sa.Integer(),nullable=False,server_default='0'), sa.Column('games_imported',sa.Integer(),nullable=False,server_default='0'), sa.Column('validation_warning_count',sa.Integer(),nullable=False,server_default='0'), sa.Column('status',sa.String(20),nullable=False), sa.Column('staged_rows',sa.Text(),nullable=False), sa.Column('preview_summary',sa.Text(),nullable=False))
    op.create_index('ix_schedule_imports_season_id','schedule_imports',['season_id'])
def downgrade(): op.drop_table('schedule_imports')
