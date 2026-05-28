import unittest
import uuid
from datetime import date, time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Division, Game, GameStatus, Organization, Season, Team, Week
from app.routes.api import build_schedule_quality_report, publish_schedule


class PublishQualityConsistencyTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        self.season = Season(id=uuid.uuid4(), name='Spring', start_date=date(2026, 4, 1), end_date=date(2026, 6, 1), is_active=True, schedule_status='draft')
        self.division = Division(id=uuid.uuid4(), name='5th Grade', required_field_layout_type='THIRTY_YARD_WIDTH', is_active=True)
        self.status = GameStatus(id=uuid.uuid4(), code='SCHEDULED', label='Scheduled', is_active=True)
        self.week = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=1, start_date=date(2026, 4, 5), end_date=date(2026, 4, 11))
        self.org = Organization(id=uuid.uuid4(), name='Org', is_active=True)
        self.team_a = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='A', is_active=True)
        self.team_b = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='B', is_active=True)
        self.db.add_all([self.season, self.division, self.status, self.week, self.org, self.team_a, self.team_b])
        self.db.add(Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            home_team_id=self.team_a.id,
            away_team_id=self.team_b.id,
            game_status_id=self.status.id,
            game_date=self.week.start_date,
            kickoff_time=time(10, 0),
        ))
        self.db.commit()

    def test_publish_uses_same_quality_report_source(self):
        report = build_schedule_quality_report(self.db, self.season.id)
        self.assertEqual(report['overall_health'], 'Excellent')
        self.assertEqual(report['hard_errors'], [])
        self.assertEqual(report['metrics']['conflicts'], 0)
        response = publish_schedule(self.season.id, db=self.db)
        self.assertTrue(response['ok'])
        self.assertEqual(response['overall_health'], 'Excellent')

