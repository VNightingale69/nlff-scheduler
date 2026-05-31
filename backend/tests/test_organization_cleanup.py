import unittest
import uuid
from datetime import date, time

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import ROLE_COMMUNITY_ADMIN, ROLE_LEAGUE_ADMIN
from app.database import Base, get_db
from app.main import app
from app.models import (
    Division,
    Field,
    FieldConfigurationOption,
    FieldInstance,
    Game,
    GameSlot,
    GameStatus,
    HostLocation,
    HostLocationConfiguration,
    HostPlanSelection,
    HostingAvailability,
    Organization,
    OrganizationDivisionParticipation,
    PhysicalFieldArea,
    Role,
    Season,
    Team,
    TurfWave,
    User,
)
from app.security import create_access_token, hash_password
from app.services.organization_cleanup import cleanup_organization_dependencies


class OrganizationCleanupTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()

        self.league_role = Role(id=uuid.uuid4(), name=ROLE_LEAGUE_ADMIN, is_active=True)
        self.community_role = Role(id=uuid.uuid4(), name=ROLE_COMMUNITY_ADMIN, is_active=True)
        self.org = Organization(id=uuid.uuid4(), name='Westosha', is_active=True)
        self.other_org = Organization(id=uuid.uuid4(), name='Westosha Falcons', is_active=True)
        self.division = Division(id=uuid.uuid4(), name='3rd', division_group='COED', sort_order=1, required_field_layout_type='SMALL', is_active=True)
        self.season = Season(id=uuid.uuid4(), name='Fall 2026', start_date=date(2026, 8, 1), end_date=date(2026, 11, 1), is_active=True)
        self.week = WeekFixture.week(self.season.id)
        self.status = GameStatus(id=uuid.uuid4(), code='scheduled', label='Scheduled', is_active=True)
        self.host = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Host A', is_active=True)
        self.other_host = HostLocation(id=uuid.uuid4(), organization_id=self.other_org.id, name='Host B', is_active=True)
        self.config = HostLocationConfiguration(id=uuid.uuid4(), host_location_id=self.host.id, configuration_name='Config A', is_active=True)
        self.area = PhysicalFieldArea(id=uuid.uuid4(), host_location_id=self.host.id, name='Area', field_space_type='grass', supports_dynamic_configuration=True, is_active=True)
        self.option = FieldConfigurationOption(id=uuid.uuid4(), physical_field_area_id=self.area.id, name='Option A', thirty_yard_capacity=1, fifty_three_yard_capacity=0, is_active=True)
        self.field = Field(id=uuid.uuid4(), host_location_id=self.host.id, physical_field_area_id=self.area.id, name='Field A', layout_type='SMALL', is_active=True)
        self.availability = HostingAvailability(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            organization_id=self.org.id,
            host_location_id=self.host.id,
            selected_configuration_id=self.config.id,
            field_id=self.field.id,
            physical_field_area_id=self.area.id,
            field_configuration_option_id=self.option.id,
            layout_type='SMALL',
            slot_index=1,
            available_date=date(2026, 9, 1),
            start_time=time(10, 0),
            end_time=time(11, 0),
            is_available=True,
        )
        self.host_plan_selection = HostPlanSelection(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            game_date=date(2026, 9, 1),
            community_id=self.org.id,
            host_location_id=self.host.id,
            availability_id=self.availability.id,
            status='SELECTED',
        )
        self.turf_wave = TurfWave(
            id=uuid.uuid4(),
            host_location_id=self.host.id,
            hosting_availability_id=self.availability.id,
            week_id=self.week.id,
            host_date=date(2026, 9, 1),
            sequence_number=1,
            wave_intent='MIXED',
            preferred_layout_code='THREE_SMALL',
            start_time=time(10, 0),
            end_time=time(11, 0),
        )
        self.instance = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=self.availability.id, instance_date=date(2026, 9, 1), field_name='Field A', field_type='SMALL', is_active=True)
        self.home = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='Home', is_active=True)
        self.away = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='Away', is_active=True)
        self.other_team = Team(id=uuid.uuid4(), organization_id=self.other_org.id, division_id=self.division.id, name='Other', is_active=True)
        self.game = Game(id=uuid.uuid4(), home_team_id=self.home.id, away_team_id=self.away.id, field_id=self.field.id, host_location_id=self.host.id, field_instance_id=self.instance.id, game_status_id=self.status.id, game_date=date(2026, 9, 1), kickoff_time=time(10, 0))
        self.slot = GameSlot(id=uuid.uuid4(), field_instance_id=self.instance.id, host_location_id=self.host.id, slot_date=date(2026, 9, 1), start_time=time(10, 0), end_time=time(11, 0), field_type='SMALL', status='OPEN', assigned_game_id=self.game.id, turf_wave_id=self.turf_wave.id)
        self.participation = OrganizationDivisionParticipation(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, is_participating=True, team_count=2, is_active=True)
        self.global_admin = User(id=uuid.uuid4(), email='global@example.com', full_name='Global Admin', password_hash='x', role_id=self.league_role.id, organization_id=None, is_active=True)
        self.assigned_admin = User(id=uuid.uuid4(), email='assigned@example.com', full_name='Assigned Admin', password_hash='x', role_id=self.league_role.id, organization_id=self.org.id, is_active=True)
        self.community_admin = User(id=uuid.uuid4(), email='community@example.com', full_name='Community Admin', password_hash='x', role_id=self.community_role.id, organization_id=self.org.id, is_active=True)

        self.db.add_all([
            self.league_role, self.community_role, self.org, self.other_org, self.division, self.season, self.week, self.status,
            self.host, self.other_host, self.config, self.area, self.option, self.field, self.availability,
            self.host_plan_selection, self.turf_wave, self.instance, self.home, self.away, self.other_team,
            self.game, self.slot, self.participation, self.global_admin, self.assigned_admin, self.community_admin,
        ])
        self.db.commit()

    def test_dry_run_reports_without_deleting(self):
        result = cleanup_organization_dependencies(self.db, self.org.id, dry_run=True)
        self.assertTrue(result['dry_run'])
        self.assertEqual(result['would_delete']['organizations'], 1)
        self.assertEqual(result['would_delete']['generated_slots'], 1)
        self.assertEqual(result['would_delete']['users'], 2)
        self.assertEqual(self.db.query(Organization).filter(Organization.id == self.org.id).count(), 1)
        self.assertEqual(self.db.query(Game).count(), 1)

    def test_cleanup_deletes_dependencies_and_selected_org_only(self):
        result = cleanup_organization_dependencies(self.db, self.org.id, dry_run=False)
        self.assertFalse(result['dry_run'])
        for key in [
            'organizations', 'teams', 'games', 'game_slots', 'generated_slots', 'host_locations', 'fields',
            'physical_field_areas', 'host_location_configurations', 'hosting_availabilities',
            'field_configuration_options', 'field_instances', 'turf_waves', 'host_plan_selections',
            'organization_division_participations', 'users',
        ]:
            self.assertGreaterEqual(result['deleted'][key], 1, key)
        self.assertIsNone(self.db.get(Organization, self.org.id))
        self.assertIsNotNone(self.db.get(Organization, self.other_org.id))
        self.assertEqual(self.db.get(Organization, self.other_org.id).name, 'Westosha Falcons')
        self.assertIsNotNone(self.db.get(Team, self.other_team.id))
        self.assertIsNotNone(self.db.get(HostLocation, self.other_host.id))
        self.assertIsNotNone(self.db.get(User, self.global_admin.id))
        self.assertIsNone(self.db.get(User, self.assigned_admin.id))
        self.assertIsNone(self.db.get(User, self.community_admin.id))
        self.assertEqual(self.db.query(GameSlot).count(), 0)
        self.assertEqual(self.db.query(Game).count(), 0)
        self.assertEqual(self.db.query(HostingAvailability).count(), 0)
        self.assertEqual(self.db.query(HostPlanSelection).count(), 0)

    def test_not_found_returns_user_friendly_error(self):
        with self.assertRaises(HTTPException) as ctx:
            cleanup_organization_dependencies(self.db, uuid.uuid4(), dry_run=False)
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, 'Organization not found')


