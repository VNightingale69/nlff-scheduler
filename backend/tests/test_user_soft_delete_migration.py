import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import patch


MIGRATION_PATH = Path(__file__).parents[1] / 'alembic' / 'versions' / '20260813_0065_repair_user_soft_delete.py'


def load_migration():
    alembic = ModuleType('alembic')
    alembic.op = None
    sqlalchemy = ModuleType('sqlalchemy')

    class Column:
        def __init__(self, name, *_args, **_kwargs):
            self.name = name

    sqlalchemy.Column = Column
    sqlalchemy.DateTime = lambda **_kwargs: object()
    sqlalchemy.inspect = lambda _bind: None
    spec = importlib.util.spec_from_file_location('user_soft_delete_repair', MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    with patch.dict(sys.modules, {'alembic': alembic, 'sqlalchemy': sqlalchemy}):
        spec.loader.exec_module(module)
    return module


class Inspector:
    def __init__(self, columns, indexes):
        self.columns = columns
        self.indexes = indexes

    def get_columns(self, _table):
        return [{'name': name} for name in self.columns]

    def get_indexes(self, _table):
        return [{'name': name} for name in self.indexes]


class Operations:
    def __init__(self):
        self.calls = []

    def get_bind(self):
        return object()

    def add_column(self, table, column):
        self.calls.append(('add_column', table, column.name))

    def create_index(self, name, table, columns, unique=False):
        self.calls.append(('create_index', name, table, columns, unique))


def test_repair_adds_missing_user_soft_delete_schema():
    migration = load_migration()
    operations = Operations()
    with patch.object(migration, 'op', operations), patch.object(
        migration.sa, 'inspect', side_effect=[Inspector({'id', 'is_active'}, set()), Inspector(set(), set())]
    ):
        migration.upgrade()
    assert ('add_column', 'users', 'deleted_at') in operations.calls
    assert ('create_index', 'ix_users_active_not_deleted', 'users', ['is_active', 'deleted_at'], False) in operations.calls


def test_repair_is_safe_when_revision_0064_was_applied():
    migration = load_migration()
    operations = Operations()
    inspector = Inspector({'id', 'is_active', 'deleted_at'}, {'ix_users_active_not_deleted'})
    with patch.object(migration, 'op', operations), patch.object(migration.sa, 'inspect', return_value=inspector):
        migration.upgrade()
    assert operations.calls == []
