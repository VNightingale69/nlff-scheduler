import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Field, HostLocation, Organization
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