class WeekFixture:
    @staticmethod
    def week(season_id):
        from app.models import Week
        return Week(id=uuid.uuid4(), season_id=season_id, week_number=1, start_date=date(2026, 8, 31), end_date=date(2026, 9, 6), primary_game_date=date(2026, 9, 1), date_type='REGULAR_SEASON')


class OrganizationDeleteEndpointPermissionsTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            'sqlite+pysqlite:///:memory:',
            future=True,
            connect_args={'check_same_thread': False},
            poolclass=StaticPool,
        )

        @event.listens_for(engine, 'connect')
        def _set_sqlite_pragma(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.close()

        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.db = self.SessionLocal()
        self.league_role = Role(id=uuid.uuid4(), name=ROLE_LEAGUE_ADMIN, is_active=True)
        self.community_role = Role(id=uuid.uuid4(), name=ROLE_COMMUNITY_ADMIN, is_active=True)
        self.org = Organization(id=uuid.uuid4(), name='Endpoint Org', is_active=True)
        self.league_user = User(id=uuid.uuid4(), email='league@example.com', full_name='League', password_hash=hash_password('Password123!'), role_id=self.league_role.id, organization_id=None, is_active=True)
        self.community_user = User(id=uuid.uuid4(), email='comm@example.com', full_name='Community', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.org.id, is_active=True)
        self.db.add_all([self.league_role, self.community_role, self.org, self.league_user, self.community_user])
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

    def test_community_admin_cannot_delete_organizations(self):
        response = self.client.delete(
            f'/api/organizations/{self.org.id}',
            headers={'Authorization': f'Bearer {create_access_token(str(self.community_user.id))}'},
        )
        self.assertEqual(response.status_code, 403)
        self.assertIsNotNone(self.db.get(Organization, self.org.id))

    def test_league_admin_can_delete_unused_duplicate_safely(self):
        response = self.client.delete(
            f'/api/organizations/{self.org.id}',
            headers={'Authorization': f'Bearer {create_access_token(str(self.league_user.id))}'},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload['deleted']['organizations'], 1)
        self.assertEqual(payload['counts']['organizations'], 1)
        self.db.expire_all()
        self.assertIsNone(self.db.get(Organization, self.org.id))


if __name__ == '__main__':
    unittest.main()
