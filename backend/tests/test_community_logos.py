import struct
from unittest.mock import patch
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


def _assert_persisted_logo_url(value, org_id):
    assert value.startswith(f'/api/public/organizations/{org_id}/logo/')
    assert not value.startswith(('blob:', 'file:'))
    assert '/app/' not in value
    assert '/workspace/' not in value


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
        self.org_one = Organization(name='Westosha', is_active=True)
        self.org_two = Organization(name='Johnsburg', is_active=True)
        self.org_three = Organization(name='Antioch', is_active=True)
        self.db.add_all([league_role, scheduling_role, community_role, self.org_one, self.org_two, self.org_three])
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
        _assert_persisted_logo_url(payload['logo_url'], self.org_two.id)

    def test_upload_logo_returns_persisted_logo_url_for_multiple_communities(self, tmp_path):
        self._set_upload_dir(tmp_path)
        for org in (self.org_one, self.org_two, self.org_three):
            response = self._upload(org.id, self.scheduler.id, filename=f'{org.name.lower()}.png')
            assert response.status_code == 200
            _assert_persisted_logo_url(response.json()['logo_url'], org.id)



    def test_upload_creates_configured_logo_directory_and_stores_file_there(self, tmp_path):
        upload_dir = tmp_path / 'configured' / 'community-logos'
        api_routes.COMMUNITY_LOGO_UPLOAD_DIR = str(upload_dir)

        response = self._upload(self.org_one.id, self.scheduler.id, filename='stored.png')

        assert response.status_code == 200
        payload = response.json()
        stored_file = upload_dir / payload['logo_filename']
        assert upload_dir.is_dir()
        assert stored_file.is_file()
        assert stored_file.read_bytes().startswith(b'\x89PNG')
        assert payload['logo_file_available'] is True
        assert payload['logo_storage_error'] is None
        assert not payload['logo_url'].startswith('/app/uploads')

    def test_upload_uses_upload_storage_dir_when_logo_upload_dir_is_unset(self, tmp_path):
        api_routes.UPLOAD_STORAGE_DIR = str(tmp_path / 'uploads')
        api_routes.COMMUNITY_LOGO_UPLOAD_DIR = ''

        response = self._upload(self.org_one.id, self.scheduler.id, filename='fallback.png')

        assert response.status_code == 200
        payload = response.json()
        assert (tmp_path / 'uploads' / 'community-logos' / payload['logo_filename']).is_file()
        assert payload['logo_url'].startswith(f'/api/public/organizations/{self.org_one.id}/logo/')

    def test_logo_upload_does_not_save_metadata_when_file_cannot_be_verified(self, tmp_path):
        self._set_upload_dir(tmp_path)

        with patch('pathlib.Path.is_file', return_value=False):
            response = self._upload(self.org_one.id, self.scheduler.id, filename='unverified.png')

        org = self.db.get(Organization, self.org_one.id)
        assert response.status_code == 500
        assert response.json()['detail'] == 'Community logo upload could not be saved to persistent storage.'
        assert org.logo_filename is None
        assert org.logo_url is None

    def test_missing_logo_file_returns_unavailable_state_and_can_be_replaced(self, tmp_path):
        self._set_upload_dir(tmp_path)
        upload = self._upload(self.org_one.id, self.scheduler.id, filename='missing.png')
        assert upload.status_code == 200
        old_filename = upload.json()['logo_filename']
        (api_routes._community_logo_storage_dir() / old_filename).unlink()

        response = self.client.get(f'/api/organizations/{self.org_one.id}', headers=_auth_header(self.scheduler.id))
        public_response = self.client.get(upload.json()['logo_url'])
        replacement = self._upload(self.org_one.id, self.scheduler.id, filename='replacement.png')

        assert response.status_code == 200
        assert response.json()['logo_file_available'] is False
        assert response.json()['logo_storage_error'] == 'Logo metadata exists, but the image file could not be found. Confirm persistent upload storage is configured, then replace the logo.'
        assert public_response.status_code == 404
        assert replacement.status_code == 200
        assert replacement.json()['logo_file_available'] is True
        assert replacement.json()['logo_filename'] != old_filename
        assert self.client.get(replacement.json()['logo_url']).status_code == 200

    def test_get_organization_includes_logo_metadata(self, tmp_path):
        self._set_upload_dir(tmp_path)
        upload = self._upload(self.org_one.id, self.scheduler.id, filename='community-logo.png')
        assert upload.status_code == 200
        response = self.client.get(f'/api/organizations/{self.org_one.id}', headers=_auth_header(self.scheduler.id))
        assert response.status_code == 200
        payload = response.json()
        assert payload['logo_url'] == upload.json()['logo_url']
        assert payload['logo_filename'].endswith('.png')
        assert payload['logo_content_type'] == 'image/png'
        assert payload['logo_file_size'] > 0
        assert payload['logo_width'] == 500
        assert payload['logo_height'] == 500
        assert payload['logo_uploaded_at']


    def test_organization_list_reconstructs_canonical_logo_url_from_persisted_filename_after_reload(self, tmp_path):
        self._set_upload_dir(tmp_path)
        upload = self._upload(self.org_one.id, self.scheduler.id, filename='westosha.png')
        assert upload.status_code == 200
        uploaded = upload.json()

        # Simulate older persisted records that kept metadata/filename but lost logo_url.
        org = self.db.get(Organization, self.org_one.id)
        org.logo_url = None
        self.db.commit()

        response = self.client.get('/api/organizations?page_size=500', headers=_auth_header(self.scheduler.id))
        assert response.status_code == 200
        items = {item['id']: item for item in response.json()['items']}
        assert items[str(self.org_one.id)]['logo_filename'] == uploaded['logo_filename']
        assert items[str(self.org_one.id)]['logo_url'] == f"/api/public/organizations/{self.org_one.id}/logo/{uploaded['logo_filename']}"

    def test_get_organization_filters_temporary_or_filesystem_logo_urls(self, tmp_path):
        self._set_upload_dir(tmp_path)
        for bad_url in ('blob:http://localhost/logo', '/app/uploads/logo.png', r'C:\uploads\logo.png', 'file:///tmp/logo.png'):
            org = self.db.get(Organization, self.org_three.id)
            org.logo_url = bad_url
            org.logo_filename = None
            self.db.commit()
            response = self.client.get(f'/api/organizations/{self.org_three.id}', headers=_auth_header(self.scheduler.id))
            assert response.status_code == 200
            assert response.json()['logo_url'] is None

    def test_public_logo_endpoint_loads_without_authentication(self, tmp_path):
        self._set_upload_dir(tmp_path)
        upload = self._upload(self.org_two.id, self.scheduler.id, filename='johnsburg.png')
        assert upload.status_code == 200
        public_response = self.client.get(upload.json()['logo_url'])
        assert public_response.status_code == 200
        assert public_response.headers['content-type'] == 'image/png'
        assert public_response.content.startswith(b'\x89PNG')

    def test_community_admin_cannot_get_another_community_logo_metadata(self, tmp_path):
        self._set_upload_dir(tmp_path)
        response = self.client.get(f'/api/organizations/{self.org_two.id}', headers=_auth_header(self.community_admin.id))
        assert response.status_code == 403

    def test_png_with_rectangular_recommended_shape_is_allowed(self, tmp_path):
        self._set_upload_dir(tmp_path)
        response = self._upload(self.org_one.id, self.scheduler.id, content=_png(500, 900))
        assert response.status_code == 200
        assert response.json()['logo_width'] == 500
        assert response.json()['logo_height'] == 900

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
