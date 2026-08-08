import unittest
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, HostLocation, HostLocationConfiguration, Organization
from app.routes.api import (
    _configuration_field_templates,
    _ensure_approved_turf_configurations,
    _select_turf_wave_configuration,
)


class TimOsmondConfigurationTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        organization = Organization(id=uuid.uuid4(), name='Antioch', is_active=True)
        self.host = HostLocation(
            id=uuid.uuid4(), organization_id=organization.id,
            name='Tim Osmond Sports Complex', surface_type='TURF_STADIUM', is_active=True,
        )
        self.db.add_all([organization, self.host])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_exposes_only_consolidated_approved_physical_layouts(self):
        _ensure_approved_turf_configurations(self.db, self.host)
        self.db.flush()

        rows = self.db.query(HostLocationConfiguration).filter_by(
            host_location_id=self.host.id, is_active=True,
        ).all()
        mixes = {
            row.configuration_name: (row.small_field_count, row.medium_field_count, row.large_field_count)
            for row in rows
        }
        self.assertEqual(mixes, {
            'FOUR_SMALL': (4, 0, 0),
            'TWO_SMALL_ONE_MEDIUM': (2, 1, 0),
            'ONE_LARGE_ONE_MEDIUM': (0, 1, 1),
        })
        self.assertNotIn((3, 0, 0), mixes.values())
        self.assertNotIn((0, 2, 0), mixes.values())
        self.assertNotIn((0, 0, 1), mixes.values())
        self.assertNotIn((1, 0, 1), mixes.values())

    def test_generated_field_templates_match_each_physical_mix(self):
        expected = {
            'FOUR_SMALL': ['SMALL'] * 4,
            'TWO_SMALL_ONE_MEDIUM': ['SMALL', 'SMALL', 'MEDIUM'],
            'ONE_LARGE_ONE_MEDIUM': ['MEDIUM', 'LARGE'],
        }
        for code, sizes in expected.items():
            with self.subTest(code=code):
                self.assertEqual([size for _name, size in _configuration_field_templates(code)], sizes)

    def test_auto_select_chooses_layout_by_weekly_size_demand(self):
        approved = {'FOUR_SMALL', 'TWO_SMALL_ONE_MEDIUM', 'ONE_LARGE_ONE_MEDIUM'}
        cases = [
            ({'SMALL': 4, 'MEDIUM': 0, 'LARGE': 0}, 'FOUR_SMALL'),
            ({'SMALL': 2, 'MEDIUM': 1, 'LARGE': 0}, 'TWO_SMALL_ONE_MEDIUM'),
            ({'SMALL': 0, 'MEDIUM': 1, 'LARGE': 1}, 'ONE_LARGE_ONE_MEDIUM'),
        ]
        for demand, expected in cases:
            with self.subTest(demand=demand):
                self.assertEqual(_select_turf_wave_configuration(demand, approved), expected)

    def test_other_stadiums_keep_standard_approved_layouts(self):
        other = HostLocation(
            id=uuid.uuid4(), organization_id=self.host.organization_id,
            name='Johnsburg Stadium', surface_type='TURF_STADIUM', is_active=True,
        )
        self.db.add(other)
        self.db.flush()
        _ensure_approved_turf_configurations(self.db, other)
        active = {
            row.configuration_name for row in self.db.query(HostLocationConfiguration).filter_by(
                host_location_id=other.id, is_active=True,
            )
        }
        self.assertEqual(active, {
            'THREE_SMALL', 'TWO_SMALL_ONE_MEDIUM', 'TWO_MEDIUM',
            'ONE_SMALL_ONE_LARGE', 'ONE_LARGE',
        })


if __name__ == '__main__':
    unittest.main()
