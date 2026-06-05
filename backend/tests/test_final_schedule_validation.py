import unittest
import uuid
from datetime import date, time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Division, FieldInstance, Game, GameSlot, GameStatus, HostLocation, HostingAvailability, Organization, Season, Team, TurfWave, Week
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

    def test_final_validation_excludes_non_regular_season_weeks_from_required_games(self):
        self._add_division_with_active_teams(4, 'Even')
        blackout_week = Week(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_number=2,
            start_date=date(2026, 9, 12),
            end_date=date(2026, 9, 18),
            primary_game_date=date(2026, 9, 12),
            date_type='BLACKOUT',
            status='active',
        )
        playoff_week = Week(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_number=3,
            start_date=date(2026, 9, 19),
            end_date=date(2026, 9, 25),
            primary_game_date=date(2026, 9, 19),
            date_type='PLAYOFF',
            status='active',
        )
        championship_week = Week(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_number=4,
            label='Championship',
            start_date=date(2026, 9, 26),
            end_date=date(2026, 10, 2),
            primary_game_date=date(2026, 9, 26),
            date_type='REGULAR_SEASON',
            status='active',
        )
        no_game_week = Week(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_number=5,
            start_date=date(2026, 10, 3),
            end_date=date(2026, 10, 9),
            primary_game_date=date(2026, 10, 3),
            date_type='REGULAR_SEASON',
            status='NO_GAMES',
        )
        self.db.add_all([blackout_week, playoff_week, championship_week, no_game_week])
        self.db.commit()

        result = _build_final_schedule_validation_result(self.db, self.season.id)

        self.assertEqual(result['required_games_expected_count'], 2)
        self.assertEqual(result['required_games_missing_count'], 2)
        missing_failure = next(
            failure for failure in result['final_validation_failures']
            if failure['code'] == 'REQUIRED_GAMES_MISSING'
        )
        self.assertEqual(len(missing_failure['details']), 1)
        self.assertEqual(missing_failure['details'][0]['week'], 1)
        diagnostics_by_week = {row['week']: row for row in result['regular_season_required_week_diagnostics']}
        self.assertTrue(diagnostics_by_week[1]['regular_season_required'])
        self.assertTrue(diagnostics_by_week[1]['required_games_calculated'])
        self.assertFalse(diagnostics_by_week[2]['regular_season_required'])
        self.assertEqual(diagnostics_by_week[2]['exclusion_reason'], 'BLACKOUT_WEEK')
        self.assertFalse(diagnostics_by_week[3]['regular_season_required'])
        self.assertEqual(diagnostics_by_week[3]['exclusion_reason'], 'PLAYOFF_WEEK')
        self.assertFalse(diagnostics_by_week[4]['regular_season_required'])
        self.assertEqual(diagnostics_by_week[4]['exclusion_reason'], 'CHAMPIONSHIP_WEEK')
        self.assertFalse(diagnostics_by_week[5]['regular_season_required'])
        self.assertEqual(diagnostics_by_week[5]['exclusion_reason'], 'NO_GAME_WEEK')


    def test_final_validation_blocks_empty_earlier_turf_wave_before_later_used_wave(self):
        division = Division(id=uuid.uuid4(), division_group='Test', name='Turf', required_field_layout_type='THIRTY_YARD_WIDTH', is_active=True)
        status = GameStatus(id=uuid.uuid4(), code='SCHEDULED', label='Scheduled', is_active=True)
        host = HostLocation(
            id=uuid.uuid4(),
            organization_id=self.org.id,
            name='Turf Host',
            surface_type='TURF_STADIUM',
            max_small_fields=1,
            max_total_fields=1,
            is_active=True,
        )
        availability = HostingAvailability(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            organization_id=self.org.id,
            host_location_id=host.id,
            available_date=date(2026, 9, 5),
            start_time=time(9, 0),
            end_time=time(13, 0),
            active=True,
            is_available=True,
        )
        self.db.add_all([division, status, host, availability])
        self.db.flush()
        teams = []
        for index in range(6):
            team = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=division.id, name=f'Turf Team {index + 1}', is_active=True)
            teams.append(team)
            self.db.add(team)
        waves = []
        slots = []
        for sequence, start in enumerate((time(9, 0), time(10, 0), time(11, 0), time(12, 0)), start=1):
            end = time(start.hour + 1, 0)
            wave = TurfWave(
                id=uuid.uuid4(),
                host_location_id=host.id,
                hosting_availability_id=availability.id,
                week_id=self.week.id,
                host_date=date(2026, 9, 5),
                sequence_number=sequence,
                wave_intent='AVAILABLE',
                preferred_layout_code='THREE_SMALL',
                start_time=start,
                end_time=end,
            )
            field_instance = FieldInstance(
                id=uuid.uuid4(),
                host_location_id=host.id,
                hosting_availability_id=availability.id,
                instance_date=date(2026, 9, 5),
                field_name=f'Wave {sequence} THREE_SMALL Small Field 1',
                field_type='SMALL',
                is_active=True,
                is_generated=True,
            )
            slot = GameSlot(
                id=uuid.uuid4(),
                field_instance_id=field_instance.id,
                host_location_id=host.id,
                season_id=self.season.id,
                week_id=self.week.id,
                slot_date=date(2026, 9, 5),
                start_time=start,
                end_time=end,
                field_type='SMALL',
                status='OPEN',
                turf_wave_id=wave.id,
            )
            waves.append(wave)
            slots.append(slot)
            self.db.add_all([wave, field_instance, slot])
        for game_index, slot_index in enumerate((0, 1, 3)):
            game = Game(
                id=uuid.uuid4(),
                season_id=self.season.id,
                week_id=self.week.id,
                home_team_id=teams[game_index * 2].id,
                away_team_id=teams[game_index * 2 + 1].id,
                host_location_id=host.id,
                field_instance_id=slots[slot_index].field_instance_id,
                game_status_id=status.id,
                game_date=date(2026, 9, 5),
                kickoff_time=slots[slot_index].start_time,
            )
            slots[slot_index].assigned_game_id = game.id
            slots[slot_index].status = 'BOOKED'
            self.db.add(game)
        self.db.commit()

        result = _build_final_schedule_validation_result(self.db, self.season.id)

        failure_codes = {failure['code'] for failure in result['final_validation_failures']}
        self.assertIn('TURF_WAVE_EARLIER_AVAILABLE_HOUR_SKIPPED', failure_codes)
        self.assertIn('TURF_WAVE_NON_CONTIGUOUS_USED_TIME', failure_codes)
        self.assertIn('TURF_WAVE_USED_LATER_WITH_EMPTY_EARLIER_WAVE', failure_codes)
        self.assertIn('TURF_WAVE_PULL_FORWARD_REQUIRED', failure_codes)
        self.assertGreater(result['turf_wave_earlier_available_hour_skipped_count'], 0)

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
