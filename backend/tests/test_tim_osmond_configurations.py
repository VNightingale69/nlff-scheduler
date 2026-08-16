import unittest
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, Field, FieldConfigurationMember, FieldConfigurationOption, HostLocation, HostLocationConfiguration, Organization, PhysicalFieldArea
from app.services.tosc_field_areas import LEGACY_FIELD_NAMES, TOSC_AREAS, ensure_tosc_physical_areas


class TimOsmondConfigurationTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        organization = Organization(id=uuid.uuid4(), name='Antioch', is_active=True)
        self.host = HostLocation(id=uuid.uuid4(), organization=organization,
            name='Tim Osmond Sports Complex', surface_type='TURF_STADIUM', is_active=True)
        self.db.add_all([organization, self.host]); self.db.flush()
        self.legacy = HostLocationConfiguration(id=uuid.uuid4(), host_location_id=self.host.id,
            configuration_name='4 Small', surface_type='TURF_STADIUM', small_field_count=4, is_active=True)
        self.legacy_fields = [Field(host_location_id=self.host.id, name=name.title(), layout_type='SMALL', is_active=True)
                              for name in LEGACY_FIELD_NAMES]
        self.db.add_all([self.legacy, *self.legacy_fields]); self.db.flush()
        self.db.add(FieldConfigurationMember(field_configuration_id=self.legacy.id, field_id=self.legacy_fields[0].id))
        self.db.commit()
        ensure_tosc_physical_areas(self.db, self.host); self.db.commit()

    def tearDown(self): self.db.close()

    def _area(self, name):
        return self.db.query(PhysicalFieldArea).filter_by(host_location_id=self.host.id, name=name, is_active=True).one()

    def _layouts(self, area):
        return {o.name: (o.large_field_count, o.medium_field_count, o.small_field_count)
                for o in self.db.query(FieldConfigurationOption).filter_by(physical_field_area_id=area.id, is_active=True)}

    def test_tosc_old_configurations_removed(self):
        self.db.refresh(self.legacy)
        self.assertFalse(self.legacy.is_active)
        self.assertTrue(self.legacy.is_legacy)
        self.assertEqual(self.db.query(HostLocationConfiguration).filter_by(host_location_id=self.host.id, is_active=True).count(), 0)

    def test_antioch_tosc_legacy_fields_deleted(self):
        self.assertEqual(self.db.query(Field).filter_by(host_location_id=self.host.id, is_active=True).count(), 0)
        self.assertTrue(all(field.deleted_at is not None for field in self.legacy_fields))
        self.assertEqual(self.db.query(FieldConfigurationMember).count(), 0)

    def test_tosc_generated_slots_are_not_physical_fields(self):
        self.assertEqual(self.db.query(Field).filter_by(host_location_id=self.host.id, is_active=True).count(), 0)
        self.assertEqual(self.db.query(PhysicalFieldArea).filter_by(host_location_id=self.host.id, is_active=True).count(), 3)
        self.assertEqual(self.db.query(FieldConfigurationOption).filter_by(is_active=True).count(), 11)

    def test_tosc_has_three_physical_areas(self):
        self.assertEqual({a.name for a in self.db.query(PhysicalFieldArea).filter_by(host_location_id=self.host.id, is_active=True)}, set(TOSC_AREAS))

    def test_tosc_football_fields_support_required_layouts(self):
        expected = {'1 Large + 1 Small': (1, 0, 1), '2 Medium': (0, 2, 0), '3 Small': (0, 0, 3)}
        self.assertEqual(self._layouts(self._area('Football Field 1')), expected)
        self.assertEqual(self._layouts(self._area('Football Field 2')), expected)

    def test_tosc_soccer_field_supports_all_layouts(self):
        self.assertEqual(self._layouts(self._area('Soccer Field')), {
            '1 Large + 1 Small': (1, 0, 1), '2 Medium': (0, 2, 0), '3 Small': (0, 0, 3),
            '1 Medium + 1 Small': (0, 1, 1), '1 Large': (1, 0, 0)})
        self.assertIn('120 yards × 75 yards', self._area('Soccer Field').notes)

    def test_tosc_areas_can_use_different_layouts_same_hour(self):
        chosen = [self._layouts(self._area('Football Field 1'))['1 Large + 1 Small'],
                  self._layouts(self._area('Football Field 2'))['1 Large + 1 Small'],
                  self._layouts(self._area('Soccer Field'))['2 Medium']]
        self.assertEqual(tuple(map(sum, zip(*chosen))), (2, 2, 2))
        self.assertEqual(sum(sum(x) for x in chosen), 6)

    def test_tosc_soccer_field_can_reconfigure_between_hours(self):
        layouts = self._layouts(self._area('Soccer Field'))
        self.assertEqual(layouts['2 Medium'], (0, 2, 0))
        self.assertEqual(layouts['3 Small'], (0, 0, 3))

    def test_tosc_capacity_validation_is_per_physical_area(self):
        ff1 = self._layouts(self._area('Football Field 1'))['1 Large + 1 Small']
        soccer = self._layouts(self._area('Soccer Field'))['3 Small']
        self.assertTrue((1, 0, 1) <= ff1)
        self.assertFalse(2 <= ff1[0])
        self.assertEqual(soccer[2], 3)
        self.assertFalse(4 <= soccer[2])

    def test_tosc_seed_is_idempotent_and_history_survives(self):
        legacy_id = self.legacy.id
        ensure_tosc_physical_areas(self.db, self.host); self.db.commit()
        self.assertEqual(self.db.query(PhysicalFieldArea).filter_by(host_location_id=self.host.id).count(), 3)
        self.assertIsNotNone(self.db.get(HostLocationConfiguration, legacy_id))


if __name__ == '__main__': unittest.main()
