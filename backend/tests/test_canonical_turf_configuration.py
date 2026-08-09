import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, HostLocation, HostLocationConfiguration, Organization
from app.routes.api import (
    _approved_layout_codes_for_host,
    _configuration_field_templates_for_host,
    _ensure_approved_turf_configurations,
    _is_approved_turf_slot_counts,
    _turf_wave_layout_counts,
)


def test_all_turf_stadiums_use_one_large_one_small_while_grass_is_unchanged():
    engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    organization = Organization(id=uuid.uuid4(), name='Any League Community', is_active=True)
    turf = HostLocation(id=uuid.uuid4(), organization_id=organization.id, name='Future Stadium', surface_type='TURF_STADIUM')
    grass = HostLocation(id=uuid.uuid4(), organization_id=organization.id, name='Park', surface_type='GRASS_FIELD')
    old = HostLocationConfiguration(
        id=uuid.uuid4(), host_location_id=turf.id,
        configuration_name='ONE_LARGE_ONE_MEDIUM', large_field_count=1,
        medium_field_count=1, small_field_count=0, is_active=True,
    )
    db.add_all([organization, turf, grass, old])
    db.commit()

    assert _approved_layout_codes_for_host(turf) == {'ONE_LARGE_ONE_SMALL'}
    assert _ensure_approved_turf_configurations(db, turf)
    assert not _ensure_approved_turf_configurations(db, grass)
    db.flush()

    active = db.query(HostLocationConfiguration).filter_by(host_location_id=turf.id, is_active=True).one()
    assert active.configuration_name == 'ONE_LARGE_ONE_SMALL'
    assert (active.large_field_count, active.medium_field_count, active.small_field_count) == (1, 0, 1)
    assert not old.is_active
    assert _configuration_field_templates_for_host(turf, active.configuration_name) == [
        ('Large Field', 'LARGE'), ('Small Field', 'SMALL'),
    ]
    assert _turf_wave_layout_counts(active.configuration_name) == {'SMALL': 1, 'MEDIUM': 0, 'LARGE': 1}
    assert _is_approved_turf_slot_counts({'SMALL': 1, 'MEDIUM': 0, 'LARGE': 1})
    assert not _is_approved_turf_slot_counts({'SMALL': 0, 'MEDIUM': 0, 'LARGE': 2})
    assert not _is_approved_turf_slot_counts({'SMALL': 2, 'MEDIUM': 0, 'LARGE': 0})
    assert db.query(HostLocationConfiguration).filter_by(host_location_id=grass.id).count() == 0

    db.close()
