import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest


MIGRATION_PATH = (Path(__file__).parents[1] / 'alembic' / 'versions' /
                  '20260820_0076_repair_canonical_layout_memberships.py')
SOURCE = MIGRATION_PATH.read_text()


def _load_migration(op=None):
    previous = sys.modules.get('alembic')
    previous_sqlalchemy = sys.modules.get('sqlalchemy')
    sys.modules['alembic'] = types.SimpleNamespace(op=op)
    if previous_sqlalchemy is None:
        sqlalchemy = types.ModuleType('sqlalchemy')
        sqlalchemy.text = lambda statement: statement
        sys.modules['sqlalchemy'] = sqlalchemy
    try:
        spec = importlib.util.spec_from_file_location('repair_0076', MIGRATION_PATH)
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


def test_uuid_candidate_is_selected_only_after_uniqueness_is_established():
    migration = _load_migration()
    sql = migration._REPAIR_RETIRED_MEMBERSHIPS_SQL

    assert 'n.id AS new_field_id' in sql
    assert 'candidate_count=1' in sql
    assert 'm.field_id IS DISTINCT FROM r.new_field_id' in sql
    assert 'NOT EXISTS (SELECT 1 FROM field_configuration_members x' in sql
    assert 'min(' not in sql.lower()
    assert 'max(' not in sql.lower()
    assert '::text' not in sql.lower()


def test_revision_remains_in_place_in_the_alembic_chain():
    migration = _load_migration()
    assert migration.revision == '20260820_0076'
    assert migration.down_revision == '20260820_0075'
    assert 'Canonical membership repair:' in SOURCE


def test_repair_cases_execute_with_postgresql_uuid_columns():
    """Set TEST_DATABASE_URL to an expendable production-driver PostgreSQL DB."""
    database_url = os.getenv('TEST_DATABASE_URL')
    if not database_url:
        pytest.skip('TEST_DATABASE_URL is required for the PostgreSQL regression test')
    if not database_url.startswith('postgresql+psycopg://'):
        pytest.fail('TEST_DATABASE_URL must use the production postgresql+psycopg driver')

    sqlalchemy = pytest.importorskip('sqlalchemy')
    migration = _load_migration()
    engine = sqlalchemy.create_engine(database_url)
    with engine.connect() as connection, connection.begin():
        connection.exec_driver_sql('''CREATE TEMP TABLE host_location_configurations (
            id uuid PRIMARY KEY, host_location_id uuid NOT NULL)''')
        connection.exec_driver_sql('''CREATE TEMP TABLE fields (
            id uuid PRIMARY KEY, host_location_id uuid NOT NULL, name text NOT NULL,
            is_active boolean NOT NULL, deleted_at timestamptz)''')
        connection.exec_driver_sql('''CREATE TEMP TABLE field_configuration_members (
            id uuid PRIMARY KEY, field_configuration_id uuid NOT NULL, field_id uuid NOT NULL,
            updated_at timestamptz,
            UNIQUE (field_configuration_id, field_id))''')
        # Hosts/configurations 1-4 represent one, zero, multiple, and existing-target cases.
        connection.exec_driver_sql('''INSERT INTO host_location_configurations VALUES
            ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001'),
            ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000002'),
            ('10000000-0000-0000-0000-000000000003', '20000000-0000-0000-0000-000000000003'),
            ('10000000-0000-0000-0000-000000000004', '20000000-0000-0000-0000-000000000004')''')
        connection.exec_driver_sql('''INSERT INTO fields VALUES
            ('30000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'Small 1', FALSE, now()),
            ('40000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', ' small 1 ', TRUE, NULL),
            ('30000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000002', 'No Match', FALSE, now()),
            ('30000000-0000-0000-0000-000000000003', '20000000-0000-0000-0000-000000000003', 'Medium 1', FALSE, now()),
            ('40000000-0000-0000-0000-000000000003', '20000000-0000-0000-0000-000000000003', 'medium 1', TRUE, NULL),
            ('40000000-0000-0000-0000-000000000013', '20000000-0000-0000-0000-000000000003', ' MEDIUM   1 ', TRUE, NULL),
            ('30000000-0000-0000-0000-000000000004', '20000000-0000-0000-0000-000000000004', 'Large 1', FALSE, now()),
            ('40000000-0000-0000-0000-000000000004', '20000000-0000-0000-0000-000000000004', 'large 1', TRUE, NULL)''')
        connection.exec_driver_sql('''INSERT INTO field_configuration_members VALUES
            ('50000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', now()),
            ('50000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000002', now()),
            ('50000000-0000-0000-0000-000000000003', '10000000-0000-0000-0000-000000000003', '30000000-0000-0000-0000-000000000003', now()),
            ('50000000-0000-0000-0000-000000000004', '10000000-0000-0000-0000-000000000004', '30000000-0000-0000-0000-000000000004', now()),
            ('50000000-0000-0000-0000-000000000014', '10000000-0000-0000-0000-000000000004', '40000000-0000-0000-0000-000000000004', now())''')

        first = connection.execute(sqlalchemy.text(migration._REPAIR_RETIRED_MEMBERSHIPS_SQL)).mappings().one()
        second = connection.execute(sqlalchemy.text(migration._REPAIR_RETIRED_MEMBERSHIPS_SQL)).mappings().one()
        rows = dict(connection.exec_driver_sql(
            'SELECT id::text, field_id::text FROM field_configuration_members').all())

    assert first == {
        'candidates_inspected': 4, 'unambiguous_repairs': 1,
        'ambiguous_skipped': 1, 'no_match_skipped': 1,
        'existing_target_skipped': 1,
    }
    assert second['unambiguous_repairs'] == 0
    assert rows['50000000-0000-0000-0000-000000000001'] == '40000000-0000-0000-0000-000000000001'
    assert rows['50000000-0000-0000-0000-000000000002'] == '30000000-0000-0000-0000-000000000002'
    assert rows['50000000-0000-0000-0000-000000000003'] == '30000000-0000-0000-0000-000000000003'
    assert rows['50000000-0000-0000-0000-000000000004'] == '30000000-0000-0000-0000-000000000004'
