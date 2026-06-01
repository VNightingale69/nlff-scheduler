import unittest
import uuid
from datetime import date, time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import ROLE_COMMUNITY_ADMIN, ROLE_LEAGUE_ADMIN
from app.database import Base, get_db
from app.main import app
from app.models import Division, Game, GameScore, GameStatus, Organization, Role, ScoreSubmission, Season, Team, User, Week
from app.security import create_access_token, hash_password


class ScoreTrackingTest(unittest.TestCase):
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
        self.home_user = User(id=uuid.uuid4(), email='home@example.com', full_name='Home Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.home_org.id, is_active=True)
        self.away_user = User(id=uuid.uuid4(), email='away@example.com', full_name='Away Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.away_org.id, is_active=True)
        self.other_user = User(id=uuid.uuid4(), email='other@example.com', full_name='Other Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.other_org.id, is_active=True)
        self.db.add_all([
            self.league_role, self.community_role, self.home_org, self.away_org, self.other_org,
            self.division, self.season, self.week, self.status, self.home_team, self.away_team,
            self.other_team, self.game, self.other_game, self.league_user, self.home_user,
            self.away_user, self.other_user,
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

    def test_community_admin_can_submit_for_eligible_scheduled_game(self):
        response = self.client.post(
            f'/api/community/games/{self.game.id}/score',
            headers=self._token(self.home_user.id),
            json={'home_score': 20, 'away_score': 12, 'community_admin_notes': 'Final'},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        score = self.db.query(GameScore).filter(GameScore.game_id == self.game.id).one()
        self.assertEqual(score.score_status, 'SUBMITTED')
        self.assertEqual(score.home_score, 20)
        self.assertEqual(self.db.query(ScoreSubmission).filter(ScoreSubmission.game_id == self.game.id).count(), 1)

    def test_community_admin_cannot_submit_for_unrelated_game(self):
        response = self.client.post(
            f'/api/community/games/{self.game.id}/score',
            headers=self._token(self.other_user.id),
            json={'home_score': 20, 'away_score': 12},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.db.query(GameScore).count(), 0)

    def test_matching_winners_do_not_flag_and_winner_changes_flag(self):
        first = self.client.post(f'/api/community/games/{self.game.id}/score', headers=self._token(self.home_user.id), json={'home_score': 20, 'away_score': 12})
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post(f'/api/community/games/{self.game.id}/score', headers=self._token(self.away_user.id), json={'home_score': 21, 'away_score': 12})
        self.assertEqual(second.status_code, 200, second.text)
        self.db.expire_all()
        self.assertEqual(self.db.query(GameScore).filter(GameScore.game_id == self.game.id).one().score_status, 'SUBMITTED')

        response = self.client.post(f'/api/community/games/{self.other_game.id}/score', headers=self._token(self.away_user.id), json={'home_score': 20, 'away_score': 12})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(f'/api/community/games/{self.other_game.id}/score', headers=self._token(self.other_user.id), json={'home_score': 12, 'away_score': 20})
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        self.assertEqual(self.db.query(GameScore).filter(GameScore.game_id == self.other_game.id).one().score_status, 'FLAGGED')
        flagged = self.client.get('/api/admin/scores/flagged', headers=self._token(self.league_user.id))
        self.assertEqual(flagged.status_code, 200, flagged.text)
        self.assertEqual(flagged.json()['total'], 1)

    def test_tie_change_flags(self):
        self.client.post(f'/api/community/games/{self.game.id}/score', headers=self._token(self.home_user.id), json={'home_score': 14, 'away_score': 14})
        response = self.client.post(f'/api/community/games/{self.game.id}/score', headers=self._token(self.away_user.id), json={'home_score': 20, 'away_score': 14})
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        self.assertEqual(self.db.query(GameScore).filter(GameScore.game_id == self.game.id).one().score_status, 'FLAGGED')

    def test_league_admin_can_approve_and_override_scores(self):
        self.client.post(f'/api/community/games/{self.game.id}/score', headers=self._token(self.home_user.id), json={'home_score': 20, 'away_score': 12})
        approve = self.client.post(f'/api/admin/games/{self.game.id}/score/approve', headers=self._token(self.league_user.id), json={'league_admin_notes': 'Approved'})
        self.assertEqual(approve.status_code, 200, approve.text)
        self.db.expire_all()
        self.assertEqual(self.db.query(GameScore).filter(GameScore.game_id == self.game.id).one().score_status, 'APPROVED')

        override = self.client.put(f'/api/admin/games/{self.game.id}/score', headers=self._token(self.league_user.id), json={'home_score': 21, 'away_score': 12, 'league_admin_notes': 'Correction'})
        self.assertEqual(override.status_code, 200, override.text)
        approve = self.client.post(f'/api/admin/games/{self.game.id}/score/approve', headers=self._token(self.league_user.id), json={})
        self.assertEqual(approve.status_code, 200, approve.text)
        self.db.expire_all()
        score = self.db.query(GameScore).filter(GameScore.game_id == self.game.id).one()
        self.assertEqual(score.home_score, 21)
        self.assertEqual(score.score_status, 'APPROVED')

    def test_public_schedule_only_exposes_approved_scores(self):
        self.client.post(f'/api/community/games/{self.game.id}/score', headers=self._token(self.home_user.id), json={'home_score': 20, 'away_score': 12})
        pending = self.client.get('/api/public/schedule?page_size=100')
        self.assertEqual(pending.status_code, 200, pending.text)
        item = next(item for item in pending.json()['items'] if item['id'] == str(self.game.id))
        self.assertIsNone(item['home_score'])
        self.assertIsNone(item['away_score'])
        self.assertEqual(item['public_score_status'], 'SCORE_PENDING')

        self.client.post(f'/api/admin/games/{self.game.id}/score/approve', headers=self._token(self.league_user.id), json={})
        approved = self.client.get('/api/public/schedule?page_size=100')
        self.assertEqual(approved.status_code, 200, approved.text)
        item = next(item for item in approved.json()['items'] if item['id'] == str(self.game.id))
        self.assertEqual(item['home_score'], 20)
        self.assertEqual(item['away_score'], 12)
        self.assertEqual(item['public_score_status'], 'APPROVED')
        self.assertNotIn('community_admin_notes', item)

    def test_missing_history_and_invalid_submissions(self):
        missing = self.client.get('/api/admin/scores/missing', headers=self._token(self.league_user.id))
        self.assertEqual(missing.status_code, 200, missing.text)
        self.assertGreaterEqual(missing.json()['total'], 2)

        negative = self.client.post(f'/api/community/games/{self.game.id}/score', headers=self._token(self.home_user.id), json={'home_score': -1, 'away_score': 12})
        self.assertEqual(negative.status_code, 422)
        partial = self.client.post(f'/api/community/games/{self.game.id}/score', headers=self._token(self.home_user.id), json={'home_score': 1})
        self.assertEqual(partial.status_code, 422)
        nonexistent = self.client.post(f'/api/community/games/{uuid.uuid4()}/score', headers=self._token(self.home_user.id), json={'home_score': 1, 'away_score': 0})
        self.assertEqual(nonexistent.status_code, 404)

        self.client.post(f'/api/community/games/{self.game.id}/score', headers=self._token(self.home_user.id), json={'home_score': 20, 'away_score': 12})
        history = self.client.get(f'/api/admin/games/{self.game.id}/score-history', headers=self._token(self.league_user.id))
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual(history.json()['total'], 1)


if __name__ == '__main__':
    unittest.main()
