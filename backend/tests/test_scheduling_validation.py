import unittest
import uuid
from datetime import date, time

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Division, Field, FieldInstance, Game, GameSlot, GameStatus, HostLocation, HostingAvailability, Organization, Season, Team, Week
from app.routes.api import create_game, get_scheduled_games_for_season, list_public_games
from app.schemas import GameCreate
from app.services.scheduling_validation import validate_game


class SchedulingValidationTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()

        self.org = Organization(id=uuid.uuid4(), name='Org', is_active=True)
        self.division = Division(id=uuid.uuid4(), name='3rd Grade', required_field_layout_type='THIRTY_YARD_WIDTH', is_active=True)
        self.host = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Park', is_active=True)
        self.field = Field(id=uuid.uuid4(), host_location_id=self.host.id, name='Field A', layout_type='THIRTY_YARD_WIDTH', is_active=True)
        self.home = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='A', is_active=True)
        self.away = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='B', is_active=True)
        self.status = GameStatus(id=uuid.uuid4(), code='scheduled', label='Scheduled', is_active=True)
        self.season = Season(id=uuid.uuid4(), name='Spring', start_date=date(2026, 4, 1), end_date=date(2026, 7, 1), is_active=True)
        self.week = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=1, start_date=date(2026, 5, 1), end_date=date(2026, 5, 7))
        self.db.add_all([self.org, self.division, self.host, self.field, self.home, self.away, self.status, self.season, self.week])
        self.db.commit()

    def add_published_game(
        self,
        *,
        home_team: Team,
        away_team: Team,
        game_date: date = date(2026, 5, 4),
        kickoff_time: time = time(11, 0),
        host_location: HostLocation | None = None,
        field_name: str = 'Field Instance',
    ) -> Game:
        published = self.db.query(GameStatus).filter(GameStatus.code == 'published').first()
        if not published:
            published = GameStatus(id=uuid.uuid4(), code='published', label='Published', is_active=True)
            self.db.add(published)
            self.db.flush()

        host_location = host_location or self.host
        field_instance = FieldInstance(
            id=uuid.uuid4(),
            host_location_id=host_location.id,
            hosting_availability_id=uuid.uuid4(),
            instance_date=game_date,
            field_name=field_name,
            field_type='SMALL',
            is_active=True,
        )
        game = Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            home_team_id=home_team.id,
            away_team_id=away_team.id,
            field_id=self.field.id,
            game_status_id=published.id,
            game_date=game_date,
            kickoff_time=kickoff_time,
        )
        self.db.add(game)
        self.db.flush()
        slot = GameSlot(
            id=uuid.uuid4(),
            field_instance_id=field_instance.id,
            host_location_id=host_location.id,
            slot_date=game_date,
            start_time=kickoff_time,
            end_time=time(kickoff_time.hour + 1, kickoff_time.minute),
            field_type='SMALL',
            status='BOOKED',
            assigned_game_id=game.id,
        )
        self.db.add_all([field_instance, slot])
        self.db.commit()
        return game

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
        self.field.layout_type = 'FIFTY_THREE_YARD_WIDTH'
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

    def test_same_time_different_host_locations_is_allowed(self):
        other_host = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='North Complex', is_active=True)
        other_field = Field(id=uuid.uuid4(), host_location_id=other_host.id, name='Field N1', layout_type='THIRTY_YARD_WIDTH', is_active=True)
        other_home = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='C', is_active=True)
        other_away = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='D', is_active=True)
        self.db.add_all([other_host, other_field, other_home, other_away])
        self.db.add(
            Game(
                id=uuid.uuid4(),
                season_id=self.season.id,
                week_id=self.week.id,
                home_team_id=other_home.id,
                away_team_id=other_away.id,
                field_id=other_field.id,
                game_status_id=self.status.id,
                game_date=date(2026, 5, 3),
                kickoff_time=time(10, 0),
            )
        )
        self.db.commit()
        result = validate_game(self.db, self.base_payload())
        self.assertFalse(any(c.code == 'field_overlap' for c in result.hard_conflicts))
        self.assertFalse(any(c.code == 'team_overlap' for c in result.hard_conflicts))

    def test_same_time_different_fields_same_host_is_allowed(self):
        second_field = Field(id=uuid.uuid4(), host_location_id=self.host.id, name='Field B', layout_type='THIRTY_YARD_WIDTH', is_active=True)
        other_home = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='C', is_active=True)
        other_away = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='D', is_active=True)
        self.db.add_all([second_field, other_home, other_away])
        self.db.add(
            Game(
                id=uuid.uuid4(),
                season_id=self.season.id,
                week_id=self.week.id,
                home_team_id=other_home.id,
                away_team_id=other_away.id,
                field_id=second_field.id,
                game_status_id=self.status.id,
                game_date=date(2026, 5, 3),
                kickoff_time=time(10, 0),
            )
        )
        self.db.commit()
        result = validate_game(self.db, self.base_payload())
        self.assertFalse(any(c.code == 'field_overlap' for c in result.hard_conflicts))
        self.assertFalse(any(c.code == 'team_overlap' for c in result.hard_conflicts))

    def test_create_game_blocks_published_with_hard_conflicts(self):
        published = GameStatus(id=uuid.uuid4(), code='published', label='Published', is_active=True)
        self.db.add(published)
        self.db.commit()
        self.field.layout_type = 'FIFTY_THREE_YARD_WIDTH'
        self.db.commit()
        payload = self.base_payload().model_copy(update={'game_status_id': published.id})
        with self.assertRaises(HTTPException):
            create_game(payload, db=self.db)

    def test_create_game_rejects_draft_schedule_status(self):
        draft = GameStatus(id=uuid.uuid4(), code='draft', label='Draft', is_active=True)
        self.db.add(draft)
        self.db.commit()
        payload = self.base_payload().model_copy(update={'game_status_id': draft.id})
        with self.assertRaises(HTTPException):
            create_game(payload, db=self.db)

    def test_public_games_uses_saved_records_and_excludes_legacy_drafts(self):
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

        self.season.schedule_status = 'draft'
        self.db.commit()

        result = list_public_games(db=self.db)
        self.assertEqual(result.total, 1)
        self.assertEqual(result.items[0].id, published_game.id)
        self.assertEqual(result.items[0].game_status_code, 'published')

    def test_public_games_organization_filter_includes_home_and_away_teams(self):
        antioch = Organization(id=uuid.uuid4(), name='Antioch Vikings', is_active=True)
        other_org = Organization(id=uuid.uuid4(), name='Other Community', is_active=True)
        other_host = HostLocation(id=uuid.uuid4(), organization_id=other_org.id, name='Other Park', is_active=True)
        antioch_home = Team(id=uuid.uuid4(), organization_id=antioch.id, division_id=self.division.id, name='Antioch Home', is_active=True)
        antioch_away = Team(id=uuid.uuid4(), organization_id=antioch.id, division_id=self.division.id, name='Antioch Away', is_active=True)
        opponent = Team(id=uuid.uuid4(), organization_id=other_org.id, division_id=self.division.id, name='Opponent', is_active=True)
        unrelated = Team(id=uuid.uuid4(), organization_id=other_org.id, division_id=self.division.id, name='Unrelated', is_active=True)
        self.db.add_all([antioch, other_org, other_host, antioch_home, antioch_away, opponent, unrelated])
        self.db.commit()

        home_game = self.add_published_game(
            home_team=antioch_home,
            away_team=opponent,
            game_date=date(2026, 5, 4),
            kickoff_time=time(9, 0),
            host_location=other_host,
            field_name='Away Host Field',
        )
        away_game = self.add_published_game(
            home_team=opponent,
            away_team=antioch_away,
            game_date=date(2026, 5, 5),
            kickoff_time=time(10, 0),
            host_location=other_host,
            field_name='Away Team Field',
        )
        self.add_published_game(home_team=opponent, away_team=unrelated, game_date=date(2026, 5, 6), kickoff_time=time(11, 0))

        rows = get_scheduled_games_for_season(
            self.db,
            self.season.id,
            {'organization_id': antioch.id, 'division_id': self.division.id},
            organization_filter_any_team=True,
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual({game.id for game, *_ in rows}, {home_game.id, away_game.id})

    def test_public_games_host_location_filter_remains_location_based(self):
        away_org = Organization(id=uuid.uuid4(), name='Away Community', is_active=True)
        away_host = HostLocation(id=uuid.uuid4(), organization_id=away_org.id, name='Away Park', is_active=True)
        away_team = Team(id=uuid.uuid4(), organization_id=away_org.id, division_id=self.division.id, name='Away Org Team', is_active=True)
        self.db.add_all([away_org, away_host, away_team])
        self.db.commit()

        home_host_game = self.add_published_game(home_team=self.home, away_team=away_team, game_date=date(2026, 5, 4), kickoff_time=time(9, 0), host_location=self.host)
        away_host_game = self.add_published_game(home_team=self.home, away_team=away_team, game_date=date(2026, 5, 5), kickoff_time=time(10, 0), host_location=away_host)

        rows = get_scheduled_games_for_season(self.db, self.season.id, {'host_location_id': away_host.id}, organization_filter_any_team=True)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0].id, away_host_game.id)
        self.assertNotEqual(rows[0][0].id, home_host_game.id)

    def test_public_games_team_filter_still_narrows_organization_filter(self):
        antioch = Organization(id=uuid.uuid4(), name='Antioch Vikings', is_active=True)
        opponent_org = Organization(id=uuid.uuid4(), name='Opponent Community', is_active=True)
        antioch_a = Team(id=uuid.uuid4(), organization_id=antioch.id, division_id=self.division.id, name='Antioch A', is_active=True)
        antioch_b = Team(id=uuid.uuid4(), organization_id=antioch.id, division_id=self.division.id, name='Antioch B', is_active=True)
        opponent = Team(id=uuid.uuid4(), organization_id=opponent_org.id, division_id=self.division.id, name='Opponent', is_active=True)
        self.db.add_all([antioch, opponent_org, antioch_a, antioch_b, opponent])
        self.db.commit()

        selected_team_game = self.add_published_game(home_team=opponent, away_team=antioch_a, game_date=date(2026, 5, 4), kickoff_time=time(9, 0))
        self.add_published_game(home_team=opponent, away_team=antioch_b, game_date=date(2026, 5, 5), kickoff_time=time(10, 0))

        rows = get_scheduled_games_for_season(
            self.db,
            self.season.id,
            {'organization_id': antioch.id, 'team_id': antioch_a.id},
            organization_filter_any_team=True,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0].id, selected_team_game.id)


if __name__ == '__main__':
    unittest.main()
