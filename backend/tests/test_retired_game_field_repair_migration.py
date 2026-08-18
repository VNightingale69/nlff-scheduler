import importlib.util
import os
import re
import sys
import types
from pathlib import Path


SOURCE = (Path(__file__).parents[1] / 'alembic' / 'versions' /
          '20260818_0073_repair_retired_game_fields.py').read_text()
MIGRATION_PATH = (Path(__file__).parents[1] / 'alembic' / 'versions' /
                  '20260818_0073_repair_retired_game_fields.py')


def _load_migration(op):
    previous = sys.modules.get('alembic')
    sys.modules['alembic'] = types.SimpleNamespace(op=op)
    try:
        spec = importlib.util.spec_from_file_location('repair_0073', MIGRATION_PATH)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        return migration
    finally:
        if previous is None:
            del sys.modules['alembic']
        else:
            sys.modules['alembic'] = previous


def test_repair_is_current_season_relational_and_ambiguity_safe():
    assert 's.is_active IS TRUE' in SOURCE
    assert 'active.hosting_availability_id = retired.hosting_availability_id' in SOURCE
    assert 'active.instance_date = retired.instance_date' in SOURCE
    assert 'active.field_type = retired.field_type' in SOURCE
    assert 'HAVING count(*) = 1' in SOURCE


def test_repair_updates_relationship_without_recreating_games_or_scores():
    assert 'UPDATE games g' in SOURCE
    assert 'SET field_instance_id = replacement.active_id' in SOURCE
    assert 'INSERT INTO games' not in SOURCE
    assert 'game_scores' not in SOURCE


def test_retired_prefix_pattern_extracts_production_style_human_names():
    migration = _load_migration(None)
    examples = {
        '__retired_generated__abc123__Medium Field 1': 'Medium Field 1',
        '__retired_generated__abc123____retired_generated__def456__Medium Field 1': 'Medium Field 1',
        # Malformed Hiller value created by repeated retirement of the same row.
        '__retired_generated__f9ac615f__retired_generated__f9ac615f__Medium Field 1': 'Medium Field 1',
    }

    for stored_name, expected in examples.items():
        assert re.sub(migration._RETIRED_PREFIX_PATTERN, '', stored_name) == expected


def test_upgrade_uses_driver_sql_without_sqlalchemy_bind_parsing():
    class Bind:
        statement = None

        def exec_driver_sql(self, statement):
            self.statement = statement

    bind = Bind()
    op = types.SimpleNamespace(get_bind=lambda: bind)
    migration = _load_migration(op)

    migration.upgrade()

    assert bind.statement == migration._UPGRADE_SQL
    assert '?:' not in bind.statement
    assert ':retired_generated__' not in bind.statement
    assert '%' not in bind.statement
    assert "starts_with(fi.field_name, '__retired_generated__')" in bind.statement
    assert "NOT starts_with(active.field_name, '__retired_generated__')" in bind.statement


