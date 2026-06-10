import struct
import zlib

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import ROLE_COMMUNITY_ADMIN, ROLE_LEAGUE_ADMIN, ROLE_SCHEDULING_ADMIN
from app.database import Base, get_db
from app.main import app
from app.models import Organization, Role, User
from app.routes import api as api_routes
from app.security import create_access_token, hash_password


def _auth_header(user_id):
    return {'Authorization': f'Bearer {create_access_token(str(user_id))}'}


def _png(width=500, height=500, extra=b''):
    def chunk(kind, data):
        payload = kind + data
        return struct.pack('>I', len(data)) + payload + struct.pack('>I', zlib.crc32(payload) & 0xFFFFFFFF)
    raw = b'\x00' + (b'\x00\x00\x00' * width)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw * height)) + chunk(b'IEND', b'') + extra


class TestCommunityLogos:
    def setup_method(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool, future=True)
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.db = self.SessionLocal()

        league_role = Role(name=ROLE_LEAGUE_ADMIN, description='League Admin', is_active=True)
        scheduling_role = Role(name=ROLE_SCHEDULING_ADMIN, description='Scheduling Admin', is_active=True)
        community_role = Role(name=ROLE_COMMUNITY_ADMIN, description='Community Admin', is_active=True)
        self.org_one = Organization(name='Community One', is_active=True)
        self.org_two = Organization(name='Community Two', is_active=True)
        self.db.add_all([league_role, scheduling_role, community_role, self.org_one, self.org_two])
        self.db.flush()
        self.scheduler = User(email='scheduler@example.com', full_name='Scheduler', password_hash=hash_password('Password123!'), role_id=scheduling_role.id, is_active=True)
        self.community_admin = User(email='community@example.com', full_name='Community Admin', password_hash=hash_password('Password123!'), role_id=community_role.id, organization_id=self.org_one.id, is_active=True)
        self.league_admin = User(email='league@example.com', full_name='League Admin', password_hash=hash_password('Password123!'), role_id=league_role.id, is_active=True)
        self.db.add_all([self.scheduler, self.community_admin, self.league_admin])
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

    def _set_upload_dir(self, tmp_path):
        api_routes.COMMUNITY_LOGO_UPLOAD_DIR = str(tmp_path / 'community-logos')

    def _upload(self, org_id, user_id, filename='logo.png', content=None, content_type='image/png'):
        return self.client.post(
            f'/api/organizations/{org_id}/logo',
            headers=_auth_header(user_id),
            files={'file': (filename, content if content is not None else _png(), content_type)},
        )

    def test_png_upload_succeeds_for_scheduling_admin_any_community(self, tmp_path):
        self._set_upload_dir(tmp_path)
        response = self._upload(self.org_two.id, self.scheduler.id)
        assert response.status_code == 200
        payload = response.json()
        assert payload['logo_content_type'] == 'image/png'
        assert payload['logo_width'] == 500
        assert payload['logo_height'] == 500
        assert payload['logo_url'].startswith(f'/api/public/organizations/{self.org_two.id}/logo/')

    def test_non_png_formats_are_rejected(self, tmp_path):
        self._set_upload_dir(tmp_path)
        for filename, content_type in [
            ('logo.jpg', 'image/jpeg'),
            ('logo.jpeg', 'image/jpeg'),
            ('logo.webp', 'image/webp'),
            ('logo.svg', 'image/svg+xml'),
        ]:
            response = self._upload(self.org_one.id, self.scheduler.id, filename=filename, content=b'not png', content_type=content_type)
            assert response.status_code == 400
            assert response.json()['detail'] == 'Only PNG logo files are accepted.'

    def test_file_larger_than_two_mb_is_rejected(self, tmp_path):
        self._set_upload_dir(tmp_path)
        response = self._upload(self.org_one.id, self.scheduler.id, content=_png(extra=b'0' * (2 * 1024 * 1024 + 1)))
        assert response.status_code == 413
        assert response.json()['detail'] == 'Logo file must be 2 MB or smaller.'

    def test_image_below_minimum_dimensions_is_rejected(self, tmp_path):
        self._set_upload_dir(tmp_path)
        response = self._upload(self.org_one.id, self.scheduler.id, content=_png(499, 500))
        assert response.status_code == 400
        assert response.json()['detail'] == 'Logo image must be at least 500 × 500 pixels.'

    def test_community_admin_cannot_upload_another_community_logo(self, tmp_path):
        self._set_upload_dir(tmp_path)
        response = self._upload(self.org_two.id, self.community_admin.id)
        assert response.status_code == 403

    def test_community_admin_can_replace_and_remove_own_logo(self, tmp_path):
        self._set_upload_dir(tmp_path)
        first = self._upload(self.org_one.id, self.community_admin.id)
        second = self._upload(self.org_one.id, self.community_admin.id, content=_png(600, 600))
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()['logo_url'] != second.json()['logo_url']
        response = self.client.delete(f'/api/organizations/{self.org_one.id}/logo', headers=_auth_header(self.community_admin.id))
        assert response.status_code == 200
        assert response.json()['logo_url'] is None

    def test_public_users_cannot_manage_logos(self, tmp_path):
        self._set_upload_dir(tmp_path)
        response = self.client.post(f'/api/organizations/{self.org_one.id}/logo', files={'file': ('logo.png', _png(), 'image/png')})
        assert response.status_code in {401, 403}
