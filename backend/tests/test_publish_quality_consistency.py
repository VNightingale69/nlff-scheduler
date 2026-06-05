import unittest
import uuid
from datetime import date, time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Division, FieldInstance, Game, GameSlot, GameStatus, HostLocation, Organization, Season, Team, Week
from app.routes.api import _build_final_schedule_validation_result, _build_global_doubleheader_validation, _raise_if_single_doubleheader_manual_move, _run_generated_slot_integrity_validation_and_repair, _run_global_doubleheader_repair, build_schedule_quality_report, publish_schedule


class PublishQualityConsistencyTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        self.season = Season(id=uuid.uuid4(), name='Spring', start_date=date(2026, 4, 1), end_date=date(2026, 6, 1), is_active=True, schedule_status='draft')
        self.division = Division(id=uuid.uuid4(), name='5th Grade', required_field_layout_type='THIRTY_YARD_WIDTH', is_active=True)
        self.status = GameStatus(id=uuid.uuid4(), code='SCHEDULED', label='Scheduled', is_active=True)
        self.week = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=1, start_date=date(2026, 4, 5), end_date=date(2026, 4, 11))
        self.org = Organization(id=uuid.uuid4(), name='Org', is_active=True)
        self.team_a = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='A', is_active=True)
        self.team_b = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='B', is_active=True)
        self.db.add_all([self.season, self.division, self.status, self.week, self.org, self.team_a, self.team_b])
        self.db.add(Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            home_team_id=self.team_a.id,
            away_team_id=self.team_b.id,
            game_status_id=self.status.id,
            game_date=self.week.start_date,
            kickoff_time=time(10, 0),
        ))
        self.db.commit()


    def _add_scheduled_game_with_slot(self, home, away, kickoff, host, field_type='SMALL'):
        field_instance = FieldInstance(
            id=uuid.uuid4(),
            host_location_id=host.id,
            hosting_availability_id=uuid.uuid4(),
            instance_date=self.week.start_date,
            field_name=f'Field {kickoff.hour}',
            field_type=field_type,
            is_active=True,
        )
        game = Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            home_team_id=home.id,
            away_team_id=away.id,
            host_location_id=host.id,
            field_instance_id=field_instance.id,
            game_status_id=self.status.id,
            game_date=self.week.start_date,
            kickoff_time=kickoff,
        )
        slot = GameSlot(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            field_instance_id=field_instance.id,
            host_location_id=host.id,
            slot_date=self.week.start_date,
            start_time=kickoff,
            end_time=time(kickoff.hour + 1, kickoff.minute),
            field_type=field_type,
            status='ASSIGNED',
            assigned_game_id=game.id,
        )
        self.db.add_all([field_instance, game, slot])
        return game


    def _add_open_slot(self, kickoff, host, field_type='SMALL'):
        field_instance = FieldInstance(
            id=uuid.uuid4(),
            host_location_id=host.id,
            hosting_availability_id=uuid.uuid4(),
            instance_date=self.week.start_date,
            field_name=f'Open Field {kickoff.hour}',
            field_type=field_type,
            is_active=True,
        )
        slot = GameSlot(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            field_instance_id=field_instance.id,
            host_location_id=host.id,
            slot_date=self.week.start_date,
            start_time=kickoff,
            end_time=time(kickoff.hour + 1, kickoff.minute),
            field_type=field_type,
            status='OPEN',
            assigned_game_id=None,
        )
        self.db.add_all([field_instance, slot])
        return slot


    def test_generated_slot_integrity_repairs_orphaned_scheduled_game_to_open_slot(self):
        self.db.query(Game).delete()
        host = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Playable Host', is_active=True)
        self.db.add(host)
        orphan = Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            home_team_id=self.team_a.id,
            away_team_id=self.team_b.id,
            game_status_id=self.status.id,
            game_date=self.week.start_date,
            kickoff_time=time(10, 0),
        )
        self.db.add(orphan)
        self._add_open_slot(time(10, 0), host, field_type='SMALL')
        self.db.commit()

        diagnostics = _run_generated_slot_integrity_validation_and_repair(self.db, self.season.id)
        self.db.refresh(orphan)

        self.assertEqual(diagnostics['invalid_scheduled_game_count'], 1)
        self.assertEqual(diagnostics['repaired_scheduled_game_count'], 1)
        self.assertEqual(diagnostics['generated_slot_integrity_failure_count'], 0)
        self.assertEqual(orphan.host_location_id, host.id)
        self.assertIsNotNone(orphan.field_instance_id)

    def test_generated_slot_integrity_unschedules_orphan_when_no_repair_exists(self):
        self.db.query(GameSlot).delete()
        self.db.query(FieldInstance).delete()
        self.db.query(Game).delete()
        unscheduled = GameStatus(id=uuid.uuid4(), code='UNSCHEDULED', label='Unscheduled', is_active=True)
        self.db.add(unscheduled)
        orphan = Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            home_team_id=self.team_a.id,
            away_team_id=self.team_b.id,
            game_status_id=self.status.id,
            game_date=self.week.start_date,
            kickoff_time=time(10, 0),
        )
        self.db.add(orphan)
        self.db.commit()

        diagnostics = _run_generated_slot_integrity_validation_and_repair(self.db, self.season.id)
        self.db.refresh(orphan)
        validation = _build_final_schedule_validation_result(self.db, self.season.id)

        self.assertEqual(diagnostics['unscheduled_orphan_game_count'], 1)
        self.assertEqual(orphan.game_status_id, unscheduled.id)
        self.assertEqual(validation['generated_slot_integrity_failure_count'], 0)
        self.assertGreater(validation['required_games_missing_count'], 0)

    def test_global_doubleheader_repair_moves_split_pair_to_same_location_adjacent_open_slot(self):
        self.db.query(Game).delete()
        host_a = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Host A', is_active=True)
        host_b = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Host B', is_active=True)
        team_c = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='C', is_active=True)
        self.db.add_all([host_a, host_b, team_c])
        first = self._add_scheduled_game_with_slot(self.team_a, self.team_b, time(9, 0), host_a)
        second = self._add_scheduled_game_with_slot(self.team_a, team_c, time(11, 0), host_b)
        self._add_open_slot(time(10, 0), host_a)
        self.db.commit()

        diagnostics = _run_global_doubleheader_repair(self.db, self.season.id)
        self.db.commit()
        validation = _build_global_doubleheader_validation(self.db, self.season.id)
        self.db.refresh(second)

        self.assertTrue(diagnostics['doubleheader_repair_ran'])
        self.assertEqual(diagnostics['doubleheader_repair_status'], 'SUCCEEDED')
        self.assertEqual(diagnostics['invalid_doubleheaders_detected_count'], 1)
        self.assertEqual(diagnostics['doubleheader_repair_success_count'], 1)
        self.assertEqual(validation['doubleheader_not_back_to_back_count'], 0)
        self.assertEqual(validation['doubleheader_split_location_count'], 0)
        self.assertEqual(second.host_location_id, host_a.id)
        self.assertEqual(second.kickoff_time, time(10, 0))
        pair = validation['doubleheader_pairs'][0]
        self.assertTrue(pair['same_location'])
        self.assertTrue(pair['back_to_back'])
        self.assertTrue(pair['pair_valid'])

    def test_global_doubleheader_repair_reports_too_many_games_as_unresolvable(self):
        self.db.query(Game).delete()
        host = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Host A', is_active=True)
        team_c = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='C', is_active=True)
        team_d = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='D', is_active=True)
        self.db.add_all([host, team_c, team_d])
        self._add_scheduled_game_with_slot(self.team_a, self.team_b, time(9, 0), host)
        self._add_scheduled_game_with_slot(self.team_a, team_c, time(10, 0), host)
        self._add_scheduled_game_with_slot(self.team_a, team_d, time(11, 0), host)
        self.db.commit()

        diagnostics = _run_global_doubleheader_repair(self.db, self.season.id)

        self.assertEqual(diagnostics['doubleheader_repair_status'], 'FAILED_UNREPAIRABLE')
        self.assertEqual(diagnostics['invalid_doubleheaders_detected_count'], 1)
        self.assertGreaterEqual(diagnostics['doubleheader_repair_failure_count'], 1)
        self.assertTrue(any(row.get('code') == 'DOUBLEHEADER_TOO_MANY_GAMES_FOR_TEAM_DIVISION_DATE' for row in diagnostics['doubleheader_repair_failures']))

    def test_quality_report_uses_global_doubleheader_validation_counts(self):
        self.db.query(Game).delete()
        host_a = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Host A', is_active=True)
        host_b = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Host B', is_active=True)
        team_c = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='C', is_active=True)
        team_d = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='D', is_active=True)
        self.db.add_all([host_a, host_b, team_c, team_d])
        self._add_scheduled_game_with_slot(self.team_a, self.team_b, time(9, 0), host_a)
        self._add_scheduled_game_with_slot(self.team_a, team_c, time(11, 0), host_b)
        self.db.commit()

        report = build_schedule_quality_report(self.db, self.season.id)

        self.assertEqual(report['metrics']['doubleheader_not_back_to_back_count'], 1)
        self.assertEqual(report['metrics']['doubleheader_split_location_count'], 1)
        self.assertTrue(any(error['code'] == 'non_back_to_back_double_headers' for error in report['hard_errors']))
        self.assertTrue(any(error['code'] == 'split_location_double_headers' for error in report['hard_errors']))

    def test_global_doubleheader_validation_detects_away_team_participation_and_required_diagnostics(self):
        self.db.query(Game).delete()
        host_a = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Host A', is_active=True)
        host_b = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Host B', is_active=True)
        team_c = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='C', is_active=True)
        self.db.add_all([host_a, host_b, team_c])
        first = self._add_scheduled_game_with_slot(self.team_b, self.team_a, time(9, 0), host_a)
        second = self._add_scheduled_game_with_slot(team_c, self.team_a, time(11, 0), host_b)
        self.db.commit()

        validation = _build_global_doubleheader_validation(self.db, self.season.id)

        self.assertEqual(validation['doubleheader_not_back_to_back_count'], 1)
        self.assertEqual(validation['doubleheader_split_location_count'], 1)
        pair = validation['doubleheader_pairs'][0]
        self.assertTrue(pair['inferred_pair'])
        self.assertEqual(pair['team_id'], str(self.team_a.id))
        self.assertEqual(pair['team_name'], self.team_a.name)
        self.assertEqual(pair['division_id'], str(self.division.id))
        self.assertEqual(pair['division_name'], self.division.name)
        self.assertEqual(pair['game_date'], self.week.start_date.isoformat())
        self.assertEqual(pair['game_1_id'], str(first.id))
        self.assertEqual(pair['game_2_id'], str(second.id))
        self.assertFalse(pair['same_location'])
        self.assertFalse(pair['back_to_back'])
        self.assertTrue(pair['compatible_field_type'])
        self.assertTrue(pair['selected_host_compliant'])
        self.assertFalse(pair['pair_valid'])
        self.assertIn('DOUBLEHEADER_SPLIT_LOCATION', pair['validation_failure_reasons'])
        self.assertIn('DOUBLEHEADER_NOT_BACK_TO_BACK', pair['validation_failure_reasons'])

    def test_manual_single_game_move_rejects_any_inferred_doubleheader_pair_member(self):
        self.db.query(Game).delete()
        host = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Host A', is_active=True)
        team_c = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='C', is_active=True)
        self.db.add_all([host, team_c])
        first = self._add_scheduled_game_with_slot(self.team_b, self.team_a, time(9, 0), host)
        self._add_scheduled_game_with_slot(team_c, self.team_a, time(10, 0), host)
        self.db.commit()

        with self.assertRaises(Exception) as ctx:
            _raise_if_single_doubleheader_manual_move(self.db, first, action_source='unit-test')

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail['error'], 'DOUBLEHEADER_PAIR_SPLIT_MOVE_REJECTED')

    def test_publish_uses_same_quality_report_source(self):
        report = build_schedule_quality_report(self.db, self.season.id)
        self.assertEqual(report['overall_health'], 'Excellent')
        self.assertEqual(report['hard_errors'], [])
        self.assertEqual(report['metrics']['conflicts'], 0)
        response = publish_schedule(self.season.id, db=self.db)
        self.assertTrue(response['ok'])
        self.assertEqual(response['overall_health'], 'Excellent')

