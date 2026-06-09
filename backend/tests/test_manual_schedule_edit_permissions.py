import os
import unittest
import uuid
from datetime import date, time
from unittest.mock import patch

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
        self.dev_admin_user = User(id=uuid.uuid4(), email='admin@example.com', full_name='Dev Scheduling Admin', password_hash=hash_password('Password123!'), role_id=self.league_role.id, is_active=True)
        self.scheduling_user = User(id=uuid.uuid4(), email='scheduler@example.com', full_name='Scheduling Admin', password_hash=hash_password('Password123!'), role_id=self.scheduling_role.id, is_active=True)
        self.community_user = User(id=uuid.uuid4(), email='community@example.com', full_name='Community Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.home_org.id, is_active=True)
        self.db.add_all([
            self.league_role, self.community_role, self.scheduling_role, self.home_org, self.away_org, self.host, self.division,
            self.season, self.week, self.status, self.cancelled, self.home_team, self.away_team, self.other_team,
            self.field, self.game, self.slot, self.league_user, self.dev_admin_user, self.scheduling_user, self.community_user,
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


    def _open_slot(self, start=time(10, 0), end=time(11, 0)):
        slot = GameSlot(
            id=uuid.uuid4(),
            field_instance_id=self.field.id,
            host_location_id=self.host.id,
            season_id=self.season.id,
            week_id=self.week.id,
            slot_date=date(2026, 8, 9),
            start_time=start,
            end_time=end,
            field_type='SMALL',
            status='OPEN',
        )
        self.db.add(slot)
        self.db.commit()
        return slot

    def test_scheduling_admin_can_load_manual_builder_and_view_all_scheduled_games(self):
        options = self.client.get('/api/manual-schedule-builder/options', headers=self._token(self.scheduling_user.id))
        self.assertEqual(options.status_code, 200, options.text)

        response = self.client.get('/api/schedule-management/games', headers=self._token(self.scheduling_user.id))
        self.assertEqual(response.status_code, 200, response.text)
        item_ids = {item['id'] for item in response.json()['items']}
        self.assertIn(str(self.game.id), item_ids)

    def test_scheduling_admin_can_save_assignment_move_unschedule_and_export(self):
        assignment_slot = self._open_slot(time(10, 0), time(11, 0))
        assignment = self.client.post(
            '/api/manual-schedule-builder/assign',
            headers=self._token(self.scheduling_user.id),
            json={
                'season_id': str(self.season.id),
                'week_id': str(self.week.id),
                'division_id': str(self.division.id),
                'home_team_id': str(self.home_team.id),
                'away_team_id': str(self.other_team.id),
                'generated_slot_id': str(assignment_slot.id),
            },
        )
        self.assertEqual(assignment.status_code, 200, assignment.text)
        created_game_id = assignment.json()['game']['id']

        move_slot = self._open_slot(time(11, 0), time(12, 0))
        move = self.client.patch(
            f'/api/schedule-management/games/{created_game_id}/move',
            headers=self._token(self.scheduling_user.id),
            json={'generated_slot_id': str(move_slot.id)},
        )
        self.assertEqual(move.status_code, 200, move.text)

        export = self.client.get('/api/schedule-management/export.csv', headers=self._token(self.scheduling_user.id))
        self.assertEqual(export.status_code, 200, export.text)
        self.assertIn('Admin Notes', export.text)

        unschedule = self.client.patch(f'/api/schedule-management/games/{created_game_id}/unschedule', headers=self._token(self.scheduling_user.id))
        self.assertEqual(unschedule.status_code, 200, unschedule.text)

    def test_scheduling_admin_can_clear_all_scheduled_games_and_community_admin_cannot(self):
        community_clear = self.client.delete(f'/api/manual-schedule-builder/scheduled-games?season_id={self.season.id}', headers=self._token(self.community_user.id))
        self.assertEqual(community_clear.status_code, 403)

        clear = self.client.delete(f'/api/manual-schedule-builder/scheduled-games?season_id={self.season.id}', headers=self._token(self.scheduling_user.id))
        self.assertEqual(clear.status_code, 200, clear.text)
        self.assertGreaterEqual(clear.json()['deleted_count'], 1)

    def test_community_and_public_users_cannot_access_schedule_admin_routes(self):
        protected_requests = [
            lambda headers: self.client.get('/api/schedule-management/games', headers=headers),
            lambda headers: self.client.post('/api/manual-schedule-builder/auto-fill-preview', headers=headers, json={'season_id': str(self.season.id), 'week_id': str(self.week.id), 'division_id': str(self.division.id)}),
            lambda headers: self.client.get('/api/schedule-management/export.csv', headers=headers),
        ]
        for request in protected_requests:
            community_response = request(self._token(self.community_user.id))
            self.assertEqual(community_response.status_code, 403, community_response.text)
            public_response = request({})
            self.assertEqual(public_response.status_code, 403, public_response.text)

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


    def test_league_admin_direct_edit_api_is_allowed_as_scheduling_admin_mapping(self):
        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.league_user.id),
            json=self._payload(),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        self.assertEqual(self.db.get(Game, self.game.id).away_team_id, self.other_team.id)

    def test_community_admin_direct_bulk_edit_api_is_forbidden(self):
        response = self.client.patch(
            '/api/schedule-management/games/manual-edit/bulk',
            headers=self._token(self.community_user.id),
            json={'overrideWarnings': True, 'changes': [dict(self._payload(), game_id=str(self.game.id))]},
        )
        self.assertEqual(response.status_code, 403)

    def test_public_user_cannot_access_bulk_edit_endpoint(self):
        response = self.client.patch(
            '/api/schedule-management/games/manual-edit/bulk',
            json={'overrideWarnings': True, 'changes': [dict(self._payload(), game_id=str(self.game.id))]},
        )
        self.assertEqual(response.status_code, 403)

    def test_scheduling_admin_can_save_manual_edit_and_audit_log(self):
        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.scheduling_user.id),
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

    def test_league_admin_can_bulk_edit_as_dev_top_level_admin(self):
        response = self.client.patch(
            '/api/schedule-management/games/manual-edit/bulk',
            headers=self._token(self.league_user.id),
            json={
                'overrideWarnings': True,
                'changes': [dict(self._payload(internal_admin_notes='League admin bulk edit'), game_id=str(self.game.id))],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()['games']), 1)
        self.db.expire_all()
        self.assertEqual(self.db.get(Game, self.game.id).away_team_id, self.other_team.id)

    def test_scheduling_admin_can_bulk_edit_multiple_games_and_save_once(self):
        second_game = Game(id=uuid.uuid4(), season_id=self.season.id, week_id=self.week.id, home_team_id=self.away_team.id, away_team_id=self.other_team.id, host_location_id=self.host.id, field_instance_id=self.field.id, game_status_id=self.status.id, game_date=date(2026, 8, 9), kickoff_time=time(9, 0))
        self.db.add(second_game)
        self.db.commit()
        response = self.client.patch(
            '/api/schedule-management/games/manual-edit/bulk',
            headers=self._token(self.scheduling_user.id),
            json={
                'overrideWarnings': True,
                'changes': [
                    dict(self._payload(away_team_id=str(self.other_team.id), internal_admin_notes='Bulk 1'), game_id=str(self.game.id)),
                    dict(self._payload(home_team_id=str(self.home_team.id), away_team_id=str(self.away_team.id), internal_admin_notes='Bulk 2'), game_id=str(second_game.id)),
                ],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()['games']), 2)
        self.db.expire_all()
        self.assertEqual(self.db.get(Game, self.game.id).away_team_id, self.other_team.id)
        self.assertEqual(self.db.get(Game, second_game.id).away_team_id, self.away_team.id)


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


    def test_manual_edit_preserves_existing_score_records(self):
        score_id = uuid.uuid4()
        self.db.add(GameScore(id=score_id, game_id=self.game.id, home_score=12, away_score=6, score_status='APPROVED'))
        self.db.commit()

        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.scheduling_user.id),
            json=self._payload(away_team_id=str(self.other_team.id), score_change_confirmed=True, override_warnings=True),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        game = self.db.get(Game, self.game.id)
        score = self.db.get(GameScore, score_id)
        self.assertIsNotNone(score)
        self.assertEqual(score.game_id, game.id)
        self.assertEqual(game.away_team_id, self.other_team.id)


    def test_field_size_mismatch_is_warning_override_not_hard_block(self):
        large_field = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=date(2026, 8, 9), field_name='Large Field 1', field_type='LARGE', is_active=True)
        self.db.add(large_field)
        self.db.commit()

        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.scheduling_user.id),
            json=self._payload(field_instance_id=str(large_field.id), override_warnings=False),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail']['error'], 'SCHEDULE_WARNINGS_REQUIRE_OVERRIDE')
        warning_codes = {warning['code'] for warning in response.json()['detail']['warnings']}
        self.assertIn('FIELD_SIZE_MISMATCH', warning_codes)

        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.scheduling_user.id),
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
            headers=self._token(self.scheduling_user.id),
            json=self._payload(field_instance_id=str(large_field.id), override_warnings=True),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        game = self.db.get(Game, self.game.id)
        self.assertEqual(game.field_instance_id, large_field.id)

    def test_two_large_fields_on_one_turf_surface_are_overrideable_warnings(self):
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
            headers=self._token(self.scheduling_user.id),
            json=self._payload(field_instance_id=str(large_field_2.id), override_warnings=False),
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'SCHEDULE_WARNINGS_REQUIRE_OVERRIDE')
        self.assertIn('TURF_FIELD_CONFIGURATION_EXCEEDS_NORMAL_CAPACITY', {warning['code'] for warning in response.json()['detail']['warnings']})

        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.scheduling_user.id),
            json=self._payload(field_instance_id=str(large_field_2.id), override_warnings=True),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('TURF_FIELD_CONFIGURATION_EXCEEDS_NORMAL_CAPACITY', {warning['code'] for warning in response.json()['warnings']})


    def test_large_field_2_on_single_turf_surface_remains_hard_blocked(self):
        self.host.surface_type = 'TURF_STADIUM'
        large_field_2 = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=date(2026, 8, 9), field_name='Large Field 2', field_type='LARGE', is_active=True)
        self.db.add(large_field_2)
        self.db.commit()

        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.scheduling_user.id),
            json=self._payload(field_instance_id=str(large_field_2.id), override_warnings=True),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['detail']['error'], 'INVALID_TURF_FIELD_SLOT')
        self.assertIn('LARGE_FIELD_2_NOT_ALLOWED_ON_ONE_TURF_SURFACE', response.json()['detail']['failure_reasons'])

    def test_turf_manual_edit_warns_for_unoptimized_but_physically_possible_layout(self):
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
            headers=self._token(self.scheduling_user.id),
            json=self._payload(field_instance_id=str(self.field.id), override_warnings=False),
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'SCHEDULE_WARNINGS_REQUIRE_OVERRIDE')
        self.assertIn('TURF_LAYOUT_MANUAL_REBALANCE', {warning['code'] for warning in response.json()['detail']['warnings']})

        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.scheduling_user.id),
            json=self._payload(field_instance_id=str(self.field.id), override_warnings=True),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('TURF_LAYOUT_MANUAL_REBALANCE', {warning['code'] for warning in response.json()['warnings']})

    def test_same_explicit_field_slot_is_warning_override_not_hard_block(self):
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
            headers=self._token(self.scheduling_user.id),
            json=self._payload(override_warnings=False),
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'SCHEDULE_WARNINGS_REQUIRE_OVERRIDE')
        self.assertIn('FIELD_TIME_CONFLICT', {warning['code'] for warning in response.json()['detail']['warnings']})

        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.scheduling_user.id),
            json=self._payload(override_warnings=True),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('FIELD_TIME_CONFLICT', {warning['code'] for warning in response.json()['warnings']})
        self.db.expire_all()
        game = self.db.get(Game, self.game.id)
        self.assertEqual(game.field_instance_id, self.field.id)

    def test_same_team_is_hard_blocked_for_scheduling_admin(self):
        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.scheduling_user.id),
            json=self._payload(away_team_id=str(self.home_team.id)),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['detail']['error'], 'SAME_TEAM_NOT_ALLOWED')

    def test_scored_game_change_requires_confirmation(self):
        self.db.add(GameScore(game_id=self.game.id, home_score=12, away_score=6, score_status='APPROVED'))
        self.db.commit()
        response = self.client.patch(
            f'/api/schedule-management/games/{self.game.id}/manual-edit',
            headers=self._token(self.scheduling_user.id),
            json=self._payload(score_change_confirmed=False, override_warnings=True),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail']['error'], 'SCORED_GAME_CHANGE_REQUIRES_CONFIRMATION')


class ManualOptimizationWorkflowPermissionsTest(ManualScheduleEditPermissionsTest):
    def setUp(self):
        super().setUp()
        self._turf_optimization_flag = patch('app.routes.api.ENABLE_TURF_OPTIMIZATION', True)
        self._turf_optimization_flag.start()

    def tearDown(self):
        self._turf_optimization_flag.stop()
        super().tearDown()

    def _optimization_payload(self, **overrides):
        payload = {
            'season_id': str(self.season.id),
            'optimize_same_community_home': True,
            'repair_double_headers': True,
            'reduce_repeat_matchups': False,
            'preserve_two_location_limit': True,
            'include_manual_edits': False,
        }
        payload.update(overrides)
        return payload


    def test_optimize_schedule_options_preflight_allows_post(self):
        response = self.client.options(
            '/api/manual-schedule-builder/optimize-schedule',
            headers={
                'Origin': 'http://localhost:3000',
                'Access-Control-Request-Method': 'POST',
                'Access-Control-Request-Headers': 'authorization,content-type',
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('POST', response.headers.get('access-control-allow-methods', ''))

    def test_optimization_endpoints_return_disabled_when_feature_flag_is_off(self):
        self._turf_optimization_flag.stop()
        endpoints = [
            '/api/manual-schedule-builder/optimize-schedule',
            '/api/manual-schedule-builder/optimize-schedule/apply',
            '/api/manual-schedule-builder/optimize-schedule/keep-first-pass',
        ]
        try:
            for endpoint in endpoints:
                with self.subTest(endpoint=endpoint):
                    response = self.client.post(endpoint, headers=self._token(self.scheduling_user.id), json=self._optimization_payload())
                    self.assertEqual(response.status_code, 410, response.text)
                    self.assertEqual(response.json()['detail'], 'Turf optimization is currently disabled.')
        finally:
            self._turf_optimization_flag.start()

    def test_optimize_endpoint_responds_within_configured_time_limit(self):
        self.host.surface_type = 'TURF_STADIUM'
        self._add_optimizer_slot(time(8, 0))
        self.db.commit()
        with patch.dict(os.environ, {'SCHEDULE_OPTIMIZATION_MAX_RUNTIME_SECONDS': '1', 'SCHEDULE_OPTIMIZATION_MAX_CANDIDATES_EVALUATED': '10'}):
            response = self.client.post(
                '/api/manual-schedule-builder/optimize-schedule',
                headers=self._token(self.scheduling_user.id),
                json=self._optimization_payload(),
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('summary', response.json())

    def test_optimizer_candidate_cap_returns_partial_diagnostics(self):
        self.host.surface_type = 'TURF_STADIUM'
        for hour in range(8, 14):
            self._add_optimizer_slot(time(hour, 0))
        self.db.commit()
        with patch.dict(os.environ, {'SCHEDULE_OPTIMIZATION_MAX_CANDIDATES_GENERATED': '2', 'SCHEDULE_OPTIMIZATION_MAX_CANDIDATES_EVALUATED': '1'}):
            response = self.client.post(
                '/api/manual-schedule-builder/optimize-schedule',
                headers=self._token(self.scheduling_user.id),
                json=self._optimization_payload(),
            )
        self.assertEqual(response.status_code, 200, response.text)
        summary = response.json()['summary']
        self.assertLessEqual(summary['optimization_candidates_generated'], 2)
        self.assertEqual(summary['optimization_candidates_evaluated'], 1)
        self.assertTrue(summary['guard_limit_reached'])
        self.assertIn('Optimization stopped after reaching guard limit', summary['partial_diagnostics_message'])

    def test_optimizer_deduplicates_candidates_across_passes(self):
        self.host.surface_type = 'TURF_STADIUM'
        self._add_optimizer_slot(time(8, 0))
        self.db.commit()
        with patch.dict(os.environ, {'SCHEDULE_OPTIMIZATION_MAX_PASSES': '2'}):
            response = self.client.post(
                '/api/manual-schedule-builder/optimize-schedule',
                headers=self._token(self.scheduling_user.id),
                json=self._optimization_payload(),
            )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        identities = {
            (change.get('type'), change.get('game_id'), change.get('from_slot_id'), change.get('to_slot_id'))
            for change in data['proposed_changes'] + data['rejected_changes']
        }
        self.assertEqual(len(identities), len(data['proposed_changes'] + data['rejected_changes']))

    def test_scheduling_admin_can_run_manual_optimization_preview_with_metrics(self):
        response = self.client.post(
            '/api/manual-schedule-builder/optimize-schedule',
            headers=self._token(self.scheduling_user.id),
            json=self._optimization_payload(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('before_metrics', data)
        self.assertIn('after_metrics', data)
        self.assertIn('metric_comparison', data)
        self.assertEqual(data['schedule_state'], 'Optimization Preview')
        self.assertTrue(data['preview'])

    def test_scheduling_admin_can_apply_manual_optimization(self):
        response = self.client.post(
            '/api/manual-schedule-builder/optimize-schedule/apply',
            headers=self._token(self.scheduling_user.id),
            json=self._optimization_payload(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['schedule_state'], 'Optimized Schedule Applied')
        self.assertTrue(data['applied'])

    def test_community_admin_cannot_run_manual_optimization_api(self):
        preview = self.client.post(
            '/api/manual-schedule-builder/optimize-schedule',
            headers=self._token(self.community_user.id),
            json=self._optimization_payload(),
        )
        apply = self.client.post(
            '/api/manual-schedule-builder/optimize-schedule/apply',
            headers=self._token(self.community_user.id),
            json=self._optimization_payload(),
        )
        self.assertEqual(preview.status_code, 403)
        self.assertEqual(apply.status_code, 403)

    def test_league_admin_cannot_run_scheduling_admin_only_optimization_api(self):
        response = self.client.post(
            '/api/manual-schedule-builder/optimize-schedule',
            headers=self._token(self.league_user.id),
            json=self._optimization_payload(),
        )
        self.assertEqual(response.status_code, 403)


    def _optimizer_mutates_game_time(self, db, season_id, **_kwargs):
        game = db.get(Game, self.game.id)
        game.kickoff_time = time(10, 0)
        db.flush()
        return {
            'summary': {'same_community_repairs_committed': 1, 'double_header_repairs_committed': 0, 'repairs_rejected': 0},
            'proposed_changes': [{'game_id': str(self.game.id), 'new_time': '10:00:00'}],
            'rejected_changes': [],
            'rejected_moves_by_reason': {},
            'warnings': [],
        }

    def test_schedule_optimization_preview_does_not_overwrite_saved_schedule(self):
        with patch('app.routes.api.run_post_schedule_repair_pass', side_effect=self._optimizer_mutates_game_time):
            response = self.client.post(
                '/api/manual-schedule-builder/optimize-schedule',
                headers=self._token(self.scheduling_user.id),
                json=self._optimization_payload(),
            )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data['preview'])
        self.assertFalse(data['applied'])
        self.assertEqual(data['schedule_state'], 'Optimization Preview')
        self.assertEqual(data['summary']['accepted_optimization_moves'], 1)
        self.assertEqual(data['optimized_preview_games'][0]['time'], '10:00:00')
        self.db.expire_all()
        self.assertEqual(self.db.get(Game, self.game.id).kickoff_time, time(9, 0))

    def test_dev_admin_example_can_run_schedule_optimization_as_local_scheduling_admin(self):
        with patch('app.routes.api.run_post_schedule_repair_pass', side_effect=self._optimizer_mutates_game_time):
            response = self.client.post(
                '/api/manual-schedule-builder/optimize-schedule',
                headers=self._token(self.dev_admin_user.id),
                json=self._optimization_payload(),
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['preview'])

    def test_public_cannot_call_schedule_optimization_actions(self):
        endpoints = [
            '/api/manual-schedule-builder/optimize-schedule',
            '/api/manual-schedule-builder/optimize-schedule/apply',
            '/api/manual-schedule-builder/optimize-schedule/keep-first-pass',
        ]
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                response = self.client.post(endpoint, json=self._optimization_payload())
                self.assertEqual(response.status_code, 403)

    def test_apply_optimized_schedule_saves_authoritative_schedule(self):
        with patch('app.routes.api.run_post_schedule_repair_pass', side_effect=self._optimizer_mutates_game_time):
            response = self.client.post(
                '/api/manual-schedule-builder/optimize-schedule/apply',
                headers=self._token(self.scheduling_user.id),
                json=self._optimization_payload(),
            )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertFalse(data['preview'])
        self.assertTrue(data['applied'])
        self.db.expire_all()
        self.assertEqual(self.db.get(Game, self.game.id).kickoff_time, time(10, 0))


    def _add_optimizer_slot(self, start, *, assigned_game=None, host=None, field=None, status='OPEN'):
        host = host or self.host
        field = field or self.field
        slot = GameSlot(
            id=uuid.uuid4(),
            field_instance_id=field.id,
            host_location_id=host.id,
            season_id=self.season.id,
            week_id=self.week.id,
            slot_date=date(2026, 8, 9),
            start_time=start,
            end_time=time(start.hour + 1, start.minute),
            field_type='SMALL',
            status=status,
            assigned_game_id=assigned_game.id if assigned_game else None,
        )
        self.db.add(slot)
        return slot

    def _add_optimizer_game(self, kickoff, home=None, away=None, *, host=None, field=None, manual=False):
        host = host or self.host
        field = field or self.field
        game = Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            home_team_id=(home or self.away_team).id,
            away_team_id=(away or self.other_team).id,
            host_location_id=host.id,
            field_instance_id=field.id,
            game_status_id=self.status.id,
            game_date=date(2026, 8, 9),
            kickoff_time=kickoff,
            is_manual_edit=manual,
        )
        self.db.add(game)
        self.db.flush()
        slot = self._add_optimizer_slot(kickoff, assigned_game=game, host=host, field=field, status='ASSIGNED')
        self.db.flush()
        return game, slot

    def test_optimizer_reports_zero_candidates_only_with_reason(self):
        response = self.client.post(
            '/api/manual-schedule-builder/optimize-schedule',
            headers=self._token(self.scheduling_user.id),
            json=self._optimization_payload(),
        )
        self.assertEqual(response.status_code, 200, response.text)
        summary = response.json()['summary']
        self.assertEqual(summary['optimization_candidates_generated'], 0)
        self.assertEqual(summary['accepted_optimization_moves'], 0)
        self.assertEqual(summary['rejected_optimization_moves'], 0)
        self.assertEqual(summary['no_candidates_message'], 'No turf optimization candidates were generated.')
        self.assertTrue(summary['no_candidate_reasons'])

    def test_optimizer_logs_rejected_locked_manual_moves(self):
        self.host.surface_type = 'TURF_STADIUM'
        self.game.is_manual_edit = True
        self._add_optimizer_slot(time(8, 0))
        self.db.commit()
        response = self.client.post(
            '/api/manual-schedule-builder/optimize-schedule',
            headers=self._token(self.scheduling_user.id),
            json=self._optimization_payload(include_manual_edits=False),
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertGreaterEqual(data['summary']['optimization_candidates_generated'], 1)
        self.assertGreaterEqual(data['summary']['rejected_optimization_moves'], 1)
        self.assertIn('manually edited game is locked', data['rejected_move_reasons'])
        self.db.expire_all()
        self.assertEqual(self.db.get(Game, self.game.id).kickoff_time, time(9, 0))

    def test_optimizer_accepts_safe_earlier_turf_move_and_preview_only(self):
        self.host.surface_type = 'TURF_STADIUM'
        late_game, _late_slot = self._add_optimizer_game(time(16, 0))
        self._add_optimizer_slot(time(10, 0))
        self.db.commit()
        response = self.client.post(
            '/api/manual-schedule-builder/optimize-schedule',
            headers=self._token(self.scheduling_user.id),
            json=self._optimization_payload(),
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertGreater(data['summary']['optimization_candidates_generated'], 0)
        self.assertGreater(data['summary']['accepted_optimization_moves'], 0)
        preview = {row['id']: row for row in data['optimized_preview_games']}
        self.assertEqual(preview[str(late_game.id)]['time'], '10:00:00')
        self.assertLessEqual(str(data['after_metrics']['latest_turf_start_time']), str(data['before_metrics']['latest_turf_start_time']))
        self.db.expire_all()
        self.assertEqual(self.db.get(Game, late_game.id).kickoff_time, time(16, 0))

    def test_optimizer_does_not_generate_broad_host_home_repair_candidates(self):
        away_host = HostLocation(id=uuid.uuid4(), organization_id=self.away_org.id, name='Away Park', is_active=True)
        away_field = FieldInstance(id=uuid.uuid4(), host_location_id=away_host.id, hosting_availability_id=uuid.uuid4(), instance_date=date(2026, 8, 9), field_name='Away Small 1', field_type='SMALL', is_active=True)
        self.db.add_all([away_host, away_field])
        self.game.host_location_id = away_host.id
        self.game.field_instance_id = away_field.id
        self.slot.assigned_game_id = None
        self._add_optimizer_slot(time(9, 0), assigned_game=self.game, host=away_host, field=away_field, status='ASSIGNED')
        self._add_optimizer_slot(time(10, 0), host=self.host, field=self.field)
        self.db.commit()
        response = self.client.post(
            '/api/manual-schedule-builder/optimize-schedule',
            headers=self._token(self.scheduling_user.id),
            json=self._optimization_payload(),
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertFalse(any(change.get('opportunity') == 'host-home repair' for change in data['proposed_changes'] + data['rejected_changes']))
        self.assertEqual(data['summary']['same_community_repairs_proposed'], 0)


    def _add_optimizer_team(self, name, org=None):
        team = Team(id=uuid.uuid4(), organization_id=(org or self.away_org).id, division_id=self.division.id, name=name, is_active=True)
        self.db.add(team)
        self.db.flush()
        return team

    def _add_turf_field(self, label='Small Field 2', host=None):
        host = host or self.host
        field = FieldInstance(id=uuid.uuid4(), host_location_id=host.id, hosting_availability_id=uuid.uuid4(), instance_date=date(2026, 8, 9), field_name=label, field_type='SMALL', is_active=True)
        self.db.add(field)
        self.db.flush()
        return field

    def test_turf_optimizer_pairs_single_game_blocks_across_all_turf_stadiums(self):
        self.host.surface_type = 'TURF_STADIUM'
        field2 = self._add_turf_field('Small Field 2')
        third = self._add_optimizer_team('Away 3')
        fourth = self._add_optimizer_team('Away 4')
        late_game, _late_slot = self._add_optimizer_game(time(11, 0), home=third, away=fourth)
        self._add_optimizer_slot(time(9, 0), field=field2)
        second_host = HostLocation(id=uuid.uuid4(), organization_id=self.away_org.id, name='Second Turf Stadium', surface_type='TURF_STADIUM', is_active=True)
        second_field = FieldInstance(id=uuid.uuid4(), host_location_id=second_host.id, hosting_availability_id=uuid.uuid4(), instance_date=date(2026, 8, 9), field_name='Small Field 1', field_type='SMALL', is_active=True)
        self.db.add_all([second_host, second_field])
        self._add_optimizer_game(time(14, 0), home=self._add_optimizer_team('Away 5'), away=self._add_optimizer_team('Away 6'), host=second_host, field=second_field)
        self._add_optimizer_slot(time(12, 0), host=second_host, field=second_field)
        self.db.commit()

        response = self.client.post('/api/manual-schedule-builder/optimize-schedule', headers=self._token(self.scheduling_user.id), json=self._optimization_payload())
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertGreater(data['summary']['optimization_candidates_generated'], 0)
        self.assertGreater(data['summary']['accepted_optimization_moves'], 0)
        self.assertGreaterEqual(len(data['summary']['per_stadium_turf_metrics']), 2)
        self.assertLess(data['summary']['total_turf_single_game_blocks_after'], data['summary']['total_turf_single_game_blocks_before'])
        self.assertGreater(data['summary']['total_turf_two_game_blocks_after'], data['summary']['total_turf_two_game_blocks_before'])
        preview = {row['id']: row for row in data['optimized_preview_games']}
        self.assertEqual(preview[str(late_game.id)]['time'], '09:00:00')

    def test_turf_optimizer_rejects_team_time_conflicts(self):
        self.host.surface_type = 'TURF_STADIUM'
        field2 = self._add_turf_field('Small Field 2')
        # This game shares Away 1 with the existing 9:00 game, so the open 9:00 turf slot is unsafe.
        self._add_optimizer_game(time(11, 0), home=self.away_team, away=self.other_team)
        self._add_optimizer_slot(time(9, 0), field=field2)
        self.db.commit()

        response = self.client.post('/api/manual-schedule-builder/optimize-schedule', headers=self._token(self.scheduling_user.id), json=self._optimization_payload())
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertIn('team-time conflict', data['rejected_move_reasons'])
        self.assertEqual(data['summary']['accepted_optimization_moves'], 0)

    def test_turf_optimizer_rejects_duplicate_exact_field_slot_conflicts(self):
        self.host.surface_type = 'TURF_STADIUM'
        third = self._add_optimizer_team('Away 3')
        fourth = self._add_optimizer_team('Away 4')
        self._add_optimizer_game(time(11, 0), home=third, away=fourth)
        # Deliberately stale/duplicate open slot: same exact field/date/time as an occupied game.
        self._add_optimizer_slot(time(9, 0), field=self.field)
        self.db.commit()

        response = self.client.post('/api/manual-schedule-builder/optimize-schedule', headers=self._token(self.scheduling_user.id), json=self._optimization_payload())
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertIn('duplicate field-slot conflict', data['rejected_move_reasons'])
        self.assertEqual(data['summary']['accepted_optimization_moves'], 0)

    def test_turf_optimizer_preserves_grass_field_labels_and_avoids_wave_output(self):
        self.host.surface_type = 'TURF_STADIUM'
        field2 = self._add_turf_field('Wave 1 THREE_SMALL Small Field 2')
        grass_host = HostLocation(id=uuid.uuid4(), organization_id=self.away_org.id, name='Grass Park', surface_type='GRASS_FIELD', is_active=True)
        grass_field = FieldInstance(id=uuid.uuid4(), host_location_id=grass_host.id, hosting_availability_id=uuid.uuid4(), instance_date=date(2026, 8, 9), field_name='Community Grass Meadow', field_type='SMALL', is_active=True)
        self.db.add_all([grass_host, grass_field])
        grass_game, _ = self._add_optimizer_game(time(10, 0), home=self._add_optimizer_team('Away 7'), away=self._add_optimizer_team('Away 8'), host=grass_host, field=grass_field)
        turf_game, _ = self._add_optimizer_game(time(11, 0), home=self._add_optimizer_team('Away 9'), away=self._add_optimizer_team('Away 10'))
        self._add_optimizer_slot(time(9, 0), field=field2)
        self.db.commit()

        response = self.client.post('/api/manual-schedule-builder/optimize-schedule', headers=self._token(self.scheduling_user.id), json=self._optimization_payload())
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        preview = {row['id']: row for row in data['optimized_preview_games']}
        self.assertEqual(preview[str(grass_game.id)]['field'], 'Community Grass Meadow')
        self.assertNotIn('Wave', str(data))
        self.assertIn(preview[str(turf_game.id)]['field'], {'Small Field 1', 'Small Field 2', 'Small Field 3', 'Medium Field 1', 'Medium Field 2', 'Large Field 1'})

    def test_community_admin_cannot_call_schedule_optimization(self):
        response = self.client.post('/api/manual-schedule-builder/optimize-schedule', headers=self._token(self.community_user.id), json=self._optimization_payload())
        self.assertEqual(response.status_code, 403)

    def test_keep_first_pass_discards_optimization_preview(self):
        response = self.client.post(
            '/api/manual-schedule-builder/optimize-schedule/keep-first-pass',
            headers=self._token(self.scheduling_user.id),
            json=self._optimization_payload(),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['discarded'])
        self.db.expire_all()
        self.assertEqual(self.db.get(Game, self.game.id).kickoff_time, time(9, 0))

if __name__ == '__main__':
    unittest.main()