def test_upgrade_executes_via_production_postgresql_driver():
    """Exercise the complete repair SQL through SQLAlchemy and psycopg.

    Set TEST_DATABASE_URL to an expendable PostgreSQL database. Each run uses a
    temporary schema and rolls its changes back; no application tables are
    accessed.
    """
    import pytest

    database_url = os.getenv('TEST_DATABASE_URL')
    if not database_url:
        pytest.skip('TEST_DATABASE_URL is required for the PostgreSQL driver regression test')

    sqlalchemy = pytest.importorskip('sqlalchemy')
    if not database_url.startswith('postgresql+psycopg://'):
        pytest.fail('TEST_DATABASE_URL must use the production postgresql+psycopg driver')

    engine = sqlalchemy.create_engine(database_url)
    with engine.connect() as connection, connection.begin():
        connection.exec_driver_sql('CREATE TEMP TABLE seasons (id uuid PRIMARY KEY, is_active boolean NOT NULL)')
        connection.exec_driver_sql(
            'CREATE TEMP TABLE hosting_availabilities (id uuid PRIMARY KEY, field_id uuid)'
        )
        connection.exec_driver_sql(
            '''CREATE TEMP TABLE field_instances (
                   id uuid PRIMARY KEY,
                   hosting_availability_id uuid NOT NULL,
                   instance_date date NOT NULL,
                   field_type text NOT NULL,
                   field_name text NOT NULL,
                   is_active boolean NOT NULL
               )'''
        )
        connection.exec_driver_sql(
            '''CREATE TEMP TABLE games (
                   id uuid PRIMARY KEY,
                   season_id uuid NOT NULL,
                   field_instance_id uuid,
                   field_id uuid,
                   field_display_name_snapshot text,
                   division_id uuid,
                   game_date date,
                   kickoff_time time,
                   home_team_id uuid,
                   away_team_id uuid,
                   home_score integer,
                   away_score integer,
                   is_published boolean
               )'''
        )
        connection.exec_driver_sql(
            '''INSERT INTO seasons VALUES
               ('00000000-0000-0000-0000-000000000001', TRUE)'''
        )
        connection.exec_driver_sql(
            '''INSERT INTO hosting_availabilities VALUES
               ('00000000-0000-0000-0000-000000000002',
                '00000000-0000-0000-0000-000000000003')'''
        )
        connection.exec_driver_sql(
            '''INSERT INTO field_instances VALUES
               ('00000000-0000-0000-0000-000000000010',
                '00000000-0000-0000-0000-000000000002', '2026-08-18', 'Medium',
                '__retired_generated__abc123__Medium Field 1', FALSE),
               ('00000000-0000-0000-0000-000000000011',
                '00000000-0000-0000-0000-000000000002', '2026-08-18', 'Medium',
                '__retired_generated__abc123____retired_generated__def456__Medium Field 1', FALSE),
               ('00000000-0000-0000-0000-000000000012',
                '00000000-0000-0000-0000-000000000002', '2026-08-18', 'Medium',
                'Medium Field 1', TRUE)'''
        )
        connection.exec_driver_sql(
            '''INSERT INTO games VALUES
               ('00000000-0000-0000-0000-000000000020',
                '00000000-0000-0000-0000-000000000001',
                '00000000-0000-0000-0000-000000000010', NULL, 'old snapshot',
                '00000000-0000-0000-0000-000000000030', '2026-08-18', '18:30',
                '00000000-0000-0000-0000-000000000031',
                '00000000-0000-0000-0000-000000000032', 4, 3, TRUE),
               ('00000000-0000-0000-0000-000000000021',
                '00000000-0000-0000-0000-000000000001',
                '00000000-0000-0000-0000-000000000011', NULL, 'old snapshot',
                '00000000-0000-0000-0000-000000000030', '2026-08-18', '19:30',
                '00000000-0000-0000-0000-000000000031',
                '00000000-0000-0000-0000-000000000032', 2, 1, FALSE)'''
        )

        migration = _load_migration(types.SimpleNamespace(get_bind=lambda: connection))
        migration.upgrade()

        rows = connection.exec_driver_sql(
            '''SELECT field_instance_id::text, field_id::text,
                      field_display_name_snapshot, division_id::text,
                      game_date::text, kickoff_time::text,
                      home_team_id::text, away_team_id::text,
                      home_score, away_score, is_published
               FROM games ORDER BY id'''
        ).all()

    assert [row[0] for row in rows] == ['00000000-0000-0000-0000-000000000012'] * 2
    assert [row[1] for row in rows] == ['00000000-0000-0000-0000-000000000003'] * 2
    assert [row[2] for row in rows] == ['Medium Field 1'] * 2
    assert rows[0][3:] == (
        '00000000-0000-0000-0000-000000000030', '2026-08-18', '18:30:00',
        '00000000-0000-0000-0000-000000000031',
        '00000000-0000-0000-0000-000000000032', 4, 3, True,
    )
    assert rows[1][3:] == (
        '00000000-0000-0000-0000-000000000030', '2026-08-18', '19:30:00',
        '00000000-0000-0000-0000-000000000031',
        '00000000-0000-0000-0000-000000000032', 2, 1, False,
    )
