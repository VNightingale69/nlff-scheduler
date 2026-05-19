import unittest
import uuid
from datetime import date, time

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Division, Field, Game, GameStatus, HostLocation, HostingAvailability, Organization, Season, Team, Week
from app.routes.api import create_game, list_public_games
from app.schemas import GameCreate
from app.services.scheduling_validation import validate_game


class SchedulingValidationTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()

        self.org = Organization(id=uuid.uuid4(), name='Org', is_active=True)
        self.division = Division(id=uuid.uuid4(), name='U10', required_field_layout_type='7v7', is_active=True)
        self.host = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Park', is_active=True)
        self.field = Field(id=uuid.uuid4(), host_location_id=self.host.id, name='Field A', layout_type='7v7', is_active=True)
        self.home = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='A', is_active=True)
        self.away = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='B', is_active=True)
        self.status = GameStatus(id=uuid.uuid4(), code='scheduled', label='Scheduled', is_active=True)
        self.season = Season(id=uuid.uuid4(), name='Spring', start_date=date(2026, 4, 1), end_date=date(2026, 7, 1), is_active=True)
        self.week = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=1, start_date=date(2026, 5, 1), end_date=date(2026, 5, 7))
        self.db.add_all([self.org, self.division, self.host, self.field, self.home, self.away, self.status, self.season, self.week])
        self.db.commit()

    def base_payload(self) -> GameCreate:
        return GameCreate(
            season_id=self.season.id,
            week_id=self.week.id,
            division_id=self.division.id,
            home_team_id=self.home.id,
            away_team_id=self.away.id,
            field_id=self.field.id,
            game_status_id=self.status.id,
            game_date=date(2026, 5, 3),
            kickoff_time=time(10, 0),
        )

    def test_field_layout_validation(self):
        self.field.layout_type = '5v5'
        self.db.commit()
        result = validate_game(self.db, self.base_payload())
        self.assertTrue(any(c.code == 'layout_mismatch' for c in result.hard_conflicts))

    def test_team_overlap_validation(self):
        other = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='C', is_active=True)
        self.db.add(other)
        self.db.add(Game(id=uuid.uuid4(), season_id=self.season.id, week_id=self.week.id, home_team_id=self.home.id, away_team_id=other.id, field_id=self.field.id, game_status_id=self.status.id, game_date=date(2026, 5, 3), kickoff_time=time(10, 30)))
        self.db.commit()
        result = validate_game(self.db, self.base_payload())
        self.assertTrue(any(c.code == 'team_overlap' for c in result.hard_conflicts))

    def test_create_game_blocks_published_with_hard_conflicts(self):
        published = GameStatus(id=uuid.uuid4(), code='published', label='Published', is_active=True)
        self.db.add(published)
        self.db.commit()
        self.field.layout_type = '5v5'
        self.db.commit()
        payload = self.base_payload().model_copy(update={'game_status_id': published.id})
        with self.assertRaises(HTTPException):
            create_game(payload, db=self.db)

    def test_create_game_allows_draft_with_hard_conflicts(self):
        draft = GameStatus(id=uuid.uuid4(), code='draft', label='Draft', is_active=True)
        self.db.add(draft)
        self.db.commit()
        self.field.layout_type = '5v5'
        self.db.commit()
        payload = self.base_payload().model_copy(update={'game_status_id': draft.id})
        result = create_game(payload, db=self.db)
        self.assertEqual(result.game.status_code, 'draft')

    def test_public_games_excludes_drafts(self):
        published = GameStatus(id=uuid.uuid4(), code='published', label='Published', is_active=True)
        draft = GameStatus(id=uuid.uuid4(), code='draft', label='Draft', is_active=True)
        self.db.add_all([published, draft])
        self.db.commit()

        draft_game = Game(
            id=uuid.uuid4(), season_id=self.season.id, week_id=self.week.id, home_team_id=self.home.id, away_team_id=self.away.id,
            field_id=self.field.id, game_status_id=draft.id, game_date=date(2026, 5, 3), kickoff_time=time(11, 0)
        )
        published_game = Game(
            id=uuid.uuid4(), season_id=self.season.id, week_id=self.week.id, home_team_id=self.home.id, away_team_id=self.away.id,
            field_id=self.field.id, game_status_id=published.id, game_date=date(2026, 5, 4), kickoff_time=time(11, 0)
        )
        self.db.add_all([draft_game, published_game])
        self.db.commit()

        result = list_public_games(db=self.db)
        self.assertEqual(result.total, 1)
        self.assertEqual(result.items[0].id, published_game.id)
        self.assertEqual(result.items[0].game_status_code, 'published')


if __name__ == '__main__':
    unittest.main()
