import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.auth import ROLE_COMMUNITY_ADMIN, ROLE_LEAGUE_ADMIN
from app.database import Base, get_db
from app.main import app
from app.models import Division, Organization, OrganizationDivisionParticipation, Role, Team, User
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
        self.org = Organization(id=uuid.uuid4(), name='Westosha', is_active=True)
        self.other_org = Organization(id=uuid.uuid4(), name='Other Community', is_active=True)
        self.division = Division(id=uuid.uuid4(), name='K-1', division_group='COED', sort_order=1, required_field_layout_type='SMALL', is_active=True)
        self.other_division = Division(id=uuid.uuid4(), name='2-3', division_group='COED', sort_order=2, required_field_layout_type='SMALL', is_active=True)
        self.league_user = User(id=uuid.uuid4(), email='league@example.com', full_name='League', password_hash=hash_password('Password123!'), role_id=self.league_role.id, organization_id=None, is_active=True)
        self.community_user = User(id=uuid.uuid4(), email='community@example.com', full_name='Community', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.org.id, is_active=True)
        self.other_user = User(id=uuid.uuid4(), email='other@example.com', full_name='Other', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.other_org.id, is_active=True)
        self.own_team = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='Own Team', is_active=True)
        self.other_team = Team(id=uuid.uuid4(), organization_id=self.other_org.id, division_id=self.division.id, name='Other Team', is_active=True)
        self.participation = OrganizationDivisionParticipation(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, is_participating=True, team_count=3, is_active=True)
        self.other_participation = OrganizationDivisionParticipation(id=uuid.uuid4(), organization_id=self.other_org.id, division_id=self.division.id, is_participating=True, team_count=3, is_active=True)
        self.db.add_all([
            self.league_role,
            self.community_role,
            self.org,
            self.other_org,
            self.division,
            self.other_division,
            self.league_user,
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
                'is_active': True,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload['organization_id'], str(self.org.id))
        self.assertEqual(payload['name'], 'Forced Org Team')

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

    def test_league_admin_team_participation_requirement_is_unchanged(self):
        response = self.client.post(
            '/api/teams',
            headers=self._token(self.league_user.id),
            json={
                'organization_id': str(self.org.id),
                'division_id': str(self.other_division.id),
                'name': 'League No Participation',
                'is_active': True,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('not participating', response.text)


if __name__ == '__main__':
    unittest.main()
