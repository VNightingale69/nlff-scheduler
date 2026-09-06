import unittest
import uuid
from datetime import date, time
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (Field, FieldConfigurationMember, HostLocation,
                        HostLocationConfiguration, Organization)
from app.services.facility_layout_validation import (get_active_supported_layouts,
                                                      validate_field_configuration)


class WestoshaConfigurationResolverTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        organization = Organization(id=uuid.uuid4(), name='Westosha', is_active=True)
        self.host = HostLocation(
            id=uuid.uuid4(), organization_id=organization.id,
            name='Westosha High School Stadium', surface_type='TURF_STADIUM',
        )
        self.large_one = Field(
            id=uuid.uuid4(), host_location_id=self.host.id,
            name='Large Field 1', layout_type='LARGE', is_active=True,
        )
        self.large_two = Field(
            id=uuid.uuid4(), host_location_id=self.host.id,
            name='Large Field 2', layout_type='LARGE', is_active=True,
        )
        self.small_two = Field(
            id=uuid.uuid4(), host_location_id=self.host.id,
            name='Small Field 2', layout_type='SMALL', is_active=True,
        )
        self.one_large = HostLocationConfiguration(
            id=uuid.uuid4(), host_location_id=self.host.id,
            configuration_name='ONE_LARGE', large_field_count=1, is_active=True,
        )
        self.one_large.members = [FieldConfigurationMember(field=self.large_one)]
        self.two_large = HostLocationConfiguration(
            id=uuid.uuid4(), host_location_id=self.host.id,
            configuration_name='TWO_LARGE', large_field_count=2, is_active=True,
        )
        self.two_large.members = [
            FieldConfigurationMember(field=self.large_one),
            FieldConfigurationMember(field=self.large_two),
        ]
        self.db.add_all([
            organization, self.host, self.large_one, self.large_two,
            self.small_two, self.one_large, self.two_large,
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def validate(self, kickoff, fields):
        return validate_field_configuration(
            self.db, self.host.id, date(2026, 9, 27), kickoff,
            [{'field_id': field.id, 'field_name': field.name,
              'required_field_size': field.layout_type} for field in fields],
        )

    def test_september_27_waves_resolve_independently_and_exactly(self):
        one_and_one = self.validate(time(13), [self.large_one, self.small_two])
        at_two = self.validate(time(14), [self.large_one])
        at_three = self.validate(time(15), [self.large_one])

        self.assertTrue(one_and_one['is_valid'])
        self.assertEqual('ONE_LARGE_ONE_SMALL', one_and_one['configuration_name'])
        for result in (at_two, at_three):
            self.assertTrue(result['is_valid'])
            self.assertEqual('ONE_LARGE', result['configuration_name'])
            self.assertEqual([], result['blocking_issues'])

    def test_two_simultaneous_large_games_are_blocked(self):
        result = self.validate(time(14), [self.large_one, self.large_two])

        self.assertFalse(result['is_valid'])
        self.assertTrue(result['is_blocking'])
        self.assertEqual('FIELD_LAYOUT_CONFLICT', result['issue_code'])

    def test_invalid_two_large_is_never_exposed_even_if_database_row_is_active(self):
        layouts = get_active_supported_layouts(self.db, self.host.id)

        self.assertNotIn('TWO_LARGE', {layout.configuration_name for layout in layouts})
        loaded_one_large = next(layout for layout in layouts
                                if layout.configuration_name == 'ONE_LARGE')
        self.assertEqual(1, loaded_one_large.large_field_count)
        self.assertEqual(['Large Field 1'],
                         [member.field.name for member in loaded_one_large.members])


class WestoshaMigrationTest(unittest.TestCase):
    def test_repair_is_host_scoped_and_idempotent(self):
        source = Path(
            'alembic/versions/20260906_0082_repair_westosha_large_layout.py'
        ).read_text()

        self.assertIn("'westosha high school stadium', 'westosha stadium'", source)
        self.assertIn("= 'TWO_LARGE'", source)
        self.assertIn("configuration_name = 'ONE_LARGE'", source)
        self.assertIn('large_field_count = 1', source)
        self.assertIn("lower(trim(name)) = 'large field 1'", source)
        self.assertIn('DELETE FROM field_configuration_members', source)
        self.assertIn('VALUES (gen_random_uuid(), :configuration_id, :field_id', source)


if __name__ == '__main__':
    unittest.main()
