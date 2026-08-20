import importlib.util
import sys
import types
from pathlib import Path


MIGRATION_PATH = (Path(__file__).parents[1] / 'alembic' / 'versions' /
                  '20260820_0077_repair_partial_layout_memberships.py')


def _load_migration():
    previous = sys.modules.get('alembic')
    previous_sqlalchemy = sys.modules.get('sqlalchemy')
    sys.modules['alembic'] = types.SimpleNamespace(op=None)
    if previous_sqlalchemy is None:
        sqlalchemy = types.ModuleType('sqlalchemy')
        sqlalchemy.text = lambda statement: statement
        sys.modules['sqlalchemy'] = sqlalchemy
    try:
        spec = importlib.util.spec_from_file_location('repair_0077', MIGRATION_PATH)
        migration = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(migration)
        return migration
    finally:
        if previous is None:
            del sys.modules['alembic']
        else:
            sys.modules['alembic'] = previous
        if previous_sqlalchemy is None:
            del sys.modules['sqlalchemy']


def test_partial_repair_is_host_agnostic_id_based_and_unambiguous():
    migration = _load_migration()
    sql = migration._REPAIR_MISSING_MEMBERSHIPS_SQL

    assert migration.down_revision == '20260820_0076'
    assert 'missing_count=candidate_count' in sql
    assert 'f.host_location_id=e.host_location_id' in sql
    assert 'm.field_id=f.id' in sql
    assert 'configuration_name=' not in sql
    assert 'Westosha' not in sql
    assert '22f37ae8-0603-4e38-8eef-4ef9acaeb63a' not in sql
    assert 'games' not in sql.lower()
