import unittest
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Field, FieldConfigurationMember, HostLocation, HostLocationConfiguration, Organization, Role, User
from app.routes.api import _validate_configuration_activation, list_host_location_configurations
from app.services.facility_layout_validation import field_combination_diagnostics, validate_field_combination


class SupportedFieldLayoutActivationTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.org = Organization(id=uuid.uuid4(), name='Example Community', is_active=True)
        self.host = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Example Park', surface_type='GRASS_FIELD')
        self.role = Role(id=uuid.uuid4(), name='LEAGUE_ADMIN', is_active=True)
        self.admin = User(id=uuid.uuid4(), email='admin@example.com', full_name='Admin', password_hash='x', role=self.role, is_active=True)
        self.fields = [Field(id=uuid.uuid4(), host_location_id=self.host.id, name=f'Small {number}', layout_type='SMALL', is_active=True) for number in range(1, 5)]
        self.large = Field(id=uuid.uuid4(), host_location_id=self.host.id, name='Large 1', layout_type='LARGE', is_active=True)
        self.medium = Field(id=uuid.uuid4(), host_location_id=self.host.id, name='Medium 1', layout_type='MEDIUM', is_active=True)
        self.canonical = HostLocationConfiguration(id=uuid.uuid4(), host_location_id=self.host.id, configuration_name='4 Small', is_active=True)
        self.canonical.members = [FieldConfigurationMember(field=field) for field in self.fields]
        self.alternatives = [
            self._layout('2 Small + 1 Medium', [self.fields[0], self.fields[1], self.medium]),
            self._layout('1 Large + 1 Medium', [self.large, self.medium]),
            self._layout('1 Large + 1 Small', [self.large, self.fields[0]]),
        ]
        self.legacy = HostLocationConfiguration(id=uuid.uuid4(), host_location_id=self.host.id, configuration_name='FOUR_SMALL', is_active=False, is_legacy=True)
        self.legacy.members = [FieldConfigurationMember(field=field) for field in self.fields]
        self.db.add_all([self.org, self.host, self.role, self.admin, *self.fields, self.large, self.medium,
                         self.canonical, *self.alternatives, self.legacy])
        self.db.commit()

    def _layout(self, name, fields):
        layout = HostLocationConfiguration(id=uuid.uuid4(), host_location_id=self.host.id, configuration_name=name, is_active=True)
        layout.members = [FieldConfigurationMember(field=field) for field in fields]
        return layout

    def tearDown(self):
        self.db.close()

    def test_overlapping_alternative_membership_can_be_activated(self):
        _validate_configuration_activation(self.db, self.legacy)

    def test_legacy_layout_is_hidden_by_default(self):
        result = list_host_location_configurations(host_location_id=self.host.id, current_user=self.admin, db=self.db)
        names = {configuration.configuration_name for configuration in result.items}
        self.assertEqual({'4 Small', '2 Small + 1 Medium', '1 Large + 1 Medium', '1 Large + 1 Small'}, names)
        self.assertEqual(4, len(result.items))
        members = {configuration.configuration_name: set(configuration.field_instances) for configuration in result.items}
        self.assertEqual({'Small 1', 'Small 2', 'Small 3', 'Small 4'}, members['4 Small'])
        self.assertEqual({'Small 1', 'Small 2', 'Medium 1'}, members['2 Small + 1 Medium'])
        self.assertEqual({'Large 1', 'Medium 1'}, members['1 Large + 1 Medium'])
        self.assertEqual({'Large 1', 'Small 1'}, members['1 Large + 1 Small'])

    def test_scheduler_accepts_subsets_of_any_active_membership(self):
        valid, layouts, _used = validate_field_combination(self.db, self.host.id, [self.fields[0].id, self.fields[1].id])
        self.assertTrue(valid)
        self.assertIn('4 Small', layouts)

    def test_scheduler_accepts_all_four_physical_field_ids(self):
        valid, layouts, _used = validate_field_combination(
            self.db, self.host.id, [field.id for field in self.fields],
        )
        diagnostics = field_combination_diagnostics(
            self.db, self.host.id, [field.id for field in self.fields],
        )

        self.assertTrue(valid)
        self.assertIn('4 Small', layouts)
        self.assertEqual('4 Small', diagnostics['compatible_configuration'])

    def test_active_empty_layout_is_not_legacy_all_fields_fallback(self):
        for configuration in [self.canonical, *self.alternatives]:
            configuration.is_active = False
        empty = HostLocationConfiguration(
            host_location_id=self.host.id, configuration_name='Empty active layout', is_active=True,
        )
        self.db.add(empty)
        self.db.commit()

        valid, layouts, _used = validate_field_combination(self.db, self.host.id, [self.fields[0].id])
        diagnostics = field_combination_diagnostics(self.db, self.host.id, [self.fields[0].id])

        self.assertFalse(valid)
        self.assertEqual(['Empty active layout'], layouts)
        self.assertEqual('ACTIVE BUT INVALID', diagnostics['configurations'][0]['status'])
        self.assertEqual('Configuration contains no assigned physical fields.', diagnostics['configurations'][0]['reason'])

    def test_activation_error_uses_administrator_guidance(self):
        empty = HostLocationConfiguration(
            host_location_id=self.host.id, configuration_name='Empty', is_active=True,
        )
        with self.assertRaises(HTTPException) as raised:
            _validate_configuration_activation(self.db, empty)
        self.assertEqual(
            'A field layout must contain at least one physical field before it can be activated.',
            raised.exception.detail['message'],
        )

    def test_scheduler_accepts_an_alternative_active_configuration(self):
        valid, layouts, _used = validate_field_combination(
            self.db, self.host.id, [self.large.id, self.medium.id],
        )

        self.assertTrue(valid)
        self.assertIn('1 Large + 1 Medium', layouts)
        self.assertGreater(len(layouts), 1)

    def test_inactive_configuration_is_excluded(self):
        valid, layouts, _used = validate_field_combination(
            self.db, self.host.id, [self.fields[2].id, self.fields[3].id],
        )

        self.assertTrue(valid)
        self.assertNotIn('FOUR_SMALL', layouts)

    def test_soft_deleted_configuration_member_is_excluded(self):
        self.large.deleted_at = datetime.now(timezone.utc)
        self.db.commit()

        valid, layouts, _used = validate_field_combination(
            self.db, self.host.id, [self.large.id, self.medium.id],
        )

        self.assertFalse(valid)
        self.assertIn('1 Large + 1 Medium', layouts)

    def test_legacy_active_field_fallback_excludes_soft_deleted_fields(self):
        for configuration in [self.canonical, *self.alternatives]:
            configuration.is_active = False
        self.fields[0].deleted_at = datetime.now(timezone.utc)
        self.db.commit()

        valid, layouts, active = validate_field_combination(
            self.db, self.host.id, [self.fields[0].id],
        )

        self.assertFalse(valid)
        self.assertEqual([], layouts)
        self.assertNotIn(self.fields[0].id, active)

    def test_legacy_active_field_fallback_returns_active_fields_without_row_attribute_error(self):
        for configuration in [self.canonical, *self.alternatives]:
            configuration.is_active = False
        self.db.commit()

        valid, layouts, active = validate_field_combination(
            self.db, self.host.id, [self.fields[0].id],
        )

        self.assertTrue(valid)
        self.assertEqual([], layouts)
        self.assertIn(self.fields[0].id, active)


if __name__ == '__main__':
    unittest.main()
