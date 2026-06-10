import ast
import re
import unittest
from pathlib import Path


STANDINGS_PAGE = Path(__file__).resolve().parents[2] / 'frontend/src/app/(dashboard)/admin/standings/page.tsx'


class ResultsStandingsFrontendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = STANDINGS_PAGE.read_text()
        match = re.search(r"const standingsHeaders = (\[[^\n]+\]);", cls.source)
        if not match:
            raise AssertionError('standingsHeaders constant not found')
        cls.standings_headers = ast.literal_eval(match.group(1))
        table_match = re.search(
            r"<tbody>\{division\.standings\.map\(\(row\) => <tr.*?</tr>\)\}</tbody>",
            cls.source,
            flags=re.DOTALL,
        )
        if not table_match:
            raise AssertionError('standings table body not found')
        cls.standings_row_markup = table_match.group(0)

    def test_standings_headers_hide_removed_columns(self):
        for removed_header in ['PF', 'PA', 'Diff', 'Win %', 'Last Updated']:
            self.assertNotIn(removed_header, self.standings_headers)

    def test_standings_headers_keep_required_columns(self):
        for required_header in ['W', 'L', 'T', 'GP', 'Scheduled', 'Remaining']:
            self.assertIn(required_header, self.standings_headers)

    def test_standings_rows_hide_removed_display_fields(self):
        for removed_field in ['points_for', 'points_against', 'point_differential', 'win_percentage', 'last_updated']:
            self.assertNotIn(f'row.{removed_field}', self.standings_row_markup)

    def test_standings_header_and_row_cell_counts_match(self):
        rendered_cell_count = self.standings_row_markup.count("<td className='p-2")
        self.assertEqual(rendered_cell_count, len(self.standings_headers))

    def test_game_results_table_keeps_score_columns(self):
        self.assertIn('Home Score', self.source)
        self.assertIn('Away Score', self.source)


if __name__ == '__main__':
    unittest.main()
