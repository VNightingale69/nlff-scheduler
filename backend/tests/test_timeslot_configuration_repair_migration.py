import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


MIGRATION_PATH = Path(__file__).parents[1] / 'alembic' / 'versions' / '20260809_0060_repair_timeslot_configuration_schema.py'


def load_migration():
    alembic = ModuleType('alembic')
    alembic.op = None
    sqlalchemy = ModuleType('sqlalchemy')

    class Column:
        def __init__(self, name, *_args, nullable=None, **_kwargs):
            self.name = name
            self.nullable = nullable

    sqlalchemy.Column = Column
    for name in ('Uuid', 'String', 'Date', 'Time', 'DateTime', 'ForeignKeyConstraint',
                 'PrimaryKeyConstraint', 'UniqueConstraint'):
        setattr(sqlalchemy, name, lambda *_args, **_kwargs: object())
    sqlalchemy.func = SimpleNamespace(now=lambda: object())
    sqlalchemy.inspect = lambda _bind: None
    spec = importlib.util.spec_from_file_location('timeslot_configuration_repair', MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    with patch.dict(sys.modules, {'alembic': alembic, 'sqlalchemy': sqlalchemy}):
        spec.loader.exec_module(module)
    return module


class Inspector:
    def __init__(self, state):
        self.state = state

    def has_table(self, name):
        return name in self.state['tables']

    def get_columns(self, table):
        return [{'name': name} for name in self.state['columns'][table]]

    def get_indexes(self, _table):
        return self.state['indexes']

    def get_foreign_keys(self, _table):
        return self.state['foreign_keys']


class Operations:
    def __init__(self, state):
        self.state = state
        self.calls = []

    def get_bind(self):
        return object()

    def create_table(self, name, *columns):
        self.calls.append(('create_table', name))
        self.state['tables'].add(name)
        self.state['columns'][name] = {column.name for column in columns if getattr(column, 'name', None)}

    def create_index(self, name, *_args):
        self.calls.append(('create_index', name))
        self.state['indexes'].append({'name': name})

    def add_column(self, table, column):
        self.calls.append(('add_column', table, column.name, column.nullable))
        self.state['columns'][table].add(column.name)

    def create_foreign_key(self, name, *_args):
        self.calls.append(('create_foreign_key', name))
        self.state['foreign_keys'].append({
            'constrained_columns': ['timeslot_configuration_id'],
            'referred_table': 'timeslot_field_configurations',
        })


class TimeslotConfigurationRepairMigrationTests(unittest.TestCase):
    def test_forward_repair_preserves_existing_games_and_adds_nullable_relationship(self):
        migration = load_migration()
        saved_games = [
            {'id': index, 'home': f'home-{index}', 'away': f'away-{index}',
             'date': '2026-08-16', 'kickoff': '09:00', 'host': 'Hiller',
             'field_id': None if index == 0 else f'field-{index % 3}'}
            for index in range(21)
        ]
        before = [dict(game) for game in saved_games]
        state = {
            'tables': {'games'},
            'columns': {'games': {'id', 'field_layout_type_override'}},
            'indexes': [], 'foreign_keys': [],
        }
        operations = Operations(state)
        with patch.object(migration, 'op', operations), patch.object(
            migration.sa, 'inspect', side_effect=lambda _bind: Inspector(state)
        ):
            migration.upgrade()

        self.assertEqual(saved_games, before)
        self.assertEqual(len(saved_games), 21)
        self.assertIn('timeslot_field_configurations', state['tables'])
        self.assertIn(('add_column', 'games', 'timeslot_configuration_id', True), operations.calls)
        self.assertNotIn(('add_column', 'games', 'field_layout_type_override', True), operations.calls)
        self.assertIn(('create_foreign_key', 'fk_games_timeslot_configuration'), operations.calls)

    def test_repair_runs_even_after_original_revision_and_is_idempotent(self):
        migration = load_migration()
        state = {
            'tables': {'games', 'timeslot_field_configurations'},
            'columns': {
                'games': {'id', 'field_layout_type_override', 'timeslot_configuration_id'},
                'timeslot_field_configurations': {
                    'id', 'host_location_id', 'configuration_id', 'configuration_date',
                    'kickoff_time', 'created_at', 'updated_at',
                },
            },
            'indexes': [{'name': 'ix_timeslot_field_configuration_lookup'}],
            'foreign_keys': [{
                'constrained_columns': ['timeslot_configuration_id'],
                'referred_table': 'timeslot_field_configurations',
            }],
        }
        operations = Operations(state)
        with patch.object(migration, 'op', operations), patch.object(
            migration.sa, 'inspect', side_effect=lambda _bind: Inspector(state)
        ):
            migration.upgrade()
        self.assertEqual(operations.calls, [])


if __name__ == '__main__':
    unittest.main()
