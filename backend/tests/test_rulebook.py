import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.auth import ROLE_COMMUNITY_ADMIN, ROLE_LEAGUE_ADMIN
from app.database import Base, get_db
from app.main import app
from app.models import Organization, Role, Rulebook, User
from app.routes import api as api_routes
from app.security import create_access_token, hash_password


def _auth_header(user_id):
    return {'Authorization': f'Bearer {create_access_token(str(user_id))}'}


class TestRulebookFeature:
    def setup_method(self):
        engine = create_engine(
            'sqlite+pysqlite:///:memory:',
            connect_args={'check_same_thread': False},
            poolclass=StaticPool,
            future=True,
        )
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.db = self.SessionLocal()

        league_role = Role(name=ROLE_LEAGUE_ADMIN, description='League Admin', is_active=True)
        community_role = Role(name=ROLE_COMMUNITY_ADMIN, description='Community Admin', is_active=True)
        organization = Organization(name='Community One', is_active=True)
        self.db.add_all([league_role, community_role, organization])
        self.db.flush()

        self.league_admin = User(
            email='league@example.com',
            full_name='League Admin',
            password_hash=hash_password('Password123!'),
            role_id=league_role.id,
            is_active=True,
        )
        self.community_admin = User(
            email='community@example.com',
            full_name='Community Admin',
            password_hash=hash_password('Password123!'),
            role_id=community_role.id,
            organization_id=organization.id,
            is_active=True,
        )
        self.db.add_all([self.league_admin, self.community_admin])
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
        api_routes.UPLOAD_STORAGE_DIR = str(tmp_path / 'uploads')
        api_routes.RULEBOOK_UPLOAD_DIR = str(tmp_path / 'rulebooks')

    def _upload_pdf(self, filename='rules.pdf', content=b'%PDF-1.4\nrulebook'):
        return self.client.post(
            '/api/admin/rulebook/upload',
            headers=_auth_header(self.league_admin.id),
            files={'file': (filename, content, 'application/pdf')},
        )

    def test_league_admin_can_upload_pdf_and_metadata_is_returned(self, tmp_path):
        self._set_upload_dir(tmp_path)

        response = self._upload_pdf('Community Rules.pdf')

        assert response.status_code == 200
        payload = response.json()
        assert payload['original_filename'] == 'Community Rules.pdf'
        assert payload['content_type'] == 'application/pdf'
        assert payload['file_size_bytes'] == len(b'%PDF-1.4\nrulebook')
        assert payload['uploaded_by_email'] == 'league@example.com'
        assert payload['is_active'] is True
        assert payload['stored_filename'].endswith('.pdf')
        assert payload['storage_path'] == f"rulebooks/{payload['stored_filename']}"
        assert payload['view_url'] == f"/api/rulebooks/{payload['id']}/view"
        assert payload['download_url'] == f"/api/rulebooks/{payload['id']}/download"
        assert payload['file_url'] == payload['view_url']
        assert payload['file_available'] is True
        assert 'file_path' not in payload

    def test_upload_creates_configured_rulebook_directory_and_stores_file_there(self, tmp_path):
        upload_dir = tmp_path / 'configured' / 'rulebooks'
        api_routes.RULEBOOK_UPLOAD_DIR = str(upload_dir)

        response = self._upload_pdf('configured.pdf', b'%PDF-1.4\nconfigured')

        assert response.status_code == 200
        payload = response.json()
        stored_file = upload_dir / payload['stored_filename']
        record = self.db.query(Rulebook).filter(Rulebook.id == uuid.UUID(payload['id'])).one()
        assert upload_dir.is_dir()
        assert stored_file.is_file()
        assert stored_file.read_bytes() == b'%PDF-1.4\nconfigured'
        assert record.storage_path == f"rulebooks/{payload['stored_filename']}"
        assert record.file_path == record.storage_path
        assert not record.file_path.startswith('/')

    def test_upload_uses_upload_storage_dir_when_rulebook_upload_dir_is_unset(self, tmp_path):
        api_routes.UPLOAD_STORAGE_DIR = str(tmp_path / 'uploads')
        api_routes.RULEBOOK_UPLOAD_DIR = ''

        response = self._upload_pdf('fallback.pdf')

        assert response.status_code == 200
        payload = response.json()
        assert (tmp_path / 'uploads' / 'rulebooks' / payload['stored_filename']).is_file()

    def test_upload_does_not_activate_rulebook_when_saved_file_cannot_be_verified(self, tmp_path):
        self._set_upload_dir(tmp_path)

        with patch('pathlib.Path.is_file', return_value=False):
            response = self._upload_pdf('unverified.pdf')

        active_rulebook = self.db.query(Rulebook).filter(Rulebook.is_active.is_(True)).first()
        assert response.status_code == 500
        assert response.json()['detail'] == 'Rulebook upload could not be saved to persistent storage.'
        assert active_rulebook is None

    def test_upload_returns_clear_error_when_storage_directory_is_unavailable(self, tmp_path):
        blocking_file = tmp_path / 'not-a-directory'
        blocking_file.write_text('blocks mkdir')
        api_routes.RULEBOOK_UPLOAD_DIR = str(blocking_file / 'rulebooks')

        response = self._upload_pdf('unavailable.pdf')

        assert response.status_code == 500
        assert response.json()['detail'] == 'Rulebook upload storage is unavailable. Please verify persistent storage configuration.'
        assert self.db.query(Rulebook).filter(Rulebook.is_active.is_(True)).first() is None

    def test_non_admin_users_cannot_upload_pdf(self, tmp_path):
        self._set_upload_dir(tmp_path)

        response = self.client.post(
            '/api/admin/rulebook/upload',
            headers=_auth_header(self.community_admin.id),
            files={'file': ('rules.pdf', b'%PDF-1.4\nrulebook', 'application/pdf')},
        )

        assert response.status_code == 403

    def test_non_pdf_upload_is_rejected(self, tmp_path):
        self._set_upload_dir(tmp_path)

        response = self.client.post(
            '/api/admin/rulebook/upload',
            headers=_auth_header(self.league_admin.id),
            files={'file': ('rules.txt', b'not a pdf', 'text/plain')},
        )

        assert response.status_code == 400
        assert response.json()['detail'] == 'Only PDF files are allowed.'

    def test_current_and_public_metadata_are_returned(self, tmp_path):
        self._set_upload_dir(tmp_path)
        self._upload_pdf('rules.pdf')

        authenticated = self.client.get('/api/rulebook', headers=_auth_header(self.community_admin.id))
        public = self.client.get('/api/public/rulebook')

        assert authenticated.status_code == 200
        assert public.status_code == 200
        assert authenticated.json()['original_filename'] == 'rules.pdf'
        assert public.json()['original_filename'] == 'rules.pdf'
        assert public.json()['download_url'].startswith('/api/rulebooks/')

    def test_public_users_can_download_active_pdf(self, tmp_path):
        self._set_upload_dir(tmp_path)
        content = b'%PDF-1.4\npublic download'
        self._upload_pdf('rules.pdf', content)

        response = self.client.get('/api/public/rulebook/download')

        assert response.status_code == 200
        assert response.content == content
        assert response.headers['content-type'] == 'application/pdf'
        assert 'attachment' in response.headers['content-disposition']


    def test_active_rulebook_download_by_stable_url_streams_pdf(self, tmp_path):
        self._set_upload_dir(tmp_path)
        content = b'%PDF-1.4\nstable url'
        upload = self._upload_pdf('stable.pdf', content).json()

        response = self.client.get(upload['download_url'])
        view_response = self.client.get(upload['view_url'])

        assert response.status_code == 200
        assert response.content == content
        assert 'attachment' in response.headers['content-disposition']
        assert view_response.status_code == 200
        assert view_response.content == content
        assert 'inline' in view_response.headers['content-disposition']

    def test_active_rulebook_resolves_after_new_session(self, tmp_path):
        self._set_upload_dir(tmp_path)
        content = b'%PDF-1.4\nafter login'
        self._upload_pdf('session.pdf', content)

        authenticated = self.client.get('/api/rulebook', headers=_auth_header(self.community_admin.id))
        public = self.client.get(authenticated.json()['download_url'])

        assert authenticated.status_code == 200
        assert authenticated.json()['original_filename'] == 'session.pdf'
        assert authenticated.json()['file_available'] is True
        assert public.status_code == 200
        assert public.content == content

    def test_missing_active_file_returns_clear_admin_and_public_errors(self, tmp_path):
        self._set_upload_dir(tmp_path)
        upload = self._upload_pdf('missing.pdf').json()
        record = self.db.query(Rulebook).filter(Rulebook.id == uuid.UUID(upload['id'])).one()
        file_path = api_routes._rulebook_storage_dir() / record.stored_filename
        file_path.unlink()

        admin_metadata = self.client.get('/api/rulebook', headers=_auth_header(self.league_admin.id))
        admin_download = self.client.get('/api/rulebook/active/download', headers=_auth_header(self.league_admin.id))
        public_metadata = self.client.get('/api/public/rulebook')
        public_download = self.client.get(upload['download_url'])

        assert admin_metadata.status_code == 200
        assert admin_metadata.json()['file_available'] is False
        assert 'Please re-upload the rulebook' in admin_metadata.json()['storage_error']
        assert admin_download.status_code == 404
        assert 'Please re-upload the rulebook' in admin_download.json()['detail']
        assert public_metadata.status_code == 404
        assert public_metadata.json()['detail'] == 'Rulebook is temporarily unavailable.'
        assert public_download.status_code == 404
        assert public_download.json()['detail'] == 'Rulebook is temporarily unavailable.'

    def test_admin_can_replace_missing_active_rulebook(self, tmp_path):
        self._set_upload_dir(tmp_path)
        old = self._upload_pdf('old.pdf').json()
        old_record = self.db.query(Rulebook).filter(Rulebook.id == uuid.UUID(old['id'])).one()
        (api_routes._rulebook_storage_dir() / old_record.stored_filename).unlink()

        new = self._upload_pdf('new.pdf', b'%PDF-1.4\nreplacement').json()
        old_record = self.db.query(Rulebook).filter(Rulebook.id == uuid.UUID(old['id'])).one()

        assert new['original_filename'] == 'new.pdf'
        assert new['file_available'] is True
        assert old_record.is_active is False
        assert self.client.get(new['download_url']).status_code == 200

    def test_replacing_rulebook_makes_newest_active_and_prior_inactive(self, tmp_path):
        self._set_upload_dir(tmp_path)
        first = self._upload_pdf('first.pdf', b'%PDF-1.4\nfirst').json()
        second = self._upload_pdf('second.pdf', b'%PDF-1.4\nsecond').json()

        public = self.client.get('/api/public/rulebook')
        inactive = self.db.query(Rulebook).filter(Rulebook.id == uuid.UUID(first['id'])).one()
        active = self.db.query(Rulebook).filter(Rulebook.id == uuid.UUID(second['id'])).one()

        assert public.status_code == 200
        assert public.json()['original_filename'] == 'second.pdf'
        assert inactive.is_active is False
        assert active.is_active is True
