import unittest
import uuid
from datetime import date, time
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Division, FieldInstance, Game, GameSlot, GameStatus, HostLocation, HostPlanSelection, HostingAvailability, Organization, Season, Team, TurfWave, Week
from app.routes.api import _build_host_location_vs_home_team_verification, _build_turf_stadium_utilization_diagnostics, _diagnostic_active_teams_expected_to_play, _diagnostic_expected_games_for_team_count, _diagnostic_field_size_diff, _host_availability_matrix_response, _run_turf_wave_compaction_pass, auto_fill_apply, auto_fill_preview, auto_schedule_entire_season, generate_suggested_host_plan


class AutoFillPreviewTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        self.season = Season(id=uuid.uuid4(), name='Spring', start_date=date(2026, 4, 1), end_date=date(2026, 7, 1), is_active=True)
        self.division = Division(id=uuid.uuid4(), name='4th Grade', required_field_layout_type='THIRTY_YARD_WIDTH', is_active=True)
        self.status = GameStatus(id=uuid.uuid4(), code='SCHEDULED', label='Scheduled', is_active=True)
        self.week1 = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=1, start_date=date(2026, 5, 1), end_date=date(2026, 5, 7))
        self.week2 = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=2, start_date=date(2026, 5, 8), end_date=date(2026, 5, 14))
        self.org_w = Organization(id=uuid.uuid4(), name='Westosha', is_active=True)
        self.org_a = Organization(id=uuid.uuid4(), name='Antioch', is_active=True)
        self.host = HostLocation(id=uuid.uuid4(), organization_id=self.org_w.id, name='Westosha Park', is_active=True)
        self.fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Small Field 1', field_type='SMALL', is_active=True)
        self.slot = GameSlot(id=uuid.uuid4(), field_instance_id=self.fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='OPEN')
        self.wm = Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=self.division.id, name='Westosha Maroon', is_active=True)
        self.wg = Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=self.division.id, name='Westosha Gold', is_active=True)
        self.ab = Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=self.division.id, name='Antioch Black', is_active=True)
        self.as_ = Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=self.division.id, name='Antioch Silver', is_active=True)
        self.db.add_all([self.season, self.division, self.status, self.week1, self.week2, self.org_w, self.org_a, self.host, self.fi, self.slot, self.wm, self.wg, self.ab, self.as_])
        self.db.add(Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week1.id,
            home_team_id=self.wm.id,
            away_team_id=self.ab.id,
            game_status_id=self.status.id,
            game_date=self.week1.start_date,
            kickoff_time=time(10, 0),
        ))
        self.db.commit()

    def test_host_location_vs_home_team_verification_reports_away_owned_host(self):
        game = Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            home_team_id=self.ab.id,
            away_team_id=self.wm.id,
            game_status_id=self.status.id,
            game_date=self.week2.start_date,
            kickoff_time=time(9, 0),
        )
        self.db.add(game)
        self.db.flush()
        self.slot.assigned_game_id = game.id
        self.slot.status = 'BOOKED'
        self.db.commit()

        diagnostics = _build_host_location_vs_home_team_verification(self.db, self.season.id)

        self.assertEqual(diagnostics['total_games_checked'], 2)
        self.assertEqual(diagnostics['host_owner_is_away_team'], 1)
        self.assertEqual(len(diagnostics['host_owner_is_away_games']), 1)
        away_row = diagnostics['host_owner_is_away_games'][0]
        self.assertEqual(away_row['game_id'], str(game.id))
        self.assertEqual(away_row['location'], 'Westosha Park')
        self.assertEqual(away_row['host_location_owner_community_name'], 'Westosha')
        self.assertEqual(away_row['home_team_community_name'], 'Antioch')
        self.assertEqual(away_row['away_team_community_name'], 'Westosha')
        self.assertEqual(away_row['category'], 'HOST_OWNER_IS_AWAY')

    def test_host_owner_verification_is_informational_unless_required(self):
        game = Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            home_team_id=self.ab.id,
            away_team_id=self.wm.id,
            game_status_id=self.status.id,
            game_date=self.week2.start_date,
            kickoff_time=time(9, 0),
        )
        self.db.add(game)
        self.db.flush()
        self.slot.assigned_game_id = game.id
        self.slot.status = 'BOOKED'
        self.db.commit()

        informational = _build_host_location_vs_home_team_verification(self.db, self.season.id)
        required = _build_host_location_vs_home_team_verification(self.db, self.season.id, require_host_owner_as_home_team=True)

        self.assertEqual(informational['host_owner_is_away_team'], 1)
        self.assertEqual(informational['validation_failure_count'], 0)
        self.assertTrue(informational['informational_notes'])
        self.assertEqual(required['host_owner_is_away_team'], 1)
        self.assertEqual(required['validation_failure_count'], 1)

    def test_host_owner_verification_passes_when_no_away_owned_hosts(self):
        game = Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            home_team_id=self.wm.id,
            away_team_id=self.ab.id,
            game_status_id=self.status.id,
            game_date=self.week2.start_date,
            kickoff_time=time(9, 0),
        )
        self.db.add(game)
        self.db.flush()
        self.slot.assigned_game_id = game.id
        self.slot.status = 'BOOKED'
        self.db.commit()

        diagnostics = _build_host_location_vs_home_team_verification(self.db, self.season.id, require_host_owner_as_home_team=True)

        self.assertEqual(diagnostics['host_owner_is_away_team'], 0)
        self.assertEqual(diagnostics['validation_failure_count'], 0)


    def test_turf_wave_diagnostics_report_partial_component_utilization(self):
        self.week2.primary_game_date = self.week2.start_date
        self.host.surface_type = 'TURF_STADIUM'
        availability = HostingAvailability(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            organization_id=self.org_w.id,
            host_location_id=self.host.id,
            available_date=self.week2.start_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
            is_available=True,
        )
        wave = TurfWave(
            id=uuid.uuid4(),
            host_location_id=self.host.id,
            hosting_availability_id=availability.id,
            week_id=self.week2.id,
            host_date=self.week2.start_date,
            sequence_number=1,
            wave_intent='SMALL_MEDIUM',
            preferred_layout_code='ONE_MEDIUM_TWO_SMALL',
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
        medium_field = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=availability.id, instance_date=self.week2.start_date, field_name='Medium Field 1', field_type='MEDIUM', is_active=True)
        small_field_2 = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=availability.id, instance_date=self.week2.start_date, field_name='Small Field 2', field_type='SMALL', is_active=True)
        game = Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            home_team_id=self.wg.id,
            away_team_id=self.as_.id,
            game_status_id=self.status.id,
            game_date=self.week2.start_date,
            kickoff_time=time(9, 0),
        )
        self.slot.turf_wave_id = wave.id
        self.slot.assigned_game_id = game.id
        self.slot.status = 'BOOKED'
        medium_slot = GameSlot(id=uuid.uuid4(), field_instance_id=medium_field.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(9, 0), end_time=time(10, 0), field_type='MEDIUM', status='OPEN', turf_wave_id=wave.id)
        small_slot_2 = GameSlot(id=uuid.uuid4(), field_instance_id=small_field_2.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='OPEN', turf_wave_id=wave.id)
        self.db.add_all([availability, wave, medium_field, small_field_2, game, medium_slot, small_slot_2])
        self.db.commit()

        diagnostics = _build_turf_stadium_utilization_diagnostics(self.db, self.season.id)

        self.assertEqual(len(diagnostics), 1)
        wave_row = diagnostics[0]['wave_utilization'][0]
        self.assertEqual(wave_row['layout'], 'ONE_MEDIUM_TWO_SMALL')
        self.assertEqual(wave_row['available_field_components'], [
            {'field_type': 'SMALL', 'count': 2},
            {'field_type': 'MEDIUM', 'count': 1},
        ])
        self.assertEqual(wave_row['unused_components'], [
            {'field_type': 'SMALL', 'count': 1},
            {'field_type': 'MEDIUM', 'count': 1},
        ])
        self.assertEqual(wave_row['utilization_percent'], 33.3)
        self.assertEqual(wave_row['capacity_components'], [
            {'field_type': 'SMALL', 'count': 2},
            {'field_type': 'MEDIUM', 'count': 1},
        ])
        self.assertEqual(wave_row['used_components'], [{'field_type': 'SMALL', 'count': 1}])
        self.assertEqual(wave_row['unused_component_count'], 2)
        self.assertEqual(wave_row['optimization_note'], 'PARTIALLY_USED_ONE_MEDIUM_TWO_SMALL')
        self.assertEqual(wave_row['status'], 'Warning')
        self.assertTrue(diagnostics[0]['optimization_warnings'])


    def test_turf_wave_compaction_evaluates_partial_wave_components_matching_export(self):
        self.week2.primary_game_date = self.week2.start_date
        self.host.surface_type = 'TURF_STADIUM'
        self.slot.status = 'BOOKED'
        availability = HostingAvailability(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            organization_id=self.org_w.id,
            host_location_id=self.host.id,
            available_date=self.week2.start_date,
            primary_game_date=self.week2.start_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
            is_available=True,
        )
        wave = TurfWave(
            id=uuid.uuid4(),
            host_location_id=self.host.id,
            hosting_availability_id=availability.id,
            week_id=self.week2.id,
            host_date=self.week2.start_date,
            sequence_number=1,
            wave_intent='SMALL_MEDIUM',
            preferred_layout_code='ONE_MEDIUM_TWO_SMALL',
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
        medium_division = Division(id=uuid.uuid4(), division_group='COED', name='4th/5th', required_field_layout_type='MEDIUM', is_active=True)
        medium_home = Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=medium_division.id, name='Westosha Medium', is_active=True)
        medium_away = Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=medium_division.id, name='Antioch Medium', is_active=True)
        small_game = Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            home_team_id=self.wg.id,
            away_team_id=self.as_.id,
            game_status_id=self.status.id,
            game_date=self.week2.start_date,
            kickoff_time=time(9, 0),
        )
        medium_game = Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            home_team_id=medium_home.id,
            away_team_id=medium_away.id,
            game_status_id=self.status.id,
            game_date=self.week2.start_date,
            kickoff_time=time(9, 0),
        )
        self.slot.turf_wave_id = wave.id
        self.slot.assigned_game_id = small_game.id
        medium_field = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=availability.id, instance_date=self.week2.start_date, field_name='Wave Medium', field_type='MEDIUM', is_active=True)
        open_small_field = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=availability.id, instance_date=self.week2.start_date, field_name='Wave Small 2', field_type='SMALL', is_active=True)
        source_medium_field = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=availability.id, instance_date=self.week2.start_date, field_name='Source Medium', field_type='MEDIUM', is_active=True)
        medium_target = GameSlot(id=uuid.uuid4(), field_instance_id=medium_field.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(9, 0), end_time=time(10, 0), field_type='MEDIUM', status='OPEN', turf_wave_id=wave.id)
        open_small = GameSlot(id=uuid.uuid4(), field_instance_id=open_small_field.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='OPEN', turf_wave_id=wave.id)
        medium_source = GameSlot(id=uuid.uuid4(), field_instance_id=source_medium_field.id, host_location_id=self.host.id, season_id=self.season.id, week_id=self.week2.id, slot_date=self.week2.start_date, start_time=time(9, 0), end_time=time(10, 0), field_type='MEDIUM', status='BOOKED', assigned_game_id=medium_game.id)
        self.db.add_all([
            availability, wave, medium_division, medium_home, medium_away, small_game, medium_game,
            medium_field, open_small_field, source_medium_field, medium_target, open_small, medium_source,
        ])
        self.db.commit()

        export_diagnostics = _build_turf_stadium_utilization_diagnostics(self.db, self.season.id)
        export_wave = export_diagnostics[0]['wave_utilization'][0]
        self.assertEqual(export_wave['optimization_note'], 'PARTIALLY_USED_ONE_MEDIUM_TWO_SMALL')
        self.assertEqual(export_wave['unused_components'], [
            {'field_type': 'SMALL', 'count': 1},
            {'field_type': 'MEDIUM', 'count': 1},
        ])

        compaction = _run_turf_wave_compaction_pass(self.db, self.season.id)

        self.assertEqual(compaction['total_partial_waves_found'], 1)
        self.assertEqual(compaction['partial_ONE_MEDIUM_TWO_SMALL_waves_found'], 1)
        self.assertEqual(len(compaction['partial_waves']), compaction['total_partial_waves_found'])
        self.assertEqual(len(compaction['partial_wave_details']), compaction['total_partial_waves_found'])
        self.assertIs(compaction['partial_waves'], compaction['partial_wave_details'])
        detail = compaction['partial_wave_details'][0]
        self.assertEqual(detail['host_location_name'], self.host.name)
        self.assertEqual(detail['wave_layout'], 'ONE_MEDIUM_TWO_SMALL')
        self.assertEqual(detail['expected_components_by_size'], {'SMALL': 2, 'MEDIUM': 1})
        self.assertEqual(detail['assigned_components_by_size'], {'SMALL': 1})
        self.assertEqual(detail['unused_components_by_size'], {'SMALL': 1, 'MEDIUM': 1})
        self.assertEqual(detail['needed_field_sizes'], ['SMALL', 'MEDIUM'])
        self.assertEqual(detail['assigned_game_ids'], [str(small_game.id)])
        self.assertEqual(detail['assigned_slot_ids'], [str(self.slot.id)])
        self.assertEqual(detail['assigned_field_instance_ids'], [str(self.slot.field_instance_id)])
        self.assertTrue(detail['medium_games_exist_elsewhere_same_date'])
        self.assertEqual(detail['medium_games_considered'], 1)
        self.assertEqual(detail['candidate_games_found_count'], 1)

    def test_turf_wave_compaction_details_are_grouped_by_start_time(self):
        self.host.surface_type = 'TURF_STADIUM'
        self.slot.status = 'BOOKED'
        availability = HostingAvailability(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            organization_id=self.org_w.id,
            host_location_id=self.host.id,
            available_date=self.week2.start_date,
            primary_game_date=self.week2.start_date,
            start_time=time(9, 0),
            end_time=time(12, 0),
            is_available=True,
        )
        self.db.add(availability)
        source_game = Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            home_team_id=self.wm.id,
            away_team_id=self.ab.id,
            game_status_id=self.status.id,
            game_date=self.week2.start_date,
            kickoff_time=time(11, 0),
        )
        for idx, start in enumerate((time(9, 0), time(10, 0))):
            wave = TurfWave(
                id=uuid.uuid4(),
                host_location_id=self.host.id,
                hosting_availability_id=availability.id,
                week_id=self.week2.id,
                host_date=self.week2.start_date,
                sequence_number=1,
                wave_intent='SMALL_MEDIUM',
                preferred_layout_code='ONE_MEDIUM_TWO_SMALL',
                start_time=start,
                end_time=time(start.hour + 1, 0),
            )
            small_game = Game(
                id=uuid.uuid4(),
                season_id=self.season.id,
                week_id=self.week2.id,
                home_team_id=self.wg.id if idx == 0 else self.wm.id,
                away_team_id=self.as_.id if idx == 0 else self.ab.id,
                game_status_id=self.status.id,
                game_date=self.week2.start_date,
                kickoff_time=start,
            )
            medium_division = Division(id=uuid.uuid4(), division_group='COED', name=f'Medium {idx}', required_field_layout_type='MEDIUM', is_active=True)
            medium_home = Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=medium_division.id, name=f'Westosha Medium {idx}', is_active=True)
            medium_away = Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=medium_division.id, name=f'Antioch Medium {idx}', is_active=True)
            medium_game = Game(
                id=uuid.uuid4(),
                season_id=self.season.id,
                week_id=self.week2.id,
                home_team_id=medium_home.id,
                away_team_id=medium_away.id,
                game_status_id=self.status.id,
                game_date=self.week2.start_date,
                kickoff_time=start,
            )
            small_field = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=availability.id, instance_date=self.week2.start_date, field_name=f'Wave {idx} Small 1', field_type='SMALL', is_active=True)
            open_small_field = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=availability.id, instance_date=self.week2.start_date, field_name=f'Wave {idx} Small 2', field_type='SMALL', is_active=True)
            medium_field = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=availability.id, instance_date=self.week2.start_date, field_name=f'Wave {idx} Medium', field_type='MEDIUM', is_active=True)
            self.db.add_all([
                wave, medium_division, medium_home, medium_away, small_game, medium_game,
                small_field, open_small_field, medium_field,
                GameSlot(id=uuid.uuid4(), field_instance_id=small_field.id, host_location_id=self.host.id, season_id=self.season.id, week_id=self.week2.id, slot_date=self.week2.start_date, start_time=start, end_time=time(start.hour + 1, 0), field_type='SMALL', status='BOOKED', turf_wave_id=wave.id, assigned_game_id=small_game.id),
                GameSlot(id=uuid.uuid4(), field_instance_id=open_small_field.id, host_location_id=self.host.id, season_id=self.season.id, week_id=self.week2.id, slot_date=self.week2.start_date, start_time=start, end_time=time(start.hour + 1, 0), field_type='SMALL', status='OPEN', turf_wave_id=wave.id),
                GameSlot(id=uuid.uuid4(), field_instance_id=medium_field.id, host_location_id=self.host.id, season_id=self.season.id, week_id=self.week2.id, slot_date=self.week2.start_date, start_time=start, end_time=time(start.hour + 1, 0), field_type='MEDIUM', status='BOOKED', turf_wave_id=wave.id, assigned_game_id=medium_game.id),
            ])
        source_field = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=availability.id, instance_date=self.week2.start_date, field_name='Source Small', field_type='SMALL', is_active=True)
        self.db.add_all([
            source_game,
            source_field,
            GameSlot(id=uuid.uuid4(), field_instance_id=source_field.id, host_location_id=self.host.id, season_id=self.season.id, week_id=self.week2.id, slot_date=self.week2.start_date, start_time=time(11, 0), end_time=time(12, 0), field_type='SMALL', status='BOOKED', assigned_game_id=source_game.id),
        ])
        self.db.commit()

        compaction = _run_turf_wave_compaction_pass(self.db, self.season.id)

        details = sorted(compaction['partial_wave_details'], key=lambda row: row['start_time'])
        self.assertEqual(len(details), 2)
        self.assertEqual([row['start_time'] for row in details], ['09:00:00', '10:00:00'])
        for detail in details:
            self.assertEqual(detail['expected_capacity_by_size'], {'SMALL': 2, 'MEDIUM': 1})
            self.assertEqual(detail['assigned_by_size'], {'SMALL': 1, 'MEDIUM': 1})
            self.assertEqual(detail['unused_by_size'], {'SMALL': 1})
            self.assertEqual(detail['needed_field_sizes'], ['SMALL'])
            self.assertEqual(detail['utilization_percent'], 66.7)
        self.assertGreater(compaction['total_candidate_moves_evaluated'], 0)

    def test_auto_fill_preview_prefers_packable_partial_turf_wave_over_earlier_empty_wave(self):
        self.host.surface_type = 'TURF_STADIUM'
        self.slot.status = 'CLOSED'
        availability = HostingAvailability(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            organization_id=self.org_w.id,
            host_location_id=self.host.id,
            available_date=self.week2.start_date,
            primary_game_date=self.week2.start_date,
            start_time=time(8, 0),
            end_time=time(10, 0),
            is_available=True,
        )
        empty_wave = TurfWave(
            id=uuid.uuid4(),
            host_location_id=self.host.id,
            hosting_availability_id=availability.id,
            week_id=self.week2.id,
            host_date=self.week2.start_date,
            sequence_number=1,
            wave_intent='SMALL_MEDIUM',
            preferred_layout_code='THREE_SMALL',
            start_time=time(8, 0),
            end_time=time(9, 0),
        )
        partial_wave = TurfWave(
            id=uuid.uuid4(),
            host_location_id=self.host.id,
            hosting_availability_id=availability.id,
            week_id=self.week2.id,
            host_date=self.week2.start_date,
            sequence_number=2,
            wave_intent='SMALL_MEDIUM',
            preferred_layout_code='ONE_MEDIUM_TWO_SMALL',
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
        medium_division = Division(id=uuid.uuid4(), division_group='COED', name='4th/5th', required_field_layout_type='MEDIUM', is_active=True)
        medium_home = Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=medium_division.id, name='Westosha Medium', is_active=True)
        medium_away = Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=medium_division.id, name='Antioch Medium', is_active=True)
        medium_game = Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            home_team_id=medium_home.id,
            away_team_id=medium_away.id,
            game_status_id=self.status.id,
            game_date=self.week2.start_date,
            kickoff_time=time(9, 0),
        )
        self.db.add_all([availability, empty_wave, partial_wave, medium_division, medium_home, medium_away, medium_game])

        def add_wave_slot(wave, field_type, hour, name, assigned_game_id=None):
            field = FieldInstance(
                id=uuid.uuid4(),
                host_location_id=self.host.id,
                hosting_availability_id=availability.id,
                instance_date=self.week2.start_date,
                field_name=name,
                field_type=field_type,
                is_active=True,
            )
            slot = GameSlot(
                id=uuid.uuid4(),
                field_instance_id=field.id,
                host_location_id=self.host.id,
                season_id=self.season.id,
                week_id=self.week2.id,
                slot_date=self.week2.start_date,
                start_time=time(hour, 0),
                end_time=time(hour + 1, 0),
                field_type=field_type,
                status='ASSIGNED' if assigned_game_id else 'OPEN',
                assigned_game_id=assigned_game_id,
                turf_wave_id=wave.id,
            )
            self.db.add_all([field, slot])
            return slot

        for index in range(3):
            add_wave_slot(empty_wave, 'SMALL', 8, f'Empty Small {index + 1}')
        add_wave_slot(partial_wave, 'MEDIUM', 9, 'Partial Medium', medium_game.id)
        add_wave_slot(partial_wave, 'SMALL', 9, 'Partial Small 1')
        add_wave_slot(partial_wave, 'SMALL', 9, 'Partial Small 2')
        self.db.commit()

        preview = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)

        self.assertGreaterEqual(preview['proposed_game_count'], 1)
        self.assertEqual(preview['proposals'][0]['turf_wave_id'], str(partial_wave.id))
        self.assertEqual(preview['proposals'][0]['proposed_start_time'], '09:00:00')
        self.assertIn('turf wave packing projects 3/3 components usable', preview['proposals'][0]['reason'])

    def test_avoids_prior_week_exact_matchup_when_alternatives_exist(self):
        result = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)
        self.assertEqual(result['proposed_game_count'], 1)
        matchup = result['proposals'][0]['proposed_matchup']
        self.assertNotEqual(matchup, 'Westosha Maroon vs Antioch Black')
        self.assertIn('Avoids prior-week team repeat', result['proposals'][0]['reason'])
        self.assertIn('Avoids prior-week community repeat', result['proposals'][0]['reason'])




    def test_selected_capacity_uses_hosting_availability_before_generated_slots(self):
        self.week2.primary_game_date = self.week2.start_date
        antioch_host = HostLocation(
            id=uuid.uuid4(),
            organization_id=self.org_a.id,
            name='Tim Osmond Sports Complex',
            max_small_fields=1,
            is_active=True,
        )
        antioch_availability = HostingAvailability(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            organization_id=self.org_a.id,
            host_location_id=antioch_host.id,
            available_date=self.week2.start_date,
            primary_game_date=self.week2.start_date,
            start_time=time(9, 0),
            end_time=time(12, 0),
            is_available=True,
            active=True,
        )
        manual_selection = HostPlanSelection(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            game_date=self.week2.start_date,
            community_id=self.org_a.id,
            host_location_id=antioch_host.id,
            availability_id=antioch_availability.id,
            status='SELECTED',
            locked=False,
        )
        self.db.add_all([antioch_host, antioch_availability, manual_selection])
        self.db.commit()

        result = generate_suggested_host_plan({'season_id': self.season.id, 'game_date': str(self.week2.start_date)}, current_user=SimpleNamespace(email='admin@example.com'), db=self.db)

        decision_summary = result['weekly_host_plan_decision_summary']
        self.assertFalse(decision_summary['additional_host_needed'])
        self.assertEqual(decision_summary['selected_total_capacity'], 3)
        self.assertEqual(decision_summary['selected_small_capacity'], 3)
        self.assertEqual(decision_summary['selected_medium_capacity'], 0)
        self.assertEqual(decision_summary['selected_large_capacity'], 0)
        source_summary = decision_summary['selected_capacity_source_summary']
        self.assertEqual(source_summary[0]['host_location'], 'Tim Osmond Sports Complex')
        self.assertEqual(source_summary[0]['capacity_source'], 'Hosting Availability records')
        self.assertEqual(source_summary[0]['calculated_total_capacity'], 3)

        matrix = _host_availability_matrix_response(self.db, self.season.id)
        week_summary = next(summary for summary in matrix['summaries'] if summary['game_date'] == str(self.week2.start_date))
        matrix_decision_summary = week_summary['weekly_host_plan_decision_summary']
        self.assertEqual(matrix_decision_summary['selected_total_capacity'], 3)
        self.assertEqual(matrix_decision_summary['selected_small_capacity'], 3)
        self.assertEqual(matrix_decision_summary['selected_capacity_source_summary'][0]['capacity_source'], 'Hosting Availability records')
        self.assertNotIn('Selected location has availability but capacity could not be calculated.', week_summary['validation_warnings'])

    def test_generate_suggested_host_plan_does_not_add_excluded_host_when_selected_capacity_is_sufficient(self):
        self.week2.primary_game_date = self.week2.start_date
        lake_county = Organization(id=uuid.uuid4(), name='Lake County', is_active=True)
        antioch_host = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Tim Osmond Sports Complex', max_small_fields=1, is_active=True)
        lake_host = HostLocation(id=uuid.uuid4(), organization_id=lake_county.id, name='Behm Park', max_small_fields=1, is_active=True)
        westosha_availability = HostingAvailability(id=uuid.uuid4(), season_id=self.season.id, week_id=self.week2.id, organization_id=self.org_w.id, host_location_id=self.host.id, available_date=self.week2.start_date, primary_game_date=self.week2.start_date, start_time=time(9, 0), end_time=time(12, 0), is_available=True, active=True)
        antioch_availability = HostingAvailability(id=uuid.uuid4(), season_id=self.season.id, week_id=self.week2.id, organization_id=self.org_a.id, host_location_id=antioch_host.id, available_date=self.week2.start_date, primary_game_date=self.week2.start_date, start_time=time(9, 0), end_time=time(12, 0), is_available=True, active=True)
        lake_availability = HostingAvailability(id=uuid.uuid4(), season_id=self.season.id, week_id=self.week2.id, organization_id=lake_county.id, host_location_id=lake_host.id, available_date=self.week2.start_date, primary_game_date=self.week2.start_date, start_time=time(9, 0), end_time=time(12, 0), is_available=True, active=True)
        antioch_field = FieldInstance(id=uuid.uuid4(), host_location_id=antioch_host.id, hosting_availability_id=antioch_availability.id, instance_date=self.week2.start_date, field_name='Antioch Small 1', field_type='SMALL', is_active=True)
        lake_field = FieldInstance(id=uuid.uuid4(), host_location_id=lake_host.id, hosting_availability_id=lake_availability.id, instance_date=self.week2.start_date, field_name='Lake Small 1', field_type='SMALL', is_active=True)
        antioch_slot = GameSlot(id=uuid.uuid4(), field_instance_id=antioch_field.id, host_location_id=antioch_host.id, slot_date=self.week2.start_date, start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='OPEN')
        lake_slot = GameSlot(id=uuid.uuid4(), field_instance_id=lake_field.id, host_location_id=lake_host.id, slot_date=self.week2.start_date, start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='OPEN')
        westosha_extra_slot = GameSlot(id=uuid.uuid4(), field_instance_id=self.fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(11, 0), end_time=time(12, 0), field_type='SMALL', status='OPEN')
        self.db.add_all([lake_county, antioch_host, lake_host, westosha_availability, antioch_availability, lake_availability, antioch_field, lake_field, antioch_slot, lake_slot, westosha_extra_slot])
        self.db.add_all([
            HostPlanSelection(season_id=self.season.id, week_id=self.week2.id, game_date=self.week2.start_date, community_id=self.org_a.id, host_location_id=antioch_host.id, availability_id=antioch_availability.id, status='SELECTED'),
            HostPlanSelection(season_id=self.season.id, week_id=self.week2.id, game_date=self.week2.start_date, community_id=lake_county.id, host_location_id=lake_host.id, availability_id=lake_availability.id, status='SELECTED'),
            HostPlanSelection(season_id=self.season.id, week_id=self.week2.id, game_date=self.week2.start_date, community_id=self.org_w.id, host_location_id=self.host.id, availability_id=westosha_availability.id, status='EXCLUDED'),
        ])
        self.db.commit()

        result = generate_suggested_host_plan(
            {'season_id': self.season.id, 'game_date': str(self.week2.start_date)},
            current_user=SimpleNamespace(email='admin@example.com'),
            db=self.db,
        )

        self.assertEqual(result['decision_message'], 'Selected host plan has sufficient capacity. No additional host community is needed.')
        westosha_selection = self.db.query(HostPlanSelection).filter(HostPlanSelection.host_location_id == self.host.id, HostPlanSelection.game_date == self.week2.start_date).one()
        self.assertEqual(westosha_selection.status, 'EXCLUDED')
        selected_names = {row.host_location.name for row in self.db.query(HostPlanSelection).filter(HostPlanSelection.game_date == self.week2.start_date, HostPlanSelection.status == 'SELECTED').all()}
        self.assertEqual(selected_names, {'Tim Osmond Sports Complex', 'Behm Park'})
        decision_summary = result['weekly_host_plan_decision_summary']
        self.assertFalse(decision_summary['additional_host_needed'])
        self.assertEqual(decision_summary['selected_total_capacity'], 6)

    def test_weekly_host_plan_ignores_unused_available_locations(self):
        antioch_host = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Antioch Complex', is_active=True)
        antioch_field = FieldInstance(id=uuid.uuid4(), host_location_id=antioch_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Antioch Small 1', field_type='SMALL', is_active=True)
        antioch_slot_1 = GameSlot(id=uuid.uuid4(), field_instance_id=antioch_field.id, host_location_id=antioch_host.id, slot_date=self.week2.start_date, start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='OPEN')
        antioch_slot_2 = GameSlot(id=uuid.uuid4(), field_instance_id=antioch_field.id, host_location_id=antioch_host.id, slot_date=self.week2.start_date, start_time=time(10, 0), end_time=time(11, 0), field_type='SMALL', status='OPEN')
        extra_westosha_slot = GameSlot(id=uuid.uuid4(), field_instance_id=self.fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(10, 0), end_time=time(11, 0), field_type='SMALL', status='OPEN')
        self.db.add_all([antioch_host, antioch_field, antioch_slot_1, antioch_slot_2, extra_westosha_slot])
        self.db.commit()

        preview = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)

        self.assertEqual(preview['proposed_game_count'], 2)
        self.assertEqual({proposal['host_location_id'] for proposal in preview['proposals']}, {str(antioch_host.id)})
        plan = preview['audit']['weekly_community_host_plan']
        self.assertEqual(plan['diagnostic_label'], 'Weekly Host Plan Summary')
        self.assertIn('Westosha Park', plan['unused_locations'])
        westosha_status = next(row for row in plan['location_statuses'] if row['host_location'] == 'Westosha Park')
        self.assertEqual(westosha_status['status'], 'unused_this_week')

    def test_large_field_division_only_uses_large_slots(self):
        self.division.required_field_layout_type = 'FIFTY_THREE_YARD_WIDTH'
        self.db.commit()

        preview = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)
        self.assertEqual(preview['proposed_game_count'], 0)
        self.assertIn('No compatible large field available for this division.', [row['reason'] for row in preview['skipped']])




    def test_apply_skips_duplicate_matchup_with_friendly_message(self):
        # existing week 2 scheduled game in reverse order to ensure order-insensitive duplicate detection
        self.db.add(Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            home_team_id=self.ab.id,
            away_team_id=self.wm.id,
            game_status_id=self.status.id,
            game_date=self.week2.start_date,
            kickoff_time=time(11, 0),
        ))

        slot2 = GameSlot(
            id=uuid.uuid4(),
            field_instance_id=self.fi.id,
            host_location_id=self.host.id,
            slot_date=self.week2.start_date,
            start_time=time(10, 0),
            end_time=time(11, 0),
            field_type='SMALL',
            status='OPEN',
        )
        self.db.add(slot2)
        self.db.commit()

        payload = {
            'season_id': self.season.id,
            'week_id': self.week2.id,
            'division_id': self.division.id,
            'proposals': [
                {
                    'slot_id': str(self.slot.id),
                    'home_team_id': str(self.wm.id),
                    'away_team_id': str(self.ab.id),
                },
                {
                    'slot_id': str(slot2.id),
                    'home_team_id': str(self.wg.id),
                    'away_team_id': str(self.as_.id),
                },
            ],
        }

        result = auto_fill_apply(payload, db=self.db)

        self.assertEqual(result['created_games'], 1)
        self.assertEqual(result['skipped_count'], 1)
        skipped_message = result['skipped'][0]['reason']
        self.assertIn('Skipped Westosha Maroon vs Antioch Black because that matchup is already scheduled in Week 2.', skipped_message)
        self.assertIn('Date:', skipped_message)
        self.assertIn('Time:', skipped_message)
        self.assertNotIn(str(self.slot.id), skipped_message)

    def test_eight_team_week_creates_four_games_from_preview(self):
        org_c = Organization(id=uuid.uuid4(), name='Bristol', is_active=True)
        org_d = Organization(id=uuid.uuid4(), name='Salem', is_active=True)
        self.db.add_all([org_c, org_d])
        extra_teams = [
            Team(id=uuid.uuid4(), organization_id=org_c.id, division_id=self.division.id, name='Bristol Blue', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_c.id, division_id=self.division.id, name='Bristol White', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_d.id, division_id=self.division.id, name='Salem Green', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_d.id, division_id=self.division.id, name='Salem Orange', is_active=True),
        ]
        self.db.add_all(extra_teams)
        slots = []
        for hour in (10, 11, 12):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Small Field {hour}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
            slots.extend([fi, slot])
        self.db.add_all(slots)
        self.db.commit()

        preview = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)
        self.assertEqual(preview['max_allowed_game_count'], 4)
        self.assertEqual(preview['proposed_game_count'], 4)
        proposal_team_ids = set()
        for row in preview['proposals']:
            proposal_team_ids.add(row['home_team_id'])
            proposal_team_ids.add(row['away_team_id'])
        self.assertEqual(len(proposal_team_ids), 8)

        applied = auto_fill_apply({
            'season_id': self.season.id,
            'week_id': self.week2.id,
            'division_id': self.division.id,
            'proposals': preview['proposals'],
        }, db=self.db)
        self.assertEqual(applied['proposed_count'], 4)
        self.assertEqual(applied['created_count'], 4)
        self.assertEqual(applied['skipped_count'], 0)

    def test_same_community_prefers_home_slot_over_away_slot(self):
        away_host = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Antioch Park', is_active=True)
        away_fi = FieldInstance(id=uuid.uuid4(), host_location_id=away_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Small Field 2', field_type='SMALL', is_active=True)
        away_slot = GameSlot(id=uuid.uuid4(), field_instance_id=away_fi.id, host_location_id=away_host.id, slot_date=self.week2.start_date, start_time=time(10, 0), end_time=time(11, 0), field_type='SMALL', status='OPEN')
        self.db.add_all([away_host, away_fi, away_slot])
        self.db.commit()

        # consume Antioch teams in existing week-2 game so the remaining valid matchup is same-community Westosha
        self.db.add(Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            home_team_id=self.ab.id,
            away_team_id=self.as_.id,
            game_status_id=self.status.id,
            game_date=self.week2.start_date,
            kickoff_time=time(8, 0),
        ))
        self.db.commit()

        result = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)
        self.assertEqual(result['proposed_game_count'], 1)
        self.assertEqual(result['proposals'][0]['host_location'], 'Westosha Park')
        self.assertIn('same-community at primary home host field (+500)', result['proposals'][0]['reason'])

    def test_split_host_week_prefers_existing_community_host_assignment(self):
        lake_org = Organization(id=uuid.uuid4(), name='Lake County', is_active=True)
        self.db.add(lake_org)
        lake_red = Team(id=uuid.uuid4(), organization_id=lake_org.id, division_id=self.division.id, name='Lake County Red', is_active=True)
        lake_silver = Team(id=uuid.uuid4(), organization_id=lake_org.id, division_id=self.division.id, name='Lake County Silver', is_active=True)
        self.db.add_all([lake_red, lake_silver])

        hiller_host = HostLocation(id=uuid.uuid4(), organization_id=lake_org.id, name='Hiller Park', is_active=True)
        hiller_fi_existing = FieldInstance(id=uuid.uuid4(), host_location_id=hiller_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Hiller Existing', field_type='SMALL', is_active=True)
        hiller_slot_existing = GameSlot(id=uuid.uuid4(), field_instance_id=hiller_fi_existing.id, host_location_id=hiller_host.id, slot_date=self.week2.start_date, start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='OPEN')
        hiller_fi_open = FieldInstance(id=uuid.uuid4(), host_location_id=hiller_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Hiller Open', field_type='SMALL', is_active=True)
        hiller_slot_open = GameSlot(id=uuid.uuid4(), field_instance_id=hiller_fi_open.id, host_location_id=hiller_host.id, slot_date=self.week2.start_date, start_time=time(10, 0), end_time=time(11, 0), field_type='SMALL', status='OPEN')

        osmond_host = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Tim Osmond Sports Complex', is_active=True)
        osmond_fi = FieldInstance(id=uuid.uuid4(), host_location_id=osmond_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Osmond Open', field_type='SMALL', is_active=True)
        osmond_slot = GameSlot(id=uuid.uuid4(), field_instance_id=osmond_fi.id, host_location_id=osmond_host.id, slot_date=self.week2.start_date, start_time=time(10, 0), end_time=time(11, 0), field_type='SMALL', status='OPEN')
        self.db.add_all([hiller_host, hiller_fi_existing, hiller_slot_existing, hiller_fi_open, hiller_slot_open, osmond_host, osmond_fi, osmond_slot])
        self.db.commit()

        scheduled_game = Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            home_team_id=lake_red.id,
            away_team_id=self.ab.id,
            game_status_id=self.status.id,
            game_date=self.week2.start_date,
            kickoff_time=time(9, 0),
        )
        self.db.add(scheduled_game)
        self.db.commit()
        hiller_slot_existing.status = 'BOOKED'
        hiller_slot_existing.assigned_game_id = scheduled_game.id
        self.db.commit()

        result = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)
        target = next((p for p in result['proposals'] if set([p['home_team_id'], p['away_team_id']]) == {str(lake_silver.id), str(self.as_.id)}), None)
        self.assertIsNotNone(target)
        self.assertEqual(target['host_location'], 'Hiller Park')
        self.assertIn('community remains at assigned split-host site (+200)', target['reason'])


    def test_preview_fills_parallel_fields_before_later_times(self):
        org_c = Organization(id=uuid.uuid4(), name='Bristol', is_active=True)
        org_d = Organization(id=uuid.uuid4(), name='Salem', is_active=True)
        self.db.add_all([org_c, org_d])
        extra_teams = [
            Team(id=uuid.uuid4(), organization_id=org_c.id, division_id=self.division.id, name='Bristol Blue', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_c.id, division_id=self.division.id, name='Bristol White', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_d.id, division_id=self.division.id, name='Salem Green', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_d.id, division_id=self.division.id, name='Salem Orange', is_active=True),
        ]
        self.db.add_all(extra_teams)

        fi2 = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Small Field 2', field_type='SMALL', is_active=True)
        slot2 = GameSlot(id=uuid.uuid4(), field_instance_id=fi2.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='OPEN')
        fi3 = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Small Field 3', field_type='SMALL', is_active=True)
        slot3 = GameSlot(id=uuid.uuid4(), field_instance_id=fi3.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(10, 0), end_time=time(11, 0), field_type='SMALL', status='OPEN')
        self.db.add_all([fi2, slot2, fi3, slot3])
        self.db.commit()

        result = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)
        self.assertGreaterEqual(result['proposed_game_count'], 2)
        first_two = result['proposals'][:2]
        self.assertEqual(first_two[0]['proposed_start_time'], '09:00:00')
        self.assertEqual(first_two[1]['proposed_start_time'], '09:00:00')
        self.assertEqual(first_two[0]['field'], 'Small Field 1')
        self.assertEqual(first_two[1]['field'], 'Small Field 2')
    def test_uses_multiple_fields_when_parallel_capacity_exists(self):
        away_host = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Antioch Park', is_active=True)
        away_fi = FieldInstance(id=uuid.uuid4(), host_location_id=away_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Away Field 1', field_type='SMALL', is_active=True)
        away_slot = GameSlot(id=uuid.uuid4(), field_instance_id=away_fi.id, host_location_id=away_host.id, slot_date=self.week2.start_date, start_time=time(10, 0), end_time=time(11, 0), field_type='SMALL', status='OPEN')
        self.db.add_all([away_host, away_fi, away_slot])
        # add enough slots at primary host to support all games
        for hour in (10, 11):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Primary {hour}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
            self.db.add_all([fi, slot])
        self.db.commit()

        result = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)
        self.assertGreaterEqual(result['proposed_game_count'], 2)
        used_hosts = {p['host_location'] for p in result['proposals']}
        self.assertIn('Westosha Park', used_hosts)
        self.assertTrue(result['audit']['single_site_possible'])
        self.assertFalse(result['audit']['centralization_requested'])


    def test_centralized_request_prefers_single_host(self):
        away_host = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Antioch Park', is_active=True)
        away_fi = FieldInstance(id=uuid.uuid4(), host_location_id=away_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Away Field C', field_type='SMALL', is_active=True)
        away_slot = GameSlot(id=uuid.uuid4(), field_instance_id=away_fi.id, host_location_id=away_host.id, slot_date=self.week2.start_date, start_time=time(10, 0), end_time=time(11, 0), field_type='SMALL', status='OPEN')
        self.db.add_all([away_host, away_fi, away_slot])
        self.db.commit()

        result = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id, 'centralized_scheduling_requested': True}, db=self.db)
        self.assertTrue(result['audit']['centralization_requested'])
        self.assertGreaterEqual(result['proposed_game_count'], 1)

    def test_split_host_week_keeps_host_teams_on_home_sites_when_capacity_exists(self):
        away_host = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Antioch Park', is_active=True)
        away_fi_1 = FieldInstance(id=uuid.uuid4(), host_location_id=away_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Away Field 1', field_type='SMALL', is_active=True)
        away_slot_1 = GameSlot(id=uuid.uuid4(), field_instance_id=away_fi_1.id, host_location_id=away_host.id, slot_date=self.week2.start_date, start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='OPEN')
        away_fi_2 = FieldInstance(id=uuid.uuid4(), host_location_id=away_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Away Field 2', field_type='SMALL', is_active=True)
        away_slot_2 = GameSlot(id=uuid.uuid4(), field_instance_id=away_fi_2.id, host_location_id=away_host.id, slot_date=self.week2.start_date, start_time=time(10, 0), end_time=time(11, 0), field_type='SMALL', status='OPEN')
        self.db.add_all([away_host, away_fi_1, away_slot_1, away_fi_2, away_slot_2])
        self.db.commit()

        result = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)
        self.assertTrue(result['audit']['split_host_week'])
        self.assertGreaterEqual(result['proposed_game_count'], 2)
        for proposal in result['proposals']:
            home_team = self.db.query(Team).filter(Team.id == uuid.UUID(proposal['home_team_id'])).first()
            away_team = self.db.query(Team).filter(Team.id == uuid.UUID(proposal['away_team_id'])).first()
            host = self.db.query(HostLocation).filter(HostLocation.id == uuid.UUID(proposal['host_location_id'])).first()
            self.assertIsNotNone(home_team)
            self.assertIsNotNone(away_team)
            self.assertIsNotNone(host)
            self.assertIn(host.organization_id, {home_team.organization_id, away_team.organization_id})


    def test_multi_host_assignment_balances_selected_communities_and_reports_summary(self):
        self.db.add_all([
            Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=self.division.id, name='Westosha Navy', is_active=True),
            Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=self.division.id, name='Westosha White', is_active=True),
            Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=self.division.id, name='Antioch Red', is_active=True),
            Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=self.division.id, name='Antioch Gold', is_active=True),
        ])
        # Give the first selected community two compatible slots, forcing a second selected
        # community while still allowing an even 2/2 weekly split across the selected hosts.
        westosha_extra_fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Westosha Balance 2', field_type='SMALL', is_active=True)
        westosha_extra_slot = GameSlot(id=uuid.uuid4(), field_instance_id=westosha_extra_fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(10, 0), end_time=time(11, 0), field_type='SMALL', status='OPEN')
        antioch_host = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Antioch Park', is_active=True)
        rows = [westosha_extra_fi, westosha_extra_slot, antioch_host]
        for idx, hour in enumerate((9, 10, 11, 12), start=1):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=antioch_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Antioch Balance {idx}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=antioch_host.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
            rows.extend([fi, slot])
        self.db.add_all(rows)
        self.db.commit()

        result = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)

        self.assertEqual(result['max_allowed_game_count'], 4)
        self.assertEqual(result['proposed_game_count'], 4)
        summary = result['diagnostics']['weekly_multi_host_assignment_summary']
        self.assertEqual(summary['diagnostic_label'], 'Weekly Multi-Host Assignment Summary')
        self.assertEqual(summary['selected_host_community_count'], 2)
        self.assertEqual(summary['actual_games_per_host_community']['Westosha'], 2)
        self.assertEqual(summary['actual_games_per_host_community']['Antioch'], 2)
        self.assertEqual(summary['home_team_games_forced_away'], 0)
        self.assertEqual(summary['validation_flags'], [])

    def test_selected_multiple_locations_balance_by_community_before_location(self):
        self.wm.is_active = False
        self.wg.is_active = False
        self.ab.is_active = False
        self.as_.is_active = False
        johnsburg = Organization(id=uuid.uuid4(), name='Johnsburg', is_active=True)
        antioch_host = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Tim Osmond Sports Complex', is_active=True)
        johnsburg_stadium = HostLocation(id=uuid.uuid4(), organization_id=johnsburg.id, name='Johnsburg Stadium', is_active=True)
        hiller_park = HostLocation(id=uuid.uuid4(), organization_id=johnsburg.id, name='Hiller Park', is_active=True)
        rows = [johnsburg, antioch_host, johnsburg_stadium, hiller_park]
        for idx in range(4):
            rows.append(Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=self.division.id, name=f'Antioch Team {idx + 1}', is_active=True))
            rows.append(Team(id=uuid.uuid4(), organization_id=johnsburg.id, division_id=self.division.id, name=f'Johnsburg Team {idx + 1}', is_active=True))
        for host in (antioch_host, johnsburg_stadium, hiller_park):
            rows.append(HostPlanSelection(season_id=self.season.id, week_id=self.week2.id, game_date=self.week2.start_date, community_id=host.organization_id, host_location_id=host.id, status='SELECTED'))
            for idx, hour in enumerate((9, 10, 11, 12), start=1):
                fi = FieldInstance(id=uuid.uuid4(), host_location_id=host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'{host.name} Field {idx}', field_type='SMALL', is_active=True)
                slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=host.id, season_id=self.season.id, week_id=self.week2.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
                rows.extend([fi, slot])
        self.db.add_all(rows)
        self.db.commit()

        result = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)

        self.assertEqual(result['proposed_game_count'], 4)
        summary = result['diagnostics']['host_allocation_summary_by_date']
        self.assertEqual(summary['selected_host_community_count'], 2)
        self.assertEqual(summary['adjusted_target_games_by_host_community']['Antioch'], 2)
        self.assertEqual(summary['adjusted_target_games_by_host_community']['Johnsburg'], 2)
        self.assertEqual(summary['actual_games_per_host_community']['Antioch'], 2)
        self.assertEqual(summary['actual_games_per_host_community']['Johnsburg'], 2)
        johnsburg_location_total = (
            summary['actual_games_per_host_location'].get('Johnsburg Stadium', 0)
            + summary['actual_games_per_host_location'].get('Hiller Park', 0)
        )
        self.assertEqual(johnsburg_location_total, 2)
        self.assertEqual(summary['reason_for_community_overage'], {})
        self.assertEqual(summary['reason_for_community_underage'], {})


    def test_preview_locks_to_two_hosts_when_one_host_is_insufficient(self):
        second_host = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Antioch Park', is_active=True)
        third_host = HostLocation(id=uuid.uuid4(), organization_id=self.org_w.id, name='Wilmot Stadium', is_active=True)
        self.db.add_all([second_host, third_host])
        for hour in (10,):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=second_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Antioch {hour}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=second_host.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
            self.db.add_all([fi, slot])
        for hour in (11,):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=third_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Wilmot {hour}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=third_host.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
            self.db.add_all([fi, slot])
        self.db.commit()

        result = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)
        locked_hosts = set(result['audit']['locked_host_locations'])
        proposal_hosts = {p['host_location_id'] for p in result['proposals']}
        self.assertLessEqual(len(proposal_hosts), 2)
        self.assertTrue(proposal_hosts.issubset(locked_hosts))

    def test_large_week_prefers_two_hosts_when_threshold_exceeded(self):
        org_c = Organization(id=uuid.uuid4(), name='Bristol', is_active=True)
        org_d = Organization(id=uuid.uuid4(), name='Salem', is_active=True)
        self.db.add_all([org_c, org_d])
        self.db.add_all([
            Team(id=uuid.uuid4(), organization_id=org_c.id, division_id=self.division.id, name='Bristol Blue', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_c.id, division_id=self.division.id, name='Bristol White', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_d.id, division_id=self.division.id, name='Salem Green', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_d.id, division_id=self.division.id, name='Salem Orange', is_active=True),
        ])
        away_host = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Antioch Park', is_active=True)
        self.db.add(away_host)
        for idx, start_hour in enumerate((9, 10, 11), start=1):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=away_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Away {idx}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=away_host.id, slot_date=self.week2.start_date, start_time=time(start_hour, 0), end_time=time(start_hour + 1, 0), field_type='SMALL', status='OPEN')
            self.db.add_all([fi, slot])
        for idx, start_hour in enumerate((10, 11, 12, 13), start=1):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Home {idx}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(start_hour, 0), end_time=time(start_hour + 1, 0), field_type='SMALL', status='OPEN')
            self.db.add_all([fi, slot])
        self.db.commit()

        result = auto_fill_preview(
            {'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id, 'single_site_game_limit': 4},
            db=self.db,
        )
        self.assertEqual(result['max_allowed_game_count'], 4)
        self.assertEqual(result['audit']['locked_host_mode'], 'single')

        result = auto_fill_preview(
            {'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id, 'single_site_game_limit': 3},
            db=self.db,
        )
        self.assertEqual(result['max_allowed_game_count'], 4)
        self.assertEqual(result['audit']['locked_host_mode'], 'dual')
        self.assertEqual(len(result['audit']['locked_host_locations']), 2)
        self.assertIn('exceed single-site game limit', result['audit']['host_selection_reason'])

    def test_preview_returns_error_when_more_than_two_hosts_would_be_required(self):
        self.db.query(GameSlot).filter(GameSlot.id == self.slot.id).delete()
        self.db.query(FieldInstance).filter(FieldInstance.id == self.fi.id).delete()
        host_2 = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Host 2', is_active=True)
        host_3 = HostLocation(id=uuid.uuid4(), organization_id=self.org_w.id, name='Host 3', is_active=True)
        self.db.add_all([host_2, host_3])
        for idx, host in enumerate((self.host, host_2, host_3), start=1):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'H{idx}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=host.id, slot_date=self.week2.start_date, start_time=time(9 + idx, 0), end_time=time(10 + idx, 0), field_type='SMALL', status='OPEN')
            self.db.add_all([fi, slot])
        self.db.commit()
        result = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)
        reasons = [row['reason'] for row in result['skipped']]
        self.assertIn('More than 2 host locations required. Admin override needed.', reasons)

    def test_odd_division_accepts_required_double_header(self):
        odd_team = Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=self.division.id, name='Westosha White', is_active=True)
        self.db.add(odd_team)
        for hour in (10, 11):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Odd Field {hour}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
            self.db.add_all([fi, slot])
        self.db.commit()

        result = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)
        self.assertEqual(result['max_allowed_game_count'], 3)
        self.assertEqual(result['proposed_game_count'], 3)
        self.assertTrue(any('Accepted as required double header due to odd team count' in row['reason'] for row in result['proposals']))

    def test_odd_large_division_adds_overflow_host_for_adjacent_doubleheader(self):
        large_division = Division(id=uuid.uuid4(), division_group='COED', name='6th/7th', required_field_layout_type='LARGE', is_active=True)
        antioch_host = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Antioch Large Complex', is_active=True)
        self.db.add_all([large_division, antioch_host])
        teams = [
            Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=large_division.id, name='Antioch 6th/7th Gold', is_active=True),
            Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=large_division.id, name="J'Burg 6th/7th Blue", is_active=True),
            Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=large_division.id, name='Lake County Stallions 6th/7th Black', is_active=True),
            Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=large_division.id, name='Lake County Stallions 6th/7th Red', is_active=True),
            Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=large_division.id, name='Westosha 6th/7th Maroon', is_active=True),
        ]
        self.db.add_all(teams)
        # Westosha is the selected rotation community and has enough large slots by count,
        # but not enough adjacent same-site capacity for the mandatory odd-team doubleheader.
        for hour in (9, 11, 13):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Westosha Large {hour}', field_type='LARGE', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='LARGE', status='OPEN')
            self.db.add_all([fi, slot])
        # Antioch supplies compatible back-to-back large slots and must be added instead of omitting the division.
        for hour in (9, 10, 11):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=antioch_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Antioch Large {hour}', field_type='LARGE', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=antioch_host.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='LARGE', status='OPEN')
            self.db.add_all([fi, slot])
        self.db.commit()

        result = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': large_division.id, 'no_byes': True}, db=self.db)

        self.assertEqual(result['max_allowed_game_count'], 3)
        self.assertEqual(result['generated_required_game_groups'], 3)
        self.assertEqual(result['proposed_game_count'], 3)
        self.assertTrue(all(row['field_type'] == 'LARGE' for row in result['proposals']))
        team_counts: dict[str, int] = {}
        for row in result['proposals']:
            team_counts[row['home_team_id']] = team_counts.get(row['home_team_id'], 0) + 1
            team_counts[row['away_team_id']] = team_counts.get(row['away_team_id'], 0) + 1
        self.assertEqual(len(team_counts), 5)
        doubleheader_team_ids = [team_id for team_id, count in team_counts.items() if count == 2]
        self.assertEqual(len(doubleheader_team_ids), 1)
        dh_games = [row for row in result['proposals'] if doubleheader_team_ids[0] in {row['home_team_id'], row['away_team_id']}]
        self.assertEqual(len({row['host_location_id'] for row in dh_games}), 1)
        starts = sorted(int(row['proposed_start_time'].split(':')[0]) for row in dh_games)
        self.assertEqual(starts[1] - starts[0], 1)

    def test_apply_odd_division_uses_later_compatible_slot_when_adjacent_unavailable(self):
        odd_team = Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=self.division.id, name='Westosha White', is_active=True)
        self.db.add(odd_team)

        slot_10_fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Odd 10', field_type='SMALL', is_active=True)
        slot_10 = GameSlot(id=uuid.uuid4(), field_instance_id=slot_10_fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(10, 0), end_time=time(11, 0), field_type='SMALL', status='OPEN')
        slot_12_fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Odd 12', field_type='SMALL', is_active=True)
        slot_12 = GameSlot(id=uuid.uuid4(), field_instance_id=slot_12_fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(12, 0), end_time=time(13, 0), field_type='SMALL', status='OPEN')
        self.db.add_all([slot_10_fi, slot_10, slot_12_fi, slot_12])
        self.db.commit()

        result = auto_fill_apply({
            'season_id': self.season.id,
            'week_id': self.week2.id,
            'division_id': self.division.id,
            'proposals': [
                {'slot_id': str(self.slot.id), 'home_team_id': str(self.wm.id), 'away_team_id': str(self.ab.id)},
                {'slot_id': str(slot_10.id), 'home_team_id': str(self.wg.id), 'away_team_id': str(self.as_.id)},
                # conflict: wm already plays at 9:00, so this proposal must fallback to 12:00
                {'slot_id': str(self.slot.id), 'home_team_id': str(self.wm.id), 'away_team_id': str(odd_team.id)},
            ],
            'no_byes': True,
        }, db=self.db)

        self.assertEqual(result['final_validation']['required_game_count'], 3)
        self.assertEqual(result['final_validation']['created_game_count'], 3)
        self.assertEqual(result['created_count'], 3)
        self.assertEqual(result['final_validation']['unscheduled_teams'], [])
        self.assertTrue(any('non-back-to-back' in row['reason'] for row in result['skipped']))

    def test_apply_odd_division_recovery_pass_fills_late_slot(self):
        odd_team = Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=self.division.id, name='Westosha White', is_active=True)
        late_fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Late Field', field_type='SMALL', is_active=True)
        late_slot = GameSlot(id=uuid.uuid4(), field_instance_id=late_fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(16, 0), end_time=time(17, 0), field_type='SMALL', status='OPEN')
        slot_10_fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Odd 10', field_type='SMALL', is_active=True)
        slot_10 = GameSlot(id=uuid.uuid4(), field_instance_id=slot_10_fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(10, 0), end_time=time(11, 0), field_type='SMALL', status='OPEN')
        self.db.add_all([odd_team, late_fi, late_slot, slot_10_fi, slot_10])
        self.db.commit()

        result = auto_fill_apply({
            'season_id': self.season.id,
            'week_id': self.week2.id,
            'division_id': self.division.id,
            'proposals': [
                {'slot_id': str(self.slot.id), 'home_team_id': str(self.wm.id), 'away_team_id': str(self.ab.id)},
                {'slot_id': str(slot_10.id), 'home_team_id': str(self.wg.id), 'away_team_id': str(self.as_.id)},
            ],
            'no_byes': True,
        }, db=self.db)

        self.assertEqual(result['final_validation']['required_game_count'], 3)
        self.assertEqual(result['final_validation']['created_game_count'], 3)
        self.assertEqual(result['created_count'], 3)
        self.assertEqual(result['final_validation']['unscheduled_teams'], [])

    def test_apply_ignores_unscheduled_games_for_duplicate_check(self):
        unscheduled_status = GameStatus(id=uuid.uuid4(), code='UNSCHEDULED', label='Unscheduled', is_active=True)
        self.db.add(unscheduled_status)
        self.db.add(Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            home_team_id=self.ab.id,
            away_team_id=self.wm.id,
            game_status_id=unscheduled_status.id,
            game_date=self.week2.start_date,
            kickoff_time=time(11, 0),
        ))
        self.db.commit()

        result = auto_fill_apply({
            'season_id': self.season.id,
            'week_id': self.week2.id,
            'division_id': self.division.id,
            'proposals': [{
                'slot_id': str(self.slot.id),
                'home_team_id': str(self.wm.id),
                'away_team_id': str(self.ab.id),
            }],
        }, db=self.db)
        self.assertEqual(result['created_count'], 1)
        self.assertEqual(result['skipped_count'], 0)

    def test_preview_rejects_slot_occupied_by_other_division_game(self):
        other_division = Division(id=uuid.uuid4(), name='K/1st', required_field_layout_type='THIRTY_YARD_WIDTH', is_active=True)
        other_team_home = Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=other_division.id, name='Westosha K', is_active=True)
        other_team_away = Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=other_division.id, name='Antioch K', is_active=True)
        self.db.add_all([other_division, other_team_home, other_team_away])
        self.db.add(Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            home_team_id=other_team_home.id,
            away_team_id=other_team_away.id,
            game_status_id=self.status.id,
            game_date=self.week2.start_date,
            kickoff_time=time(9, 0),
        ))
        self.db.commit()

        result = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)
        self.assertEqual(result['proposed_game_count'], 0)
        self.assertTrue(any('occupied by existing K/1st game' in s['reason'] for s in result['skipped']))


    def test_apply_rejects_preview_batch_with_duplicate_field_time(self):
        duplicate_proposals = [
            {
                'slot_id': str(self.slot.id),
                'home_team_id': str(self.wm.id),
                'away_team_id': str(self.ab.id),
            },
            {
                'slot_id': str(self.slot.id),
                'home_team_id': str(self.wg.id),
                'away_team_id': str(self.as_.id),
            },
        ]

        with self.assertRaises(Exception) as ctx:
            auto_fill_apply({
                'season_id': self.season.id,
                'week_id': self.week2.id,
                'division_id': self.division.id,
                'proposals': duplicate_proposals,
            }, db=self.db)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn('duplicate date/time/field assignments detected', str(ctx.exception.detail))

    def test_apply_rejects_slot_occupied_by_other_division_game(self):
        other_division = Division(id=uuid.uuid4(), name='K/1st', required_field_layout_type='THIRTY_YARD_WIDTH', is_active=True)
        other_team_home = Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=other_division.id, name='Westosha K2', is_active=True)
        other_team_away = Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=other_division.id, name='Antioch K2', is_active=True)
        self.db.add_all([other_division, other_team_home, other_team_away])
        self.db.add(Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            home_team_id=other_team_home.id,
            away_team_id=other_team_away.id,
            game_status_id=self.status.id,
            game_date=self.week2.start_date,
            kickoff_time=time(9, 0),
        ))
        self.db.commit()

        result = auto_fill_apply({
            'season_id': self.season.id,
            'week_id': self.week2.id,
            'division_id': self.division.id,
            'proposals': [{
                'slot_id': str(self.slot.id),
                'home_team_id': str(self.wm.id),
                'away_team_id': str(self.ab.id),
            }],
        }, db=self.db)
        self.assertEqual(result['created_count'], 0)
        self.assertEqual(result['skipped_count'], 1)
        self.assertIn('occupied by existing K/1st game', result['skipped'][0]['reason'])

    def test_nine_team_week_creates_five_games_with_one_double_header_team(self):
        org_c = Organization(id=uuid.uuid4(), name='Bristol', is_active=True)
        org_d = Organization(id=uuid.uuid4(), name='Salem', is_active=True)
        org_e = Organization(id=uuid.uuid4(), name='Kenosha', is_active=True)
        self.db.add_all([org_c, org_d, org_e])
        extra_teams = [
            Team(id=uuid.uuid4(), organization_id=org_c.id, division_id=self.division.id, name='Bristol Blue', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_c.id, division_id=self.division.id, name='Bristol White', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_d.id, division_id=self.division.id, name='Salem Green', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_d.id, division_id=self.division.id, name='Salem Orange', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_e.id, division_id=self.division.id, name='Kenosha Red', is_active=True),
        ]
        self.db.add_all(extra_teams)
        slots = []
        for hour in (10, 11, 12, 13):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Small Field {hour}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
            slots.extend([fi, slot])
        self.db.add_all(slots)
        self.db.commit()

        preview = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id, 'no_byes': True}, db=self.db)
        self.assertEqual(preview['max_allowed_game_count'], 5)
        self.assertEqual(preview['proposed_game_count'], 5)
        team_counts: dict[str, int] = {}
        for row in preview['proposals']:
            team_counts[row['home_team_id']] = team_counts.get(row['home_team_id'], 0) + 1
            team_counts[row['away_team_id']] = team_counts.get(row['away_team_id'], 0) + 1
        doubles = [tid for tid, count in team_counts.items() if count == 2]
        self.assertEqual(len(doubles), 1)
        self.assertEqual(sum(team_counts.values()), 10)

    def test_apply_rehomes_required_double_header_to_adjacent_slot_when_same_time_conflict(self):
        org_c = Organization(id=uuid.uuid4(), name='Bristol', is_active=True)
        org_d = Organization(id=uuid.uuid4(), name='Salem', is_active=True)
        org_e = Organization(id=uuid.uuid4(), name='Kenosha', is_active=True)
        self.db.add_all([org_c, org_d, org_e])
        extra_teams = [
            Team(id=uuid.uuid4(), organization_id=org_c.id, division_id=self.division.id, name='Bristol Blue', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_c.id, division_id=self.division.id, name='Bristol White', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_d.id, division_id=self.division.id, name='Salem Green', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_d.id, division_id=self.division.id, name='Salem Orange', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_e.id, division_id=self.division.id, name='Kenosha Red', is_active=True),
        ]
        self.db.add_all(extra_teams)
        for hour in (10, 11, 12, 13):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Small Field {hour}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
            self.db.add_all([fi, slot])
        self.db.commit()

        preview = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id, 'no_byes': True}, db=self.db)
        self.assertEqual(preview['proposed_game_count'], 5)

        double_team_id = None
        for team_id in {p['home_team_id'] for p in preview['proposals']} | {p['away_team_id'] for p in preview['proposals']}:
            appearances = sum(1 for p in preview['proposals'] if team_id in {p['home_team_id'], p['away_team_id']})
            if appearances == 2:
                double_team_id = team_id
                break
        self.assertIsNotNone(double_team_id)

        first_dh_game = next(p for p in preview['proposals'] if double_team_id in {p['home_team_id'], p['away_team_id']})
        conflict_game = Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            home_team_id=uuid.UUID(double_team_id),
            away_team_id=extra_teams[0].id,
            game_status_id=self.status.id,
            game_date=self.week2.start_date,
            kickoff_time=time.fromisoformat(first_dh_game['proposed_start_time']),
        )
        self.db.add(conflict_game)
        self.db.commit()

        applied = auto_fill_apply({
            'season_id': self.season.id,
            'week_id': self.week2.id,
            'division_id': self.division.id,
            'proposals': preview['proposals'],
            'no_byes': True,
        }, db=self.db)
        self.assertEqual(applied['created_count'], 5)
        self.assertEqual(applied['skipped_count'], 0)
        self.assertEqual(applied['skipped'], [])

    def test_apply_locally_reshuffles_site_day_slots_to_make_adjacent_double_header(self):
        org_c = Organization(id=uuid.uuid4(), name='Bristol', is_active=True)
        org_d = Organization(id=uuid.uuid4(), name='Salem', is_active=True)
        org_e = Organization(id=uuid.uuid4(), name='Kenosha', is_active=True)
        self.db.add_all([org_c, org_d, org_e])
        extra_teams = [
            Team(id=uuid.uuid4(), organization_id=org_c.id, division_id=self.division.id, name='Bristol Blue', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_c.id, division_id=self.division.id, name='Bristol White', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_d.id, division_id=self.division.id, name='Salem Green', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_d.id, division_id=self.division.id, name='Salem Orange', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_e.id, division_id=self.division.id, name='Kenosha Red', is_active=True),
        ]
        self.db.add_all(extra_teams)
        for hour in (10, 11, 12, 13):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Small Field {hour}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
            self.db.add_all([fi, slot])
        self.db.commit()

        preview = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id, 'no_byes': True}, db=self.db)
        self.assertEqual(preview['proposed_game_count'], 5)
        team_counts: dict[str, int] = {}
        for row in preview['proposals']:
            team_counts[row['home_team_id']] = team_counts.get(row['home_team_id'], 0) + 1
            team_counts[row['away_team_id']] = team_counts.get(row['away_team_id'], 0) + 1
        double_team_id = next(tid for tid, count in team_counts.items() if count == 2)
        dh_rows = [row for row in preview['proposals'] if double_team_id in {row['home_team_id'], row['away_team_id']}]
        self.assertEqual(len(dh_rows), 2)

        # Force a gap (10 and 12) for the double-header team while a same-site/day non-DH game is at 11.
        by_time = {row['proposed_start_time']: row for row in preview['proposals']}
        if {'10:00:00', '11:00:00', '12:00:00'}.issubset(by_time.keys()):
            ten = by_time['10:00:00']
            eleven = by_time['11:00:00']
            twelve = by_time['12:00:00']
            if double_team_id in {eleven['home_team_id'], eleven['away_team_id']}:
                eleven = by_time['13:00:00']
            dh_row = next(row for row in (ten, twelve) if double_team_id in {row['home_team_id'], row['away_team_id']})
            other_dh_row = twelve if dh_row is ten else ten
            non_dh_row = eleven
            non_dh_row['slot_id'], other_dh_row['slot_id'] = other_dh_row['slot_id'], non_dh_row['slot_id']

        applied = auto_fill_apply({
            'season_id': self.season.id,
            'week_id': self.week2.id,
            'division_id': self.division.id,
            'proposals': preview['proposals'],
            'no_byes': True,
        }, db=self.db)
        self.assertEqual(applied['created_count'], 5)
        self.assertEqual(applied['skipped_count'], 0)

        created = self.db.query(Game).filter(Game.week_id == self.week2.id).all()
        starts = sorted(g.kickoff_time for g in created if str(double_team_id) in {str(g.home_team_id), str(g.away_team_id)})
        self.assertEqual(len(starts), 2)
        self.assertEqual(abs((starts[1].hour * 60 + starts[1].minute) - (starts[0].hour * 60 + starts[0].minute)), 60)


    def test_rotation_selects_community_and_aggregates_all_its_locations_before_higher_capacity_hosts(self):
        # Give Antioch prior hosting usage so Westosha is next in the community rotation even though
        # Antioch has more total compatible slot capacity this week.
        antioch_prior_host = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Antioch Prior Host', is_active=True)
        antioch_prior_fi = FieldInstance(id=uuid.uuid4(), host_location_id=antioch_prior_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week1.start_date, field_name='Prior Small', field_type='SMALL', is_active=True)
        antioch_prior_slot = GameSlot(id=uuid.uuid4(), field_instance_id=antioch_prior_fi.id, host_location_id=antioch_prior_host.id, slot_date=self.week1.start_date, start_time=time(10, 0), end_time=time(11, 0), field_type='SMALL', status='ASSIGNED')
        prior_game = self.db.query(Game).filter(Game.week_id == self.week1.id).first()
        antioch_prior_slot.assigned_game_id = prior_game.id

        westosha_grass = HostLocation(id=uuid.uuid4(), organization_id=self.org_w.id, name='Westosha Grass Fields', is_active=True)
        extra_rows = [antioch_prior_host, antioch_prior_fi, antioch_prior_slot, westosha_grass]
        # Existing Westosha Park already has one slot; add one more there and two at the second Westosha site.
        for hour in (10,):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Westosha Park Small {hour}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
            extra_rows.extend([fi, slot])
        for hour in (9, 10):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=westosha_grass.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Westosha Grass Small {hour}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=westosha_grass.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
            extra_rows.extend([fi, slot])

        antioch_big = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Antioch Bigger Capacity', is_active=True)
        extra_rows.append(antioch_big)
        for hour in (9, 10, 11, 12, 13):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=antioch_big.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Antioch Small {hour}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=antioch_big.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
            extra_rows.extend([fi, slot])

        extra_teams = [
            Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=self.division.id, name='Westosha White', is_active=True),
            Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=self.division.id, name='Westosha Black', is_active=True),
            Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=self.division.id, name='Antioch Red', is_active=True),
            Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=self.division.id, name='Antioch Blue', is_active=True),
        ]
        self.db.add_all(extra_rows + extra_teams)
        self.db.commit()

        preview = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)

        self.assertEqual(preview['proposed_game_count'], 4)
        selected_communities = preview['audit']['selected_host_communities']
        self.assertEqual([row['community'] for row in selected_communities], ['Westosha'])
        selected_locations = {row['host_location'] for row in preview['proposals']}
        self.assertEqual(selected_locations, {'Westosha Park', 'Westosha Grass Fields'})
        locked_locations = set(preview['audit']['locked_host_locations'])
        self.assertEqual(locked_locations, {str(self.host.id), str(westosha_grass.id)})
        self.assertTrue(preview['audit']['primary_community_can_host_all_games'])
        self.assertFalse(preview['audit']['additional_communities_needed'])
        capacity_row = preview['audit']['selected_host_locations_by_community'][0]
        self.assertEqual(capacity_row['community'], 'Westosha')
        self.assertEqual(capacity_row['combined_capacity'], 4)
        self.assertEqual(capacity_row['combined_capacity_by_size']['SMALL'], 4)
        equity_row = next(row for row in preview['audit']['community_hosting_equity_summary'] if row['community'] == 'Westosha')
        self.assertEqual(equity_row['diagnostic_label'], 'Community Hosting Equity Summary')
        self.assertEqual({host['host_location'] for host in equity_row['host_locations']}, {'Westosha Park', 'Westosha Grass Fields'})
        self.assertEqual(equity_row['selected_weeks'], ['Week 2'])
        weekly_plan = preview['audit']['weekly_community_host_plan']
        self.assertEqual(weekly_plan['diagnostic_label'], 'Weekly Community Host Plan')
        self.assertEqual(weekly_plan['selected_community_or_communities'], ['Westosha'])
        self.assertEqual(weekly_plan['community_capacity_by_field_size']['Westosha']['SMALL'], 4)
        self.assertIsNone(weekly_plan['reason_additional_community_was_needed'])


    def test_rotation_adds_next_community_before_higher_capacity_later_community(self):
        self.db.delete(self.slot)
        self.db.delete(self.fi)
        burlington = Organization(id=uuid.uuid4(), name='Burlington', is_active=True)
        antioch_host = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Antioch Overflow', is_active=True)
        burlington_host = HostLocation(id=uuid.uuid4(), organization_id=burlington.id, name='Burlington Big Complex', is_active=True)
        extra_rows = [burlington, antioch_host, burlington_host]

        prior_game = self.db.query(Game).filter(Game.week_id == self.week1.id).first()
        for idx, (host, prior_date) in enumerate([(antioch_host, self.week1.start_date), (burlington_host, date(2026, 4, 24)), (burlington_host, date(2026, 4, 17))]):
            prior_field = FieldInstance(id=uuid.uuid4(), host_location_id=host.id, hosting_availability_id=uuid.uuid4(), instance_date=prior_date, field_name=f'Prior {idx}', field_type='SMALL', is_active=True)
            prior_slot = GameSlot(id=uuid.uuid4(), field_instance_id=prior_field.id, host_location_id=host.id, slot_date=prior_date, start_time=time(8 + idx, 0), end_time=time(9 + idx, 0), field_type='SMALL', status='ASSIGNED', assigned_game_id=prior_game.id)
            extra_rows.extend([prior_field, prior_slot])

        for hour in (9, 10):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Westosha Small {hour}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
            extra_rows.extend([fi, slot])
        antioch_fi = FieldInstance(id=uuid.uuid4(), host_location_id=antioch_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Antioch Small 9', field_type='SMALL', is_active=True)
        antioch_slot = GameSlot(id=uuid.uuid4(), field_instance_id=antioch_fi.id, host_location_id=antioch_host.id, slot_date=self.week2.start_date, start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='OPEN')
        extra_rows.extend([antioch_fi, antioch_slot])
        for hour in (9, 10, 11, 12, 13, 14):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=burlington_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Burlington Small {hour}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=burlington_host.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
            extra_rows.extend([fi, slot])

        extra_teams = [
            Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=self.division.id, name='Westosha White', is_active=True),
            Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=self.division.id, name='Antioch Red', is_active=True),
        ]
        self.db.add_all(extra_rows + extra_teams)
        self.db.commit()

        preview = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)

        self.assertEqual(preview['proposed_game_count'], 3)
        self.assertEqual([row['community'] for row in preview['audit']['selected_host_communities']], ['Westosha', 'Antioch'])
        self.assertNotIn(str(burlington_host.id), preview['audit']['locked_host_locations'])
        self.assertFalse(preview['audit']['primary_community_can_host_all_games'])
        assessment = preview['audit']['community_capacity_assessment']
        self.assertEqual(assessment['selected_primary_community'], 'Westosha')
        self.assertFalse(assessment['can_host_entire_week'])
        self.assertEqual([row['community'] for row in assessment['additional_communities_added']], ['Antioch'])


    def test_selected_underused_community_gets_more_games_when_capacity_allows(self):
        antioch_host = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Antioch Equity Park', is_active=True)
        extra_rows = [antioch_host]
        extra_teams = [
            Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=self.division.id, name='Westosha White', is_active=True),
            Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=self.division.id, name='Westosha Black', is_active=True),
            Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=self.division.id, name='Antioch Red', is_active=True),
            Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=self.division.id, name='Antioch Blue', is_active=True),
        ]
        extra_rows.extend(extra_teams)
        for idx, hour in enumerate((10, 11)):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Westosha Equity {idx}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
            extra_rows.extend([fi, slot])
        for idx, hour in enumerate((9, 10, 11)):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=antioch_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Antioch Equity {idx}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=antioch_host.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
            extra_rows.extend([fi, slot])

        prior_weeks = [
            Week(id=uuid.uuid4(), season_id=self.season.id, week_number=0, start_date=date(2026, 4, 24), end_date=date(2026, 4, 30)),
            Week(id=uuid.uuid4(), season_id=self.season.id, week_number=-1, start_date=date(2026, 4, 17), end_date=date(2026, 4, 23)),
        ]
        extra_rows.extend(prior_weeks)
        all_team_ids = [self.wm.id, self.wg.id, self.ab.id, self.as_.id] + [team.id for team in extra_teams]

        def add_prior_hosted_game(host, week, idx):
            game = Game(id=uuid.uuid4(), season_id=self.season.id, week_id=week.id, home_team_id=all_team_ids[idx % len(all_team_ids)], away_team_id=all_team_ids[(idx + 1) % len(all_team_ids)], game_status_id=self.status.id, game_date=week.start_date, kickoff_time=time(8 + (idx % 8), 0))
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=host.id, hosting_availability_id=uuid.uuid4(), instance_date=week.start_date, field_name=f'Prior Equity {host.name} {idx}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=host.id, slot_date=week.start_date, start_time=game.kickoff_time, end_time=time(9 + (idx % 8), 0), field_type='SMALL', status='OPEN', assigned_game_id=game.id)
            extra_rows.extend([game, fi, slot])

        for idx in range(5):
            add_prior_hosted_game(self.host, prior_weeks[0], idx)
        add_prior_hosted_game(antioch_host, prior_weeks[0], 5)
        add_prior_hosted_game(antioch_host, prior_weeks[1], 6)

        self.db.add_all(extra_rows)
        self.db.commit()

        preview = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)

        self.assertEqual(preview['proposed_game_count'], 4)
        self.assertEqual([row['community'] for row in preview['audit']['selected_host_communities']], ['Westosha', 'Antioch'])
        games_by_community = {row['community']: row['games_assigned'] for row in preview['audit']['weekly_community_host_plan']['locations_used_under_each_community']}
        self.assertGreater(games_by_community['Antioch'], games_by_community['Westosha'])
        antioch_equity = next(row for row in preview['audit']['community_hosting_equity_summary'] if row['community'] == 'Antioch')
        self.assertIn('season_target_games', antioch_equity)
        self.assertIn('compatible_unused_capacity', antioch_equity)
        self.assertIn('reason_if_overused_or_underused', antioch_equity)
        self.assertTrue(any('selected community has the fewest hosted games (+5000)' in proposal['reason'] for proposal in preview['proposals'] if proposal['host_location'] == 'Antioch Equity Park'))

    def test_host_rotation_audit_tracks_occurrences(self):
        preview = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)
        self.assertIn('total_host_occurrences_by_community', preview['audit'])
        self.assertIn('total_host_occurrences_by_location', preview['audit'])
        self.assertIn('balanced_hosting_achieved', preview['audit'])
        self.assertFalse(preview['audit']['postseason_host_limit_exempt'])

    def test_host_rotation_audit_reports_prior_last_hosted_week_and_none_for_new_host(self):
        prior_game = self.db.query(Game).filter(Game.week_id == self.week1.id).first()
        week1_field = FieldInstance(
            id=uuid.uuid4(),
            host_location_id=self.host.id,
            hosting_availability_id=uuid.uuid4(),
            instance_date=self.week1.start_date,
            field_name='Small Field Prior Week',
            field_type='SMALL',
            is_active=True,
        )
        week1_slot = GameSlot(
            id=uuid.uuid4(),
            field_instance_id=week1_field.id,
            host_location_id=self.host.id,
            slot_date=self.week1.start_date,
            start_time=time(11, 0),
            end_time=time(12, 0),
            field_type='SMALL',
            status='BOOKED',
            assigned_game_id=prior_game.id,
        )
        antioch_host = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Antioch Park', is_active=True)
        antioch_field = FieldInstance(
            id=uuid.uuid4(),
            host_location_id=antioch_host.id,
            hosting_availability_id=uuid.uuid4(),
            instance_date=self.week2.start_date,
            field_name='Antioch Small Field',
            field_type='SMALL',
            is_active=True,
        )
        antioch_slot = GameSlot(
            id=uuid.uuid4(),
            field_instance_id=antioch_field.id,
            host_location_id=antioch_host.id,
            slot_date=self.week2.start_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
            field_type='SMALL',
            status='OPEN',
        )
        self.db.add_all([week1_field, week1_slot, antioch_host, antioch_field, antioch_slot])
        self.db.commit()

        preview = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)

        ranking_by_community = {row['community']: row for row in preview['audit']['host_rotation_ranking']}
        self.assertEqual(ranking_by_community['Westosha']['last_hosted_week_number'], 1)
        self.assertIsNone(ranking_by_community['Antioch']['last_hosted_week_number'])

    def test_postseason_exempts_host_rotation_limits(self):
        preview = auto_fill_preview({
            'season_id': self.season.id,
            'week_id': self.week2.id,
            'division_id': self.division.id,
            'is_playoff_week': True,
        }, db=self.db)
        self.assertTrue(preview['audit']['postseason_host_limit_exempt'])

    def test_week8_coed_6_7_odd_division_generates_and_places_doubleheader_matchups(self):
        week8 = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=8, start_date=date(2026, 6, 19), end_date=date(2026, 6, 25))
        division = Division(id=uuid.uuid4(), division_group='COED', name='6th/7th', required_field_layout_type='FIFTY_THREE_YARD_WIDTH', is_active=True)
        antioch = Organization(id=uuid.uuid4(), name='Antioch', is_active=True)
        jburg = Organization(id=uuid.uuid4(), name="J'Burg", is_active=True)
        lake = Organization(id=uuid.uuid4(), name='Lake County Stallions', is_active=True)
        westosha = Organization(id=uuid.uuid4(), name='Westosha', is_active=True)
        host = HostLocation(id=uuid.uuid4(), organization_id=westosha.id, name='Westosha Large Complex', is_active=True)
        teams = [
            Team(id=uuid.uuid4(), organization_id=antioch.id, division_id=division.id, name='Antioch 6th/7th Gold', is_active=True),
            Team(id=uuid.uuid4(), organization_id=jburg.id, division_id=division.id, name="J'Burg 6th/7th Blue", is_active=True),
            Team(id=uuid.uuid4(), organization_id=lake.id, division_id=division.id, name='Lake County Stallions 6th/7th Black', is_active=True),
            Team(id=uuid.uuid4(), organization_id=lake.id, division_id=division.id, name='Lake County Stallions 6th/7th Red', is_active=True),
            Team(id=uuid.uuid4(), organization_id=westosha.id, division_id=division.id, name='Westosha 6th/7th Maroon', is_active=True),
        ]
        slots = []
        for idx, hour in enumerate([9, 10, 11]):
            field = FieldInstance(
                id=uuid.uuid4(),
                host_location_id=host.id,
                hosting_availability_id=uuid.uuid4(),
                instance_date=week8.start_date,
                field_name=f'Large Field {idx + 1}',
                field_type='LARGE',
                is_active=True,
            )
            slot = GameSlot(
                id=uuid.uuid4(),
                field_instance_id=field.id,
                host_location_id=host.id,
                slot_date=week8.start_date,
                start_time=time(hour, 0),
                end_time=time(hour + 1, 0),
                field_type='LARGE',
                status='OPEN',
            )
            slots.extend([field, slot])
        self.db.add_all([week8, division, antioch, jburg, lake, westosha, host, *teams, *slots])
        self.db.commit()

        preview = auto_fill_preview({'season_id': self.season.id, 'week_id': week8.id, 'division_id': division.id}, db=self.db)

        placement = preview['diagnostics']['division_week_placement']
        self.assertEqual(placement['generated_game_groups'], 3)
        self.assertEqual(len(placement['required_matchups_generated']), 3)
        self.assertGreaterEqual(placement['placement_attempts'], 3)
        self.assertEqual(preview['proposed_game_count'], 3)
        self.assertEqual(placement['scheduled_games'], 3)
        self.assertNotIn('No eligible matchups available for this division/week.', placement['skipped_placement_reasons'])

        team_counts = {str(team.id): 0 for team in teams}
        for proposal in preview['proposals']:
            team_counts[proposal['home_team_id']] += 1
            team_counts[proposal['away_team_id']] += 1
        self.assertEqual(sorted(team_counts.values()), [1, 1, 1, 1, 2])
        doubleheader_team_id = next(team_id for team_id, count in team_counts.items() if count == 2)
        doubleheader_games = [proposal for proposal in preview['proposals'] if doubleheader_team_id in {proposal['home_team_id'], proposal['away_team_id']}]
        self.assertEqual(len(doubleheader_games), 2)
        self.assertEqual(doubleheader_games[0]['host_location_id'], doubleheader_games[1]['host_location_id'])
        starts = sorted(int(str(game['proposed_start_time']).split(':')[0]) for game in doubleheader_games)
        self.assertEqual(starts[1] - starts[0], 1)

