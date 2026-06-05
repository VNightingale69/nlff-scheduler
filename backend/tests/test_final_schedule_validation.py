import unittest
import uuid
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Division, Organization, Season, Team, Week
from app.routes.api import _build_final_schedule_validation_result, _division_required_games


class FinalScheduleValidationTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        self.season = Season(
            id=uuid.uuid4(),
            name='Fall',
            start_date=date(2026, 9, 1),
            end_date=date(2026, 11, 1),
            is_active=True,
        )
        self.week = Week(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_number=1,
            start_date=date(2026, 9, 5),
            end_date=date(2026, 9, 11),
        )
        self.org = Organization(id=uuid.uuid4(), name='Org', is_active=True)
        self.db.add_all([self.season, self.week, self.org])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _add_division_with_active_teams(self, team_count: int, name: str) -> Division:
        division = Division(id=uuid.uuid4(), division_group='Test', name=name, required_field_layout_type='THIRTY_YARD_WIDTH', is_active=True)
        self.db.add(division)
        self.db.flush()
        for index in range(team_count):
            self.db.add(Team(
                id=uuid.uuid4(),
                organization_id=self.org.id,
                division_id=division.id,
                name=f'{name} Team {index + 1}',
                is_active=True,
            ))
        self.db.commit()
        return division

    def test_division_required_games_uses_global_active_team_count_calculation(self):
        self.assertEqual(_division_required_games(4), 2)
        self.assertEqual(_division_required_games(7), 4)
        self.assertEqual(_division_required_games(1), 0)
        self.assertEqual(_division_required_games(0), 0)
        self.assertEqual(_division_required_games(None), 0)

    def test_final_validation_counts_even_and_odd_required_games_without_crashing(self):
        self._add_division_with_active_teams(4, 'Even')
        self._add_division_with_active_teams(7, 'Odd')
        self._add_division_with_active_teams(1, 'Single')
        self._add_division_with_active_teams(0, 'Empty')

        result = _build_final_schedule_validation_result(self.db, self.season.id)

        self.assertTrue(result['final_validation_ran'])
        self.assertEqual(result['final_validation_status'], 'PARTIAL_SUCCESS')
        self.assertIsNone(result['diagnostics_error'])
        self.assertEqual(result['required_games_missing_count'], 6)
        missing_failure = next(
            failure for failure in result['final_validation_failures']
            if failure['code'] == 'REQUIRED_GAMES_MISSING'
        )
        required_games_by_division = {
            row['division']: row['required_games']
            for row in missing_failure['details']
        }
        self.assertEqual(required_games_by_division['Test Even'], 2)
        self.assertEqual(required_games_by_division['Test Odd'], 4)
        self.assertNotIn('Test Single', required_games_by_division)
        self.assertNotIn('Test Empty', required_games_by_division)

    def test_final_validation_reports_error_status_for_diagnostics_errors(self):
        result = _build_final_schedule_validation_result(
            self.db,
            self.season.id,
            diagnostics_error='diagnostics unavailable',
        )

        self.assertTrue(result['final_validation_ran'])
        self.assertEqual(result['final_validation_status'], 'ERROR')
        self.assertEqual(result['schedule_quality_status'], 'ERROR')
        self.assertEqual(result['diagnostics_status'], 'ERROR')
        self.assertEqual(result['diagnostics_error'], 'diagnostics unavailable')


if __name__ == '__main__':
    unittest.main()
