import unittest
import uuid
from datetime import date, time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import HostLocation, HostingAvailability, Organization, Season, Week
from app.routes.api import _host_availability_matrix_response


class HostAvailabilityMatrixResponseTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()

        self.season = Season(id=uuid.uuid4(), name='2026', start_date=date(2026, 6, 1), end_date=date(2026, 8, 31), is_active=True)
        self.week = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=1, label='Week 1', start_date=date(2026, 6, 6), end_date=date(2026, 6, 6), primary_game_date=date(2026, 6, 6))
        self.available_org = Organization(id=uuid.uuid4(), name='Available Org', is_active=True)
        self.unavailable_org = Organization(id=uuid.uuid4(), name='Unavailable Org', is_active=True)
        self.available_host = HostLocation(id=uuid.uuid4(), organization_id=self.available_org.id, name='Available Field', is_active=True, max_small_fields=1)
        self.unavailable_host = HostLocation(id=uuid.uuid4(), organization_id=self.unavailable_org.id, name='Unavailable Field', is_active=True, max_small_fields=1)
        self.availability = HostingAvailability(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            organization_id=self.available_org.id,
            host_location_id=self.available_host.id,
            available_date=date(2026, 6, 6),
            start_time=time(9, 0),
            end_time=time(10, 0),
            active=True,
            is_available=True,
        )
        self.db.add_all([
            self.season,
            self.week,
            self.available_org,
            self.unavailable_org,
            self.available_host,
            self.unavailable_host,
            self.availability,
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_available_and_unavailable_cells_without_selections_do_not_lock(self):
        response = _host_availability_matrix_response(self.db, self.season.id)
        rows_by_host = {row['host_location_name']: row for row in response['rows']}
        available_cell = rows_by_host['Available Field']['cells']['2026-06-06']
        unavailable_cell = rows_by_host['Unavailable Field']['cells']['2026-06-06']

        self.assertEqual('AVAILABLE', available_cell['status'])
        self.assertFalse(available_cell['locked'])
        self.assertTrue(available_cell['has_saved_availability'])

        self.assertEqual('NOT_AVAILABLE', unavailable_cell['status'])
        self.assertFalse(unavailable_cell['locked'])
        self.assertFalse(unavailable_cell['has_saved_availability'])


if __name__ == '__main__':
    unittest.main()
