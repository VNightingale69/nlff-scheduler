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
from app.models import Division, Game, GameScore, GameStatus, Organization, Role, Season, Team, Tournament, TournamentGame, User, Week
from app.security import create_access_token, hash_password


class TournamentBuilderTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool, future=True)
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.db = self.SessionLocal()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.scheduler_role = Role(id=uuid.uuid4(), name=ROLE_SCHEDULING_ADMIN, is_active=True)
        self.community_role = Role(id=uuid.uuid4(), name=ROLE_COMMUNITY_ADMIN, is_active=True)
        self.division = Division(id=uuid.uuid4(), name='K-1', division_group='COED', sort_order=1, required_field_layout_type='SMALL', is_active=True)
        self.season = Season(id=uuid.uuid4(), name='Fall 2026', start_date=date.today() - timedelta(days=10), end_date=date.today() + timedelta(days=90), is_active=True, schedule_status='published')
        self.week = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=1, start_date=date.today() - timedelta(days=8), end_date=date.today() - timedelta(days=2), primary_game_date=date.today() - timedelta(days=5), date_type='REGULAR_SEASON')
        self.status = GameStatus(id=uuid.uuid4(), code='published', label='Published', is_active=True)
        self.scheduler = User(id=uuid.uuid4(), email='scheduler@example.com', full_name='Scheduler', password_hash=hash_password('Password123!'), role_id=self.scheduler_role.id, is_active=True)
        self.orgs = [Organization(id=uuid.uuid4(), name=f'Org {i}', is_active=True) for i in range(1, 9)]
        self.teams = [Team(id=uuid.uuid4(), organization_id=org.id, division_id=self.division.id, name=f'Team {i}', is_active=True) for i, org in enumerate(self.orgs, start=1)]
        self.community_user = User(id=uuid.uuid4(), email='org1@example.com', full_name='Org 1 Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.orgs[0].id, is_active=True)
        self.db.add_all([self.scheduler_role, self.community_role, self.division, self.season, self.week, self.status, self.scheduler, self.community_user, *self.orgs, *self.teams])
        self.db.commit()

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def _token(self, user):
        return {'Authorization': f'Bearer {create_access_token(str(user.id))}'}

    def _regular_game(self, home, away, score):
        game = Game(id=uuid.uuid4(), season_id=self.season.id, week_id=self.week.id, home_team_id=home.id, away_team_id=away.id, game_status_id=self.status.id, game_date=date.today() - timedelta(days=5), kickoff_time=time(9, 0), game_type='REGULAR_SEASON')
        self.db.add(game); self.db.flush()
        self.db.add(GameScore(game_id=game.id, home_score=score[0], away_score=score[1], score_status='PUBLISHED', is_published=True))
        self.db.commit()
        return game

    def _create(self, team_count=4, seed_overrides=None, excluded=None):
        payload = {
            'season_id': str(self.season.id),
            'name': 'Playoffs',
            'division_ids': [str(self.division.id)],
            'seed_overrides': seed_overrides or [],
            'excluded_team_ids': excluded or [],
            'generate_bracket': True,
        }
        return self.client.post('/api/tournaments', headers=self._token(self.scheduler), json=payload)

    def test_create_tournament_from_standings_includes_active_teams_and_default_seeds(self):
        # Team 1 earns the top regular-season ranking and should become seed 1.
        self._regular_game(self.teams[0], self.teams[1], (20, 0))
        response = self._create()
        self.assertEqual(response.status_code, 200, response.text)
        division = response.json()['tournament']['divisions'][0]
        self.assertEqual(len(division['teams']), 8)
        seeds = {team['team_name']: team['seed'] for team in division['teams']}
        self.assertEqual(seeds['Team 1'], 1)
        self.assertTrue(all(team['included'] for team in division['teams']))

    def test_manual_seed_override_and_four_team_bracket(self):
        response = self._create(seed_overrides=[{'team_id': str(self.teams[3].id), 'seed': 1}], excluded=[str(team.id) for team in self.teams[4:]])
        self.assertEqual(response.status_code, 200, response.text)
        division = response.json()['tournament']['divisions'][0]
        self.assertEqual(next(team for team in division['teams'] if team['team_id'] == str(self.teams[3].id))['seed_source'], 'MANUAL')
        games = division['games']
        self.assertEqual([game['round_name'] for game in games].count('Semifinal'), 2)
        self.assertEqual([game['round_name'] for game in games].count('Championship'), 1)

    def test_non_power_brackets_create_byes(self):
        expectations = {5: ('Play-In', 4), 6: ('Play-In', 5), 7: ('Play-In', 6), 8: ('Quarterfinal', 7)}
        for count, (first_round_name, game_count) in expectations.items():
            with self.subTest(count=count):
                excluded = [str(team.id) for team in self.teams[count:]]
                response = self._create(excluded=excluded)
                self.assertEqual(response.status_code, 200, response.text)
                games = response.json()['tournament']['divisions'][0]['games']
                self.assertEqual(len(games), game_count)
                self.assertIn(first_round_name, {game['round_name'] for game in games})
                self.db.query(Tournament).delete()
                self.db.commit()

    def test_winner_advances_tie_rejected_and_forfeit_advances_opponent(self):
        response = self._create(excluded=[str(team.id) for team in self.teams[4:]])
        self.assertEqual(response.status_code, 200, response.text)
        games = response.json()['tournament']['divisions'][0]['games']
        semifinal = next(game for game in games if game['round_name'] == 'Semifinal')
        tie = self.client.post(f"/api/tournament-games/{semifinal['id']}/approve-and-publish", headers=self._token(self.scheduler), json={'home_score': 7, 'away_score': 7})
        self.assertEqual(tie.status_code, 400)
        publish = self.client.post(f"/api/tournament-games/{semifinal['id']}/approve-and-publish", headers=self._token(self.scheduler), json={'home_score': 'F', 'away_score': ''})
        self.assertEqual(publish.status_code, 200, publish.text)
        winner_id = publish.json()['game']['winner_team_id']
        tournament = self.client.get(f"/api/tournaments/{response.json()['tournament']['id']}", headers=self._token(self.scheduler)).json()['tournament']
        championship = next(game for game in tournament['divisions'][0]['games'] if game['round_name'] == 'Championship')
        self.assertIn(winner_id, {championship['team_1_id'], championship['team_2_id']})


    def test_bracket_api_groups_rounds_and_uses_game_number_placeholders(self):
        response = self._create(excluded=[str(team.id) for team in self.teams[4:]])
        self.assertEqual(response.status_code, 200, response.text)
        tournament_id = response.json()['tournament']['id']
        bracket = self.client.get(f'/api/tournaments/{tournament_id}/bracket', headers=self._token(self.scheduler))
        self.assertEqual(bracket.status_code, 200, bracket.text)
        rounds = bracket.json()['tournament']['divisions'][0]['rounds']
        self.assertEqual([round_row['round_name'] for round_row in rounds], ['Semifinal', 'Championship'])
        championship = rounds[-1]['games'][0]
        self.assertEqual(championship['team_1_placeholder'], 'Winner of Game 1')
        self.assertEqual(championship['team_2_placeholder'], 'Winner of Game 2')

    def test_unpublish_and_corrected_winner_recalculate_downstream_bracket(self):
        response = self._create(excluded=[str(team.id) for team in self.teams[4:]])
        tournament_id = response.json()['tournament']['id']
        games = response.json()['tournament']['divisions'][0]['games']
        semifinal = next(game for game in games if game['round_name'] == 'Semifinal')
        publish = self.client.post(f"/api/tournament-games/{semifinal['id']}/approve-and-publish", headers=self._token(self.scheduler), json={'home_score': 14, 'away_score': 6})
        self.assertEqual(publish.status_code, 200, publish.text)
        first_winner = publish.json()['game']['winner_team_id']
        bracket = self.client.get(f'/api/tournaments/{tournament_id}/bracket', headers=self._token(self.scheduler)).json()['tournament']
        championship = next(game for game in bracket['divisions'][0]['games'] if game['round_name'] == 'Championship')
        self.assertIn(first_winner, {championship['team_1_id'], championship['team_2_id']})

        unpublish = self.client.post(f"/api/tournament-games/{semifinal['id']}/unpublish-score", headers=self._token(self.scheduler), json={})
        self.assertEqual(unpublish.status_code, 200, unpublish.text)
        bracket = self.client.get(f'/api/tournaments/{tournament_id}/bracket', headers=self._token(self.scheduler)).json()['tournament']
        championship = next(game for game in bracket['divisions'][0]['games'] if game['round_name'] == 'Championship')
        self.assertIn('Winner of Game', {championship['team_1_placeholder'], championship['team_2_placeholder']})
        self.assertNotIn(first_winner, {championship['team_1_id'], championship['team_2_id']})

        corrected = self.client.post(f"/api/tournament-games/{semifinal['id']}/approve-and-publish", headers=self._token(self.scheduler), json={'home_score': 6, 'away_score': 14})
        self.assertEqual(corrected.status_code, 200, corrected.text)
        corrected_winner = corrected.json()['game']['winner_team_id']
        self.assertNotEqual(first_winner, corrected_winner)
        bracket = self.client.get(f'/api/tournaments/{tournament_id}/bracket', headers=self._token(self.scheduler)).json()['tournament']
        championship = next(game for game in bracket['divisions'][0]['games'] if game['round_name'] == 'Championship')
        self.assertIn(corrected_winner, {championship['team_1_id'], championship['team_2_id']})

    def test_public_bracket_hides_unpublished_scores_and_internal_review(self):
        response = self._create(excluded=[str(team.id) for team in self.teams[4:]])
        tournament_id = response.json()['tournament']['id']
        game = response.json()['tournament']['divisions'][0]['games'][0]
        self.client.patch(f"/api/tournament-games/{game['id']}/submit-score", headers=self._token(self.community_user), json={'home_score': 5, 'away_score': 3})
        hidden = self.client.get(f'/api/public/tournaments/{tournament_id}/bracket')
        self.assertEqual(hidden.status_code, 404)
        self.client.post(f'/api/tournaments/{tournament_id}/publish', headers=self._token(self.scheduler), json={})
        public = self.client.get(f'/api/public/tournaments/{tournament_id}/bracket')
        self.assertEqual(public.status_code, 200, public.text)
        public_game = public.json()['tournament']['divisions'][0]['games'][0]
        self.assertIsNone(public_game['home_score'])
        self.assertEqual(public_game['score_status'], 'MISSING')
        self.assertFalse(public_game['needs_review'])

    def test_community_admin_can_view_bracket_but_cannot_edit_structure(self):
        response = self._create(excluded=[str(team.id) for team in self.teams[4:]])
        tournament_id = response.json()['tournament']['id']
        game_id = response.json()['tournament']['divisions'][0]['games'][0]['id']
        bracket = self.client.get(f'/api/tournaments/{tournament_id}/bracket', headers=self._token(self.community_user))
        self.assertEqual(bracket.status_code, 200, bracket.text)
        edit = self.client.patch(f'/api/tournament-games/{game_id}/schedule', headers=self._token(self.community_user), json={'date': str(date.today())})
        self.assertEqual(edit.status_code, 403)

    def test_downstream_published_game_is_marked_for_review_when_upstream_changes(self):
        response = self._create(excluded=[str(team.id) for team in self.teams[4:]])
        games = response.json()['tournament']['divisions'][0]['games']
        semifinals = [game for game in games if game['round_name'] == 'Semifinal']
        for game in semifinals:
            result = self.client.post(f"/api/tournament-games/{game['id']}/approve-and-publish", headers=self._token(self.scheduler), json={'home_score': 10, 'away_score': 1})
            self.assertEqual(result.status_code, 200, result.text)
        tournament = self.client.get(f"/api/tournaments/{response.json()['tournament']['id']}", headers=self._token(self.scheduler)).json()['tournament']
        championship = next(game for game in tournament['divisions'][0]['games'] if game['round_name'] == 'Championship')
        final = self.client.post(f"/api/tournament-games/{championship['id']}/approve-and-publish", headers=self._token(self.scheduler), json={'home_score': 9, 'away_score': 2})
        self.assertEqual(final.status_code, 200, final.text)
        corrected = self.client.post(f"/api/tournament-games/{semifinals[0]['id']}/approve-and-publish", headers=self._token(self.scheduler), json={'home_score': 1, 'away_score': 10})
        self.assertEqual(corrected.status_code, 200, corrected.text)
        final_row = self.db.query(TournamentGame).filter(TournamentGame.id == uuid.UUID(championship['id'])).first()
        self.assertTrue(final_row.needs_review)
        self.assertEqual(final_row.status, 'NEEDS_REVIEW')

    def test_permissions_publication_and_regular_standings_separation(self):
        community_attempt = self.client.post('/api/tournaments', headers=self._token(self.community_user), json={'season_id': str(self.season.id), 'division_ids': [str(self.division.id)]})
        self.assertEqual(community_attempt.status_code, 403)
        response = self._create(excluded=[str(team.id) for team in self.teams[4:]])
        tournament_id = response.json()['tournament']['id']
        self.assertEqual(self.client.get('/api/public/tournaments').json()['items'], [])
        self.client.post(f'/api/tournaments/{tournament_id}/publish', headers=self._token(self.scheduler), json={})
        self.assertEqual(len(self.client.get('/api/public/tournaments').json()['items']), 1)
        before = self.client.get(f'/api/standings?season_id={self.season.id}', headers=self._token(self.scheduler)).json()
        game = response.json()['tournament']['divisions'][0]['games'][0]
        self.client.post(f"/api/tournament-games/{game['id']}/approve-and-publish", headers=self._token(self.scheduler), json={'home_score': 21, 'away_score': 0})
        after = self.client.get(f'/api/standings?season_id={self.season.id}', headers=self._token(self.scheduler)).json()
        self.assertEqual(before['divisions'][0]['standings'], after['divisions'][0]['standings'])


if __name__ == '__main__':
    unittest.main()
