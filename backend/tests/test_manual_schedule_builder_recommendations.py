import unittest
import uuid
from datetime import date, time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Division, FieldInstance, GameSlot, HostLocation, Organization, Season, Team, Week
from app.routes.api import manual_schedule_builder_recommendations


class ManualScheduleBuilderRecommendationsTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()

        self.season = Season(id=uuid.uuid4(), name='Spring', start_date=date(2026, 4, 1), end_date=date(2026, 7, 1), is_active=True)
        self.week = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=3, start_date=date(2026, 5, 15), end_date=date(2026, 5, 21))
        self.org = Organization(id=uuid.uuid4(), name='Westosha', is_active=True)
        self.girls_k1 = Division(id=uuid.uuid4(), name='K/1st', division_group='GIRLS', sort_order=1, required_field_layout_type='THIRTY_YARD_WIDTH', is_active=True)
        self.host = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Westosha Park', is_active=True)
        self.fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week.start_date, field_name='Small Field 1', field_type='SMALL', is_active=True)
        self.slot = GameSlot(id=uuid.uuid4(), field_instance_id=self.fi.id, host_location_id=self.host.id, slot_date=self.week.start_date, start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='OPEN')
        self.t1 = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.girls_k1.id, name='Girls K1 A', is_active=True)
        self.t2 = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.girls_k1.id, name='Girls K1 B', is_active=True)

        self.db.add_all([self.season, self.week, self.org, self.girls_k1, self.host, self.fi, self.slot, self.t1, self.t2])
        self.db.commit()

    def test_girls_division_generates_matchups_and_slots(self):
        result = manual_schedule_builder_recommendations(
            {'season_id': self.season.id, 'week_id': self.week.id, 'division_id': self.girls_k1.id},
            db=self.db,
        )

        self.assertGreaterEqual(len(result['suggested_matchups']), 1)
        self.assertGreaterEqual(len(result['suggested_slots']), 1)
        self.assertFalse(result['all_available_weekly_matchups_scheduled'])
        self.assertFalse(result['no_eligible_team_matchups'])


if __name__ == '__main__':
    unittest.main()
