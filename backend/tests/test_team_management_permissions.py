import unittest
import uuid
from datetime import date, time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.auth import ROLE_COMMUNITY_ADMIN, ROLE_LEAGUE_ADMIN, ROLE_SCHEDULING_ADMIN
from app.database import Base, get_db
from app.main import app
from app.models import Division, Game, GameScore, GameStatus, Organization, OrganizationDivisionParticipation, Role, ScoreHistory, Team, User
from app.security import create_access_token, hash_password


class TeamManagementPermissionsTest(unittest.TestCase):
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
        self.community_role = Role(id=uuid.uuid4(), name=ROLE_COMMUNITY_ADMIN, is_active=True)
        self.scheduling_role = Role(id=uuid.uuid4(), name=ROLE_SCHEDULING_ADMIN, is_active=True)
        self.org = Organization(id=uuid.uuid4(), name='Westosha', is_active=True)
        self.other_org = Organization(id=uuid.uuid4(), name='Other Community', is_active=True)
        self.division = Division(id=uuid.uuid4(), name='K-1', division_group='COED', sort_order=1, required_field_layout_type='SMALL', is_active=True)
        self.other_division = Division(id=uuid.uuid4(), name='2-3', division_group='COED', sort_order=2, required_field_layout_type='SMALL', is_active=True)
        self.league_user = User(id=uuid.uuid4(), email='league@example.com', full_name='League', password_hash=hash_password('Password123!'), role_id=self.league_role.id, organization_id=None, is_active=True)
        self.scheduling_user = User(id=uuid.uuid4(), email='scheduler@example.com', full_name='Scheduler', password_hash=hash_password('Password123!'), role_id=self.scheduling_role.id, organization_id=None, is_active=True)
        self.community_user = User(id=uuid.uuid4(), email='community@example.com', full_name='Community', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.org.id, is_active=True)
        self.other_user = User(id=uuid.uuid4(), email='other@example.com', full_name='Other', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.other_org.id, is_active=True)
        self.own_team = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='Own Team', is_active=True)
        self.other_team = Team(id=uuid.uuid4(), organization_id=self.other_org.id, division_id=self.division.id, name='Other Team', is_active=True)
        self.participation = OrganizationDivisionParticipation(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, is_participating=True, team_count=3, is_active=True)
        self.other_participation = OrganizationDivisionParticipation(id=uuid.uuid4(), organization_id=self.other_org.id, division_id=self.division.id, is_participating=True, team_count=3, is_active=True)
        self.db.add_all([
            self.league_role,
            self.community_role,
            self.scheduling_role,
            self.org,
            self.other_org,
            self.division,
            self.other_division,
            self.league_user,
            self.scheduling_user,
            self.community_user,
            self.other_user,
            self.own_team,
            self.other_team,
            self.participation,
            self.other_participation,
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

    def _token(self, user_id):
        return {'Authorization': f'Bearer {create_access_token(str(user_id))}'}

    def _add_scheduled_game_for_team(self, team):
        opponent = self.other_team if team.id != self.other_team.id else self.own_team
        status = GameStatus(id=uuid.uuid4(), code='SCHEDULED', label='Scheduled', is_active=True)
        game = Game(
            id=uuid.uuid4(),
            home_team_id=team.id,
            away_team_id=opponent.id,
            game_status_id=status.id,
            game_date=date(2026, 9, 12),
            kickoff_time=time(9, 0),
        )
        self.db.add_all([status, game])
        self.db.commit()
        return game

    def test_community_admin_list_teams_is_scoped_to_own_organization(self):
        response = self.client.get('/api/teams?page_size=500', headers=self._token(self.community_user.id))
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()['items']
        self.assertEqual([item['organization_id'] for item in items], [str(self.org.id)])
        self.assertEqual([item['name'] for item in items], ['Own Team'])

    def test_community_admin_create_forces_own_organization(self):
        response = self.client.post(
            '/api/teams',
            headers=self._token(self.community_user.id),
            json={
                'organization_id': str(self.other_org.id),
                'division_id': str(self.other_division.id),
                'name': 'Forced Org Team',
                'coach_name': '  Coach One  ',
                'coach_email': 'COACH.ONE@EXAMPLE.COM',
                'is_active': True,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload['organization_id'], str(self.org.id))
        self.assertEqual(payload['name'], 'Forced Org Team')
        self.assertEqual(payload['coach_name'], 'Coach One')
        self.assertEqual(payload['coach_email'], 'coach.one@example.com')

    def test_community_admin_cannot_update_or_delete_other_organization_team(self):
        update = self.client.patch(
            f'/api/teams/{self.other_team.id}',
            headers=self._token(self.community_user.id),
            json={'name': 'Not Allowed'},
        )
        self.assertEqual(update.status_code, 403)

        delete = self.client.delete(f'/api/teams/{self.other_team.id}', headers=self._token(self.community_user.id))
        self.assertEqual(delete.status_code, 403)
        self.db.expire_all()
        self.assertTrue(self.db.get(Team, self.other_team.id).is_active)


    def test_default_team_list_excludes_inactive_teams(self):
        self.own_team.is_active = False
        self.db.commit()

        response = self.client.get('/api/teams?page_size=500', headers=self._token(self.community_user.id))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['items'], [])

    def test_scheduling_admin_can_include_inactive_teams(self):
        self.own_team.is_active = False
        self.db.commit()

        default_response = self.client.get('/api/teams?page_size=500', headers=self._token(self.scheduling_user.id))
        self.assertEqual(default_response.status_code, 200, default_response.text)
        self.assertNotIn(str(self.own_team.id), [item['id'] for item in default_response.json()['items']])

        response = self.client.get('/api/teams?page_size=500&include_inactive=true', headers=self._token(self.scheduling_user.id))
        self.assertEqual(response.status_code, 200, response.text)
        inactive = next(item for item in response.json()['items'] if item['id'] == str(self.own_team.id))
        self.assertFalse(inactive['is_active'])

    def test_community_admin_cannot_include_inactive_teams(self):
        response = self.client.get('/api/teams?page_size=500&include_inactive=true', headers=self._token(self.community_user.id))
        self.assertEqual(response.status_code, 403)

    def test_delete_soft_deactivates_and_hides_team_from_default_list(self):
        delete = self.client.delete(f'/api/teams/{self.own_team.id}', headers=self._token(self.community_user.id))
        self.assertEqual(delete.status_code, 200, delete.text)
        self.assertEqual(delete.json()['message'], 'Team removed from active teams.')
        self.db.expire_all()
        self.assertFalse(self.db.get(Team, self.own_team.id).is_active)

        response = self.client.get('/api/teams?page_size=500', headers=self._token(self.community_user.id))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['items'], [])

    def test_inactive_team_does_not_count_toward_participation_limit(self):
        self.participation.team_count = 1
        self.own_team.is_active = False
        self.db.commit()

        response = self.client.post(
            '/api/teams',
            headers=self._token(self.community_user.id),
            json={
                'organization_id': str(self.org.id),
                'division_id': str(self.division.id),
                'name': 'Replacement Team',
                'coach_name': 'Replacement Coach',
                'coach_email': 'replacement@example.com',
                'is_active': True,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['name'], 'Replacement Team')

    def test_community_admin_cannot_delete_team_with_scheduled_games(self):
        game = self._add_scheduled_game_for_team(self.own_team)

        response = self.client.delete(f'/api/teams/{self.own_team.id}', headers=self._token(self.community_user.id))
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('already scheduled', response.json()['detail'])
        self.db.expire_all()
        self.assertTrue(self.db.get(Team, self.own_team.id).is_active)
        self.assertIsNotNone(self.db.get(Game, game.id))

    def test_scheduling_admin_can_soft_delete_scheduled_team_without_breaking_game_reference(self):
        game = self._add_scheduled_game_for_team(self.own_team)
        score = GameScore(id=uuid.uuid4(), game_id=game.id, home_score=14, away_score=7, score_status='APPROVED')
        history = ScoreHistory(id=uuid.uuid4(), game_id=game.id, action='score_saved', new_home_score=14, new_away_score=7)
        self.db.add_all([score, history])
        self.db.commit()

        response = self.client.delete(f'/api/teams/{self.own_team.id}', headers=self._token(self.scheduling_user.id))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['scheduled_game_count'], 1)
        self.db.expire_all()
        self.assertFalse(self.db.get(Team, self.own_team.id).is_active)
        self.assertEqual(self.db.get(Game, game.id).home_team_id, self.own_team.id)
        self.assertEqual(self.db.get(GameScore, score.id).game_id, game.id)
        self.assertEqual(self.db.get(ScoreHistory, history.id).game_id, game.id)

    def test_team_creation_requires_coach_name_and_email(self):
        response = self.client.post(
            '/api/teams',
            headers=self._token(self.community_user.id),
            json={
                'organization_id': str(self.org.id),
                'division_id': str(self.division.id),
                'name': 'No Coach Team',
                'is_active': True,
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_invalid_coach_email_is_rejected(self):
        response = self.client.post(
            '/api/teams',
            headers=self._token(self.community_user.id),
            json={
                'organization_id': str(self.org.id),
                'division_id': str(self.division.id),
                'name': 'Bad Email Team',
                'coach_name': 'Bad Email Coach',
                'coach_email': 'not-an-email',
                'is_active': True,
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_community_admin_can_update_own_team_coach_info(self):
        response = self.client.patch(
            f'/api/teams/{self.own_team.id}',
            headers=self._token(self.community_user.id),
            json={'coach_name': ' Updated Coach ', 'coach_email': 'UPDATED.COACH@EXAMPLE.COM'},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload['coach_name'], 'Updated Coach')
        self.assertEqual(payload['coach_email'], 'updated.coach@example.com')

    def test_scheduling_admin_can_update_any_team_coach_info(self):
        response = self.client.patch(
            f'/api/teams/{self.other_team.id}',
            headers=self._token(self.scheduling_user.id),
            json={'coach_name': 'Scheduler Coach', 'coach_email': 'scheduler.coach@example.com'},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['coach_email'], 'scheduler.coach@example.com')

    def test_existing_team_without_coach_info_still_loads(self):
        response = self.client.get('/api/teams?page_size=500', headers=self._token(self.league_user.id))
        self.assertEqual(response.status_code, 200, response.text)
        own = next(item for item in response.json()['items'] if item['id'] == str(self.own_team.id))
        self.assertIsNone(own['coach_name'])
        self.assertIsNone(own['coach_email'])

    def test_league_admin_team_participation_requirement_is_unchanged(self):
        response = self.client.post(
            '/api/teams',
            headers=self._token(self.league_user.id),
            json={
                'organization_id': str(self.org.id),
                'division_id': str(self.other_division.id),
                'name': 'League No Participation',
                'coach_name': 'Coach Two',
                'coach_email': 'coach.two@example.com',
                'is_active': True,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('not participating', response.text)


if __name__ == '__main__':
    unittest.main()
