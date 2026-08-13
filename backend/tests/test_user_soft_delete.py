import logging

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import ROLE_COMMUNITY_ADMIN, ROLE_LEAGUE_ADMIN, ROLE_SCHEDULING_ADMIN
from app.database import Base, get_db
from app.main import app
from app.models import Division, HostLocation, Organization, Role, Team, User
from app.security import create_access_token, hash_password


def auth(user):
    return {'Authorization': f'Bearer {create_access_token(str(user.id))}'}


class TestUserSoftDelete:
    def setup_method(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.league_role = Role(name=ROLE_LEAGUE_ADMIN, is_active=True)
        self.community_role = Role(name=ROLE_COMMUNITY_ADMIN, is_active=True)
        self.scheduling_role = Role(name=ROLE_SCHEDULING_ADMIN, is_active=True)
        self.community = Organization(name='Preserved Community', is_active=True)
        self.division = Division(name='5th', division_group='COED', sort_order=1, required_field_layout_type='LARGE', is_active=True)
        self.db.add_all([self.league_role, self.community_role, self.scheduling_role, self.community, self.division]); self.db.flush()
        self.league_admin = User(email='league@example.com', full_name='League Admin', password_hash=hash_password('Password123!'), role_id=self.league_role.id, is_active=True)
        self.community_admin = User(email='community@example.com', full_name='Community Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.community.id, is_active=True)
        self.scheduling_admin = User(email='scheduler@example.com', full_name='Scheduling Admin', password_hash=hash_password('Password123!'), role_id=self.scheduling_role.id, is_active=True)
        self.other_admin = User(email='other@example.com', full_name='Other Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.community.id, is_active=True)
        self.team = Team(name='Preserved Team', organization_id=self.community.id, division_id=self.division.id, is_active=True)
        self.facility = HostLocation(name='Preserved Facility', organization_id=self.community.id, is_active=True)
        self.db.add_all([self.league_admin, self.scheduling_admin, self.community_admin, self.other_admin, self.team, self.facility]); self.db.commit()

        def override_db():
            db = self.Session()
            try: yield db
            finally: db.close()
        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def teardown_method(self):
        app.dependency_overrides.clear(); self.db.close()

    def test_league_admin_deletes_only_account_and_preserves_community_data(self, caplog):
        caplog.set_level(logging.INFO, logger='app.routes.api')
        response = self.client.delete(f'/api/users/{self.community_admin.id}', headers=auth(self.league_admin))
        assert response.status_code == 204
        self.db.expire_all()
        deleted = self.db.get(User, self.community_admin.id)
        assert deleted.is_active is False and deleted.deleted_at is not None
        assert deleted.organization_id == self.community.id
        assert self.db.get(Organization, self.community.id).name == 'Preserved Community'
        assert self.db.get(Team, self.team.id).name == 'Preserved Team'
        assert self.db.get(HostLocation, self.facility.id).name == 'Preserved Facility'
        assert self.db.get(User, self.other_admin.id).is_active is True

        list_response = self.client.get('/api/users?page_size=100', headers=auth(self.league_admin))
        assert list_response.status_code == 200
        assert str(self.community_admin.id) not in {item['id'] for item in list_response.json()['items']}
        for marker in (
            'DELETE USER REQUEST RECEIVED',
            'DELETE USER TARGET LOOKUP',
            'DELETE USER TARGET FOUND',
            'DELETE USER VALIDATION COMPLETE',
            'DELETE USER SOFT DELETE START',
            'DELETE USER FLUSH START',
            'DELETE USER FLUSH SUCCESS',
            'DELETE USER COMMIT START',
            'DELETE USER COMMIT SUCCESS',
        ):
            assert marker in caplog.text

    def test_deleted_user_cannot_login_or_use_existing_token(self):
        assert self.client.delete(f'/api/users/{self.community_admin.id}', headers=auth(self.league_admin)).status_code == 204
        assert self.client.post('/api/auth/login', json={'email': self.community_admin.email, 'password': 'Password123!'}).status_code == 401
        assert self.client.get('/api/auth/me', headers=auth(self.community_admin)).status_code == 401

    def test_self_delete_is_blocked(self):
        response = self.client.delete(f'/api/users/{self.league_admin.id}', headers=auth(self.league_admin))
        assert response.status_code == 409
        assert response.json()['detail'] == 'You cannot delete your own user account.'

    def test_community_admin_cannot_delete_user(self):
        assert self.client.delete(f'/api/users/{self.league_admin.id}', headers=auth(self.community_admin)).status_code == 403

    def test_second_delete_is_graceful(self):
        assert self.client.delete(f'/api/users/{self.community_admin.id}', headers=auth(self.league_admin)).status_code == 204
        response = self.client.delete(f'/api/users/{self.community_admin.id}', headers=auth(self.league_admin))
        assert response.status_code == 404 and response.json()['detail'] == 'User not found'

    def test_deleted_user_is_excluded_but_deactivated_user_remains_listed(self):
        self.other_admin.is_active = False; self.db.commit()
        assert self.client.delete(f'/api/users/{self.community_admin.id}', headers=auth(self.league_admin)).status_code == 204
        response = self.client.get('/api/users?page_size=100', headers=auth(self.league_admin))
        ids = {item['id'] for item in response.json()['items']}
        assert str(self.community_admin.id) not in ids and str(self.other_admin.id) in ids
        assert next(item for item in response.json()['items'] if item['id'] == str(self.other_admin.id))['deleted_at'] is None

    def test_scheduling_admin_delete_then_browser_reload_succeeds(self):
        delete_response = self.client.delete(
            f'/api/users/{self.community_admin.id}', headers=auth(self.scheduling_admin)
        )
        assert delete_response.status_code == 204

        list_response = self.client.get('/api/users?page_size=500', headers=auth(self.scheduling_admin))
        assert list_response.status_code == 200
        assert str(self.community_admin.id) not in {item['id'] for item in list_response.json()['items']}

        verification_db = self.Session()
        try:
            deleted = verification_db.get(User, self.community_admin.id)
            assert deleted.is_active is False
            assert deleted.deleted_at is not None
            assert verification_db.get(Organization, self.community.id) is not None
            assert verification_db.get(Team, self.team.id) is not None
            assert verification_db.get(HostLocation, self.facility.id) is not None
        finally:
            verification_db.close()
