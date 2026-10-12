import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import text

import test_tournament_builder as fixtures
from app.models import Division, Team, Tournament, TournamentDivision, TournamentGame, TournamentTeam
from app.routes.api import _generate_bracket_for_division


class TournamentBracketRemovalTest(unittest.TestCase):
    _create = fixtures.TournamentBuilderTest._create
    _token = fixtures.TournamentBuilderTest._token
    tearDown = fixtures.TournamentBuilderTest.tearDown
    def setUp(self):
        fixtures.TournamentBuilderTest.setUp(self)
        self.db.execute(text('PRAGMA foreign_keys=ON'))
        response = self._create(seed_overrides=[{'team_id': str(self.teams[2].id), 'seed': 1}], excluded=[str(self.teams[-1].id)])
        self.assertEqual(response.status_code, 200, response.text)
        self.tournament_id = response.json()['tournament']['id']
        self.division_id = response.json()['tournament']['divisions'][0]['id']
        self.path = f'/api/tournaments/{self.tournament_id}/divisions/{self.division_id}/bracket'
        self.headers = self._token(self.scheduler)

    def _game_ids(self):
        return {game.id for game in self.db.query(TournamentGame).filter_by(tournament_division_id=uuid.UUID(self.division_id))}

    def test_remove_and_regenerate_preserves_saved_seeds_and_other_division(self):
        tournament = self.db.get(Tournament, uuid.UUID(self.tournament_id))
        second_division = Division(id=uuid.uuid4(), name='2-3', division_group='COED', required_field_layout_type='SMALL', is_active=True)
        self.db.add(second_division)
        other = TournamentDivision(tournament_id=tournament.id, division_id=second_division.id, status='SEEDED')
        self.db.add(other)
        self.db.flush()
        self.db.add_all([TournamentTeam(tournament_division_id=other.id, team_id=team.id, seed=i, included=True) for i, team in enumerate(self.teams[:2], 1)])
        self.db.flush()
        _generate_bracket_for_division(self.db, other)
        self.db.commit()
        old_games = self._game_ids()
        other_games = {game.id for game in self.db.query(TournamentGame).filter_by(tournament_division_id=other.id)}
        seeds = [(row.team_id, row.seed, row.included) for row in self.db.query(TournamentTeam).filter_by(tournament_division_id=uuid.UUID(self.division_id))]
        response = self.client.delete(self.path, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._game_ids(), set())
        self.assertEqual([(row.team_id, row.seed, row.included) for row in self.db.query(TournamentTeam).filter_by(tournament_division_id=uuid.UUID(self.division_id))], seeds)
        response = self.client.post(self.path, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        new_games = self._game_ids()
        self.assertEqual(len(new_games), len(old_games))
        self.assertFalse(new_games & old_games)
        self.assertEqual({game.id for game in self.db.query(TournamentGame).filter_by(tournament_division_id=other.id)}, other_games)
        for division in response.json()['tournament']['divisions']:
            ids = {game['id'] for game in division['games']}
            for game in division['games']:
                for field in ['team_1_source_game_id', 'team_2_source_game_id']:
                    if game[field]: self.assertIn(game[field], ids)

    def test_delete_only_selected_duplicate_tournament(self):
        duplicate = self._create().json()['tournament']['id']
        self.client.post(f'/api/tournaments/{self.tournament_id}/publish', headers=self.headers)
        response = self.client.delete(f'/api/tournaments/{self.tournament_id}', headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(self.db.get(Tournament, uuid.UUID(self.tournament_id)))
        self.assertIsNotNone(self.db.get(Tournament, uuid.UUID(duplicate)))
        self.assertEqual(self.db.query(TournamentDivision).filter_by(tournament_id=uuid.UUID(self.tournament_id)).count(), 0)
        self.assertEqual(self.db.query(TournamentTeam).filter_by(tournament_division_id=uuid.UUID(self.division_id)).count(), 0)
        self.assertEqual(self._game_ids(), set())
        self.assertEqual(self.db.query(Team).count(), len(self.teams))
        public = self.client.get('/api/public/tournaments')
        self.assertNotIn(self.tournament_id, [item['id'] for item in public.json()['items']])

    def test_unauthorized_and_wrong_tournament_scope_leave_bracket_intact(self):
        games = self._game_ids()
        for method, path in [('delete', self.path), ('post', self.path), ('delete', f'/api/tournaments/{self.tournament_id}')]:
            response = getattr(self.client, method)(path, headers=self._token(self.community_user))
            self.assertEqual(response.status_code, 403, response.text)
        other_tournament_id = self._create().json()['tournament']['id']
        response = self.client.delete(f'/api/tournaments/{other_tournament_id}/divisions/{self.division_id}/bracket', headers=self.headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self._game_ids(), games)

    def test_recorded_result_blocks_removal_and_regeneration(self):
        game = self.db.query(TournamentGame).filter_by(tournament_division_id=uuid.UUID(self.division_id)).first()
        game.home_score = 0
        self.db.commit()
        games = self._game_ids()
        for method, path in [('delete', self.path), ('post', self.path), ('delete', f'/api/tournaments/{self.tournament_id}')]:
            response = getattr(self.client, method)(path, headers=self.headers)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(self._game_ids(), games)

    def test_failed_tournament_delete_keeps_all_records(self):
        games = self._game_ids()
        with patch('sqlalchemy.orm.Session.commit', side_effect=RuntimeError('database unavailable')):
            response = self.client.delete(f'/api/tournaments/{self.tournament_id}', headers=self.headers)
        self.assertEqual(response.status_code, 500, response.text)
        self.assertIsNotNone(self.db.get(Tournament, uuid.UUID(self.tournament_id)))
        self.assertEqual(self._game_ids(), games)
        self.assertEqual(self.db.query(TournamentTeam).filter_by(tournament_division_id=uuid.UUID(self.division_id)).count(), len(self.teams))

    def test_failed_regeneration_rolls_back_old_bracket(self):
        games = self._game_ids()
        with patch('app.routes.api._generate_bracket_for_division', side_effect=RuntimeError('generation failed')):
            response = self.client.post(self.path, headers=self.headers)
        self.assertEqual(response.status_code, 500, response.text)
        self.assertEqual(self._game_ids(), games)

