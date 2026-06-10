import unittest
import uuid
from datetime import date, time, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import ROLE_COMMUNITY_ADMIN, ROLE_SCHEDULING_ADMIN
from app.database import Base, get_db
from app.main import app
from app.models import Division, Game, GameScore, GameStatus, Organization, Role, Season, Team, User, Week
from app.security import create_access_token, hash_password


class StandingsTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool, future=True)
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.db = self.SessionLocal()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

        self.scheduling_role = Role(id=uuid.uuid4(), name=ROLE_SCHEDULING_ADMIN, is_active=True)
        self.community_role = Role(id=uuid.uuid4(), name=ROLE_COMMUNITY_ADMIN, is_active=True)
        self.org_a = Organization(id=uuid.uuid4(), name='Westosha', is_active=True)
        self.org_b = Organization(id=uuid.uuid4(), name='Lake County', is_active=True)
        self.org_c = Organization(id=uuid.uuid4(), name='Other', is_active=True)
        self.division = Division(id=uuid.uuid4(), name='K-1', division_group='COED', sort_order=1, required_field_layout_type='SMALL', is_active=True)
        self.season = Season(id=uuid.uuid4(), name='Fall 2026', start_date=date.today() - timedelta(days=20), end_date=date.today() + timedelta(days=80), is_active=True, schedule_status='published')
        self.week = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=1, label='Week 1', start_date=date.today() - timedelta(days=14), end_date=date.today() - timedelta(days=8), primary_game_date=date.today() - timedelta(days=10), status='REGULAR_SEASON')
        self.status = GameStatus(id=uuid.uuid4(), code='published', label='Published', is_active=True)
        self.teams = [
            Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=self.division.id, name='A Team', is_active=True),
            Team(id=uuid.uuid4(), organization_id=self.org_b.id, division_id=self.division.id, name='B Team', is_active=True),
            Team(id=uuid.uuid4(), organization_id=self.org_c.id, division_id=self.division.id, name='C Team', is_active=True),
            Team(id=uuid.uuid4(), organization_id=self.org_c.id, division_id=self.division.id, name='D No Scores', is_active=True),
        ]
        self.scheduling_user = User(id=uuid.uuid4(), email='scheduler@example.com', full_name='Scheduler', password_hash=hash_password('Password123!'), role_id=self.scheduling_role.id, is_active=True)
        self.community_user = User(id=uuid.uuid4(), email='a@example.com', full_name='A Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.org_a.id, is_active=True)
        self.db.add_all([self.scheduling_role, self.community_role, self.org_a, self.org_b, self.org_c, self.division, self.season, self.week, self.status, *self.teams, self.scheduling_user, self.community_user])
        self.db.commit()

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def _token(self, user):
        return {'Authorization': f'Bearer {create_access_token(str(user.id))}'}

    def _game(self, home, away, days=-10, kickoff=time(9, 0), score=None, status='PUBLISHED', published=True, home_forfeit=False, away_forfeit=False, conflict=False, flagged=False):
        game = Game(id=uuid.uuid4(), season_id=self.season.id, week_id=self.week.id, home_team_id=home.id, away_team_id=away.id, game_status_id=self.status.id, game_date=date.today() + timedelta(days=days), kickoff_time=kickoff)
        self.db.add(game)
        self.db.flush()
        if score is not None:
            home_score, away_score = score
            self.db.add(GameScore(game_id=game.id, home_score=home_score, away_score=away_score, home_forfeit=home_forfeit, away_forfeit=away_forfeit, score_status=status, is_published=published, score_conflict=conflict, flagged=flagged))
        self.db.commit()
        return game

    def _standings(self, user=None, public=False):
        path = f'/api/public/standings?season_id={self.season.id}' if public else f'/api/standings?season_id={self.season.id}'
        return self.client.get(path, headers={} if public else self._token(user or self.scheduling_user))

    def test_division_standings_include_zero_score_teams_and_count_published_results_only(self):
        self._game(self.teams[0], self.teams[1], score=(21, 14))
        self._game(self.teams[1], self.teams[2], score=(7, 20), status='SUBMITTED', published=False)
        self._game(self.teams[0], self.teams[2])
        response = self._standings()
        self.assertEqual(response.status_code, 200, response.text)
        division = response.json()['divisions'][0]
        rows = {row['team_name']: row for row in division['standings']}
        self.assertEqual(set(rows), {'A Team', 'B Team', 'C Team', 'D No Scores'})
        self.assertEqual(rows['A Team']['wins'], 1)
        self.assertEqual(rows['B Team']['losses'], 1)
        self.assertEqual(rows['C Team']['wins'], 0)
        self.assertEqual(rows['D No Scores']['games_played'], 0)
        self.assertEqual(division['summary']['official_played'], 1)
        self.assertEqual(division['summary']['pending_approval'], 1)
        self.assertEqual(division['summary']['missing'], 1)

    def test_ties_forfeits_points_and_ranking_tiebreakers(self):
        self._game(self.teams[0], self.teams[1], score=(14, 14), kickoff=time(9, 0))
        self._game(self.teams[2], self.teams[0], score=(0, 1), kickoff=time(10, 0), home_forfeit=True)
        self._game(self.teams[1], self.teams[2], score=(1, 0), kickoff=time(11, 0), away_forfeit=True)
        response = self._standings()
        self.assertEqual(response.status_code, 200, response.text)
        rows = {row['team_name']: row for row in response.json()['divisions'][0]['standings']}
        self.assertEqual(rows['A Team']['ties'], 1)
        self.assertEqual(rows['A Team']['wins'], 1)
        self.assertEqual(rows['A Team']['points_for'], 15)
        self.assertEqual(rows['A Team']['points_against'], 14)
        self.assertEqual(rows['A Team']['forfeits_won'], 1)
        self.assertEqual(rows['C Team']['forfeits_lost'], 2)
        ordered = [row['team_name'] for row in response.json()['divisions'][0]['standings']]
        self.assertLess(ordered.index('A Team'), ordered.index('B Team'))

    def test_rank_order_is_deterministic_for_equal_records(self):
        response = self._standings()
        self.assertEqual(response.status_code, 200, response.text)
        ordered = [row['team_name'] for row in response.json()['divisions'][0]['standings']]
        self.assertEqual(ordered, ['A Team', 'B Team', 'C Team', 'D No Scores'])

    def test_unpublish_and_republish_recalculate_standings(self):
        game = self._game(self.teams[0], self.teams[1], score=(10, 0))
        first = self._standings().json()['divisions'][0]['standings'][0]
        self.assertEqual(first['team_name'], 'A Team')
        unpublish = self.client.post(f'/api/scores/{game.id}/unpublish', headers=self._token(self.scheduling_user), json={'reason': 'test'})
        self.assertEqual(unpublish.status_code, 200, unpublish.text)
        after_unpublish = {row['team_name']: row for row in self._standings().json()['divisions'][0]['standings']}
        self.assertEqual(after_unpublish['A Team']['wins'], 0)
        score = self.db.query(GameScore).filter(GameScore.game_id == game.id).one()
        score.home_score = 0
        score.away_score = 12
        score.score_status = 'PUBLISHED'
        score.is_published = True
        self.db.commit()
        after_republish = {row['team_name']: row for row in self._standings().json()['divisions'][0]['standings']}
        self.assertEqual(after_republish['B Team']['wins'], 1)
        self.assertEqual(after_republish['A Team']['losses'], 1)

    def test_flagged_conflict_future_public_and_community_permissions(self):
        self._game(self.teams[0], self.teams[1], score=(6, 3), status='CONFLICT', published=True, conflict=True)
        self._game(self.teams[0], self.teams[2], days=5)
        self._game(self.teams[1], self.teams[2], score=(8, 2))
        admin = self._standings().json()
        summary = admin['divisions'][0]['summary']
        self.assertEqual(summary['flagged_conflict'], 1)
        self.assertEqual(summary['future'], 1)
        rows = {row['team_name']: row for row in admin['divisions'][0]['standings']}
        self.assertEqual(rows['A Team']['wins'], 0)
        community = self._standings(self.community_user)
        self.assertEqual(community.status_code, 200, community.text)
        self.assertTrue(all('Approve' not in row['actions'] and 'Publish' not in row['actions'] for row in community.json()['game_results']))
        self.assertTrue(all(row['home_team'] == 'A Team' or row['away_team'] == 'A Team' for row in community.json()['game_results']))
        public = self._standings(public=True)
        self.assertEqual(public.status_code, 200, public.text)
        public_results = public.json()['game_results']
        self.assertTrue(all(row['score_status'] == 'PUBLISHED' or row['result_status'] == 'Future Game' for row in public_results))
        self.assertFalse(any(row['score_status'] == 'CONFLICT' for row in public_results))


if __name__ == '__main__':
    unittest.main()
