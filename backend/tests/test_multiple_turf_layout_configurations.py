import uuid
from datetime import date, time

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Field, HostLocation, HostLocationConfiguration, Organization, Role, TimeslotFieldConfiguration, User
from app.routes.api import create_host_location_configuration
from app.schemas import HostLocationConfigurationCreate
from app.services.facility_layout_validation import select_supported_layout


@pytest.fixture()
def facility():
    engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    org = Organization(id=uuid.uuid4(), name='Westosha')
    host = HostLocation(id=uuid.uuid4(), organization_id=org.id, name='Westosha Stadium',
                        surface_type='TURF_STADIUM')
    role = Role(id=uuid.uuid4(), name='LEAGUE_ADMIN')
    user = User(id=uuid.uuid4(), email='admin@example.com', full_name='Admin', password_hash='x', role=role)
    fields = {
        name: Field(id=uuid.uuid4(), host_location_id=host.id, name=name, layout_type=size)
        for name, size in (
            ('Large Field 1', 'LARGE'), ('Medium 1', 'MEDIUM'), ('Medium 2', 'MEDIUM'),
            ('Small Field 1', 'SMALL'), ('Small Field 2', 'SMALL'), ('Small Field 3', 'SMALL'),
        )
    }
    db.add_all([org, host, role, user, *fields.values()]); db.commit()
    yield db, host, user, fields
    db.close()


def _add(db, host, user, fields, code):
    return create_host_location_configuration(HostLocationConfigurationCreate(
        host_location_id=host.id, configuration_name=code,
        field_ids=[fields[name].id for name in fields],
    ), current_user=user, db=db)


def test_three_alternative_layouts_remain_active_and_match_whole_waves(facility):
    db, host, user, fields = facility
    _add(db, host, user, {name: fields[name] for name in ('Small Field 1', 'Small Field 2', 'Small Field 3')}, 'THREE_SMALL')
    _add(db, host, user, {name: fields[name] for name in ('Medium 1', 'Medium 2')}, 'TWO_MEDIUM')
    _add(db, host, user, {name: fields[name] for name in ('Large Field 1', 'Small Field 1')}, 'ONE_LARGE_ONE_SMALL')

    layouts = db.query(HostLocationConfiguration).filter_by(host_location_id=host.id, is_active=True).all()
    assert {layout.configuration_name for layout in layouts} == {
        'THREE_SMALL', 'TWO_MEDIUM', 'ONE_LARGE_ONE_SMALL',
    }
    assert select_supported_layout(db, host.id, None, None, ['SMALL'] * 3)[1].configuration_name == 'THREE_SMALL'
    assert select_supported_layout(db, host.id, None, None, ['MEDIUM'] * 2)[1].configuration_name == 'TWO_MEDIUM'
    assert select_supported_layout(db, host.id, None, None, ['LARGE', 'SMALL'])[1].configuration_name == 'ONE_LARGE_ONE_SMALL'
    assert not select_supported_layout(db, host.id, None, None, ['LARGE', 'MEDIUM'])[2]


def test_validation_and_host_scoped_code_uniqueness(facility):
    db, host, user, fields = facility
    selected = {'Small Field 1': fields['Small Field 1']}
    _add(db, host, user, selected, 'THREE_SMALL')
    with pytest.raises(HTTPException) as duplicate:
        _add(db, host, user, selected, 'three small')
    assert duplicate.value.status_code == 409
    assert duplicate.value.detail['code'] == 'DUPLICATE_CONFIGURATION_CODE'
    with pytest.raises(HTTPException) as empty:
        _add(db, host, user, {}, 'EMPTY')
    assert empty.value.detail['code'] == 'EMPTY_FIELD_CONFIGURATION'

    other = HostLocation(id=uuid.uuid4(), organization_id=host.organization_id, name='Johnsburg Stadium',
                         surface_type='TURF_STADIUM')
    other_field = Field(id=uuid.uuid4(), host_location_id=other.id, name='Small Field 1', layout_type='SMALL')
    db.add_all([other, other_field]); db.commit()
    _add(db, other, user, {'Small Field 1': other_field}, 'THREE_SMALL')
    assert db.query(HostLocationConfiguration).filter_by(configuration_name='THREE_SMALL').count() == 2


def test_retired_timeslot_selection_does_not_override_current_layouts(facility):
    db, host, user, fields = facility
    three_small = _add(db, host, user, {name: fields[name] for name in ('Small Field 1', 'Small Field 2', 'Small Field 3')}, 'THREE_SMALL')
    two_medium = _add(db, host, user, {name: fields[name] for name in ('Medium 1', 'Medium 2')}, 'TWO_MEDIUM')
    large_small = _add(db, host, user, {name: fields[name] for name in ('Large Field 1', 'Small Field 1')}, 'ONE_LARGE_ONE_SMALL')
    retired = HostLocationConfiguration(
        id=uuid.uuid4(), host_location_id=host.id, configuration_name='RETIRED_GENERATED',
        medium_field_count=1, is_active=False,
    )
    selected_day = date(2026, 8, 23)
    selected_time = time(13)
    stale = TimeslotFieldConfiguration(
        id=uuid.uuid4(), host_location_id=host.id, configuration_id=retired.id,
        configuration_date=selected_day, kickoff_time=selected_time,
    )
    db.add_all([retired, stale]); db.commit()

    override, matched, valid = select_supported_layout(
        db, host.id, selected_day, selected_time, ['MEDIUM'],
    )
    assert valid
    assert override is None
    assert matched.id == two_medium.id
    assert {three_small.configuration_name, two_medium.configuration_name, large_small.configuration_name} == {
        'THREE_SMALL', 'TWO_MEDIUM', 'ONE_LARGE_ONE_SMALL',
    }
