import uuid
from datetime import date, time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import ROLE_COMMUNITY_ADMIN, ROLE_LEAGUE_ADMIN, ROLE_SCHEDULING_ADMIN
from app.database import Base, get_db
from app.main import app
from app.models import Division, Game, GameStatus, Organization, Role, Season, Team, User, Week
from app.organizations import normalize_organization_name
from app.security import create_access_token, hash_password


def _auth_header(user_id):
    return {'Authorization': f'Bearer {create_access_token(str(user_id))}'}


class TestOrganizationSoftDelete:
    def setup_method(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool, future=True)
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.db = self.SessionLocal()

        self.league_role = Role(name=ROLE_LEAGUE_ADMIN, description='League Admin', is_active=True)
        self.scheduling_role = Role(name=ROLE_SCHEDULING_ADMIN, description='Scheduling Admin', is_active=True)
        self.community_role = Role(name=ROLE_COMMUNITY_ADMIN, description='Community Admin', is_active=True)
        self.org = Organization(name='Example Community', is_active=True)
        self.other_org = Organization(name='Other Community', is_active=True)
        self.db.add_all([self.league_role, self.scheduling_role, self.community_role, self.org, self.other_org])
        self.db.flush()
        self.league_admin = User(email='league@example.com', full_name='League Admin', password_hash=hash_password('Password123!'), role_id=self.league_role.id, is_active=True)
        self.scheduler = User(email='scheduler@example.com', full_name='Scheduler', password_hash=hash_password('Password123!'), role_id=self.scheduling_role.id, is_active=True)
        self.community_admin = User(email='community@example.com', full_name='Community Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.org.id, is_active=True)
        self.db.add_all([self.league_admin, self.scheduler, self.community_admin])
        self.db.commit()

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def teardown_method(self):
        app.dependency_overrides.clear()
        self.db.close()

    def test_scheduling_admin_soft_delete_persists_and_list_excludes_deleted_by_default(self):
        response = self.client.delete(f'/api/organizations/{self.org.id}', headers=_auth_header(self.scheduler.id))
        assert response.status_code == 200
        payload = response.json()
        assert payload['id'] == str(self.org.id)
        assert payload['name'] == 'Example Community'
        assert payload['is_active'] is False
        assert payload['deleted_at'] is not None
        assert payload['deleted_by_user_id'] == str(self.scheduler.id)
        assert payload['deletion_status'] == 'deleted'

        persisted = self.db.get(Organization, self.org.id)
        self.db.refresh(persisted)
        assert persisted.is_active is False
        assert persisted.deleted_at is not None
        assert persisted.deleted_by_user_id == self.scheduler.id

        list_response = self.client.get('/api/organizations?page_size=100', headers=_auth_header(self.scheduler.id))
        assert list_response.status_code == 200
        returned_ids = {item['id'] for item in list_response.json()['items']}
        assert str(self.org.id) not in returned_ids
        assert str(self.other_org.id) in returned_ids

    def test_page_reload_and_login_refresh_use_backend_list_without_deleted_community(self):
        delete_response = self.client.delete(f'/api/organizations/{self.org.id}', headers=_auth_header(self.league_admin.id))
        assert delete_response.status_code == 200

        first_load = self.client.get('/api/organizations?page_size=100', headers=_auth_header(self.scheduler.id))
        second_load = self.client.get('/api/organizations?page_size=100', headers=_auth_header(self.scheduler.id))
        for response in (first_load, second_load):
            assert response.status_code == 200
            assert str(self.org.id) not in {item['id'] for item in response.json()['items']}

    def test_community_admin_and_public_user_cannot_delete_organization(self):
        community_response = self.client.delete(f'/api/organizations/{self.other_org.id}', headers=_auth_header(self.community_admin.id))
        assert community_response.status_code == 403
        public_response = self.client.delete(f'/api/organizations/{self.other_org.id}')
        assert public_response.status_code in {401, 403}

        persisted = self.db.get(Organization, self.other_org.id)
        self.db.refresh(persisted)
        assert persisted.is_active is True
        assert persisted.deleted_at is None

    def test_deleted_community_admin_token_is_rejected_after_soft_delete(self):
        delete_response = self.client.delete(f'/api/organizations/{self.org.id}', headers=_auth_header(self.scheduler.id))
        assert delete_response.status_code == 200

        response = self.client.get('/api/organizations?page_size=100', headers=_auth_header(self.community_admin.id))
        assert response.status_code == 401


    def test_deleted_community_admin_cannot_log_back_in(self):
        delete_response = self.client.delete(f'/api/organizations/{self.org.id}', headers=_auth_header(self.scheduler.id))
        assert delete_response.status_code == 200

        login_response = self.client.post('/api/auth/login', json={'email': 'community@example.com', 'password': 'Password123!'})
        assert login_response.status_code == 401

    def test_duplicate_active_normalized_organization_names_are_rejected(self):
        assert normalize_organization_name(' Example   Community ') == normalize_organization_name('example community')
        response = self.client.post(
            '/api/organizations',
            headers=_auth_header(self.league_admin.id),
            json={'name': ' example   community ', 'is_active': True},
        )
        assert response.status_code == 409
        assert response.json()['detail'] == 'An active organization with this name already exists.'

    def test_deleted_organization_name_is_not_recreated_as_active(self):
        delete_response = self.client.delete(f'/api/organizations/{self.org.id}', headers=_auth_header(self.scheduler.id))
        assert delete_response.status_code == 200
        response = self.client.post(
            '/api/organizations',
            headers=_auth_header(self.league_admin.id),
            json={'name': ' example community ', 'is_active': True},
        )
        assert response.status_code == 409
        assert 'inactive or deleted organization with this name already exists' in response.json()['detail']
        assert self.db.query(Organization).count() == 2

    def test_deleted_community_logo_card_source_endpoint_excludes_deleted_organization(self):
        self.client.delete(f'/api/organizations/{self.org.id}', headers=_auth_header(self.scheduler.id))
        response = self.client.get('/api/organizations?page_size=100', headers=_auth_header(self.league_admin.id))
        assert response.status_code == 200
        names = {item['name'] for item in response.json()['items']}
        assert 'Example Community' not in names

    def test_historical_game_references_survive_organization_soft_delete(self):
        season = Season(name='Historical Season', start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), is_active=True)
        week = Week(season=season, week_number=1, start_date=date(2026, 1, 1), end_date=date(2026, 1, 7))
        division = Division(name='Test Division', division_group='Test', sort_order=1, required_field_layout_type='SMALL', is_active=True)
        status = GameStatus(code='SCHEDULED', label='Scheduled', sort_order=1, is_active=True)
        home = Team(organization_id=self.org.id, division=division, name='Home', coach_name='Coach', coach_email='home@example.com', is_active=True)
        away = Team(organization_id=self.other_org.id, division=division, name='Away', coach_name='Coach', coach_email='away@example.com', is_active=True)
        self.db.add_all([season, week, division, status, home, away])
        self.db.flush()
        game = Game(season_id=season.id, week_id=week.id, home_team_id=home.id, away_team_id=away.id, game_status_id=status.id, game_date=date(2026, 1, 1), kickoff_time=time(9, 0))
        self.db.add(game)
        self.db.commit()

        delete_response = self.client.delete(f'/api/organizations/{self.org.id}', headers=_auth_header(self.scheduler.id))
        assert delete_response.status_code == 200

        persisted_game = self.db.get(Game, game.id)
        assert persisted_game is not None
        assert persisted_game.home_team_id == home.id
        assert persisted_game.home_team.organization_id == self.org.id
