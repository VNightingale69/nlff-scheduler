import unittest
import uuid
from datetime import date, time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Division, FieldInstance, Game, GameSlot, GameStatus, HostLocation, Organization, Season, Team, Week
from app.routes.api import auto_fill_apply, auto_fill_preview


class AutoFillPreviewTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        self.season = Season(id=uuid.uuid4(), name='Spring', start_date=date(2026, 4, 1), end_date=date(2026, 7, 1), is_active=True)
        self.division = Division(id=uuid.uuid4(), name='4th Grade', required_field_layout_type='THIRTY_YARD_WIDTH', is_active=True)
        self.status = GameStatus(id=uuid.uuid4(), code='SCHEDULED', label='Scheduled', is_active=True)
        self.week1 = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=1, start_date=date(2026, 5, 1), end_date=date(2026, 5, 7))
        self.week2 = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=2, start_date=date(2026, 5, 8), end_date=date(2026, 5, 14))
        self.org_w = Organization(id=uuid.uuid4(), name='Westosha', is_active=True)
        self.org_a = Organization(id=uuid.uuid4(), name='Antioch', is_active=True)
        self.host = HostLocation(id=uuid.uuid4(), organization_id=self.org_w.id, name='Westosha Park', is_active=True)
        self.fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Small Field 1', field_type='SMALL', is_active=True)
        self.slot = GameSlot(id=uuid.uuid4(), field_instance_id=self.fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='OPEN')
        self.wm = Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=self.division.id, name='Westosha Maroon', is_active=True)
        self.wg = Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=self.division.id, name='Westosha Gold', is_active=True)
        self.ab = Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=self.division.id, name='Antioch Black', is_active=True)
        self.as_ = Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=self.division.id, name='Antioch Silver', is_active=True)
        self.db.add_all([self.season, self.division, self.status, self.week1, self.week2, self.org_w, self.org_a, self.host, self.fi, self.slot, self.wm, self.wg, self.ab, self.as_])
        self.db.add(Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week1.id,
            home_team_id=self.wm.id,
            away_team_id=self.ab.id,
            game_status_id=self.status.id,
            game_date=self.week1.start_date,
            kickoff_time=time(10, 0),
        ))
        self.db.commit()

    def test_avoids_prior_week_exact_matchup_when_alternatives_exist(self):
        result = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)
        self.assertEqual(result['proposed_game_count'], 1)
        matchup = result['proposals'][0]['proposed_matchup']
        self.assertNotEqual(matchup, 'Westosha Maroon vs Antioch Black')
        self.assertIn('Avoids prior-week team repeat', result['proposals'][0]['reason'])
        self.assertIn('Avoids prior-week community repeat', result['proposals'][0]['reason'])




    def test_apply_skips_duplicate_matchup_with_friendly_message(self):
        # existing week 2 scheduled game in reverse order to ensure order-insensitive duplicate detection
        self.db.add(Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            home_team_id=self.ab.id,
            away_team_id=self.wm.id,
            game_status_id=self.status.id,
            game_date=self.week2.start_date,
            kickoff_time=time(11, 0),
        ))

        slot2 = GameSlot(
            id=uuid.uuid4(),
            field_instance_id=self.fi.id,
            host_location_id=self.host.id,
            slot_date=self.week2.start_date,
            start_time=time(10, 0),
            end_time=time(11, 0),
            field_type='SMALL',
            status='OPEN',
        )
        self.db.add(slot2)
        self.db.commit()

        payload = {
            'season_id': self.season.id,
            'week_id': self.week2.id,
            'division_id': self.division.id,
            'proposals': [
                {
                    'slot_id': str(self.slot.id),
                    'home_team_id': str(self.wm.id),
                    'away_team_id': str(self.ab.id),
                },
                {
                    'slot_id': str(slot2.id),
                    'home_team_id': str(self.wg.id),
                    'away_team_id': str(self.as_.id),
                },
            ],
        }

        result = auto_fill_apply(payload, db=self.db)

        self.assertEqual(result['created_games'], 1)
        self.assertEqual(len(result['skipped']), 1)
        skipped_message = result['skipped'][0]
        self.assertIn('Skipped Westosha Maroon vs Antioch Black because that matchup is already scheduled in Week 2.', skipped_message)
        self.assertIn('Date:', skipped_message)
        self.assertIn('Time:', skipped_message)
        self.assertNotIn(str(self.slot.id), skipped_message)

if __name__ == '__main__':
    unittest.main()
