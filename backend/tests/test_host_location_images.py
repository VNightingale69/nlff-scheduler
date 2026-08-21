import io

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import ROLE_COMMUNITY_ADMIN, ROLE_LEAGUE_ADMIN, ROLE_SCHEDULING_ADMIN
from app.database import Base, get_db
from app.main import app
from app.models import HostLocation, Organization, Role, User
from app.routes import api as api_routes
from app.security import create_access_token, hash_password


def image_bytes(fmt: str) -> bytes:
    output = io.BytesIO()
    Image.new('RGB', (80, 40), 'green').save(output, format=fmt)
    return output.getvalue()


def auth(user):
    return {'Authorization': f'Bearer {create_access_token(str(user.id))}'}


class TestHostLocationImages:
    def setup_method(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        self.Session = sessionmaker(bind=engine)
        Base.metadata.create_all(engine)
        db = self.Session()
        league_role = Role(name=ROLE_LEAGUE_ADMIN, is_active=True)
        scheduling_role = Role(name=ROLE_SCHEDULING_ADMIN, is_active=True)
        community_role = Role(name=ROLE_COMMUNITY_ADMIN, is_active=True)
        self.own_org = Organization(name='Johnsburg', is_active=True)
        self.other_org = Organization(name='Antioch', is_active=True)
        db.add_all([league_role, scheduling_role, community_role, self.own_org, self.other_org]); db.flush()
        password = hash_password('Password123!')
        self.league = User(email='league@example.com', password_hash=password, role_id=league_role.id, is_active=True)
        self.scheduler = User(email='scheduler@example.com', password_hash=password, role_id=scheduling_role.id, is_active=True)
        self.community = User(email='community@example.com', password_hash=password, role_id=community_role.id, organization_id=self.own_org.id, is_active=True)
        self.own_location = HostLocation(organization_id=self.own_org.id, name='Johnsburg Stadium', is_active=True)
        self.other_location = HostLocation(organization_id=self.other_org.id, name='Antioch Stadium', is_active=True)
        db.add_all([self.league, self.scheduler, self.community, self.own_location, self.other_location]); db.commit()
        self.ids = {x: str(getattr(self, x).id) for x in ('own_location', 'other_location')}
        db.close()

        def override_db():
            session = self.Session()
            try: yield session
            finally: session.close()
        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def teardown_method(self):
        app.dependency_overrides.clear()

    def upload(self, location, user, fmt='PNG', content_type='image/png', content=None):
        extension = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}.get(fmt, 'txt')
        return self.client.post(
            f'/api/admin/host-locations/{location.id}/image', headers=auth(user),
            files={'file': (f'layout.{extension}', content if content is not None else image_bytes(fmt), content_type)},
        )

    def test_valid_formats_replace_remove_and_public_safe_response(self, tmp_path):
        api_routes.HOST_LOCATION_IMAGE_UPLOAD_DIR = str(tmp_path / 'host-locations')
        for fmt, mime in [('JPEG', 'image/jpeg'), ('PNG', 'image/png'), ('WEBP', 'image/webp')]:
            response = self.upload(self.own_location, self.league, fmt, mime)
            assert response.status_code == 200
            assert response.json()['location_image_filename'] == f"layout.{ {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}[fmt] }"
        stored_files = list((tmp_path / 'host-locations' / str(self.own_location.id)).iterdir())
        assert len(stored_files) == 1, 'replacement deletes the prior object'
        public = self.client.get('/api/public/hosting-locations').json()
        own = next(row for row in public if row['id'] == str(self.own_location.id))
        assert own['location_image_url'].startswith(f'/api/public/hosting-locations/{self.own_location.id}/image/')
        assert 'location_image_storage_key' not in own and 'notes' not in own
        assert self.client.get(own['location_image_url']).status_code == 200
        removed = self.client.delete(f'/api/admin/host-locations/{self.own_location.id}/image', headers=auth(self.league))
        assert removed.status_code == 200 and removed.json()['location_image_url'] is None
        assert not list((tmp_path / 'host-locations' / str(self.own_location.id)).iterdir())

    def test_community_ownership_is_enforced_for_direct_api_manipulation(self, tmp_path):
        api_routes.HOST_LOCATION_IMAGE_UPLOAD_DIR = str(tmp_path / 'host-locations')
        assert self.upload(self.own_location, self.community).status_code == 200
        assert self.upload(self.own_location, self.community).status_code == 200
        assert self.client.delete(f'/api/admin/host-locations/{self.own_location.id}/image', headers=auth(self.community)).status_code == 200
        assert self.upload(self.other_location, self.community).status_code == 403
        assert self.client.delete(f'/api/admin/host-locations/{self.other_location.id}/image', headers=auth(self.community)).status_code == 403
        assert self.upload(self.other_location, self.league).status_code == 200
        assert self.upload(self.own_location, self.scheduler).status_code == 200

    def test_invalid_oversized_and_anonymous_uploads_are_rejected(self, tmp_path, monkeypatch):
        api_routes.HOST_LOCATION_IMAGE_UPLOAD_DIR = str(tmp_path / 'host-locations')
        assert self.upload(self.own_location, self.league, 'TXT', 'text/plain', b'<script>alert(1)</script>').status_code == 400
        monkeypatch.setattr(api_routes, 'HOST_LOCATION_IMAGE_MAX_SIZE_BYTES', 5)
        assert self.upload(self.own_location, self.league, content=b'123456').status_code == 413
        response = self.client.post(f'/api/admin/host-locations/{self.own_location.id}/image', files={'file': ('x.png', image_bytes('PNG'), 'image/png')})
        assert response.status_code == 401

    def test_existing_location_without_image_remains_valid(self):
        response = self.client.get('/api/public/hosting-locations')
        assert response.status_code == 200
        assert all(row['location_image_url'] is None for row in response.json())
