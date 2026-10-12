import csv
import io
import unittest
from unittest.mock import patch
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime

import test_score_tracking as fixtures
from app.models import GameScore


class ScoreExportTest(unittest.TestCase):
    setUp = fixtures.ScoreTrackingTest.setUp
    tearDown = fixtures.ScoreTrackingTest.tearDown
    _token = fixtures.ScoreTrackingTest._token

    def _export(self, query='', user=None):
        return self.client.get('/api/scores/export.csv' + query, headers=self._token((user or self.league_user).id))

    def _rows(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        return list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))

    def _score(self):
        score = GameScore(game_id=self.game.id, home_score=0, away_score=6, away_forfeit=True,
                          score_status='PUBLISHED', is_published=True, flagged=True, score_conflict=True,
                          submitted_by_user_id=self.league_user.id, submitted_at=datetime(2026, 5, 2, 15, 0),
                          last_updated_at=datetime(2026, 5, 2, 16, 0))
        self.db.add(score)
        self.db.commit()
        return score

    def test_export_saved_scores_missing_zero_forfeit_and_metadata(self):
        self._score()
        response = self._export()
        rows = self._rows(response)
        self.assertEqual(response.headers['content-disposition'], 'attachment; filename="scores-export.csv"')
        self.assertIn('text/csv', response.headers['content-type'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        by_id = {row['Game ID']: row for row in rows}
        self.assertEqual(len(rows), 2)
        game = by_id[str(self.game.id)]
        self.assertEqual(game['Home Score'], '0')
        self.assertEqual(game['Away Score'], 'F')
        self.assertEqual(game['Submitted By'], 'League Admin')
        self.assertEqual(game['Submitted (America/Chicago)'], '2026-05-02T10:00:00-05:00')
        self.assertEqual(game['Updated (America/Chicago)'], '2026-05-02T11:00:00-05:00')
        self.assertEqual(game['Division'], 'COED K-1')
        self.assertEqual(game['Flagged'], 'Yes')
        self.assertEqual(game['Conflict'], 'Yes')
        self.assertEqual(by_id[str(self.other_game.id)]['Home Score'], '')
        self.assertEqual(by_id[str(self.other_game.id)]['Score Status'], 'MISSING')

    def test_export_matches_table_for_all_supported_filters(self):
        self._score()
        queries = ['?published=published', '?published=unpublished', '?missing=true', '?flagged=true',
                   '?conflicts=true', '?status=PUBLISHED', '?status=MISSING', '?date=2026-05-02',
                   f'?division_id={self.division.id}', f'?host_location_id={self.host.id}',
                   f'?organization_id={self.home_org.id}', f'?organization_id={self.away_org.id}',
                   f'?week_id={self.week.id}', '?game_type=REGULAR_SEASON',
                   '?published=published&flagged=true&conflicts=true&date=2026-05-02']
        for query in queries:
            with self.subTest(query=query):
                table = self.client.get('/api/scores' + query, headers=self._token(self.league_user.id))
                self.assertEqual(table.status_code, 200, table.text)
                rows = self._rows(self._export(query))
                self.assertEqual([row['Game ID'] for row in rows], [row['game_id'] for row in table.json()['items']])

    def test_empty_export_has_headers_and_scheduler_access(self):
        response = self._export('?date=2026-01-01', self.scheduling_user)
        self.assertEqual(self._rows(response), [])
        self.assertIn('Home Score', response.text)

    def test_unauthorized_export_is_rejected(self):
        response = self._export(user=self.home_user)
        self.assertEqual(response.status_code, 403)
        response = self.client.get('/api/scores/export.csv')
        self.assertIn(response.status_code, {401, 403})
        response = self.client.get('/api/admin/scores/export.csv', headers=self._token(self.home_user.id))
        self.assertEqual(response.status_code, 403)

    def test_backend_failure_does_not_return_a_csv_download(self):
        with patch('app.routes.api._score_rows', side_effect=SQLAlchemyError('Database unavailable')):
            response = self._export()
        self.assertEqual(response.status_code, 500, response.text)
        self.assertNotIn('content-disposition', response.headers)
        self.assertEqual(response.json()['error'], 'database_error')

    def test_csv_escaping_and_formula_protection(self):
        self.home_team.name = 'Westosha, "Blue"\nTeam'
        self.away_team.name = '=SUM(1,2)'
        self.db.commit()
        rows = self._rows(self._export())
        row = next(row for row in rows if row['Game ID'] == str(self.game.id))
        self.assertEqual(row['Home Team'], 'Westosha, "Blue"\nTeam')
        self.assertEqual(row['Away Team'], "'=SUM(1,2)")
        self.assertEqual(self.db.query(GameScore).count(), 0)