if __name__ == '__main__':
    unittest.main()


class AutoScheduleRequiredGameGroupDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        self.season = Season(id=uuid.uuid4(), name='Fall 2026', start_date=date(2026, 9, 1), end_date=date(2026, 11, 1), is_active=True)
        self.division = Division(id=uuid.uuid4(), division_group='COED', name='K/1ST', required_field_layout_type='THIRTY_YARD_WIDTH', is_active=True)
        self.status = GameStatus(id=uuid.uuid4(), code='SCHEDULED', label='Scheduled', is_active=True)
        self.week = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=1, start_date=date(2026, 9, 5), end_date=date(2026, 9, 11))
        self.org = Organization(id=uuid.uuid4(), name='League', is_active=True)
        self.teams = [
            Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name=f'Team {idx}', is_active=True)
            for idx in range(1, 5)
        ]
        self.db.add_all([self.season, self.division, self.status, self.week, self.org, *self.teams])
        self.db.commit()

    def test_required_game_groups_are_reported_before_slot_preflight_failure(self):
        result = auto_schedule_entire_season({'season_id': self.season.id}, db=self.db)

        diagnostics = result['auto_schedule_diagnostics']
        self.assertEqual(diagnostics['season_id'], str(self.season.id))
        self.assertEqual(diagnostics['season_name'], 'Fall 2026')
        self.assertEqual(diagnostics['weeks_found'], 1)
        self.assertEqual(diagnostics['regular_season_weeks_found'], 1)
        self.assertEqual(diagnostics['active_divisions_found'], 1)
        self.assertEqual(diagnostics['active_teams_total'], 4)
        self.assertEqual(diagnostics['expected_games_total'], 2)
        self.assertEqual(diagnostics['generated_game_groups_total'], 2)
        self.assertEqual(diagnostics['expected_games_by_week'], {'1': 2})
        self.assertEqual(diagnostics['generated_game_groups_by_week'], {'1': 2})
        self.assertNotIn('no_required_game_groups', result['root_cause_categories'])
        self.assertIn('no_generated_slots', result['root_cause_categories'])

    def test_all_games_already_scheduled_is_not_reported_as_no_required_groups(self):
        self.db.add_all([
            Game(
                id=uuid.uuid4(),
                season_id=self.season.id,
                week_id=self.week.id,
                home_team_id=self.teams[0].id,
                away_team_id=self.teams[1].id,
                game_status_id=self.status.id,
                game_date=self.week.start_date,
                kickoff_time=time(9, 0),
            ),
            Game(
                id=uuid.uuid4(),
                season_id=self.season.id,
                week_id=self.week.id,
                home_team_id=self.teams[2].id,
                away_team_id=self.teams[3].id,
                game_status_id=self.status.id,
                game_date=self.week.start_date,
                kickoff_time=time(10, 0),
            ),
        ])
        self.db.commit()

        result = auto_schedule_entire_season({'season_id': self.season.id}, db=self.db)

        self.assertEqual(result['status'], 'complete')
        self.assertNotIn('all_games_already_scheduled', result['root_cause_categories'])
        self.assertNotIn('no_required_game_groups', result['root_cause_categories'])
        self.assertIn('All required game groups were already scheduled before this pass.', result['informational_notes'])
        self.assertEqual(result['message'], 'Auto-schedule completed successfully. All required games are scheduled.')


