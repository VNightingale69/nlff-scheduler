"""seed 2026 fall flag season calendar

Revision ID: 20260530_0024
Revises: 20260530_0023
Create Date: 2026-05-30 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260530_0024'
down_revision = '20260530_0023'
branch_labels = None
depends_on = None

FALL_2026_SEASON_NAME = '2026 Fall Flag'
FALL_2026_CALENDAR = [
    (1, 'Week 1', '2026-08-09', 'REGULAR_SEASON'),
    (2, 'Week 2', '2026-08-16', 'REGULAR_SEASON'),
    (3, 'Week 3', '2026-08-23', 'REGULAR_SEASON'),
    (4, 'Week 4', '2026-08-30', 'REGULAR_SEASON'),
    (5, 'Labor Day Blackout', '2026-09-06', 'BLACKOUT'),
    (6, 'Week 5', '2026-09-13', 'REGULAR_SEASON'),
    (7, 'Week 6', '2026-09-20', 'REGULAR_SEASON'),
    (8, 'Week 7', '2026-09-27', 'REGULAR_SEASON'),
    (9, 'Week 8', '2026-10-04', 'REGULAR_SEASON'),
    (10, 'Playoff Saturday', '2026-10-10', 'PLAYOFF'),
    (11, 'Playoff Sunday', '2026-10-11', 'PLAYOFF'),
]


def _uuid_sql() -> str:
    return 'gen_random_uuid()'


def _add_column_if_missing(inspector, table_name: str, column: sa.Column) -> None:
    columns = {c['name'] for c in inspector.get_columns(table_name)}
    if column.name not in columns:
        op.add_column(table_name, column)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'weeks' not in inspector.get_table_names() or 'seasons' not in inspector.get_table_names():
        return

    _add_column_if_missing(inspector, 'weeks', sa.Column('date_type', sa.String(length=30), nullable=False, server_default='REGULAR_SEASON'))
    op.execute("UPDATE weeks SET date_type = 'REGULAR_SEASON' WHERE date_type IS NULL OR date_type = ''")
    try:
        op.alter_column('weeks', 'date_type', server_default=None)
    except Exception:
        pass

    season_id = bind.execute(sa.text("SELECT id FROM seasons WHERE name = :name"), {'name': FALL_2026_SEASON_NAME}).scalar()
    if season_id is None:
        bind.execute(sa.text(f"""
            INSERT INTO seasons (id, name, start_date, end_date, schedule_status, is_active)
            VALUES ({_uuid_sql()}, :name, DATE '2026-08-09', DATE '2026-10-11', 'draft', true)
        """), {'name': FALL_2026_SEASON_NAME})
        season_id = bind.execute(sa.text("SELECT id FROM seasons WHERE name = :name"), {'name': FALL_2026_SEASON_NAME}).scalar()
    else:
        bind.execute(sa.text("""
            UPDATE seasons
            SET start_date = DATE '2026-08-09', end_date = DATE '2026-10-11', is_active = true
            WHERE id = :season_id
        """), {'season_id': season_id})

    for week_number, label, game_date, date_type in FALL_2026_CALENDAR:
        existing_id = bind.execute(sa.text("""
            SELECT id FROM weeks
            WHERE season_id = :season_id AND (week_number = :week_number OR start_date = CAST(:game_date AS date) OR primary_game_date = CAST(:game_date AS date))
            ORDER BY CASE WHEN week_number = :week_number THEN 0 ELSE 1 END
            LIMIT 1
        """), {'season_id': season_id, 'week_number': week_number, 'game_date': game_date}).scalar()
        if existing_id is None:
            bind.execute(sa.text(f"""
                INSERT INTO weeks (id, season_id, week_number, label, start_date, end_date, primary_game_date, date_type, status)
                VALUES ({_uuid_sql()}, :season_id, :week_number, :label, CAST(:game_date AS date), CAST(:game_date AS date), CAST(:game_date AS date), :date_type, 'active')
            """), {'season_id': season_id, 'week_number': week_number, 'label': label, 'game_date': game_date, 'date_type': date_type})
        else:
            bind.execute(sa.text("""
                UPDATE weeks
                SET week_number = :week_number,
                    label = :label,
                    start_date = CAST(:game_date AS date),
                    end_date = CAST(:game_date AS date),
                    primary_game_date = CAST(:game_date AS date),
                    date_type = :date_type,
                    status = COALESCE(NULLIF(status, ''), 'active')
                WHERE id = :existing_id
            """), {'existing_id': existing_id, 'week_number': week_number, 'label': label, 'game_date': game_date, 'date_type': date_type})


def downgrade() -> None:
    # Keep seeded calendar rows in place; removing them could delete user-entered hosting/scheduling data.
    pass
