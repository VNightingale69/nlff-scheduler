import unittest
import uuid
from datetime import date, time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import HostLocation, HostPlanSelection, HostingAvailability, Organization, Season, Week
from app.routes.api import _host_availability_matrix_response, create_missing_hosting_availabilities


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
            primary_game_date=date(2026, 6, 6),
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
        self.assertEqual('2026-06-06', response['dates'][0]['game_date'])
        self.assertEqual('2026-06-06', response['dates'][0]['primary_game_date'])
        self.assertEqual('2026-06-06', response['dates'][0]['start_date'])
        self.assertEqual('2026-06-06', response['dates'][0]['end_date'])
        self.assertEqual('Week 1', response['dates'][0]['week_label'])

        rows_by_host = {row['host_location_name']: row for row in response['rows']}
        available_cell = rows_by_host['Available Field']['cells']['2026-06-06']
        unavailable_cell = rows_by_host['Unavailable Field']['cells']['2026-06-06']

        self.assertEqual('AVAILABLE', available_cell['status'])
        self.assertFalse(available_cell['locked'])
        self.assertTrue(available_cell['has_saved_availability'])

        self.assertEqual('NOT_AVAILABLE', unavailable_cell['status'])
        self.assertFalse(unavailable_cell['locked'])
        self.assertFalse(unavailable_cell['has_saved_availability'])

    def test_selected_host_without_matching_availability_renders_not_available(self):
        self.db.add(HostPlanSelection(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            game_date=date(2026, 6, 6),
            community_id=self.unavailable_org.id,
            host_location_id=self.unavailable_host.id,
            status='SELECTED',
        ))
        self.db.commit()

        response = _host_availability_matrix_response(self.db, self.season.id)

        rows_by_host = {row['host_location_name']: row for row in response['rows']}
        cell = rows_by_host['Unavailable Field']['cells']['2026-06-06']
        self.assertEqual('MISSING_AVAILABILITY', cell['status'])
        self.assertFalse(cell['locked'])
        self.assertFalse(cell['has_saved_availability'])
        self.assertEqual('Missing Hosting Availability', cell['reason'])
        self.assertEqual([], response['summaries'][0]['selected_fields'])


    def test_selected_host_with_legacy_non_keyed_availability_is_missing_until_repaired(self):
        self.availability.primary_game_date = None
        self.db.add(HostPlanSelection(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            game_date=date(2026, 6, 6),
            community_id=self.available_org.id,
            host_location_id=self.available_host.id,
            status='SELECTED',
        ))
        self.db.commit()

        response = _host_availability_matrix_response(self.db, self.season.id)
        cell = {row['host_location_name']: row for row in response['rows']}['Available Field']['cells']['2026-06-06']
        self.assertEqual('MISSING_AVAILABILITY', cell['status'])
        self.assertEqual('Missing Hosting Availability', cell['reason'])

        user = type('User', (), {'email': 'admin@example.com'})()
        result = create_missing_hosting_availabilities(
            {'season_id': str(self.season.id), 'game_date': '2026-06-06', 'confirmed': True},
            current_user=user,
            db=self.db,
        )
        self.assertEqual(0, result['created'])
        self.assertEqual(1, result['updated'])
        self.db.refresh(self.availability)
        self.assertEqual(self.week.id, self.availability.week_id)
        self.assertEqual(date(2026, 6, 6), self.availability.primary_game_date)

        repaired_response = _host_availability_matrix_response(self.db, self.season.id)
        repaired_cell = {row['host_location_name']: row for row in repaired_response['rows']}['Available Field']['cells']['2026-06-06']
        self.assertEqual('SELECTED', repaired_cell['status'])
        self.assertTrue(repaired_cell['has_saved_availability'])

    def test_selected_host_uses_lookup_for_capacity_summary(self):
        self.db.add(HostPlanSelection(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            game_date=date(2026, 6, 6),
            community_id=self.available_org.id,
            host_location_id=self.available_host.id,
            availability_id=self.availability.id,
            status='SELECTED',
        ))
        self.db.commit()

        response = _host_availability_matrix_response(self.db, self.season.id)

        summary = response['summaries'][0]
        self.assertEqual([{'community_name': 'Available Org', 'host_location_name': 'Available Field'}], summary['selected_fields'])
        self.assertEqual('Available Field', summary['weekly_host_plan_decision_summary']['selected_capacity_source_summary'][0]['host_location'])

    def test_missing_selection_host_location_logs_warning_without_crashing(self):
        missing_host_id = uuid.uuid4()
        self.db.add(HostPlanSelection(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            game_date=date(2026, 6, 6),
            community_id=self.available_org.id,
            host_location_id=missing_host_id,
            status='SELECTED',
        ))
        self.db.commit()

        with self.assertLogs('app.routes.api', level='WARNING') as logs:
            response = _host_availability_matrix_response(self.db, self.season.id)

        self.assertEqual('2026-06-06', response['dates'][0]['game_date'])
        self.assertTrue(any(str(missing_host_id) in message for message in logs.output))


if __name__ == '__main__':
    unittest.main()
