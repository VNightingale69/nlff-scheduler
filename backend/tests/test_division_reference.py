import unittest
import uuid
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Division, Game, GameStatus, Organization, Season, Team
from app.services.division_reference import division_reference_query


class DivisionReferenceTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        self.current = Season(name='Current', start_date=date(2026, 8, 1), end_date=date(2026, 11, 1), is_active=True)
        self.historical = Season(name='Historical', start_date=date(2025, 8, 1), end_date=date(2025, 11, 1), is_active=False)
        self.current_division = Division(name='K-2', division_group='GIRLS', sort_order=1, required_field_layout_type='SMALL', is_active=True)
        self.legacy_division = Division(name='K/1st', division_group='GIRLS', sort_order=1, required_field_layout_type='SMALL', is_active=False)
        self.org = Organization(name='Community', is_active=True)
        self.status = GameStatus(code='SCHEDULED', label='Scheduled', is_active=True)
        self.db.add_all([self.current, self.historical, self.current_division, self.legacy_division, self.org, self.status])
        self.db.flush()
        home = Team(organization_id=self.org.id, division_id=self.legacy_division.id, name='Historical Home', is_active=False)
        away = Team(organization_id=self.org.id, division_id=self.legacy_division.id, name='Historical Away', is_active=False)
        self.db.add_all([home, away])
        self.db.flush()
        self.db.add(Game(season_id=self.historical.id, home_team_id=home.id, away_team_id=away.id,
                         game_status_id=self.status.id, game_date=date(2025, 9, 1)))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_default_and_active_season_return_only_active_configuration(self):
        for season_id in (None, self.current.id):
            rows = division_reference_query(self.db, season_id).all()
            self.assertEqual([division.name for division in rows], ['K-2'])

    def test_historical_season_returns_retired_division_used_by_its_games(self):
        rows = division_reference_query(self.db, self.historical.id).all()
        self.assertEqual([division.name for division in rows], ['K/1st'])

    def test_unknown_season_returns_no_divisions(self):
        self.assertEqual(division_reference_query(self.db, uuid.uuid4()).count(), 0)


if __name__ == '__main__':
    unittest.main()
