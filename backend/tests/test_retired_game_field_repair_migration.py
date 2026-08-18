import importlib.util
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
    assert "LIKE '__retired_generated__%'" in bind.statement
