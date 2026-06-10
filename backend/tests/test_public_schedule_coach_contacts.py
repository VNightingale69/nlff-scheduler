import unittest
import uuid
from datetime import date, time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import ROLE_COMMUNITY_ADMIN, ROLE_LEAGUE_ADMIN, ROLE_SCHEDULING_ADMIN
from app.database import Base, get_db
from app.main import app
from app.models import Division, Game, GameStatus, HostLocation, Organization, Role, Season, Team, User
from app.security import create_access_token, hash_password


class PublicScheduleCoachContactsTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            'sqlite+pysqlite:///:memory:',
            connect_args={'check_same_thread': False},
            poolclass=StaticPool,
            future=True,
        )
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.db = self.SessionLocal()

        self.league_role = Role(id=uuid.uuid4(), name=ROLE_LEAGUE_ADMIN, is_active=True)
        self.scheduling_role = Role(id=uuid.uuid4(), name=ROLE_SCHEDULING_ADMIN, is_active=True)
        self.community_role = Role(id=uuid.uuid4(), name=ROLE_COMMUNITY_ADMIN, is_active=True)
        self.home_org = Organization(id=uuid.uuid4(), name='Home Community', is_active=True)
        self.away_org = Organization(id=uuid.uuid4(), name='Away Community', is_active=True)
        self.other_org = Organization(id=uuid.uuid4(), name='Other Community', is_active=True)
        self.division = Division(id=uuid.uuid4(), name='K-1', division_group='COED', sort_order=1, required_field_layout_type='SMALL', is_active=True)
        self.season = Season(id=uuid.uuid4(), name='Fall 2026', start_date=date(2026, 8, 1), end_date=date(2026, 11, 1), schedule_status='published', is_active=True)
        self.status = GameStatus(id=uuid.uuid4(), code='SCHEDULED', label='Scheduled', is_active=True)
        self.host = HostLocation(id=uuid.uuid4(), organization_id=self.home_org.id, name='Home Field', is_active=True)
        self.home_team = Team(id=uuid.uuid4(), organization_id=self.home_org.id, division_id=self.division.id, name='Home Team', coach_name='Home Coach', coach_email='home.coach@example.com', is_active=True)
        self.away_team = Team(id=uuid.uuid4(), organization_id=self.away_org.id, division_id=self.division.id, name='Away Team', coach_name='Away Coach', coach_email='away.coach@example.com', is_active=True)
        self.game = Game(id=uuid.uuid4(), season_id=self.season.id, home_team_id=self.home_team.id, away_team_id=self.away_team.id, host_location_id=self.host.id, game_status_id=self.status.id, game_date=date(2026, 8, 9), kickoff_time=time(9, 0))
        self.scheduler = User(id=uuid.uuid4(), email='scheduler@example.com', full_name='Scheduler', password_hash=hash_password('Password123!'), role_id=self.scheduling_role.id, is_active=True)
        self.home_admin = User(id=uuid.uuid4(), email='home@example.com', full_name='Home Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.home_org.id, is_active=True)
        self.other_admin = User(id=uuid.uuid4(), email='other@example.com', full_name='Other Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.other_org.id, is_active=True)
        self.db.add_all([
            self.league_role, self.scheduling_role, self.community_role,
            self.home_org, self.away_org, self.other_org, self.division, self.season,
            self.status, self.host, self.home_team, self.away_team, self.game,
            self.scheduler, self.home_admin, self.other_admin,
        ])
        self.db.commit()

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def _headers(self, user_id):
        return {'Authorization': f'Bearer {create_access_token(str(user_id))}'}

    def _first_public_game(self, headers=None):
        response = self.client.get('/api/public/schedule', headers=headers or {})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['items'][0]

    def test_public_schedule_does_not_expose_coach_emails_unauthenticated(self):
        row = self._first_public_game()
        self.assertEqual(row['home_team_coach_name'], 'Home Coach')
        self.assertEqual(row['away_team_coach_name'], 'Away Coach')
        self.assertIsNone(row['home_team_coach_email'])
        self.assertIsNone(row['away_team_coach_email'])
        self.assertFalse(row['coach_contacts_visible'])

    def test_scheduling_admin_sees_all_coach_contacts(self):
        row = self._first_public_game(self._headers(self.scheduler.id))
        self.assertEqual(row['home_team_coach_email'], 'home.coach@example.com')
        self.assertEqual(row['away_team_coach_email'], 'away.coach@example.com')
        self.assertTrue(row['coach_contacts_visible'])

    def test_community_admin_sees_contacts_for_games_involving_their_community(self):
        row = self._first_public_game(self._headers(self.home_admin.id))
        self.assertEqual(row['home_team_coach_email'], 'home.coach@example.com')
        self.assertEqual(row['away_team_coach_email'], 'away.coach@example.com')
        self.assertTrue(row['coach_contacts_visible'])

    def test_community_admin_does_not_see_contacts_for_unrelated_games(self):
        row = self._first_public_game(self._headers(self.other_admin.id))
        self.assertIsNone(row['home_team_coach_email'])
        self.assertIsNone(row['away_team_coach_email'])
        self.assertFalse(row['coach_contacts_visible'])


if __name__ == '__main__':
    unittest.main()
