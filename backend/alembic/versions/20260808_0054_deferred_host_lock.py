"""add week-level deferred host lock

Revision ID: 20260808_0054
Revises: 20260807_0053
"""
from alembic import op
import sqlalchemy as sa

revision = '20260808_0054'
down_revision = '20260807_0053'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('weeks', sa.Column('host_assignment_locked', sa.Boolean(), nullable=False, server_default=sa.false()))
    # The known Fall 2026 Week 4 exception is scheduling state, never placeholder
    # community/location/field inventory.
    op.execute("""
        UPDATE weeks w SET host_assignment_pending = true
        WHERE w.week_number = 4 AND w.primary_game_date = DATE '2026-09-13'
          AND EXISTS (
              SELECT 1 FROM seasons s
              WHERE s.id = w.season_id AND lower(trim(s.name)) = '2026 fall flag'
          )
    """)
    op.execute("""
        DELETE FROM host_plan_selections hps
        WHERE hps.game_date = DATE '2026-09-13'
          AND EXISTS (
              SELECT 1 FROM seasons s
              WHERE s.id = hps.season_id AND lower(trim(s.name)) = '2026 fall flag'
          )
    """)


def downgrade():
    op.drop_column('weeks', 'host_assignment_locked')
