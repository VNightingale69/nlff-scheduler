import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / 'alembic'
    / 'versions'
    / '20260816_0069_repair_tosc_legacy_fields.py'
)
PHYSICAL_AREAS_MIGRATION_PATH = (
    Path(__file__).parents[1]
    / 'alembic'
    / 'versions'
    / '20260816_0068_tosc_physical_areas.py'
)


def load_migration():
    alembic = ModuleType('alembic')
    alembic.op = None
    sqlalchemy = ModuleType('sqlalchemy')

    class Text(str):
        def bindparams(self, *_args):
            return self

    sqlalchemy.text = Text
    sqlalchemy.bindparam = lambda *_args, **_kwargs: object()
    sqlalchemy.inspect = lambda _bind: None
    spec = importlib.util.spec_from_file_location('tosc_legacy_field_repair', MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    with patch.dict(sys.modules, {'alembic': alembic, 'sqlalchemy': sqlalchemy}):
        spec.loader.exec_module(module)
    return module


class Result:
    def __init__(self, values=()):
        self.values = list(values)

    def scalars(self):
        return self

    def all(self):
        return self.values


class Inspector:
    def __init__(self, migration, include_legacy=False, legacy_columns=None):
        self.columns = {
            table: set(columns)
            for table, columns in migration.REQUIRED_TABLE_COLUMNS.items()
        }
        # Timestamp columns are present in the real schema but intentionally
        # optional for the pre-Alembic compatibility path.
        for columns in self.columns.values():
            columns.add('updated_at')
        if include_legacy:
            self.columns['hosting_availability'] = set(
                legacy_columns
                or {'field_id', 'active', 'is_available', 'updated_at'}
            )

    def get_table_names(self):
        return list(self.columns)

    def get_columns(self, table):
        return [{'name': name} for name in self.columns[table]]


class Bind:
    def __init__(self, field_ids=('field-1',), config_ids=('config-1',)):
        self.field_ids = field_ids
        self.config_ids = config_ids
        self.calls = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if sql.lstrip().startswith('SELECT h.id FROM host_locations'):
            return Result(('host-1',))
        if sql.lstrip().startswith('SELECT id FROM fields'):
            return Result(self.field_ids)
        if sql.lstrip().startswith('SELECT DISTINCT field_configuration_id'):
            return Result(self.config_ids)
        return Result()


class Operations:
    def __init__(self, bind):
        self.bind = bind

    def get_bind(self):
        return self.bind


class ToscLegacyFieldRepairMigrationTests(unittest.TestCase):
    def run_upgrade(self, *, include_legacy=False, legacy_columns=None, field_ids=('field-1',)):
        migration = load_migration()
        bind = Bind(field_ids=field_ids)
        inspector = Inspector(migration, include_legacy, legacy_columns)
        with patch.object(migration, 'op', Operations(bind)), patch.object(
            migration.sa, 'inspect', return_value=inspector
        ):
            migration.upgrade()
        return migration, bind, inspector

    def test_database_without_singular_hosting_availability_uses_current_plural_table(self):
        _migration, bind, _inspector = self.run_upgrade()
        statements = [sql for sql, _params in bind.calls]

        self.assertTrue(any(sql.lstrip().startswith('UPDATE hosting_availabilities') for sql in statements))
        self.assertFalse(any(sql.lstrip().startswith('UPDATE hosting_availability\n') for sql in statements))

    def test_compatible_legacy_singular_hosting_availability_is_cleaned(self):
        _migration, bind, _inspector = self.run_upgrade(include_legacy=True)
        statements = [sql for sql, _params in bind.calls]

        self.assertTrue(any(sql.lstrip().startswith('UPDATE hosting_availability\n') for sql in statements))

    def test_historical_games_are_detached_with_their_field_identity_preserved(self):
        _migration, bind, _inspector = self.run_upgrade()
        statements = [sql for sql, _params in bind.calls]
        game_update = next(sql for sql in statements if sql.lstrip().startswith('UPDATE games g'))
        slot_delete = next(sql for sql in statements if sql.lstrip().startswith('DELETE FROM game_slots'))

        self.assertIn('previous_field_id=COALESCE(g.previous_field_id,g.field_id)', game_update)
        self.assertIn('previous_field_name=COALESCE(g.previous_field_name,f.name)', game_update)
        self.assertIn('field_id=NULL', game_update)
        self.assertIn('assigned_game_id IS NULL', slot_delete)

    def test_partially_migrated_configuration_converges_without_duplicate_areas(self):
        _migration, bind, _inspector = self.run_upgrade(field_ids=())
        repair_statements = [sql for sql, _params in bind.calls]
        physical_area_source = PHYSICAL_AREAS_MIGRATION_PATH.read_text()

        # 0068 upserts the three canonical names; 0069 deactivates every other
        # area even when legacy fields were already repaired in an earlier run.
        self.assertEqual(physical_area_source.count("'Football Field 1':"), 1)
        self.assertEqual(physical_area_source.count("'Football Field 2':"), 1)
        self.assertEqual(physical_area_source.count("'Soccer Field':"), 1)
        self.assertIn('ON CONFLICT(host_location_id,name) DO UPDATE', physical_area_source)
        area_update = next(
            sql for sql in repair_statements
            if sql.lstrip().startswith('UPDATE physical_field_areas')
        )
        self.assertIn('name NOT IN', area_update)

    def test_required_current_schema_drift_fails_clearly(self):
        migration = load_migration()
        inspector = Inspector(migration)
        del inspector.columns['hosting_availabilities']

        with self.assertRaisesRegex(RuntimeError, 'hosting_availabilities'):
            migration._validate_current_schema(inspector)

    def test_revision_is_ordered_directly_after_physical_area_conversion(self):
        migration = load_migration()
        self.assertEqual('20260816_0069', migration.revision)
        self.assertEqual('20260816_0068', migration.down_revision)


if __name__ == '__main__':
    unittest.main()
