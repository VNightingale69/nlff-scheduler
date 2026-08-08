import unittest
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, HostLocation, HostLocationConfiguration, Organization
from app.routes.api import (
    _approved_layout_codes_for_host,
    _configuration_field_templates_for_host,
    _ensure_approved_turf_configurations,
    _plan_turf_layout_blocks,
    _turf_wave_layout_counts,
)


class JohnsburgFacilityConfigurationTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        self.johnsburg = Organization(id=uuid.uuid4(), name='Johnsburg', is_active=True)
        self.other = Organization(id=uuid.uuid4(), name='Cary', is_active=True)
        self.hosts = {
            name: HostLocation(
                id=uuid.uuid4(), organization_id=self.johnsburg.id, name=name,
                surface_type='TURF_STADIUM', is_active=True,
            )
            for name in ('Johnsburg Stadium', 'Hiller Park', 'Hiller Stadium')
        }
        self.db.add_all([self.johnsburg, self.other, *self.hosts.values()])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _active_mixes(self, host):
        _ensure_approved_turf_configurations(self.db, host)
        self.db.flush()
        return {
            row.configuration_name: (row.small_field_count, row.medium_field_count, row.large_field_count)
            for row in self.db.query(HostLocationConfiguration).filter_by(
                host_location_id=host.id, is_active=True,
            )
        }

    def test_each_facility_exposes_only_its_physical_layout_and_positions(self):
        expected = {
            'Johnsburg Stadium': ({'ONE_LARGE_ONE_MEDIUM': (0, 1, 1)}, [('Field 1', 'LARGE'), ('Field 3', 'MEDIUM')]),
            'Hiller Park': ({'FOUR_SMALL': (4, 0, 0)}, [(f'Field {index}', 'SMALL') for index in range(1, 5)]),
            'Hiller Stadium': ({'TWO_MEDIUM': (0, 2, 0)}, [('Field 1', 'MEDIUM'), ('Field 3', 'MEDIUM')]),
        }
        for name, (mix, fields) in expected.items():
            with self.subTest(facility=name):
                host = self.hosts[name]
                self.assertEqual(self._active_mixes(host), mix)
                code = next(iter(mix))
                self.assertEqual(_configuration_field_templates_for_host(host, code), fields)
                if name != 'Hiller Park':
                    self.assertNotIn('Field 2', dict(fields))
                    self.assertNotIn('Field 4', dict(fields))

    def test_initialization_reuses_facilities_and_configuration_rows_idempotently(self):
        host_ids = {host.id for host in self.hosts.values()}
        stadium = self.hosts['Johnsburg Stadium']
        obsolete = HostLocationConfiguration(
            id=uuid.uuid4(), host_location_id=stadium.id,
            configuration_name='THREE_SMALL', is_active=True,
        )
        self.db.add(obsolete)
        self.db.commit()

        for _ in range(2):
            for host in self.hosts.values():
                _ensure_approved_turf_configurations(self.db, host)
            self.db.commit()

        self.assertEqual({host.id for host in self.hosts.values()}, host_ids)
        self.assertEqual(self.db.query(HostLocation).filter(HostLocation.organization_id == self.johnsburg.id).count(), 3)
        self.assertEqual(self.db.query(HostLocationConfiguration).filter_by(host_location_id=stadium.id, configuration_name='ONE_LARGE_ONE_MEDIUM').count(), 1)
        self.assertFalse(self.db.get(HostLocationConfiguration, obsolete.id).is_active)

    def test_capacity_planning_never_infers_more_simultaneous_games(self):
        expected = {
            'Johnsburg Stadium': ({'SMALL': 0, 'MEDIUM': 1, 'LARGE': 1}, 2),
            'Hiller Park': ({'SMALL': 4, 'MEDIUM': 0, 'LARGE': 0}, 4),
            'Hiller Stadium': ({'SMALL': 0, 'MEDIUM': 2, 'LARGE': 0}, 2),
        }
        for name, (counts, maximum) in expected.items():
            with self.subTest(facility=name):
                host = self.hosts[name]
                codes = _approved_layout_codes_for_host(host)
                code = next(iter(codes))
                self.assertEqual(_turf_wave_layout_counts(code), counts)
                blocks = _plan_turf_layout_blocks({'SMALL': 99, 'MEDIUM': 99, 'LARGE': 99}, 3, set(codes))
                self.assertEqual(blocks, [(code, 1)] * 3)
                self.assertLessEqual(sum(counts.values()), maximum)

    def test_same_named_non_johnsburg_facility_is_unchanged(self):
        host = HostLocation(
            id=uuid.uuid4(), organization_id=self.other.id, name='Hiller Park',
            surface_type='TURF_STADIUM', is_active=True,
        )
        self.db.add(host)
        self.db.commit()
        self.assertEqual(_approved_layout_codes_for_host(host), {
            'THREE_SMALL', 'TWO_SMALL_ONE_MEDIUM', 'TWO_MEDIUM',
            'ONE_SMALL_ONE_LARGE', 'ONE_LARGE',
        })


if __name__ == '__main__':
    unittest.main()
