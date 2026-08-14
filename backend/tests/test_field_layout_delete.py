import unittest
import uuid
from datetime import date, time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import LEGACY_ROLE_LEAGUE_ADMIN, ROLE_COMMUNITY_ADMIN, ROLE_SCHEDULING_ADMIN
from app.database import Base, get_db
from app.main import app
from app.models import Field, FieldConfigurationMember, HostLocation, HostLocationConfiguration, HostingAvailability, Organization, Role, User, Week
from app.security import create_access_token, hash_password


class FieldLayoutDeleteTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool, future=True)
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.db = self.SessionLocal()
        self.org = Organization(id=uuid.uuid4(), name='Home Community', is_active=True)
        self.host = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Hiller Park', surface_type='GRASS_FIELD', is_active=True)
        roles = [
            Role(id=uuid.uuid4(), name=LEGACY_ROLE_LEAGUE_ADMIN, is_active=True),
            Role(id=uuid.uuid4(), name=ROLE_SCHEDULING_ADMIN, is_active=True),
            Role(id=uuid.uuid4(), name=ROLE_COMMUNITY_ADMIN, is_active=True),
        ]
        self.users = {
            role.name: User(id=uuid.uuid4(), email=f'{role.name.lower()}@example.com', full_name=role.name, password_hash=hash_password('Password123!'), role=role, organization_id=self.org.id, is_active=True)
            for role in roles
        }
        self.fields = [Field(id=uuid.uuid4(), host_location_id=self.host.id, name=f'Small {name}', layout_type='SMALL', is_active=True) for name in ('NE', 'NW', 'SE', 'SW')]
        self.layout_a = self._layout('2 Small', self.fields[:2])
        self.layout_b = self._layout('4 Small', self.fields)
        self.used_layout = self._layout('Legacy Layout', self.fields[:1])
        self.week = Week(id=uuid.uuid4(), season_id=None, week_number=3, label='Week 3', start_date=date(2026, 8, 17), end_date=date(2026, 8, 23), primary_game_date=date(2026, 8, 23), date_type='REGULAR_SEASON')
        self.availability = HostingAvailability(id=uuid.uuid4(), week_id=self.week.id, organization_id=self.org.id, host_location_id=self.host.id, selected_configuration_id=self.used_layout.id, available_date=date(2026, 8, 23), start_time=time(9), end_time=time(12), active=True, is_available=True)
        self.db.add_all([self.org, self.host, *roles, *self.users.values(), *self.fields, self.layout_a, self.layout_b, self.used_layout, self.week, self.availability])
        self.db.commit()

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()
        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def _layout(self, name, fields):
        layout = HostLocationConfiguration(id=uuid.uuid4(), host_location_id=self.host.id, configuration_name=name, surface_type='GRASS_FIELD', is_active=True)
        layout.members = [FieldConfigurationMember(field=field) for field in fields]
        return layout

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def _headers(self, role):
        return {'Authorization': f'Bearer {create_access_token(str(self.users[role].id))}'}

    def test_scheduling_admin_deletes_only_layout_and_preserves_shared_fields(self):
        response = self.client.delete(f'/api/host-location-configurations/{self.layout_a.id}', headers=self._headers(ROLE_SCHEDULING_ADMIN))
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual('Field layout deleted successfully.', response.json()['message'])
        self.db.expire_all()
        self.assertIsNone(self.db.get(HostLocationConfiguration, self.layout_a.id))
        self.assertIsNotNone(self.db.get(HostLocationConfiguration, self.layout_b.id))
        self.assertEqual(4, self.db.query(Field).filter(Field.host_location_id == self.host.id).count())

    def test_league_admin_can_delete_inactive_unused_layout(self):
        self.layout_a.is_active = False
        self.db.commit()
        response = self.client.delete(f'/api/host-location-configurations/{self.layout_a.id}', headers=self._headers(LEGACY_ROLE_LEAGUE_ADMIN))
        self.assertEqual(200, response.status_code, response.text)
        self.db.expire_all()
        self.assertIsNone(self.db.get(HostLocationConfiguration, self.layout_a.id))

    def test_community_admin_is_forbidden(self):
        response = self.client.delete(f'/api/host-location-configurations/{self.layout_a.id}', headers=self._headers(ROLE_COMMUNITY_ADMIN))
        self.assertEqual(403, response.status_code, response.text)
        self.db.expire_all()
        self.assertIsNotNone(self.db.get(HostLocationConfiguration, self.layout_a.id))

    def test_hosting_dependency_blocks_delete_and_identifies_week(self):
        response = self.client.delete(f'/api/host-location-configurations/{self.used_layout.id}', headers=self._headers(ROLE_SCHEDULING_ADMIN))
        self.assertEqual(409, response.status_code, response.text)
        self.assertEqual('FIELD_LAYOUT_IN_USE', response.json()['detail']['code'])
        self.assertIn('hosting availability for Week 3', response.json()['detail']['message'])
        self.db.expire_all()
        self.assertIsNotNone(self.db.get(HostLocationConfiguration, self.used_layout.id))
        self.assertIsNotNone(self.db.get(HostingAvailability, self.availability.id))


if __name__ == '__main__':
    unittest.main()
