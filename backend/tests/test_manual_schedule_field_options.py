import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Field, FieldConfigurationOption, HostLocation, HostLocationConfiguration, Organization, PhysicalFieldArea
from app.routes.api import manual_schedule_builder_options


def test_manual_builder_uses_active_canonical_fields_by_host_with_short_labels():
    engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    organization = Organization(id=uuid.uuid4(), name='Johnsburg', is_active=True)
    hosts = {
        name: HostLocation(
            id=uuid.uuid4(), organization_id=organization.id, name=name,
            surface_type='GRASS_FIELD', is_active=True,
        )
        for name in ('Hiller Park', 'Hiller Stadium', 'Johnsburg Stadium')
    }
    db.add_all([organization, *hosts.values()])
    db.flush()
    expected = {
        'Hiller Park': ['SW', 'SE', 'North', 'NE', 'Middle'],
        'Hiller Stadium': ['Medium Field 1', 'Medium Field 2'],
        'Johnsburg Stadium': ['Large Field 1', 'Medium Field 1'],
    }
    fields = []
    for host_name, labels in expected.items():
        for label in labels:
            fields.append(Field(
                id=uuid.uuid4(), host_location_id=hosts[host_name].id,
                name=f'Johnsburg - {host_name} - Configured - {label}',
                layout_type='SMALL', is_active=True,
            ))
    fields.append(Field(
        id=uuid.uuid4(), host_location_id=hosts['Hiller Park'].id,
        name='Johnsburg - Hiller - Small - Inactive', layout_type='SMALL',
        is_active=False,
    ))
    db.add_all(fields)
    db.commit()

    result = manual_schedule_builder_options(db)
    by_host = {
        host_name: [
            field for field in result['fields']
            if field['host_location_id'] == hosts[host_name].id
        ]
        for host_name in expected
    }

    for host_name, labels in expected.items():
        assert {field['display_name'] for field in by_host[host_name]} == set(labels)
        assert all(field['is_active'] for field in by_host[host_name])
        assert all(field['id'] == field['field_id'] for field in by_host[host_name])
        assert all(field['host_location_id'] == hosts[host_name].id for field in by_host[host_name])
    assert 'Inactive' not in {field['display_name'] for field in result['fields']}
    db.close()


def test_manual_builder_materializes_turf_layout_positions_without_generated_slots():
    engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    organization = Organization(id=uuid.uuid4(), name='Johnsburg', is_active=True)
    stadium = HostLocation(
        id=uuid.uuid4(), organization_id=organization.id, name='Johnsburg Stadium',
        surface_type='TURF_STADIUM', is_active=True,
    )
    db.add_all([organization, stadium])
    db.flush()
    db.add(HostLocationConfiguration(
        host_location_id=stadium.id, configuration_name='ONE_LARGE_ONE_MEDIUM',
        surface_type='TURF_STADIUM', is_active=True,
    ))
    db.commit()

    result = manual_schedule_builder_options(db)
    stadium_fields = [
        field for field in result['fields']
        if field['host_location_id'] == stadium.id
    ]

    assert {field['display_name'] for field in stadium_fields} == {'Field 1', 'Field 3'}
    assert all(field['field_id'] for field in stadium_fields)
    assert db.query(Field).filter_by(host_location_id=stadium.id, is_active=True).count() == 2
    # Repeated option loads reuse the stable canonical records and IDs.
    second = manual_schedule_builder_options(db)
    assert {field['field_id'] for field in second['fields']} == {field['field_id'] for field in stadium_fields}
    db.close()


def test_tim_osmond_options_traverse_active_areas_and_materialize_physical_fields():
    engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    organization = Organization(id=uuid.uuid4(), name='Antioch', is_active=True)
    host = HostLocation(
        id=uuid.uuid4(), organization_id=organization.id,
        name='Tim Osmond Sports Complex', surface_type='GRASS_FIELD', is_active=True,
    )
    other_host = HostLocation(
        id=uuid.uuid4(), organization_id=organization.id,
        name='Another Antioch Park', surface_type='GRASS_FIELD', is_active=True,
    )
    db.add_all([organization, host, other_host]); db.flush()
    areas = [
        PhysicalFieldArea(
            id=uuid.uuid4(), host_location_id=host.id, name=name,
            field_space_type='FULL_SIZE_FIELD', supports_dynamic_configuration=True,
            is_active=True,
        )
        for name in ('Football Field 1', 'Football Field 2', 'Soccer Field')
    ]
    db.add_all(areas); db.flush()
    for area in areas:
        db.add_all([
            FieldConfigurationOption(physical_field_area_id=area.id, name='1 Large + 1 Small', configuration_name='1 Large + 1 Small', large_field_count=1, small_field_count=1, is_active=True),
            FieldConfigurationOption(physical_field_area_id=area.id, name='2 Medium', configuration_name='2 Medium', medium_field_count=2, is_active=True),
            FieldConfigurationOption(physical_field_area_id=area.id, name='3 Small', configuration_name='3 Small', small_field_count=3, is_active=True),
        ])
    inactive = Field(host_location_id=host.id, name='Inactive Field', layout_type='SMALL', is_active=False)
    deleted = Field(host_location_id=host.id, name='Deleted Field', layout_type='LARGE', is_active=True, deleted_at=datetime.now(timezone.utc))
    other = Field(host_location_id=other_host.id, name='Other Small 1', layout_type='SMALL', is_active=True)
    db.add_all([inactive, deleted, other]); db.commit()

    result = manual_schedule_builder_options(db)
    fields = [item for item in result['fields'] if item['host_location_id'] == host.id]

    assert {item['field_type'] for item in fields} == {'LARGE', 'MEDIUM', 'SMALL'}
    assert len([item for item in fields if item['field_type'] == 'LARGE']) == 3
    assert len([item for item in fields if item['field_type'] == 'MEDIUM']) == 6
    assert len([item for item in fields if item['field_type'] == 'SMALL']) == 9
    assert all(item['physical_area_id'] for item in fields)
    assert 'Soccer Field — Small 3' in {item['display_name'] for item in fields}
    assert not {'Inactive Field', 'Deleted Field'} & {item['name'] for item in fields}
    assert all(item['host_location_id'] != other_host.id for item in fields)
    # Loading options again preserves the selected-value IDs.
    second = manual_schedule_builder_options(db)
    assert {item['id'] for item in fields} == {
        item['id'] for item in second['fields'] if item['host_location_id'] == host.id
    }
    db.close()
