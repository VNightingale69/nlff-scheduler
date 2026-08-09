import unittest
import uuid

from app.routes.api import _publish_validation_issue_summary


class PublishValidationGameLabelTest(unittest.TestCase):
    def setUp(self):
        self.game_id = str(uuid.uuid4())
        self.lookup = {
            self.game_id: {
                'home_team_name': 'Antioch Girls 6-8',
                'away_team_name': 'Westosha Girls 6-8 Maroon',
                'scheduled_game_display_name': 'Antioch Girls 6-8 vs Westosha Girls 6-8 Maroon',
            }
        }

    def _summary(self, code):
        return _publish_validation_issue_summary(
            {'failure_code': code, 'scheduled_game_id': self.game_id},
            code,
            self.lookup,
        )

    def test_validation_row_displays_matchup_and_retains_scheduled_game_id(self):
        result = self._summary('VALIDATION_FAILURE')

        self.assertEqual(result['scheduled_game_display_name'], 'Antioch Girls 6-8 vs Westosha Girls 6-8 Maroon')
        self.assertNotEqual(result['scheduled_game_display_name'], self.game_id)
        self.assertEqual(result['scheduled_game_id'], self.game_id)

    def test_field_type_mismatch_displays_actual_matchup(self):
        self.assertEqual(self._summary('FIELD_TYPE_MISMATCH')['scheduled_game_display_name'], self.lookup[self.game_id]['scheduled_game_display_name'])

    def test_missing_field_displays_actual_matchup(self):
        self.assertEqual(self._summary('SCHEDULED_GAME_MISSING_FIELD')['scheduled_game_display_name'], self.lookup[self.game_id]['scheduled_game_display_name'])

    def test_doubleheader_detail_with_specific_game_displays_matchup(self):
        self.assertEqual(self._summary('DOUBLEHEADER_FIELD_TYPE_MISMATCH')['scheduled_game_display_name'], self.lookup[self.game_id]['scheduled_game_display_name'])

    def test_doubleheader_pair_without_single_game_displays_multiple_games(self):
        result = _publish_validation_issue_summary(
            {'game_1_id': str(uuid.uuid4()), 'game_2_id': str(uuid.uuid4())},
            'DOUBLEHEADER_SPLIT_LOCATION',
            self.lookup,
        )
        self.assertEqual(result['scheduled_game_display_name'], 'Multiple games')

    def test_schedule_level_diagnostic_has_nontechnical_label(self):
        result = _publish_validation_issue_summary({'code': 'SCHEDULE_SOURCE_MISMATCH'}, 'SCHEDULE_SOURCE_MISMATCH', self.lookup)
        self.assertEqual(result['scheduled_game_display_name'], 'Schedule-level check')


if __name__ == '__main__':
    unittest.main()
