import unittest
from unittest.mock import patch
import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import ROLE_COMMUNITY_ADMIN, ROLE_LEAGUE_ADMIN, ROLE_SCHEDULING_ADMIN
from app.database import Base, get_db
from app.main import app
from app.models import Division, FieldInstance, Game, GameScore, GameSlot, GameStatus, HostLocation, Organization, Role, ScoreHistory, ScoreSubmission, Season, Team, User, Week
from app.security import create_access_token, hash_password


class ScoreTrackingTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool, future=True)
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.db = self.SessionLocal()

        self.league_role = Role(id=uuid.uuid4(), name=ROLE_LEAGUE_ADMIN, is_active=True)
        self.scheduling_role = Role(id=uuid.uuid4(), name=ROLE_SCHEDULING_ADMIN, is_active=True)
        self.community_role = Role(id=uuid.uuid4(), name=ROLE_COMMUNITY_ADMIN, is_active=True)
        self.home_org = Organization(id=uuid.uuid4(), name='Westosha', is_active=True)
        self.away_org = Organization(id=uuid.uuid4(), name='Lake County', is_active=True)
        self.other_org = Organization(id=uuid.uuid4(), name='Other', is_active=True)
        self.division = Division(id=uuid.uuid4(), name='K-1', division_group='COED', sort_order=1, required_field_layout_type='SMALL', is_active=True)
        self.host = HostLocation(id=uuid.uuid4(), organization_id=self.home_org.id, name='Westosha Park', surface_type='GRASS_FIELD', is_active=True)
        self.season = Season(id=uuid.uuid4(), name='Fall 2026', start_date=date(2026, 8, 1), end_date=date(2026, 11, 1), is_active=True, schedule_status='published')
        self.week = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=1, label='Week 1', start_date=date(2026, 5, 1), end_date=date(2026, 5, 7), primary_game_date=date(2026, 5, 2), status='REGULAR_SEASON')
        self.status = GameStatus(id=uuid.uuid4(), code='published', label='Published', is_active=True)
        self.home_team = Team(id=uuid.uuid4(), organization_id=self.home_org.id, division_id=self.division.id, name='Westosha 1', is_active=True)
        self.away_team = Team(id=uuid.uuid4(), organization_id=self.away_org.id, division_id=self.division.id, name='Lake 1', is_active=True)
        self.field = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=date(2026, 5, 2), field_name='Small Field 1', field_type='SMALL', is_active=True)
        self.other_field = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=date(2026, 5, 2), field_name='Small Field 2', field_type='SMALL', is_active=True)
        self.other_team = Team(id=uuid.uuid4(), organization_id=self.other_org.id, division_id=self.division.id, name='Other 1', is_active=True)
        self.game = Game(id=uuid.uuid4(), season_id=self.season.id, week_id=self.week.id, home_team_id=self.home_team.id, away_team_id=self.away_team.id, host_location_id=self.host.id, field_instance_id=self.field.id, game_status_id=self.status.id, game_date=date(2026, 5, 2), kickoff_time=time(9, 0))
        self.other_game = Game(id=uuid.uuid4(), season_id=self.season.id, week_id=self.week.id, home_team_id=self.other_team.id, away_team_id=self.away_team.id, host_location_id=self.host.id, field_instance_id=self.other_field.id, game_status_id=self.status.id, game_date=date(2026, 5, 2), kickoff_time=time(10, 0))
        self.slot = GameSlot(id=uuid.uuid4(), field_instance_id=self.field.id, host_location_id=self.host.id, season_id=self.season.id, week_id=self.week.id, slot_date=date(2026, 5, 2), start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='ASSIGNED', assigned_game_id=self.game.id)
        self.other_slot = GameSlot(id=uuid.uuid4(), field_instance_id=self.other_field.id, host_location_id=self.host.id, season_id=self.season.id, week_id=self.week.id, slot_date=date(2026, 5, 2), start_time=time(10, 0), end_time=time(11, 0), field_type='SMALL', status='ASSIGNED', assigned_game_id=self.other_game.id)
        self.league_user = User(id=uuid.uuid4(), email='league@example.com', full_name='League Admin', password_hash=hash_password('Password123!'), role_id=self.league_role.id, organization_id=None, is_active=True)
        self.scheduling_user = User(id=uuid.uuid4(), email='scheduling@example.com', full_name='Scheduling Admin', password_hash=hash_password('Password123!'), role_id=self.scheduling_role.id, organization_id=None, is_active=True)
        self.home_user = User(id=uuid.uuid4(), email='home@example.com', full_name='Home Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.home_org.id, is_active=True)
        self.away_user = User(id=uuid.uuid4(), email='away@example.com', full_name='Away Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.away_org.id, is_active=True)
        self.other_user = User(id=uuid.uuid4(), email='other@example.com', full_name='Other Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.other_org.id, is_active=True)
        self.db.add_all([self.league_role, self.scheduling_role, self.community_role, self.home_org, self.away_org, self.other_org, self.division, self.host, self.season, self.week, self.status, self.home_team, self.away_team, self.field, self.other_field, self.other_team, self.game, self.other_game, self.slot, self.other_slot, self.league_user, self.scheduling_user, self.home_user, self.away_user, self.other_user])
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

    def _submit(self, user, game=None, home=20, away=12):
        return self.client.patch(f'/api/scores/{game or self.game.id}/submit', headers=self._token(user.id), json={'home_score': home, 'away_score': away})

    def test_missing_score_summary_scopes_to_community_and_clears_after_submit(self):
        home_summary = self.client.get('/api/scores/missing-summary', headers=self._token(self.home_user.id))
        self.assertEqual(home_summary.status_code, 200, home_summary.text)
        self.assertEqual(home_summary.json()['missing_count'], 1)
        self.assertEqual(home_summary.json()['link_target'], '/admin/score-entry')
        self.assertEqual(home_summary.json()['missing_games'][0]['game_id'], str(self.game.id))

        other_summary = self.client.get('/api/scores/missing-summary', headers=self._token(self.other_user.id))
        self.assertEqual(other_summary.status_code, 200, other_summary.text)
        self.assertEqual(other_summary.json()['missing_count'], 1)
        self.assertEqual(other_summary.json()['missing_games'][0]['game_id'], str(self.other_game.id))

        submit = self.client.patch(f'/api/scores/{self.game.id}/submit', headers=self._token(self.home_user.id), json={'home_score': '', 'away_score': '14'})
        self.assertEqual(submit.status_code, 200, submit.text)
        self.assertEqual(submit.json()['score']['home_score'], 0)
        self.assertEqual(submit.json()['score']['away_score'], 14)
        cleared = self.client.get('/api/scores/missing-summary', headers=self._token(self.home_user.id))
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertEqual(cleared.json()['missing_count'], 0)

    def test_blank_normalization_validation_and_forfeits(self):
        blank_away = self.client.patch(f'/api/scores/{self.game.id}/submit', headers=self._token(self.home_user.id), json={'home_score': '21', 'away_score': ''})
        self.assertEqual(blank_away.status_code, 200, blank_away.text)
        self.assertEqual(blank_away.json()['score']['away_score'], 0)

        for bad_home in ['-1', '1.5', 'W', '7F']:
            response = self.client.patch(f'/api/scores/{self.other_game.id}/submit', headers=self._token(self.away_user.id), json={'home_score': bad_home, 'away_score': '1'})
            self.assertEqual(response.status_code, 422, response.text)
            self.assertIn('Scores must be non-negative whole numbers, or F for a forfeiting team.', response.text)

        home_forfeit = self.client.patch(f'/api/scores/{self.other_game.id}/submit', headers=self._token(self.away_user.id), json={'home_score': 'f', 'away_score': ''})
        self.assertEqual(home_forfeit.status_code, 200, home_forfeit.text)
        self.assertEqual(home_forfeit.json()['score']['home_score'], 'F')
        self.assertEqual(home_forfeit.json()['score']['away_score'], 1)
        self.assertTrue(home_forfeit.json()['score']['home_forfeit'])
        submission = home_forfeit.json()['submission_id']
        self.assertTrue(submission)

        ff = self.client.patch(f'/api/scores/{self.game.id}/submit', headers=self._token(self.home_user.id), json={'home_score': 'F', 'away_score': 'F'})
        self.assertEqual(ff.status_code, 422, ff.text)

    def test_scheduling_admin_can_publish_forfeit_and_public_hides_until_published(self):
        edit = self.client.patch(f'/api/scores/{self.game.id}', headers=self._token(self.scheduling_user.id), json={'home_score': '', 'away_score': 'F'})
        self.assertEqual(edit.status_code, 200, edit.text)
        self.assertEqual(edit.json()['score']['home_score'], 1)
        self.assertEqual(edit.json()['score']['away_score'], 'F')
        approve = self.client.post(f'/api/scores/{self.game.id}/approve', headers=self._token(self.scheduling_user.id), json={})
        self.assertEqual(approve.status_code, 200, approve.text)
        hidden_public = self.client.get('/api/public/schedule?page_size=100')
        item = next(item for item in hidden_public.json()['items'] if item['id'] == str(self.game.id))
        self.assertIsNone(item['home_score'])

        publish = self.client.post(f'/api/scores/{self.game.id}/publish', headers=self._token(self.scheduling_user.id))
        self.assertEqual(publish.status_code, 200, publish.text)
        public = self.client.get('/api/public/schedule?page_size=100')
        item = next(item for item in public.json()['items'] if item['id'] == str(self.game.id))
        self.assertEqual(item['home_score'], 1)
        self.assertEqual(item['away_score'], 'F')
        self.assertEqual(item['public_score_status'], 'PUBLISHED')

    def test_community_admin_can_submit_when_home_or_away_but_not_unrelated(self):
        home_response = self._submit(self.home_user)
        self.assertEqual(home_response.status_code, 200, home_response.text)
        self.assertEqual(home_response.json()['score']['score_status'], 'SUBMITTED')
        self.assertEqual(home_response.json()['score']['submitted_by_community_id'], str(self.home_org.id))

        away_response = self._submit(self.away_user, self.other_game.id, home=7, away=19)
        self.assertEqual(away_response.status_code, 200, away_response.text)
        self.assertEqual(away_response.json()['score']['submitted_by_community_id'], str(self.away_org.id))

        unrelated = self._submit(self.other_user, self.game.id)
        self.assertEqual(unrelated.status_code, 403)
        self.db.expire_all()
        self.assertEqual(self.db.query(GameScore).filter(GameScore.game_id == self.game.id).count(), 1)

    def test_community_admin_cannot_administer_scores(self):
        self._submit(self.home_user)
        for path in ['approve', 'publish', 'unpublish', 'clear', 'resolve-conflict']:
            response = self.client.post(f'/api/scores/{self.game.id}/{path}', headers=self._token(self.home_user.id), json={'home_score': 1, 'away_score': 0})
            self.assertEqual(response.status_code, 403, f'{path}: {response.text}')


    def test_publish_unpublish_and_republish_schedule_hash_lifecycle(self):
        publish = self.client.post(f'/api/seasons/{self.season.id}/publish-schedule', headers=self._token(self.scheduling_user.id))
        self.assertEqual(publish.status_code, 200, publish.text)
        self.db.expire_all()
        season = self.db.query(Season).filter(Season.id == self.season.id).one()
        self.assertIsNotNone(season.last_published_schedule_hash)
        self.assertEqual(season.last_published_game_count, 2)
        first_hash = season.last_published_schedule_hash

        before_game_ids = {game.id for game in self.db.query(Game).filter(Game.season_id == self.season.id).all()}
        unpublish = self.client.post(f'/api/seasons/{self.season.id}/unpublish-schedule', headers=self._token(self.scheduling_user.id))
        self.assertEqual(unpublish.status_code, 200, unpublish.text)
        self.db.expire_all()
        season = self.db.query(Season).filter(Season.id == self.season.id).one()
        self.assertEqual(season.last_published_schedule_hash, first_hash)
        self.assertEqual({game.id for game in self.db.query(Game).filter(Game.season_id == self.season.id).all()}, before_game_ids)

        with patch('app.routes.api.build_publish_schedule_quality_report', side_effect=AssertionError('unchanged republish should not validate')):
            republish = self.client.post(f'/api/seasons/{self.season.id}/publish-schedule', headers=self._token(self.scheduling_user.id))
        self.assertEqual(republish.status_code, 200, republish.text)
        self.assertTrue(republish.json()['republish_without_validation'])
        self.assertEqual(republish.json()['message'], 'Schedule republished. No schedule changes were detected since it was last published.')

    def test_already_unpublished_without_hash_republishes_if_games_unchanged_since_unpublish(self):
        self.season.schedule_status = 'unpublished'
        self.season.last_published_schedule_hash = None
        self.season.last_published_game_count = None
        self.season.schedule_unpublished_at = datetime.now(timezone.utc) + timedelta(days=1)
        self.db.commit()

        with patch('app.routes.api.build_publish_schedule_quality_report', side_effect=AssertionError('fallback unchanged republish should not validate')):
            republish = self.client.post(f'/api/seasons/{self.season.id}/publish-schedule', headers=self._token(self.scheduling_user.id))
        self.assertEqual(republish.status_code, 200, republish.text)
        self.assertTrue(republish.json()['republish_without_validation'])
        self.assertEqual(republish.json()['message'], 'Schedule republished. No schedule changes were detected since it was unpublished. Future publish checks will use the stored schedule snapshot.')
        self.db.expire_all()
        season = self.db.query(Season).filter(Season.id == self.season.id).one()
        self.assertIsNotNone(season.last_published_schedule_hash)
        self.assertEqual(season.last_published_game_count, 2)

    def test_changed_republish_runs_validation_and_returns_summary(self):
        self.season.schedule_status = 'unpublished'
        self.season.last_published_schedule_hash = None
        self.season.schedule_unpublished_at = datetime.now(timezone.utc) - timedelta(days=1)
        self.db.commit()
        validation = {
            'final_validation_status': 'VALIDATION_FAILED',
            'hard_errors': [{
                'code': 'DOUBLEHEADER_NOT_BACK_TO_BACK',
                'count': 1,
                'details': [{
                    'failure_code': 'DOUBLEHEADER_NOT_BACK_TO_BACK',
                    'team_name': 'Westosha Girls 3-5 Maroon',
                    'game_date': '2026-08-23',
                    'kickoff_time': '09:00',
                    'host_location_name': 'Westosha Stadium',
                    'field_name': 'Turf A',
                }],
            }],
            'warnings': [],
            'overall_health': 'Blocked',
            'generated_slot_integrity_diagnostics': {},
        }
        with patch('app.routes.api.build_publish_schedule_quality_report', return_value=validation) as validator:
            republish = self.client.post(f'/api/seasons/{self.season.id}/publish-schedule', headers=self._token(self.scheduling_user.id))
        self.assertEqual(republish.status_code, 400, republish.text)
        validator.assert_called_once()
        detail = republish.json()['detail']
        self.assertEqual(detail['error'], 'publish_validation_failed')
        self.assertEqual(detail['message'], 'Schedule changed since last publication and failed validation. Fix blocking issues before publishing.')
        self.assertIn('validation_summary', detail)
        self.assertNotIn('hard_errors', detail)
        self.assertEqual(detail['validation_summary']['issues'][0]['issue_type'], 'DOUBLEHEADER_NOT_BACK_TO_BACK')

    def test_schedule_publication_permissions_and_score_preservation(self):
        publish_status = self.client.post(f'/api/seasons/{self.season.id}/publish-schedule', headers=self._token(self.scheduling_user.id))
        self.assertEqual(publish_status.status_code, 200, publish_status.text)
        self.assertTrue(publish_status.json()['schedule_published'])

        community_publish = self.client.post(f'/api/seasons/{self.season.id}/publish-schedule', headers=self._token(self.home_user.id))
        self.assertEqual(community_publish.status_code, 403, community_publish.text)

        self._submit(self.home_user, home=24, away=18)
        approve_publish = self.client.post(f'/api/scores/{self.game.id}/approve-and-publish', headers=self._token(self.scheduling_user.id), json={})
        self.assertEqual(approve_publish.status_code, 200, approve_publish.text)

        before_score = self.db.query(GameScore).filter(GameScore.game_id == self.game.id).one()
        before_score_id = before_score.id
        before_game_id = before_score.game_id
        before_history_count = self.db.query(ScoreHistory).filter(ScoreHistory.game_id == self.game.id).count()
        before_game_count = self.db.query(Game).filter(Game.season_id == self.season.id).count()

        public_before = self.client.get('/api/public/schedule?page_size=100')
        self.assertEqual(public_before.status_code, 200, public_before.text)
        before_item = next(item for item in public_before.json()['items'] if item['id'] == str(self.game.id))
        self.assertEqual(before_item['home_score'], 24)
        self.assertEqual(before_item['away_score'], 18)

        unpublish = self.client.post(f'/api/seasons/{self.season.id}/unpublish-schedule', headers=self._token(self.scheduling_user.id))
        self.assertEqual(unpublish.status_code, 200, unpublish.text)
        self.assertFalse(unpublish.json()['schedule_published'])

        community_unpublish = self.client.post(f'/api/seasons/{self.season.id}/unpublish-schedule', headers=self._token(self.home_user.id))
        self.assertEqual(community_unpublish.status_code, 403, community_unpublish.text)

        public_hidden = self.client.get('/api/public/schedule?page_size=100')
        self.assertEqual(public_hidden.status_code, 200, public_hidden.text)
        self.assertEqual(public_hidden.json()['items'], [])
        self.assertEqual(public_hidden.json()['total'], 0)

        self.db.expire_all()
        after_unpublish_score = self.db.query(GameScore).filter(GameScore.game_id == self.game.id).one()
        self.assertEqual(after_unpublish_score.id, before_score_id)
        self.assertEqual(after_unpublish_score.game_id, before_game_id)
        self.assertEqual(after_unpublish_score.home_score, 24)
        self.assertEqual(after_unpublish_score.away_score, 18)
        self.assertEqual(after_unpublish_score.score_status, 'PUBLISHED')
        self.assertTrue(after_unpublish_score.is_published)
        self.assertEqual(self.db.query(ScoreHistory).filter(ScoreHistory.game_id == self.game.id).count(), before_history_count)
        self.assertEqual(self.db.query(Game).filter(Game.season_id == self.season.id).count(), before_game_count)

        republish = self.client.post(f'/api/seasons/{self.season.id}/publish-schedule', headers=self._token(self.scheduling_user.id))
        self.assertEqual(republish.status_code, 200, republish.text)
        self.assertTrue(republish.json()['schedule_published'])

        self.db.expire_all()
        after_republish_score = self.db.query(GameScore).filter(GameScore.game_id == self.game.id).one()
        self.assertEqual(after_republish_score.id, before_score_id)
        self.assertEqual(after_republish_score.game_id, before_game_id)
        self.assertTrue(after_republish_score.is_published)
        self.assertEqual(self.db.query(ScoreHistory).filter(ScoreHistory.game_id == self.game.id).count(), before_history_count)
        self.assertEqual(self.db.query(Game).filter(Game.season_id == self.season.id).count(), before_game_count)

        public_after = self.client.get('/api/public/schedule?page_size=100')
        self.assertEqual(public_after.status_code, 200, public_after.text)
        after_item = next(item for item in public_after.json()['items'] if item['id'] == str(self.game.id))
        self.assertEqual(after_item['home_score'], 24)
        self.assertEqual(after_item['away_score'], 18)
        self.assertEqual(after_item['public_score_status'], 'PUBLISHED')

    def test_schedule_republish_keeps_submitted_unpublished_scores_hidden(self):
        submit = self._submit(self.home_user, home=8, away=6)
        self.assertEqual(submit.status_code, 200, submit.text)

        unpublish = self.client.post(f'/api/seasons/{self.season.id}/unpublish-schedule', headers=self._token(self.scheduling_user.id))
        self.assertEqual(unpublish.status_code, 200, unpublish.text)
        republish = self.client.post(f'/api/seasons/{self.season.id}/publish-schedule', headers=self._token(self.scheduling_user.id))
        self.assertEqual(republish.status_code, 200, republish.text)

        self.db.expire_all()
        score = self.db.query(GameScore).filter(GameScore.game_id == self.game.id).one()
        self.assertEqual(score.score_status, 'SUBMITTED')
        self.assertFalse(score.is_published)

        public_after = self.client.get('/api/public/schedule?page_size=100')
        self.assertEqual(public_after.status_code, 200, public_after.text)
        item = next(item for item in public_after.json()['items'] if item['id'] == str(self.game.id))
        self.assertIsNone(item['home_score'])
        self.assertIsNone(item['away_score'])
        self.assertEqual(item['public_score_status'], 'MISSING')

    def test_scheduling_administrator_can_edit_approve_publish_and_unpublish(self):
        edit = self.client.patch(f'/api/scores/{self.game.id}', headers=self._token(self.scheduling_user.id), json={'home_score': 21, 'away_score': 12, 'league_admin_notes': 'inline correction'})
        self.assertEqual(edit.status_code, 200, edit.text)
        self.assertEqual(edit.json()['score']['score_status'], 'SUBMITTED')

        approve = self.client.post(f'/api/scores/{self.game.id}/approve', headers=self._token(self.scheduling_user.id), json={'league_admin_notes': 'approved'})
        self.assertEqual(approve.status_code, 200, approve.text)
        self.assertEqual(approve.json()['score']['score_status'], 'APPROVED')
        approved_public = self.client.get('/api/public/schedule?page_size=100')
        item = next(item for item in approved_public.json()['items'] if item['id'] == str(self.game.id))
        self.assertIsNone(item['home_score'])

        publish = self.client.post(f'/api/scores/{self.game.id}/publish', headers=self._token(self.scheduling_user.id))
        self.assertEqual(publish.status_code, 200, publish.text)
        self.assertTrue(publish.json()['score']['is_published'])
        published_public = self.client.get('/api/public/schedule?page_size=100')
        item = next(item for item in published_public.json()['items'] if item['id'] == str(self.game.id))
        self.assertEqual(item['home_score'], 21)
        self.assertEqual(item['away_score'], 12)
        self.assertEqual(item['public_score_status'], 'PUBLISHED')

        unpublish = self.client.post(f'/api/scores/{self.game.id}/unpublish', headers=self._token(self.scheduling_user.id), json={'reason': 'disputed'})
        self.assertEqual(unpublish.status_code, 200, unpublish.text)
        self.assertFalse(unpublish.json()['score']['is_published'])
        hidden_public = self.client.get('/api/public/schedule?page_size=100')
        item = next(item for item in hidden_public.json()['items'] if item['id'] == str(self.game.id))
        self.assertIsNone(item['home_score'])
        self.assertEqual(item['public_score_status'], 'MISSING')

    def test_approve_and_publish_and_correcting_published_score_marks_correction_pending(self):
        self._submit(self.home_user)
        approve_publish = self.client.post(f'/api/scores/{self.game.id}/approve-and-publish', headers=self._token(self.scheduling_user.id), json={})
        self.assertEqual(approve_publish.status_code, 200, approve_publish.text)
        self.assertEqual(approve_publish.json()['score']['score_status'], 'PUBLISHED')

        correction = self.client.patch(f'/api/scores/{self.game.id}', headers=self._token(self.scheduling_user.id), json={'home_score': 22, 'away_score': 12})
        self.assertEqual(correction.status_code, 200, correction.text)
        self.assertEqual(correction.json()['score']['score_status'], 'CORRECTION_PENDING')
        self.assertFalse(correction.json()['score']['is_published'])
        public = self.client.get('/api/public/schedule?page_size=100')
        item = next(item for item in public.json()['items'] if item['id'] == str(self.game.id))
        self.assertIsNone(item['home_score'])

    def test_matching_opponent_submission_confirms_and_different_submission_conflicts(self):
        self._submit(self.home_user, home=20, away=12)
        same = self._submit(self.away_user, home=20, away=12)
        self.assertEqual(same.status_code, 200, same.text)
        self.assertTrue(same.json()['score']['confirmed_by_opponent'])
        self.assertEqual(same.json()['score']['score_status'], 'SUBMITTED')

        self._submit(self.away_user, self.other_game.id, home=20, away=12)
        conflict = self._submit(self.other_user, self.other_game.id, home=12, away=20)
        self.assertEqual(conflict.status_code, 200, conflict.text)
        self.assertEqual(conflict.json()['score']['score_status'], 'CONFLICT')
        self.assertTrue(conflict.json()['score']['score_conflict'])
        flagged = self.client.get('/api/admin/scores/flagged', headers=self._token(self.scheduling_user.id))
        self.assertEqual(flagged.status_code, 200, flagged.text)
        self.assertEqual(flagged.json()['total'], 1)

        resolved = self.client.post(f'/api/scores/{self.other_game.id}/resolve-conflict', headers=self._token(self.scheduling_user.id), json={'home_score': 20, 'away_score': 12})
        self.assertEqual(resolved.status_code, 200, resolved.text)
        self.assertEqual(resolved.json()['score']['score_status'], 'APPROVED')
        self.assertFalse(resolved.json()['score']['score_conflict'])

    def test_history_missing_flagged_validation_and_scheduled_game_id_tie(self):
        missing = self.client.get('/api/admin/scores/missing', headers=self._token(self.scheduling_user.id))
        self.assertEqual(missing.status_code, 200, missing.text)
        self.assertGreaterEqual(missing.json()['total'], 2)

        negative = self._submit(self.home_user, home=-1, away=12)
        self.assertEqual(negative.status_code, 422)
        partial = self.client.patch(f'/api/scores/{self.game.id}/submit', headers=self._token(self.home_user.id), json={'home_score': 1})
        self.assertEqual(partial.status_code, 422)
        nonexistent = self.client.patch(f'/api/scores/{uuid.uuid4()}/submit', headers=self._token(self.home_user.id), json={'home_score': 1, 'away_score': 0})
        self.assertEqual(nonexistent.status_code, 404)

        submit = self._submit(self.home_user, home=14, away=14)
        self.assertEqual(submit.status_code, 200, submit.text)
        self.assertEqual(submit.json()['score']['score_status'], 'SUBMITTED')
        self.assertEqual(submit.json()['score']['home_score'], 14)
        self.assertEqual(submit.json()['score']['away_score'], 14)

        flag = self.client.post(f'/api/scores/{self.game.id}/flag', headers=self._token(self.home_user.id), json={'reason': 'wrong total'})
        self.assertEqual(flag.status_code, 200, flag.text)
        flagged = self.client.get('/api/admin/scores/flagged', headers=self._token(self.scheduling_user.id))
        self.assertEqual(flagged.json()['total'], 1)

        history = self.client.get(f'/api/scores/{self.game.id}/history', headers=self._token(self.scheduling_user.id))
        self.assertEqual(history.status_code, 200, history.text)
        actions = [item['action'] for item in history.json()['items']]
        self.assertIn('SUBMITTED', actions)
        self.assertIn('FLAGGED', actions)
        self.db.expire_all()
        self.assertEqual(self.db.query(ScoreHistory).filter(ScoreHistory.game_id == self.game.id).count(), len(actions))
        self.assertEqual(self.db.query(ScoreSubmission).filter(ScoreSubmission.game_id == self.game.id).one().game_id, self.game.id)


if __name__ == '__main__':
    unittest.main()
