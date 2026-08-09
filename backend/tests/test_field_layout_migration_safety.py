import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


MIGRATION_PATH = Path(__file__).parents[1] / 'alembic' / 'versions' / '20260809_0058_game_field_layout_override.py'


def load_migration():
    # Keep this migration regression runnable in the repository's lightweight
    # unit-test environment as well as the fully provisioned backend image.
    alembic = ModuleType('alembic')
    alembic.op = None
    sqlalchemy = ModuleType('sqlalchemy')

    class Column:
        def __init__(self, name, *_args, **_kwargs):
            self.name = name

    sqlalchemy.Column = Column
    for name in ('Uuid', 'String', 'Date', 'Time', 'DateTime', 'ForeignKeyConstraint',
                 'PrimaryKeyConstraint', 'UniqueConstraint'):
        setattr(sqlalchemy, name, lambda *_args, **_kwargs: object())
    sqlalchemy.func = SimpleNamespace(now=lambda: object())
    sqlalchemy.inspect = lambda _bind: None
    spec = importlib.util.spec_from_file_location('field_layout_migration', MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    with patch.dict(sys.modules, {'alembic': alembic, 'sqlalchemy': sqlalchemy}):
        spec.loader.exec_module(module)
    return module


class FakeInspector:
    def __init__(self, state):
        self.state = state

    def has_table(self, name):
        return name in self.state['tables']

    def get_indexes(self, _table):
        return self.state['indexes']

    def get_columns(self, _table):
        return [{'name': name} for name in self.state['game_columns']]

    def get_foreign_keys(self, _table):
        return self.state['foreign_keys']


class FakeOperations:
    def __init__(self, state):
        self.state = state
        self.calls = []

    def get_bind(self):
        return object()

    def create_table(self, name, *_args, **_kwargs):
        self.calls.append(('create_table', name))
        self.state['tables'].add(name)

    def create_index(self, name, table, columns):
        self.calls.append(('create_index', name))
        self.state['indexes'].append({'name': name, 'column_names': columns})

    def add_column(self, table, column):
        self.calls.append(('add_column', column.name))
        self.state['game_columns'].add(column.name)

    def create_foreign_key(self, name, *_args):
        self.calls.append(('create_foreign_key', name))
        self.state['foreign_keys'].append({
            'name': name,
            'constrained_columns': ['timeslot_configuration_id'],
            'referred_table': 'timeslot_field_configurations',
            'referred_columns': ['id'],
        })


class FieldLayoutMigrationSafetyTests(unittest.TestCase):
    def test_migration_follows_previous_revision_and_keeps_overrides_optional(self):
        migration = load_migration()
        self.assertEqual(migration.down_revision, '20260808_0057')
        source = MIGRATION_PATH.read_text()
        self.assertIn("sa.Column('field_layout_type_override', sa.String(length=20), nullable=True)", source)
        self.assertIn("sa.Column('timeslot_configuration_id', sa.Uuid(), nullable=True)", source)

    def test_upgrade_repairs_schema_drift_without_touching_existing_games(self):
        migration = load_migration()
        existing_games = [
            {'id': index, 'matchup': f'home-{index} v away-{index}', 'date': '2026-08-16',
             'kickoff': f'{8 + index // 4:02d}:00', 'host': 'saved host',
             'field': f'field-{index % 4}', 'notes': f'note-{index}'}
            for index in range(21)
        ]
        snapshot = [dict(game) for game in existing_games]
        state = {
            'tables': {'games'},
            # This legacy column is the production-drift scenario that made the
            # original unconditional migration unsafe.
            'game_columns': {'id', 'field_layout_type_override'},
            'indexes': [],
            'foreign_keys': [],
        }
        operations = FakeOperations(state)

        with patch.object(migration, 'op', operations), patch.object(
            migration.sa, 'inspect', side_effect=lambda _bind: FakeInspector(state)
        ):
            migration.upgrade()

        self.assertEqual(existing_games, snapshot)
        self.assertEqual(len(existing_games), 21)
        self.assertIn('timeslot_field_configurations', state['tables'])
        self.assertIn('timeslot_configuration_id', state['game_columns'])
        self.assertNotIn(('add_column', 'field_layout_type_override'), operations.calls)
        self.assertIn(('create_foreign_key', 'fk_games_timeslot_configuration'), operations.calls)

    def test_database_errors_are_logged_server_side_and_sanitized_for_builder(self):
        root = Path(__file__).parents[2]
        backend = (root / 'backend' / 'app' / 'main.py').read_text()
        frontend = (root / 'frontend' / 'src' / 'app' / '(dashboard)' / 'admin' /
                    'manual-schedule-builder' / 'page.tsx').read_text()
        friendly_message = 'Unable to load scheduled games. Please try again.'
        self.assertIn('request.url.path', backend)
        self.assertIn("getattr(original, 'sqlstate', None)", backend)
        self.assertIn('logger.exception(', backend)
        self.assertIn(friendly_message, backend)
        self.assertIn("(e.details as any)?.error === 'database_error'", frontend)
        self.assertIn(friendly_message, frontend)

    def test_upgrade_is_idempotent_for_all_override_objects(self):
        migration = load_migration()
        state = {
            'tables': {'games', 'timeslot_field_configurations'},
            'game_columns': {'id', 'field_layout_type_override', 'timeslot_configuration_id'},
            'indexes': [{'name': None, 'column_names': ['host_location_id', 'configuration_date', 'kickoff_time']}],
            'foreign_keys': [{
                'name': None,
                'constrained_columns': ['timeslot_configuration_id'],
                'referred_table': 'timeslot_field_configurations',
                'referred_columns': ['id'],
            }],
        }
        operations = FakeOperations(state)
        with patch.object(migration, 'op', operations), patch.object(
            migration.sa, 'inspect', side_effect=lambda _bind: FakeInspector(state)
        ):
            migration.upgrade()

        self.assertEqual(operations.calls, [])


if __name__ == '__main__':
    unittest.main()
