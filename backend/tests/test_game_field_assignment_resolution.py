import uuid
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Field, FieldInstance, HostLocation, HostingAvailability, Organization
from app.services.field_resolution import normalize_field_identifier, resolve_game_field_assignment


def _db():
    engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_separator_variants_normalize_to_one_identifier():
    expected = normalize_field_identifier('Football Field 2 / Small 1')
    assert normalize_field_identifier('Football Field 2 - Small 1') == expected
    assert normalize_field_identifier('Football Field 2 – Small 1') == expected


def test_legacy_field_instance_uniquely_repairs_canonical_field_id():
    db = _db()
    organization = Organization(id=uuid.uuid4(), name='Community', is_active=True)
    host = HostLocation(id=uuid.uuid4(), organization_id=organization.id,
                        name='Tim Osmond Sports Complex', is_active=True)
    field = Field(id=uuid.uuid4(), host_location_id=host.id,
                  name='Football Field 2 / Small 1', layout_type='SMALL', is_active=True)
    availability = HostingAvailability(
        id=uuid.uuid4(), organization_id=organization.id, host_location_id=host.id,
        available_date=__import__('datetime').date(2026, 8, 23),
        start_time=__import__('datetime').time(8), end_time=__import__('datetime').time(16),
        is_available=True,
    )
    instance = FieldInstance(
        id=uuid.uuid4(), host_location_id=host.id, hosting_availability_id=availability.id,
        instance_date=availability.available_date, field_name='Football Field 2 – Small 1',
        field_type='SMALL', is_active=True,
    )
    db.add_all([organization, host, field, availability, instance])
    db.commit()
    game = SimpleNamespace(field_id=None, field=None, host_location_id=host.id,
                           field_instance_id=instance.id, field_instance=instance)

    resolved = resolve_game_field_assignment(db, game, field_instance=instance, repair=True)

    assert resolved is not None
    assert resolved.issue_code is None
    assert resolved.physical_field_id == field.id
    assert resolved.field_size == 'SMALL'
    assert resolved.repaired is True
    assert game.field_id == field.id


def test_no_saved_relational_assignment_is_truly_missing():
    db = _db()
    game = SimpleNamespace(field_id=None, field=None, field_instance_id=None,
                           field_instance=None, host_location_id=uuid.uuid4())
    assert resolve_game_field_assignment(db, game) is None


def test_wrong_host_is_not_reported_as_missing():
    db = _db()
    field = SimpleNamespace(id=uuid.uuid4(), host_location_id=uuid.uuid4(),
                            name='Large 1', layout_type='LARGE', is_active=True,
                            deleted_at=None)
    game = SimpleNamespace(field_id=field.id, field=field,
                           host_location_id=uuid.uuid4())
    resolved = resolve_game_field_assignment(db, game)
    assert resolved.issue_code == 'FIELD_LOCATION_MISMATCH'
