import unittest
import uuid
from datetime import date, time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import ROLE_COMMUNITY_ADMIN, ROLE_LEAGUE_ADMIN, ROLE_SCHEDULING_ADMIN
from app.database import Base, get_db
from app.main import app
from app.models import Division, FieldInstance, Game, GameScore, GameSlot, GameStatus, HostLocation, Organization, Role, ScheduleChangeLog, Season, Team, User, Week
from app.security import create_access_token, hash_password


class ManualScheduleEditPermissionsTest(unittest.TestCase):
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
        self.scheduling_role = Role(id=uuid.uuid4(), name=ROLE_SCHEDULING_ADMIN, is_active=True)
        self.home_org = Organization(id=uuid.uuid4(), name='Home Community', is_active=True)
        self.away_org = Organization(id=uuid.uuid4(), name='Away Community', is_active=True)
        self.host = HostLocation(id=uuid.uuid4(), organization_id=self.home_org.id, name='Main Park', is_active=True)
        self.division = Division(id=uuid.uuid4(), name='2-3', division_group='COED', sort_order=1, required_field_layout_type='THIRTY_YARD_WIDTH', is_active=True)
        self.season = Season(id=uuid.uuid4(), name='Fall 2026', start_date=date(2026, 8, 1), end_date=date(2026, 11, 1), is_active=True, schedule_status='published')
        self.week = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=1, label='Week 1', start_date=date(2026, 8, 8), end_date=date(2026, 8, 14), primary_game_date=date(2026, 8, 9))
        self.status = GameStatus(id=uuid.uuid4(), code='SCHEDULED', label='Scheduled', is_active=True)
        self.cancelled = GameStatus(id=uuid.uuid4(), code='CANCELLED', label='Cancelled', is_active=True)
        self.home_team = Team(id=uuid.uuid4(), organization_id=self.home_org.id, division_id=self.division.id, name='Home 1', is_active=True)
        self.away_team = Team(id=uuid.uuid4(), organization_id=self.away_org.id, division_id=self.division.id, name='Away 1', is_active=True)
        self.other_team = Team(id=uuid.uuid4(), organization_id=self.away_org.id, division_id=self.division.id, name='Away 2', is_active=True)
        self.field = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=date(2026, 8, 9), field_name='Small Field 1', field_type='SMALL', is_active=True)
        self.slot = GameSlot(id=uuid.uuid4(), field_instance_id=self.field.id, host_location_id=self.host.id, season_id=self.season.id, week_id=self.week.id, slot_date=date(2026, 8, 9), start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='ASSIGNED')
        self.game = Game(id=uuid.uuid4(), season_id=self.season.id, week_id=self.week.id, home_team_id=self.home_team.id, away_team_id=self.away_team.id, host_location_id=self.host.id, field_instance_id=self.field.id, game_status_id=self.status.id, game_date=date(2026, 8, 9), kickoff_time=time(9, 0))
        self.slot.assigned_game_id = self.game.id
        self.league_user = User(id=uuid.uuid4(), email='league@example.com', full_name='League Admin', password_hash=hash_password('Password123!'), role_id=self.league_role.id, is_active=True)
        self.scheduling_user = User(id=uuid.uuid4(), email='scheduler@example.com', full_name='Scheduling Admin', password_hash=hash_password('Password123!'), role_id=self.scheduling_role.id, is_active=True)
        self.community_user = User(id=uuid.uuid4(), email='community@example.com', full_name='Community Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.home_org.id, is_active=True)
        self.db.add_all([
            self.league_role, self.community_role, self.scheduling_role, self.home_org, self.away_org, self.host, self.division,
            self.season, self.week, self.status, self.cancelled, self.home_team, self.away_team, self.other_team,
            self.field, self.game, self.slot, self.league_user, self.scheduling_user, self.community_user,
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

    def _payload(self, **overrides):
        payload = {
            'season_id': str(self.season.id),
            'week_id': str(self.week.id),
            'division_id': str(self.division.id),
            'home_team_id': str(self.home_team.id),
            'away_team_id': str(self.other_team.id),
            'host_location_id': str(self.host.id),
            'field_instance_id': str(self.field.id),
            'game_status_id': str(self.status.id),
            'game_date': '2026-08-09',
            'kickoff_time': '09:00:00',
            'public_notes': 'Public update',
            'internal_admin_notes': 'Internal note',
            'override_warnings': True,
            'score_change_confirmed': True,
        }
        payload.update(overrides)
        return payload

    def test_community_admin_direct_edit_api_is_forbidden_and_data_unchanged(self):
        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.community_user.id),
            json=self._payload(),
        )
        self.assertEqual(response.status_code, 403)
        self.db.expire_all()
        game = self.db.get(Game, self.game.id)
        self.assertEqual(game.away_team_id, self.away_team.id)
        self.assertFalse(game.is_manual_edit)
        self.assertEqual(self.db.query(ScheduleChangeLog).count(), 0)

    def test_public_user_cannot_access_manual_edit_endpoint(self):
        response = self.client.patch(f'/api/schedule-management/games/{self.game.id}/manual-edit', json=self._payload())
        self.assertEqual(response.status_code, 403)

    def test_league_admin_can_save_manual_edit_and_audit_log(self):
        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.league_user.id),
            json=self._payload(),
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['game']['id'], str(self.game.id))
        self.assertTrue(data['game']['is_manual_edit'])
        self.assertEqual(data['game']['away_team_id'], str(self.other_team.id))
        self.assertGreaterEqual(len(data['change_log']), 1)
        self.db.expire_all()
        game = self.db.get(Game, self.game.id)
        self.assertEqual(game.away_team_id, self.other_team.id)
        self.assertTrue(game.is_manual_edit)
        self.assertEqual(game.internal_admin_notes, 'Internal note')
        self.assertGreaterEqual(self.db.query(ScheduleChangeLog).filter(ScheduleChangeLog.game_id == self.game.id).count(), 1)


    def test_scheduling_admin_can_save_generated_game_without_status_payload_and_status_is_preserved(self):
        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.scheduling_user.id),
            json=self._payload(game_status_id=None, away_team_id=str(self.other_team.id), internal_admin_notes='Scheduler override'),
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['game']['id'], str(self.game.id))
        self.assertEqual(data['game']['game_status_id'], str(self.status.id))
        self.assertEqual(data['game']['status_code'], 'SCHEDULED')
        self.assertEqual(data['game']['away_team_id'], str(self.other_team.id))
        self.db.expire_all()
        game = self.db.get(Game, self.game.id)
        self.assertEqual(game.id, self.game.id)
        self.assertEqual(game.game_status_id, self.status.id)
        self.assertEqual(game.away_team_id, self.other_team.id)
        self.assertEqual(game.internal_admin_notes, 'Scheduler override')


    def test_field_size_mismatch_is_warning_override_not_hard_block(self):
        large_field = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=date(2026, 8, 9), field_name='Large Field 1', field_type='LARGE', is_active=True)
        self.db.add(large_field)
        self.db.commit()

        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.league_user.id),
            json=self._payload(field_instance_id=str(large_field.id), override_warnings=False),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail']['error'], 'SCHEDULE_WARNINGS_REQUIRE_OVERRIDE')
        warning_codes = {warning['code'] for warning in response.json()['detail']['warnings']}
        self.assertIn('FIELD_SIZE_MISMATCH', warning_codes)

        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.league_user.id),
            json=self._payload(field_instance_id=str(large_field.id), override_warnings=True),
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['game']['id'], str(self.game.id))
        self.assertEqual(data['game']['field_instance_id'], str(large_field.id))
        self.assertIn('FIELD_SIZE_MISMATCH', {warning['code'] for warning in data['warnings']})
        self.db.expire_all()
        game = self.db.get(Game, self.game.id)
        self.assertEqual(game.field_instance_id, large_field.id)

    def test_unoptimized_turf_subset_is_warning_not_hard_block(self):
        self.host.surface_type = 'TURF_STADIUM'
        large_field = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=date(2026, 8, 9), field_name='Large Field 1', field_type='LARGE', is_active=True)
        self.db.add(large_field)
        self.db.commit()

        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.league_user.id),
            json=self._payload(field_instance_id=str(large_field.id), override_warnings=True),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        game = self.db.get(Game, self.game.id)
        self.assertEqual(game.field_instance_id, large_field.id)

    def test_two_large_fields_on_one_turf_surface_are_hard_blocked(self):
        self.host.surface_type = 'TURF_STADIUM'
        large_field_1 = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=date(2026, 8, 9), field_name='Large Field 1', field_type='LARGE', is_active=True)
        large_field_2 = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=date(2026, 8, 9), field_name='Large Field 3', field_type='LARGE', is_active=True)
        conflict_home = Team(id=uuid.uuid4(), organization_id=self.home_org.id, division_id=self.division.id, name='Home 2', is_active=True)
        conflict_away = Team(id=uuid.uuid4(), organization_id=self.away_org.id, division_id=self.division.id, name='Away 3', is_active=True)
        conflict_game = Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            home_team_id=conflict_home.id,
            away_team_id=conflict_away.id,
            host_location_id=self.host.id,
            field_instance_id=large_field_1.id,
            game_status_id=self.status.id,
            game_date=date(2026, 8, 9),
            kickoff_time=time(9, 0),
        )
        self.db.add_all([large_field_1, large_field_2, conflict_home, conflict_away, conflict_game])
        self.db.commit()

        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.league_user.id),
            json=self._payload(field_instance_id=str(large_field_2.id), override_warnings=True),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['detail']['error'], 'INVALID_TURF_FIELD_SLOT_COMBINATION')
        self.assertIn('TWO_LARGE_FIELDS_NOT_ALLOWED_ON_ONE_TURF_SURFACE', response.json()['detail']['failure_reasons'])

    def test_turf_manual_edit_blocks_small_field_1_with_unsupported_medium_field_2_same_time(self):
        self.host.surface_type = 'TURF_STADIUM'
        medium_field_2 = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=date(2026, 8, 9), field_name='Medium Field 2', field_type='MEDIUM', is_active=True)
        conflict_home = Team(id=uuid.uuid4(), organization_id=self.home_org.id, division_id=self.division.id, name='Home 2', is_active=True)
        conflict_away = Team(id=uuid.uuid4(), organization_id=self.away_org.id, division_id=self.division.id, name='Away 3', is_active=True)
        conflict_game = Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            home_team_id=conflict_home.id,
            away_team_id=conflict_away.id,
            host_location_id=self.host.id,
            field_instance_id=medium_field_2.id,
            game_status_id=self.status.id,
            game_date=date(2026, 8, 9),
            kickoff_time=time(9, 0),
        )
        conflict_slot = GameSlot(
            id=uuid.uuid4(),
            field_instance_id=medium_field_2.id,
            host_location_id=self.host.id,
            season_id=self.season.id,
            week_id=self.week.id,
            slot_date=date(2026, 8, 9),
            start_time=time(9, 0),
            end_time=time(10, 0),
            field_type='MEDIUM',
            status='BOOKED',
            assigned_game_id=conflict_game.id,
        )
        self.db.add_all([medium_field_2, conflict_home, conflict_away, conflict_game, conflict_slot])
        self.db.commit()

        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.league_user.id),
            json=self._payload(field_instance_id=str(self.field.id), override_warnings=True),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['detail']['error'], 'INVALID_TURF_FIELD_SLOT_COMBINATION')
        self.assertIn('TURF_FIELD_SLOT_COMBINATION_NOT_APPROVED', response.json()['detail']['failure_reasons'])

    def test_same_explicit_field_slot_is_hard_blocked(self):
        conflict_home = Team(id=uuid.uuid4(), organization_id=self.home_org.id, division_id=self.division.id, name='Home 2', is_active=True)
        conflict_away = Team(id=uuid.uuid4(), organization_id=self.away_org.id, division_id=self.division.id, name='Away 3', is_active=True)
        conflict_game = Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            home_team_id=conflict_home.id,
            away_team_id=conflict_away.id,
            host_location_id=self.host.id,
            field_instance_id=self.field.id,
            game_status_id=self.status.id,
            game_date=date(2026, 8, 9),
            kickoff_time=time(9, 0),
        )
        self.db.add_all([conflict_home, conflict_away, conflict_game])
        self.db.commit()

        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.league_user.id),
            json=self._payload(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['detail']['error'], 'FIELD_TIME_CONFLICT')

    def test_same_team_is_hard_blocked_for_league_admin(self):
        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.league_user.id),
            json=self._payload(away_team_id=str(self.home_team.id)),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['detail']['error'], 'SAME_TEAM_NOT_ALLOWED')

    def test_scored_game_change_requires_confirmation(self):
        self.db.add(GameScore(game_id=self.game.id, home_score=12, away_score=6, score_status='APPROVED'))
        self.db.commit()
        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.league_user.id),
            json=self._payload(score_change_confirmed=False, override_warnings=True),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail']['error'], 'SCORED_GAME_CHANGE_REQUIRES_CONFIRMATION')


if __name__ == '__main__':
    unittest.main()
