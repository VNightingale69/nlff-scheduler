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
from app.models import Division, Game, GameScore, GameStatus, Organization, Role, ScoreHistory, ScoreSubmission, Season, Team, User, Week
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
        self.season = Season(id=uuid.uuid4(), name='Fall 2026', start_date=date(2026, 8, 1), end_date=date(2026, 11, 1), is_active=True, schedule_status='published')
        self.week = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=1, label='Week 1', start_date=date(2026, 5, 1), end_date=date(2026, 5, 7), primary_game_date=date(2026, 5, 2), status='REGULAR_SEASON')
        self.status = GameStatus(id=uuid.uuid4(), code='published', label='Published', is_active=True)
        self.home_team = Team(id=uuid.uuid4(), organization_id=self.home_org.id, division_id=self.division.id, name='Westosha 1', is_active=True)
        self.away_team = Team(id=uuid.uuid4(), organization_id=self.away_org.id, division_id=self.division.id, name='Lake 1', is_active=True)
        self.other_team = Team(id=uuid.uuid4(), organization_id=self.other_org.id, division_id=self.division.id, name='Other 1', is_active=True)
        self.game = Game(id=uuid.uuid4(), season_id=self.season.id, week_id=self.week.id, home_team_id=self.home_team.id, away_team_id=self.away_team.id, game_status_id=self.status.id, game_date=date(2026, 5, 2), kickoff_time=time(9, 0))
        self.other_game = Game(id=uuid.uuid4(), season_id=self.season.id, week_id=self.week.id, home_team_id=self.other_team.id, away_team_id=self.away_team.id, game_status_id=self.status.id, game_date=date(2026, 5, 2), kickoff_time=time(10, 0))
        self.league_user = User(id=uuid.uuid4(), email='league@example.com', full_name='League Admin', password_hash=hash_password('Password123!'), role_id=self.league_role.id, organization_id=None, is_active=True)
        self.scheduling_user = User(id=uuid.uuid4(), email='scheduling@example.com', full_name='Scheduling Admin', password_hash=hash_password('Password123!'), role_id=self.scheduling_role.id, organization_id=None, is_active=True)
        self.home_user = User(id=uuid.uuid4(), email='home@example.com', full_name='Home Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.home_org.id, is_active=True)
        self.away_user = User(id=uuid.uuid4(), email='away@example.com', full_name='Away Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.away_org.id, is_active=True)
        self.other_user = User(id=uuid.uuid4(), email='other@example.com', full_name='Other Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.other_org.id, is_active=True)
        self.db.add_all([self.league_role, self.scheduling_role, self.community_role, self.home_org, self.away_org, self.other_org, self.division, self.season, self.week, self.status, self.home_team, self.away_team, self.other_team, self.game, self.other_game, self.league_user, self.scheduling_user, self.home_user, self.away_user, self.other_user])
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
