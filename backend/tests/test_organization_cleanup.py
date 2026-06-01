import unittest
import uuid
from datetime import date, time

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
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

        @event.listens_for(engine, 'connect')
        def _set_sqlite_pragma(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.close()

        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()

        self.league_role = Role(id=uuid.uuid4(), name=ROLE_LEAGUE_ADMIN, is_active=True)
        self.community_role = Role(id=uuid.uuid4(), name=ROLE_COMMUNITY_ADMIN, is_active=True)
        self.org = Organization(id=uuid.uuid4(), name='Antioch Vikings', is_active=True)
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
        self.assertEqual(result['organization_id'], str(self.org.id))
        self.assertEqual(result['organization_name'], 'Antioch Vikings')
        fk_pairs = {(fk['table'], fk['referred_table']) for fk in result['dependent_foreign_keys']}
        self.assertIn(('host_locations', 'organizations'), fk_pairs)
        self.assertIn(('users', 'organizations'), fk_pairs)
        self.assertIn(('organization_division_participations', 'organizations'), fk_pairs)
        self.assertIn(('host_plan_selections', 'organizations'), fk_pairs)
        self.assertIn(('hosting_availabilities', 'organizations'), fk_pairs)
        self.assertIn(('fields', 'host_locations'), fk_pairs)
        self.assertIn(('physical_field_areas', 'host_locations'), fk_pairs)
        self.assertIn(('host_location_configurations', 'host_locations'), fk_pairs)
        self.assertIn(('field_instances', 'hosting_availabilities'), fk_pairs)
        self.assertIn(('turf_waves', 'hosting_availabilities'), fk_pairs)
        self.assertIn(('game_slots', 'games'), fk_pairs)
        self.assertIn(('games', 'teams'), fk_pairs)
        self.assertEqual(result['would_delete']['organizations'], 1)
        self.assertEqual(result['would_delete']['generated_slots'], 1)
        self.assertEqual(result['would_delete']['users'], 2)
        self.assertEqual(self.db.query(Organization).filter(Organization.id == self.org.id).count(), 1)
        self.assertEqual(self.db.query(Game).count(), 1)

    def test_cleanup_deletes_dependencies_and_selected_org_only(self):
        org_id = self.org.id
        organization_id = str(org_id)
        assigned_admin_id = self.assigned_admin.id
        community_admin_id = self.community_admin.id
        result = cleanup_organization_dependencies(self.db, org_id, dry_run=False)
        self.assertFalse(result['dry_run'])
        self.assertEqual(result['organization_id'], organization_id)
        self.assertEqual(result['organization_name'], 'Antioch Vikings')
        for key in [
            'organizations', 'teams', 'games', 'game_slots', 'generated_slots', 'host_locations', 'fields',
            'physical_field_areas', 'host_location_configurations', 'hosting_availabilities',
            'field_configuration_options', 'field_instances', 'turf_waves', 'host_plan_selections',
            'organization_division_participations', 'users',
        ]:
            self.assertGreaterEqual(result['deleted'][key], 1, key)
        self.assertIsNone(self.db.get(Organization, org_id))
        self.assertIsNotNone(self.db.get(Organization, self.other_org.id))
        self.assertEqual(self.db.get(Organization, self.other_org.id).name, 'Westosha Falcons')
        self.assertIsNotNone(self.db.get(Team, self.other_team.id))
        self.assertIsNotNone(self.db.get(HostLocation, self.other_host.id))
        self.assertIsNotNone(self.db.get(User, self.global_admin.id))
        self.assertIsNone(self.db.get(User, assigned_admin_id))
        self.assertIsNone(self.db.get(User, community_admin_id))
        self.assertEqual(self.db.query(GameSlot).count(), 0)
        self.assertEqual(self.db.query(Game).count(), 0)
        self.assertEqual(self.db.query(HostingAvailability).count(), 0)
        self.assertEqual(self.db.query(HostPlanSelection).count(), 0)
        self.assert_no_orphaned_organization_dependencies()

    def assert_no_orphaned_organization_dependencies(self):
        orphan_checks = {
            'users.organization_id': "SELECT COUNT(*) FROM users WHERE organization_id IS NOT NULL AND organization_id NOT IN (SELECT id FROM organizations)",
            'host_locations.organization_id': "SELECT COUNT(*) FROM host_locations WHERE organization_id NOT IN (SELECT id FROM organizations)",
            'teams.organization_id': "SELECT COUNT(*) FROM teams WHERE organization_id NOT IN (SELECT id FROM organizations)",
            'organization_division_participations.organization_id': "SELECT COUNT(*) FROM organization_division_participations WHERE organization_id NOT IN (SELECT id FROM organizations)",
            'hosting_availabilities.organization_id': "SELECT COUNT(*) FROM hosting_availabilities WHERE organization_id IS NOT NULL AND organization_id NOT IN (SELECT id FROM organizations)",
            'host_plan_selections.community_id': "SELECT COUNT(*) FROM host_plan_selections WHERE community_id NOT IN (SELECT id FROM organizations)",
            'fields.host_location_id': "SELECT COUNT(*) FROM fields WHERE host_location_id NOT IN (SELECT id FROM host_locations)",
            'physical_field_areas.host_location_id': "SELECT COUNT(*) FROM physical_field_areas WHERE host_location_id NOT IN (SELECT id FROM host_locations)",
            'field_configuration_options.physical_field_area_id': "SELECT COUNT(*) FROM field_configuration_options WHERE physical_field_area_id NOT IN (SELECT id FROM physical_field_areas)",
            'hosting_availabilities.host_location_id': "SELECT COUNT(*) FROM hosting_availabilities WHERE host_location_id IS NOT NULL AND host_location_id NOT IN (SELECT id FROM host_locations)",
            'hosting_availabilities.field_id': "SELECT COUNT(*) FROM hosting_availabilities WHERE field_id IS NOT NULL AND field_id NOT IN (SELECT id FROM fields)",
            'hosting_availabilities.physical_field_area_id': "SELECT COUNT(*) FROM hosting_availabilities WHERE physical_field_area_id IS NOT NULL AND physical_field_area_id NOT IN (SELECT id FROM physical_field_areas)",
            'hosting_availabilities.field_configuration_option_id': "SELECT COUNT(*) FROM hosting_availabilities WHERE field_configuration_option_id IS NOT NULL AND field_configuration_option_id NOT IN (SELECT id FROM field_configuration_options)",
            'hosting_availabilities.selected_configuration_id': "SELECT COUNT(*) FROM hosting_availabilities WHERE selected_configuration_id IS NOT NULL AND selected_configuration_id NOT IN (SELECT id FROM host_location_configurations)",
            'field_instances.host_location_id': "SELECT COUNT(*) FROM field_instances WHERE host_location_id NOT IN (SELECT id FROM host_locations)",
            'field_instances.hosting_availability_id': "SELECT COUNT(*) FROM field_instances WHERE hosting_availability_id NOT IN (SELECT id FROM hosting_availabilities)",
            'turf_waves.host_location_id': "SELECT COUNT(*) FROM turf_waves WHERE host_location_id NOT IN (SELECT id FROM host_locations)",
            'turf_waves.hosting_availability_id': "SELECT COUNT(*) FROM turf_waves WHERE hosting_availability_id NOT IN (SELECT id FROM hosting_availabilities)",
            'game_slots.field_instance_id': "SELECT COUNT(*) FROM game_slots WHERE field_instance_id NOT IN (SELECT id FROM field_instances)",
            'game_slots.host_location_id': "SELECT COUNT(*) FROM game_slots WHERE host_location_id NOT IN (SELECT id FROM host_locations)",
            'game_slots.assigned_game_id': "SELECT COUNT(*) FROM game_slots WHERE assigned_game_id IS NOT NULL AND assigned_game_id NOT IN (SELECT id FROM games)",
            'game_slots.turf_wave_id': "SELECT COUNT(*) FROM game_slots WHERE turf_wave_id IS NOT NULL AND turf_wave_id NOT IN (SELECT id FROM turf_waves)",
            'games.home_team_id': "SELECT COUNT(*) FROM games WHERE home_team_id NOT IN (SELECT id FROM teams)",
            'games.away_team_id': "SELECT COUNT(*) FROM games WHERE away_team_id NOT IN (SELECT id FROM teams)",
            'games.field_id': "SELECT COUNT(*) FROM games WHERE field_id IS NOT NULL AND field_id NOT IN (SELECT id FROM fields)",
            'games.host_location_id': "SELECT COUNT(*) FROM games WHERE host_location_id IS NOT NULL AND host_location_id NOT IN (SELECT id FROM host_locations)",
            'games.field_instance_id': "SELECT COUNT(*) FROM games WHERE field_instance_id IS NOT NULL AND field_instance_id NOT IN (SELECT id FROM field_instances)",
        }
        for label, sql in orphan_checks.items():
            with self.subTest(label=label):
                self.assertEqual(self.db.execute(text(sql)).scalar_one(), 0)

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
        self.division = Division(id=uuid.uuid4(), name='Endpoint 3rd', division_group='COED', sort_order=1, required_field_layout_type='SMALL', is_active=True)
        self.league_user = User(id=uuid.uuid4(), email='league@example.com', full_name='League', password_hash=hash_password('Password123!'), role_id=self.league_role.id, organization_id=None, is_active=True)
        self.community_user = User(id=uuid.uuid4(), email='comm@example.com', full_name='Community', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.org.id, is_active=True)
        self.db.add_all([self.league_role, self.community_role, self.org, self.division, self.league_user, self.community_user])
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

    def _create_dependent_organization(self, name: str, email_prefix: str):
        org = Organization(id=uuid.uuid4(), name=name, is_active=True)
        host = HostLocation(id=uuid.uuid4(), organization_id=org.id, name=f'{name} Fields', is_active=True)
        team = Team(id=uuid.uuid4(), organization_id=org.id, division_id=self.division.id, name=f'{name} Team', is_active=True)
        participation = OrganizationDivisionParticipation(
            id=uuid.uuid4(),
            organization_id=org.id,
            division_id=self.division.id,
            is_participating=True,
            team_count=1,
            is_active=True,
        )
        user = User(
            id=uuid.uuid4(),
            email=f'{email_prefix}@example.com',
            full_name=f'{name} Admin',
            password_hash=hash_password('Password123!'),
            role_id=self.community_role.id,
            organization_id=org.id,
            is_active=True,
        )
        self.db.add_all([org, host, team, participation, user])
        self.db.commit()
        return org.id, org.name

    def _assert_no_basic_org_orphans(self):
        orphan_checks = {
            'users.organization_id': "SELECT COUNT(*) FROM users WHERE organization_id IS NOT NULL AND organization_id NOT IN (SELECT id FROM organizations)",
            'host_locations.organization_id': "SELECT COUNT(*) FROM host_locations WHERE organization_id NOT IN (SELECT id FROM organizations)",
            'teams.organization_id': "SELECT COUNT(*) FROM teams WHERE organization_id NOT IN (SELECT id FROM organizations)",
            'organization_division_participations.organization_id': "SELECT COUNT(*) FROM organization_division_participations WHERE organization_id NOT IN (SELECT id FROM organizations)",
        }
        for label, sql in orphan_checks.items():
            with self.subTest(label=label):
                self.assertEqual(self.db.execute(text(sql)).scalar_one(), 0)

    def test_community_admin_cannot_delete_organizations(self):
        response = self.client.delete(
            f'/api/organizations/{self.org.id}',
            headers={'Authorization': f'Bearer {create_access_token(str(self.community_user.id))}'},
        )
        self.assertEqual(response.status_code, 403)
        self.assertIsNotNone(self.db.get(Organization, self.org.id))

    def test_league_admin_can_delete_dependent_organizations_without_object_deleted_error(self):
        token = create_access_token(str(self.league_user.id))
        for org_name, email_prefix in [('Johnsburg Skyhawks', 'johnsburg'), ('Westosha Falcons', 'westosha')]:
            org_id, expected_name = self._create_dependent_organization(org_name, email_prefix)
            response = self.client.delete(
                f'/api/organizations/{org_id}',
                headers={'Authorization': f'Bearer {token}'},
            )
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            self.assertEqual(payload['organization_id'], str(org_id))
            self.assertEqual(payload['organization_name'], expected_name)
            self.assertEqual(payload['deleted']['organizations'], 1)
            self.assertGreaterEqual(payload['deleted']['users'], 1)
            self.assertGreaterEqual(payload['deleted']['teams'], 1)
            self.assertGreaterEqual(payload['deleted']['host_locations'], 1)
            self.assertGreaterEqual(payload['deleted']['organization_division_participations'], 1)
            self.db.expire_all()
            self.assertIsNone(self.db.get(Organization, org_id))
            self._assert_no_basic_org_orphans()

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
