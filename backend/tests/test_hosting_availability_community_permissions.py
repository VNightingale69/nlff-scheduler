import unittest
import uuid
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import ROLE_COMMUNITY_ADMIN, ROLE_LEAGUE_ADMIN
from app.database import Base, get_db
from app.main import app
from app.models import FieldConfigurationOption, HostLocation, Organization, PhysicalFieldArea, Role, Season, User, Week, HostingAvailability
from app.security import create_access_token, hash_password


class HostingAvailabilityCommunityPermissionsTest(unittest.TestCase):
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
        self.other_org = Organization(id=uuid.uuid4(), name='Lake County', is_active=True)
        self.season = Season(id=uuid.uuid4(), name='Fall 2026', start_date=date(2026, 9, 1), end_date=date(2026, 11, 1), is_active=True)
        self.week = Week(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_number=1,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 7),
            primary_game_date=date(2026, 9, 6),
            status='draft',
        )
        self.host = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Westosha Fields', surface_type='GRASS_FIELD', is_active=True)
        self.other_host = HostLocation(id=uuid.uuid4(), organization_id=self.other_org.id, name='Lake County Fields', surface_type='GRASS_FIELD', is_active=True)
        self.area = PhysicalFieldArea(id=uuid.uuid4(), host_location_id=self.host.id, name='Westosha Area', field_space_type='GRASS_FIELD', is_active=True)
        self.other_area = PhysicalFieldArea(id=uuid.uuid4(), host_location_id=self.other_host.id, name='Lake Area', field_space_type='GRASS_FIELD', is_active=True)
        self.option = FieldConfigurationOption(id=uuid.uuid4(), physical_field_area_id=self.area.id, name='Small Field', small_field_count=1, is_active=True)
        self.other_option = FieldConfigurationOption(id=uuid.uuid4(), physical_field_area_id=self.other_area.id, name='Other Small Field', small_field_count=1, is_active=True)
        self.community_user = User(id=uuid.uuid4(), email='westosha@example.com', full_name='Westosha Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.org.id, is_active=True)
        self.other_user = User(id=uuid.uuid4(), email='lake@example.com', full_name='Lake Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.other_org.id, is_active=True)
        self.league_user = User(id=uuid.uuid4(), email='league@example.com', full_name='League Admin', password_hash=hash_password('Password123!'), role_id=self.league_role.id, organization_id=None, is_active=True)
        self.db.add_all([
            self.league_role, self.community_role, self.org, self.other_org, self.season, self.week,
            self.host, self.other_host, self.area, self.other_area, self.option, self.other_option,
            self.community_user, self.other_user, self.league_user,
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

    def _slot_payload(self, **overrides):
        payload = {
            'season_id': str(self.season.id),
            'week_id': str(self.week.id),
            'physical_field_area_id': str(self.area.id),
            'field_configuration_option_id': str(self.option.id),
            'available_date': '2026-09-06',
            'start_time': '09:00:00',
            'end_time': '10:00:00',
            'is_available': True,
        }
        payload.update(overrides)
        return payload

    def test_community_admin_bulk_upsert_forces_own_organization_and_generated_slots_refresh_is_allowed(self):
        response = self.client.post(
            '/api/hosting-availabilities/bulk-upsert',
            headers=self._token(self.community_user.id),
            json={'slots': [self._slot_payload()]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        availability = self.db.query(HostingAvailability).one()
        self.assertEqual(availability.organization_id, self.org.id)
        self.assertEqual(availability.host_location_id, self.host.id)

        slots_response = self.client.get(
            f'/api/hosting-availabilities/generated-slots?host_location_id={self.host.id}&available_date=2026-09-06',
            headers=self._token(self.community_user.id),
        )
        self.assertEqual(slots_response.status_code, 200, slots_response.text)

    def test_community_admin_cannot_bulk_upsert_for_another_organization(self):
        response = self.client.post(
            '/api/hosting-availabilities/bulk-upsert',
            headers=self._token(self.community_user.id),
            json={'slots': [self._slot_payload(organization_id=str(self.other_org.id))]},
        )
        self.assertEqual(response.status_code, 403)
        self.db.expire_all()
        self.assertEqual(self.db.query(HostingAvailability).count(), 0)

    def test_community_admin_cannot_use_another_organizations_field_area(self):
        response = self.client.post(
            '/api/hosting-availabilities/bulk-upsert',
            headers=self._token(self.community_user.id),
            json={'slots': [self._slot_payload(physical_field_area_id=str(self.other_area.id), field_configuration_option_id=str(self.other_option.id))]},
        )
        self.assertEqual(response.status_code, 403)
        self.db.expire_all()
        self.assertEqual(self.db.query(HostingAvailability).count(), 0)

    def test_league_admin_retains_cross_organization_access(self):
        response = self.client.post(
            '/api/hosting-availabilities/bulk-upsert',
            headers=self._token(self.league_user.id),
            json={'slots': [self._slot_payload(physical_field_area_id=str(self.other_area.id), field_configuration_option_id=str(self.other_option.id), organization_id=str(self.other_org.id))]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        availability = self.db.query(HostingAvailability).one()
        self.assertEqual(availability.organization_id, self.other_org.id)
        self.assertEqual(availability.host_location_id, self.other_host.id)


if __name__ == '__main__':
    unittest.main()
