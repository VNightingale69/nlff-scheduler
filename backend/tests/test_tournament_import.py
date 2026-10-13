import csv
import io
import unittest
import uuid
from datetime import date

import test_tournament_builder as fixtures
from app.models import Field, HostLocation, Tournament, TournamentGame
from app.routes.api import _generate_bracket_for_division


class TournamentImportTest(unittest.TestCase):
    setUp = fixtures.TournamentBuilderTest.setUp
    tearDown = fixtures.TournamentBuilderTest.tearDown
    _token = fixtures.TournamentBuilderTest._token
    _create = fixtures.TournamentBuilderTest._create

    def create(self, count=4, double=False):
        payload = {'season_id': str(self.season.id), 'division_ids': [str(self.division.id)],
                   'excluded_team_ids': [str(t.id) for t in self.teams[count:]],
                   'bracket_type': 'DOUBLE_ELIMINATION' if double else 'SINGLE_ELIMINATION'}
        response = self.client.post('/api/tournaments', headers=self._token(self.scheduler), json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        tournament = self.db.get(Tournament, uuid.UUID(response.json()['tournament']['id']))
        self.site = HostLocation(organization_id=self.orgs[0].id, name='Tim Osmond Sports Complex')
        self.db.add(self.site); self.db.flush()
        self.field = Field(host_location_id=self.site.id, name='Soccer Field - Medium 1', layout_type='SMALL')
        self.db.add(self.field); self.db.commit()
        return tournament

    def csv_for(self, tournament):
        games = sorted(tournament.divisions[0].games, key=lambda g: (g.round_number, g.game_number))
        ids = {g.id: f'D45-{i}' for i, g in enumerate(games, 1)}
        rows = []
        for i, game in enumerate(games):
            participants = []
            seeds = []
            for side in (1, 2):
                source = getattr(game, f'team_{side}_source_game_id')
                team = getattr(game, f'team_{side}')
                outcome = getattr(game, f'team_{side}_source_outcome').title()
                participants.append(f'{outcome} of {ids[source]}' if source else team.name)
                seeds.append('TBD' if source else getattr(game, f'team_{side}_seed'))
            rows.append(['10/17/2026', f'{8+i}:00', 'COED K-1', ids[game.id], game.round_name,
                         self.site.name, self.field.name, seeds[0], participants[0], seeds[1], participants[1]])
        return rows

    def encode(self, rows):
        out = io.StringIO(); writer = csv.writer(out)
        writer.writerow(['Date','Time','Division','Game ID','Round','Host Location','Field','Home Seed','Home Team','Away Seed','Away Team'])
        writer.writerows(rows)
        return out.getvalue().encode('utf-8-sig')

    def upload(self, tournament, rows, query='', user=None):
        return self.client.post(f'/api/tournaments/{tournament.id}/schedule-import{query}',
                                headers=self._token(user or self.scheduler),
                                files={'file': ('schedule.csv', self.encode(rows), 'text/csv')})

    def test_preview_apply_double_with_shuffled_order_preserves_results(self):
        tournament = self.create(double=True)
        rows = list(reversed(self.csv_for(tournament)))
        response = self.upload(tournament, rows)
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()['preview']
        self.assertEqual(report['invalid_rows'], 0, report)
        self.assertTrue(all(g.game_date is None for g in tournament.divisions[0].games))
        applied = self.upload(tournament, rows, '?apply=true&fingerprint='+report['fingerprint'])
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertEqual(applied.json()['updated_games'], 6)
        self.assertFalse(applied.json()['tournament']['is_published'])
        self.assertTrue(all(g.game_date == date(2026,10,17) and g.home_score is None for g in tournament.divisions[0].games))

    def test_stale_preview_permissions_duplicates_and_atomic_errors(self):
        tournament = self.create()
        rows = self.csv_for(tournament)
        self.assertEqual(self.upload(tournament, rows, user=self.community_user).status_code, 403)
        report = self.upload(tournament, rows).json()['preview']
        game = tournament.divisions[0].games[0]
        game.game_date = date(2026,10,18); self.db.commit()
        self.assertEqual(self.upload(tournament, rows, '?apply=true&fingerprint='+report['fingerprint']).status_code, 409)
        rows.append(rows[0])
        report = self.upload(tournament, rows).json()['preview']
        self.assertGreater(report['invalid_rows'], 0)
        self.assertEqual(self.upload(tournament, rows, '?apply=true&fingerprint='+report['fingerprint']).status_code, 400)
        self.assertEqual(game.game_date, date(2026,10,18))

    def test_reset_and_seed_mismatch_are_blocking(self):
        tournament = self.create(double=True)
        rows = self.csv_for(tournament)
        rows[0][7] = '99'
        rows[-1][4] = 'Championship Reset'
        report = self.upload(tournament, rows).json()['preview']
        messages = ' '.join(e for r in report['rows'] for e in r['errors'])
        self.assertIn('seed differs', messages)
        self.assertIn('without a reset', messages)

    def test_double_graph_counts_advancement_and_no_reset_for_two_to_eight(self):
        tournament = self.create(double=True)
        td = tournament.divisions[0]
        for count in range(2, 9):
            for i, tt in enumerate(sorted(td.teams, key=lambda t: t.seed)):
                tt.included = i < count
            _generate_bracket_for_division(self.db, td); self.db.flush(); self.db.expire(td, ['games'])
            games = sorted(td.games, key=lambda g: (g.round_number, g.game_number))
            self.assertEqual(len(games), 2 * count - 2, count)
            losses = {}
            for game in games:
                self.assertTrue(game.team_1_id and game.team_2_id, (count, game.round_name))
                self.assertNotEqual(game.team_1_id, game.team_2_id)
                losing = game.team_2_id
                losses[losing] = losses.get(losing, 0) + 1
                result = self.client.post(f'/api/tournament-games/{game.id}/approve-and-publish', headers=self._token(self.scheduler), json={'home_score':10,'away_score':0})
                self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(games[-1].round_name, 'Grand Final')
            self.assertNotIn('Reset', ' '.join(g.round_name for g in games))
            self.assertTrue(all(value <= 2 for value in losses.values()))

    def test_quarterfinal_alias_for_six_team_bracket_and_explicit_reset_exclusion(self):
        tournament = self.create(count=6)
        rows = self.csv_for(tournament)
        for row in rows:
            if row[4] == 'Play-In':
                row[4] = 'Quarterfinal'
        reset = list(rows[-1]); reset[3] = 'Reset'; reset[4] = 'Championship Reset'
        rows.append(reset)
        report = self.upload(tournament, rows, '?skip_resets=true').json()['preview']
        self.assertEqual(report['invalid_rows'], 0, report)
        self.assertEqual(report['valid_games'], 5)
        self.assertEqual(report['skipped_rows'], 1)
        self.assertTrue(report['rows'][-1]['skipped'])

    def test_loser_advancement_forfeit_and_correction(self):
        tournament = self.create(double=True)
        games = sorted(tournament.divisions[0].games, key=lambda g: (g.round_number,g.game_number))
        semifinal = games[0]
        original_home, original_away = semifinal.team_1_id, semifinal.team_2_id
        response = self.client.post(f'/api/tournament-games/{semifinal.id}/approve-and-publish', headers=self._token(self.scheduler), json={'home_score':'F','away_score':''})
        self.assertEqual(response.status_code,200,response.text)
        feeders = [g for g in games if g.team_1_source_game_id == semifinal.id or g.team_2_source_game_id == semifinal.id]
        self.assertEqual(len(feeders),2)
        for g in feeders:
            side = 1 if g.team_1_source_game_id == semifinal.id else 2
            outcome = getattr(g,f'team_{side}_source_outcome')
            self.assertEqual(getattr(g,f'team_{side}_id'),original_home if outcome == 'LOSER' else original_away)
        response = self.client.post(f'/api/tournament-games/{semifinal.id}/approve-and-publish', headers=self._token(self.scheduler), json={'home_score':10,'away_score':0})
        self.assertEqual(response.status_code,200,response.text)
        for g in feeders:
            side = 1 if g.team_1_source_game_id == semifinal.id else 2
            outcome = getattr(g,f'team_{side}_source_outcome')
            self.assertEqual(getattr(g,f'team_{side}_id'),original_away if outcome == 'LOSER' else original_home)
        response = self.client.post(f'/api/tournament-games/{semifinal.id}/unpublish-score', headers=self._token(self.scheduler), json={})
        self.assertEqual(response.status_code,200,response.text)
        payload = self.client.get(f'/api/tournaments/{tournament.id}/bracket',headers=self._token(self.scheduler)).json()['tournament']
        self.assertIn('Loser of Game', str(payload))
        for g in feeders:
            side = 1 if g.team_1_source_game_id == semifinal.id else 2
            self.assertIsNone(getattr(g,f'team_{side}_id'))

    def test_regenerate_changes_format_and_preserves_seeds(self):
        tournament = self.create()
        td = tournament.divisions[0]
        seeds = [(tt.team_id,tt.seed) for tt in td.teams]
        response = self.client.post(f'/api/tournaments/{tournament.id}/divisions/{td.id}/bracket', headers=self._token(self.scheduler), json={'bracket_type':'DOUBLE_ELIMINATION'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['tournament']['divisions'][0]['bracket_type'],'DOUBLE_ELIMINATION')
        self.assertEqual([(tt.team_id,tt.seed) for tt in td.teams],seeds)
        self.assertEqual(len(response.json()['tournament']['divisions'][0]['games']),6)
