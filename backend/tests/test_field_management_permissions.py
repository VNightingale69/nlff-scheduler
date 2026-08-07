import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import LEGACY_ROLE_LEAGUE_ADMIN
from app.database import Base, get_db
from app.main import app
from app.models import HostLocation, Organization, Role, User
from app.security import create_access_token, hash_password


class FieldManagementPermissionsTest(unittest.TestCase):
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

        league_role = Role(id=uuid.uuid4(), name=LEGACY_ROLE_LEAGUE_ADMIN, is_active=True)
        unauthorized_role = Role(id=uuid.uuid4(), name='READ_ONLY', is_active=True)
        self.organization = Organization(id=uuid.uuid4(), name='Field Test Community', is_active=True)
        self.host = HostLocation(
            id=uuid.uuid4(),
            organization_id=self.organization.id,
            name='Test Grass Fields',
            surface_type='GRASS_FIELD',
            is_active=True,
        )
        self.league_admin = User(
            id=uuid.uuid4(), email='league-fields@example.com', full_name='League Fields Admin',
            password_hash=hash_password('Password123!'), role=league_role, is_active=True,
        )
        self.unauthorized_user = User(
            id=uuid.uuid4(), email='readonly@example.com', full_name='Read Only',
            password_hash=hash_password('Password123!'), role=unauthorized_role, is_active=True,
        )
        self.db.add_all([league_role, unauthorized_role, self.organization, self.host, self.league_admin, self.unauthorized_user])
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

    @staticmethod
    def _headers(user):
        return {'Authorization': f'Bearer {create_access_token(str(user.id))}'}

    def _payload(self, **changes):
        payload = {
            'host_location_id': str(self.host.id),
            'physical_field_area_id': None,
            'name': 'Small Field 1',
            'layout_type': 'SMALL',
            'is_active': True,
            'notes': None,
        }
        payload.update(changes)
        return payload

    def test_legacy_league_admin_session_can_create_edit_toggle_and_delete_field(self):
        headers = self._headers(self.league_admin)
        session = self.client.get('/api/auth/me', headers=headers)
        self.assertEqual(session.status_code, 200, session.text)
        self.assertEqual(session.json()['user']['role_name'], 'LEAGUE_ADMIN')

        created = self.client.post('/api/fields', json=self._payload(), headers=headers)
        self.assertEqual(created.status_code, 200, created.text)
        field_id = created.json()['id']

        edited = self.client.put(
            f'/api/fields/{field_id}',
            json=self._payload(name='Renamed Medium Field', layout_type='MEDIUM'),
            headers=headers,
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual((edited.json()['name'], edited.json()['layout_type']), ('Renamed Medium Field', 'MEDIUM'))

        deactivated = self.client.put(
            f'/api/fields/{field_id}',
            json=self._payload(name='Renamed Medium Field', layout_type='MEDIUM', is_active=False),
            headers=headers,
        )
        self.assertEqual(deactivated.status_code, 200, deactivated.text)
        self.assertFalse(deactivated.json()['is_active'])

        activated = self.client.put(
            f'/api/fields/{field_id}',
            json=self._payload(name='Renamed Medium Field', layout_type='MEDIUM', is_active=True),
            headers=headers,
        )
        self.assertEqual(activated.status_code, 200, activated.text)
        self.assertTrue(activated.json()['is_active'])

        deleted = self.client.delete(f'/api/fields/{field_id}', headers=headers)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()['affected_scheduled_games_count'], 0)

    def test_unauthorized_role_receives_403_for_every_field_mutation(self):
        headers = self._headers(self.unauthorized_user)
        created = self.client.post('/api/fields', json=self._payload(), headers=headers)
        self.assertEqual(created.status_code, 403, created.text)

        authorized_create = self.client.post('/api/fields', json=self._payload(), headers=self._headers(self.league_admin))
        self.assertEqual(authorized_create.status_code, 200, authorized_create.text)
        field_id = authorized_create.json()['id']

        updated = self.client.put(f'/api/fields/{field_id}', json=self._payload(name='Forbidden Edit'), headers=headers)
        impact = self.client.get(f'/api/fields/{field_id}/delete-impact', headers=headers)
        deleted = self.client.delete(f'/api/fields/{field_id}', headers=headers)
        self.assertEqual(updated.status_code, 403, updated.text)
        self.assertEqual(impact.status_code, 403, impact.text)
        self.assertEqual(deleted.status_code, 403, deleted.text)


if __name__ == '__main__':
    unittest.main()