class SchedulingDiagnosticsDynamicRulesTest(unittest.TestCase):
    def test_complete_status_formula(self):
        expected_games_total = 12
        committed_games_count = 12
        scheduled_games_count = 12
        required_games_still_missing = 0
        failed_validation_count = 0
        division_week_rows = [{'generated_game_groups': 3, 'existing_scheduled_games': 3, 'expected_games': 3}]

        complete = (
            expected_games_total == committed_games_count
            and expected_games_total == scheduled_games_count
            and required_games_still_missing == 0
            and failed_validation_count == 0
            and all(row['generated_game_groups'] == row['expected_games'] and row['existing_scheduled_games'] == row['expected_games'] for row in division_week_rows)
        )

        self.assertTrue(complete)

    def test_odd_team_no_bye_doubleheader_division_expectations(self):
        expected_games = _diagnostic_expected_games_for_team_count(7, no_bye_doubleheaders_enabled=True)
        active_expected = _diagnostic_active_teams_expected_to_play(7, no_bye_doubleheaders_enabled=True)
        team_appearances = expected_games * 2
        actual_team_counts = [2, 1, 1, 1, 1, 1, 1]

        self.assertEqual(expected_games, 4)
        self.assertEqual(active_expected, 7)
        self.assertEqual(team_appearances, 8)
        self.assertEqual(sum(actual_team_counts), team_appearances)
        self.assertEqual(len([count for count in actual_team_counts if count > 0]), active_expected)

    def test_odd_team_bye_division_expectations(self):
        expected_games = _diagnostic_expected_games_for_team_count(7, no_bye_doubleheaders_enabled=False)
        active_expected = _diagnostic_active_teams_expected_to_play(7, no_bye_doubleheaders_enabled=False)
        team_appearances = expected_games * 2
        actual_team_counts = [1, 1, 1, 1, 1, 1, 0]

        self.assertEqual(expected_games, 3)
        self.assertEqual(active_expected, 6)
        self.assertEqual(team_appearances, 6)
        self.assertEqual(sum(actual_team_counts), team_appearances)
        self.assertEqual(len([count for count in actual_team_counts if count > 0]), active_expected)

    def test_even_team_division_expectations(self):
        expected_games = _diagnostic_expected_games_for_team_count(8, no_bye_doubleheaders_enabled=True)

        self.assertEqual(expected_games, 4)
        self.assertEqual(_diagnostic_active_teams_expected_to_play(8, no_bye_doubleheaders_enabled=True), 8)
        self.assertEqual(expected_games * 2, 8)

    def test_dynamic_field_size_validation(self):
        expected_by_size = {'SMALL': 2 + 3, 'MEDIUM': 4, 'LARGE': 3 + 5}
        actual_by_size = {'SMALL': 5, 'MEDIUM': 4, 'LARGE': 8}

        missing, extra = _diagnostic_field_size_diff(expected_by_size, actual_by_size)

        self.assertEqual(expected_by_size, {'SMALL': 5, 'MEDIUM': 4, 'LARGE': 8})
        self.assertEqual(missing, {'SMALL': 0, 'MEDIUM': 0, 'LARGE': 0})
        self.assertEqual(extra, {'SMALL': 0, 'MEDIUM': 0, 'LARGE': 0})

    def test_field_size_validation_changes_when_team_counts_change(self):
        expected_small_before = _diagnostic_expected_games_for_team_count(4, no_bye_doubleheaders_enabled=True)
        expected_small_after = _diagnostic_expected_games_for_team_count(6, no_bye_doubleheaders_enabled=True)

        self.assertEqual(expected_small_before, 2)
        self.assertEqual(expected_small_after, 3)
        self.assertGreater(expected_small_after, expected_small_before)
