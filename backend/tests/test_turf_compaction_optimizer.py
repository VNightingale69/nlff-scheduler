import os
import unittest
import uuid
from datetime import date, time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Division, FieldInstance, Game, GameScore, GameSlot, GameStatus, HostLocation, Organization, Season, Team, Week
from app.routes.api import _run_manual_optimization_workflow, get_saved_scheduled_game_rows_for_export, run_post_schedule_repair_pass


class TurfCompactionOptimizerTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            'sqlite+pysqlite:///:memory:',
            future=True,
            connect_args={'check_same_thread': False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        self.season = Season(id=uuid.uuid4(), name='Fall 2026', start_date=date(2026, 8, 1), end_date=date(2026, 11, 1), is_active=True)
        self.week = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=1, start_date=date(2026, 8, 9), end_date=date(2026, 8, 15), primary_game_date=date(2026, 8, 9))
        self.status = GameStatus(id=uuid.uuid4(), code='SCHEDULED', label='Scheduled', is_active=True)
        self.org = Organization(id=uuid.uuid4(), name='Host Org', is_active=True)
        self.host = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Host Turf Stadium', surface_type='TURF_STADIUM', max_small_fields=3, max_total_fields=3, is_active=True)
        self.division = Division(id=uuid.uuid4(), name='K-1', division_group='Coed', sort_order=1, required_field_layout_type='THIRTY_YARD_WIDTH', is_active=True)
        self.medium_division = Division(id=uuid.uuid4(), name='4-5', division_group='Coed', sort_order=2, required_field_layout_type='FIFTY_YARD', is_active=True)
        self.large_division = Division(id=uuid.uuid4(), name='6-7', division_group='Coed', sort_order=3, required_field_layout_type='FULL_FIELD', is_active=True)
        self.db.add_all([self.season, self.week, self.status, self.org, self.host, self.division, self.medium_division, self.large_division])
        self.fields = {}
        for label, field_type in (
            ('Small Field 1', 'SMALL'),
            ('Small Field 2', 'SMALL'),
            ('Small Field 3', 'SMALL'),
            ('Medium Field 1', 'MEDIUM'),
            ('Medium Field 2', 'MEDIUM'),
            ('Large Field 1', 'LARGE'),
        ):
            field = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=date(2026, 8, 9), field_name=label, field_type=field_type, is_active=True)
            self.fields[label] = field
            self.db.add(field)
        self.teams = []
        for idx in range(30):
            if idx >= 20:
                division = self.large_division
            elif idx >= 10:
                division = self.medium_division
            else:
                division = self.division
            team = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=division.id, name=f'Team {idx}', is_active=True)
            self.teams.append(team)
            self.db.add(team)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        for key in ('SCHEDULE_OPTIMIZATION_MAX_RUNTIME_SECONDS', 'SCHEDULE_OPTIMIZATION_MAX_CANDIDATES_EVALUATED', 'SCHEDULE_OPTIMIZATION_MAX_ACCEPTED_MOVES', 'SCHEDULE_OPTIMIZATION_MAX_CANDIDATES_PER_SINGLE_BLOCK'):
            os.environ.pop(key, None)

    def _slot(self, label, start, assigned_game_id=None):
        end = time(start.hour + 1, start.minute)
        field = self.fields[label]
        slot = GameSlot(
            id=uuid.uuid4(),
            field_instance_id=field.id,
            host_location_id=self.host.id,
            season_id=self.season.id,
            week_id=self.week.id,
            slot_date=date(2026, 8, 9),
            start_time=start,
            end_time=end,
            field_type=field.field_type,
            status='BOOKED' if assigned_game_id else 'OPEN',
            assigned_game_id=assigned_game_id,
        )
        self.db.add(slot)
        return slot


    def _add_turf_host(self, name='Additional Turf Stadium', surface_type='TURF_STADIUM'):
        host = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name=name, surface_type=surface_type, max_small_fields=3, max_total_fields=3, is_active=True)
        self.db.add(host)
        fields = {}
        for label, field_type in (
            ('Small Field 1', 'SMALL'),
            ('Small Field 2', 'SMALL'),
            ('Small Field 3', 'SMALL'),
            ('Medium Field 1', 'MEDIUM'),
            ('Medium Field 2', 'MEDIUM'),
            ('Large Field 1', 'LARGE'),
        ):
            field = FieldInstance(id=uuid.uuid4(), host_location_id=host.id, hosting_availability_id=uuid.uuid4(), instance_date=date(2026, 8, 9), field_name=label, field_type=field_type, is_active=True)
            fields[label] = field
            self.db.add(field)
        self.db.flush()
        return host, fields

    def _slot_for(self, host, fields, label, start, assigned_game_id=None):
        end = time(start.hour + 1, start.minute)
        field = fields[label]
        slot = GameSlot(
            id=uuid.uuid4(),
            field_instance_id=field.id,
            host_location_id=host.id,
            season_id=self.season.id,
            week_id=self.week.id,
            slot_date=date(2026, 8, 9),
            start_time=start,
            end_time=end,
            field_type=field.field_type,
            status='BOOKED' if assigned_game_id else 'OPEN',
            assigned_game_id=assigned_game_id,
        )
        self.db.add(slot)
        return slot

    def _game(self, home_idx, away_idx, slot, *, manual=False):
        game = Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            home_team_id=self.teams[home_idx].id,
            away_team_id=self.teams[away_idx].id,
            game_status_id=self.status.id,
            host_location_id=slot.host_location_id,
            field_instance_id=slot.field_instance_id,
            game_date=slot.slot_date,
            kickoff_time=slot.start_time,
            is_manual_edit=manual,
            manual_edit_locked=manual,
        )
        self.db.add(game)
        self.db.flush()
        slot.assigned_game_id = game.id
        slot.status = 'BOOKED'
        return game

    def test_safe_turf_compaction_move_pairs_single_game_blocks(self):
        target_booked = self._slot('Small Field 1', time(9, 0))
        target_open = self._slot('Small Field 2', time(9, 0))
        source_slot = self._slot('Small Field 1', time(11, 0))
        self._game(0, 1, target_booked)
        source_game = self._game(2, 3, source_slot)
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        self.assertEqual(diagnostics['summary']['optimization_scope'], 'DETERMINISTIC_SAME_STADIUM_DATE_TURF_REPACKING')
        self.assertGreaterEqual(diagnostics['summary']['optimization_candidates_evaluated'], 1)
        self.assertEqual(diagnostics['summary']['accepted_optimization_moves'], 1)
        self.assertEqual(diagnostics['summary']['measurable_improvements_found'], 'Yes')
        self.assertEqual(diagnostics['summary']['metrics_calculated_from_preview_state'], 'Yes')
        accepted_change = diagnostics['accepted_changes'][0]
        self.assertEqual(accepted_change['atomic_or_bundled'], 'turf_stadium_date_repack')
        self.assertTrue(accepted_change['turf_metric_improved'])
        self.assertGreater(accepted_change['score_delta'], 0)
        self.assertEqual(diagnostics['summary']['total_turf_single_game_blocks_after'], 0)
        self.assertEqual(diagnostics['summary']['total_turf_two_game_blocks_after'], 1)
        self.assertLessEqual(diagnostics['summary']['optimization_runtime_seconds'], diagnostics['summary']['optimization_runtime_limit_seconds'])
        self.db.refresh(source_game)
        self.assertEqual(source_game.kickoff_time, time(9, 0))
        self.assertEqual(source_game.field_instance_id, target_open.field_instance_id)

    def test_unsafe_team_time_conflict_is_rejected_with_reason(self):
        target_booked = self._slot('Small Field 1', time(9, 0))
        self._slot('Small Field 2', time(9, 0))
        source_slot = self._slot('Small Field 1', time(11, 0))
        self._game(0, 1, target_booked)
        self._game(0, 2, source_slot)
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        self.assertEqual(diagnostics['summary']['accepted_optimization_moves'], 0)
        self.assertEqual(diagnostics['summary']['measurable_improvements_found'], 'No')
        self.assertIn('team-time conflict', diagnostics['summary']['rejected_moves_by_reason'])
        self.assertIn('No measurable turf stadium improvement found', diagnostics['summary']['no_safe_moves_message'])

    def test_manual_edited_games_are_locked_unless_included(self):
        target_booked = self._slot('Small Field 1', time(9, 0))
        self._slot('Small Field 2', time(9, 0))
        source_slot = self._slot('Small Field 1', time(11, 0))
        self._game(0, 1, target_booked)
        source_game = self._game(2, 3, source_slot, manual=True)
        self.db.commit()

        locked = run_post_schedule_repair_pass(self.db, self.season.id, include_manual_edits=False)
        self.assertEqual(locked['summary']['accepted_optimization_moves'], 0)
        self.assertIn('game locked by manual edit', locked['summary']['rejected_moves_by_reason'])
        self.db.rollback()

        included = run_post_schedule_repair_pass(self.db, self.season.id, include_manual_edits=True)
        self.assertEqual(included['summary']['accepted_optimization_moves'], 1)
        self.db.refresh(source_game)
        self.assertEqual(source_game.kickoff_time, time(9, 0))


    def test_preview_rolls_back_so_export_uses_saved_authoritative_schedule_until_applied(self):
        target_booked = self._slot('Small Field 1', time(9, 0))
        self._slot('Small Field 2', time(9, 0))
        source_slot = self._slot('Small Field 1', time(11, 0))
        self._game(0, 1, target_booked)
        source_game = self._game(2, 3, source_slot)
        self.db.commit()

        preview = _run_manual_optimization_workflow({'season_id': self.season.id}, self.db, apply=False)

        self.assertTrue(preview['preview'])
        self.assertEqual(preview['summary']['accepted_optimization_moves'], 1)
        self.db.expire_all()
        saved_source = self.db.get(Game, source_game.id)
        self.assertEqual(saved_source.kickoff_time, time(11, 0))
        export_rows = get_saved_scheduled_game_rows_for_export(self.db, self.season.id)
        exported_source = next(row for row in export_rows if row[0].id == source_game.id)
        self.assertEqual(exported_source[0].kickoff_time, time(11, 0))

    def test_repack_evaluation_counts_stadium_dates(self):
        target_booked = self._slot('Small Field 1', time(9, 0))
        self._slot('Small Field 2', time(9, 0))
        source_slot = self._slot('Small Field 1', time(11, 0))
        self._game(0, 1, target_booked)
        self._game(2, 3, source_slot)
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        self.assertEqual(diagnostics['summary']['turf_stadium_date_repacks_evaluated'], 1)
        self.assertEqual(diagnostics['summary']['repacked_dates_accepted'], 1)
        self.assertIn('per_stadium_date_diagnostics', diagnostics['summary'])


    def test_large_field_bottleneck_converts_three_small_when_full_day_improves(self):
        early_small_slots = [self._slot(f'Small Field {idx}', time(9, 0)) for idx in (1, 2, 3)]
        later_small_slots = [self._slot(f'Small Field {idx}', time(10, 0)) for idx in (1, 2, 3)]
        self._slot('Large Field 1', time(9, 0))
        late_large_slot = self._slot('Large Field 1', time(16, 0))
        for idx, slot in enumerate(early_small_slots):
            self._game(idx * 2, idx * 2 + 1, slot)
        self._game(6, 7, later_small_slots[0])
        large_game = self._game(20, 21, late_large_slot)
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        self.db.refresh(large_game)
        self.assertEqual(large_game.kickoff_time, time(9, 0))
        self.assertEqual(diagnostics['summary']['latest_turf_start_time_after'], '10:00:00')
        self.assertLess(diagnostics['summary']['total_turf_active_time_blocks_after'], diagnostics['summary']['total_turf_active_time_blocks_before'])
        repack = diagnostics['accepted_changes'][0]
        self.assertEqual(repack['atomic_or_bundled'], 'turf_stadium_date_repack')
        self.assertIn('ONE_SMALL_ONE_LARGE', repack['target_layout_attempted'])
        bottleneck = diagnostics['summary']['large_field_bottleneck_diagnostics'][0]
        self.assertEqual(bottleneck['small_count'], 4)
        self.assertEqual(bottleneck['large_count'], 1)

    def test_high_priority_large_bottleneck_runs_before_generic_single_game_pairing(self):
        early_small_slots = [self._slot(f'Small Field {idx}', time(9, 0)) for idx in (1, 2, 3)]
        later_small_slots = [self._slot(f'Small Field {idx}', time(10, 0)) for idx in (1, 2, 3)]
        self._slot('Large Field 1', time(9, 0))
        late_large_slot = self._slot('Large Field 1', time(16, 0))
        generic_target = self._slot('Medium Field 1', time(12, 0))
        self._slot('Medium Field 2', time(12, 0))
        generic_source = self._slot('Medium Field 1', time(13, 0))
        for idx, slot in enumerate(early_small_slots):
            self._game(idx * 2, idx * 2 + 1, slot)
        self._game(6, 7, later_small_slots[0])
        large_game = self._game(20, 21, late_large_slot)
        self._game(8, 9, generic_target)
        self._game(10, 11, generic_source)
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        self.db.refresh(large_game)
        self.assertEqual(large_game.kickoff_time, time(9, 0))
        self.assertIn('ONE_SMALL_ONE_LARGE', diagnostics['accepted_changes'][0]['target_layout_attempted'])
        self.assertEqual(diagnostics['summary']['repacked_dates_accepted'], 1)


    def test_no_op_optimization_is_reported_when_no_measurable_improvement_exists(self):
        self._game(0, 1, self._slot('Small Field 1', time(9, 0)))
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        self.assertEqual(diagnostics['summary']['accepted_optimization_moves'], 0)
        self.assertEqual(diagnostics['summary']['measurable_improvements_found'], 'No')
        self.assertIn('No measurable turf stadium improvement found', diagnostics['summary']['no_safe_moves_message'])
        self.assertEqual(diagnostics['summary']['metrics_calculated_from_preview_state'], 'Yes')

    def test_valid_empty_block_reshuffle_without_turf_improvement_is_rejected(self):
        source_slot = self._slot('Medium Field 1', time(11, 0))
        empty_target = self._slot('Medium Field 1', time(12, 0))
        source_game = self._game(10, 11, source_slot)
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        self.db.refresh(source_game)
        self.assertEqual(source_game.kickoff_time, time(11, 0))
        self.assertEqual(source_game.field_instance_id, source_slot.field_instance_id)
        self.assertEqual(empty_target.assigned_game_id, None)
        self.assertEqual(diagnostics['summary']['accepted_optimization_moves'], 0)
        self.assertEqual(diagnostics['summary']['measurable_improvements_found'], 'No')
        self.assertEqual(diagnostics['summary']['stop_reason'], 'No measurable turf stadium improvement found.')
        self.assertIn('Rejected: valid candidate but no measurable turf stadium improvement.', diagnostics['summary']['rejected_moves_by_reason'])
        rejected = next(change for change in diagnostics['rejected_changes'] if change['reason'] == 'Rejected: valid candidate but no measurable turf stadium improvement.')
        self.assertEqual(rejected['turf_metric_before_value']['active_blocks'], rejected['turf_metric_after_value']['active_blocks'])
        self.assertEqual(rejected['turf_metric_before_value']['single_game_blocks'], rejected['turf_metric_after_value']['single_game_blocks'])

    def test_field_reassignment_same_time_without_turf_improvement_is_rejected(self):
        source_slot = self._slot('Small Field 1', time(9, 0))
        empty_same_block_slot = self._slot('Small Field 2', time(9, 0))
        source_game = self._game(0, 1, source_slot)
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        self.db.refresh(source_game)
        self.assertEqual(source_game.field_instance_id, source_slot.field_instance_id)
        self.assertEqual(empty_same_block_slot.assigned_game_id, None)
        self.assertEqual(diagnostics['summary']['accepted_optimization_moves'], 0)
        self.assertEqual(diagnostics['summary']['total_turf_active_time_blocks_before'], diagnostics['summary']['total_turf_active_time_blocks_after'])
        self.assertIn('Rejected: valid candidate but no measurable turf stadium improvement.', diagnostics['summary']['rejected_moves_by_reason'])

    def test_accepted_changes_include_required_metric_impact_fields(self):
        target_booked = self._slot('Small Field 1', time(9, 0))
        self._slot('Small Field 2', time(9, 0))
        source_slot = self._slot('Small Field 1', time(11, 0))
        self._game(0, 1, target_booked)
        self._game(2, 3, source_slot)
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        accepted_change = diagnostics['accepted_changes'][0]
        self.assertEqual(diagnostics['summary']['accepted_optimization_moves'], 1)
        self.assertEqual(diagnostics['summary']['candidates_accepted'], 1)
        self.assertTrue(accepted_change['metric_impact'])
        self.assertTrue(accepted_change['metric_improved'])
        self.assertGreater(accepted_change['score_delta'], 0)
        self.assertIn('accepted_reason', accepted_change)
        self.assertIn('turf_metric_before_value', accepted_change)
        self.assertIn('turf_metric_after_value', accepted_change)

    def test_per_stadium_diagnostics_include_three_or_more_configured_turf_stadiums(self):
        host_two, fields_two = self._add_turf_host('Second Turf Stadium')
        host_three, fields_three = self._add_turf_host('Future Turf Stadium', surface_type='ARTIFICIAL_TURF_STADIUM')
        self._game(0, 1, self._slot('Small Field 1', time(9, 0)))
        self._game(2, 3, self._slot_for(host_two, fields_two, 'Small Field 1', time(10, 0)))
        self._game(4, 5, self._slot_for(host_three, fields_three, 'Small Field 1', time(11, 0)))
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        per_stadium = diagnostics['summary']['per_stadium_turf_metrics']
        self.assertEqual(diagnostics['summary']['turf_stadium_count'], 3)
        self.assertEqual({row['host_location_name'] for row in per_stadium}, {'Host Turf Stadium', 'Second Turf Stadium', 'Future Turf Stadium'})
        self.assertTrue(all('late_large_game_count_at_3pm_or_4pm_before' in row for row in per_stadium))
        self.assertEqual(diagnostics['summary']['accepted_optimization_moves'], 0)
        self.assertEqual(diagnostics['summary']['stop_reason'], 'No measurable turf stadium improvement found.')

    def test_one_configured_turf_stadium_is_supported(self):
        self._game(0, 1, self._slot('Small Field 1', time(9, 0)))
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        self.assertEqual(diagnostics['summary']['turf_stadium_count'], 1)
        self.assertEqual(len(diagnostics['summary']['per_stadium_turf_metrics']), 1)
        self.assertEqual(diagnostics['summary']['per_stadium_turf_metrics'][0]['host_location_name'], 'Host Turf Stadium')

    def test_two_configured_turf_stadiums_are_supported(self):
        host_two, fields_two = self._add_turf_host('Second Turf Stadium')
        self._game(0, 1, self._slot('Small Field 1', time(9, 0)))
        self._game(2, 3, self._slot_for(host_two, fields_two, 'Small Field 1', time(10, 0)))
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        self.assertEqual(diagnostics['summary']['turf_stadium_count'], 2)
        self.assertEqual({row['host_location_name'] for row in diagnostics['summary']['per_stadium_turf_metrics']}, {'Host Turf Stadium', 'Second Turf Stadium'})

    def test_turf_labels_are_standard_and_grass_labels_are_not_normalized(self):
        grass = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Grass Park', surface_type='GRASS_FIELD', is_active=True)
        grass_field = FieldInstance(id=uuid.uuid4(), host_location_id=grass.id, hosting_availability_id=uuid.uuid4(), instance_date=date(2026, 8, 9), field_name='North Diamond', field_type='SMALL', is_active=True)
        self.db.add_all([grass, grass_field])
        self._game(0, 1, self._slot('Small Field 1', time(9, 0)))
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        self.assertEqual(diagnostics['summary']['turf_stadium_count'], 1)
        self.assertEqual(grass_field.field_name, 'North Diamond')
        turf_labels = {field.field_name for field in self.fields.values()}
        self.assertLessEqual(turf_labels, {'Small Field 1', 'Small Field 2', 'Small Field 3', 'Medium Field 1', 'Medium Field 2', 'Large Field 1'})

    def test_rejection_reasons_logged_are_distinct_from_rejected_candidate_records(self):
        source_slot = self._slot('Medium Field 1', time(11, 0))
        self._slot('Medium Field 1', time(12, 0))
        self._game(10, 11, source_slot)
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        self.assertIn('candidates_rejected', diagnostics['summary'])
        self.assertIn('rejection_reasons_logged', diagnostics['summary'])
        self.assertLessEqual(diagnostics['summary']['candidates_rejected'], diagnostics['summary']['rejection_reasons_logged'])

    def test_large_field_bottleneck_bundle_counts_only_completed_bundle(self):
        early_small_slots = [self._slot(f'Small Field {idx}', time(9, 0)) for idx in (1, 2, 3)]
        later_small_slots = [self._slot(f'Small Field {idx}', time(10, 0)) for idx in (1, 2, 3)]
        self._slot('Large Field 1', time(9, 0))
        late_large_slot = self._slot('Large Field 1', time(16, 0))
        for idx, slot in enumerate(early_small_slots):
            self._game(idx * 2, idx * 2 + 1, slot)
        self._game(6, 7, later_small_slots[0])
        self._game(20, 21, late_large_slot)
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        accepted = diagnostics['accepted_changes']
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]['atomic_or_bundled'], 'turf_stadium_date_repack')
        self.assertIn('ONE_SMALL_ONE_LARGE', accepted[0]['target_layout_attempted'])
        self.assertEqual(diagnostics['summary']['candidates_accepted'], 1)

    def test_repacker_preserves_game_set_ids_host_date_and_score_relationships(self):
        target = self._slot('Small Field 1', time(9, 0))
        self._slot('Small Field 2', time(9, 0))
        source = self._slot('Small Field 1', time(11, 0))
        stable = self._game(0, 1, target)
        moved = self._game(2, 3, source)
        score = GameScore(id=uuid.uuid4(), game_id=moved.id, score_status='SCHEDULED')
        self.db.add(score)
        original_game_ids = {stable.id, moved.id}
        original_host_id = moved.host_location_id
        original_date = moved.game_date
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        self.assertEqual(diagnostics['summary']['accepted_optimization_moves'], 1)
        self.db.refresh(moved)
        self.db.refresh(score)
        self.assertEqual({stable.id, moved.id}, original_game_ids)
        self.assertEqual(moved.id, score.game_id)
        self.assertEqual(moved.host_location_id, original_host_id)
        self.assertEqual(moved.game_date, original_date)
        self.assertEqual(moved.kickoff_time, time(9, 0))

    def test_four_small_three_medium_three_large_uses_large_bottleneck_compact_pattern(self):
        games = []
        # Four small games originally spread into early and late single blocks.
        for idx, start_hour in enumerate((9, 10, 15, 16)):
            games.append(self._game(idx * 2, idx * 2 + 1, self._slot('Small Field 1', time(start_hour, 0))))
        # Three medium games.
        for idx, start_hour in enumerate((12, 14, 16)):
            games.append(self._game(10 + idx * 2, 11 + idx * 2, self._slot('Medium Field 1', time(start_hour, 0))))
        # Three large games extending the day.
        for idx, start_hour in enumerate((13, 15, 16)):
            games.append(self._game(20 + idx * 2, 21 + idx * 2, self._slot('Large Field 1', time(start_hour, 0))))
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        self.assertEqual(diagnostics['summary']['accepted_optimization_moves'], 1)
        self.assertEqual(diagnostics['summary']['latest_turf_start_time_after'], '13:00:00')
        date_diag = diagnostics['summary']['per_stadium_date_diagnostics'][0]
        self.assertEqual((date_diag['small_count'], date_diag['medium_count'], date_diag['large_count']), (4, 3, 3))
        self.assertEqual(date_diag['target_layout_attempted'][:5], ['ONE_SMALL_ONE_LARGE', 'ONE_SMALL_ONE_LARGE', 'ONE_SMALL_ONE_LARGE', 'TWO_SMALL_ONE_MEDIUM', 'TWO_MEDIUM'])
        by_time = {}
        for game in games:
            self.db.refresh(game)
            label = self.db.get(FieldInstance, game.field_instance_id).field_name
            by_time.setdefault(game.kickoff_time, set()).add(label)
        self.assertEqual(by_time[time(9, 0)], {'Small Field 1', 'Large Field 1'})
        self.assertEqual(by_time[time(10, 0)], {'Small Field 1', 'Large Field 1'})
        self.assertEqual(by_time[time(11, 0)], {'Small Field 1', 'Large Field 1'})
        self.assertEqual(by_time[time(12, 0)], {'Small Field 1', 'Medium Field 1'})
        self.assertEqual(by_time[time(13, 0)], {'Medium Field 1', 'Medium Field 2'})

    def test_three_small_preserved_when_large_demand_already_satisfied(self):
        small_games = [self._game(idx * 2, idx * 2 + 1, self._slot('Small Field 1', time(hour, 0))) for idx, hour in enumerate((9, 11, 12))]
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        self.assertEqual(diagnostics['summary']['accepted_optimization_moves'], 1)
        accepted = diagnostics['accepted_changes'][0]
        self.assertIn('THREE_SMALL', accepted['target_layout_attempted'])
        for game in small_games:
            self.db.refresh(game)
            self.assertEqual(game.kickoff_time, time(9, 0))
        labels = {self.db.get(FieldInstance, game.field_instance_id).field_name for game in small_games}
        self.assertEqual(labels, {'Small Field 1', 'Small Field 2', 'Small Field 3'})

    def test_global_and_per_stadium_date_metrics_reconcile(self):
        host_two, fields_two = self._add_turf_host('Second Turf Stadium')
        self._game(0, 1, self._slot('Small Field 1', time(9, 0)))
        self._game(2, 3, self._slot('Small Field 1', time(11, 0)))
        self._game(4, 5, self._slot_for(host_two, fields_two, 'Small Field 1', time(10, 0)))
        self._game(6, 7, self._slot_for(host_two, fields_two, 'Small Field 1', time(12, 0)))
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        per_stadium = diagnostics['summary']['per_stadium_turf_metrics']
        self.assertEqual(sum(row['active_blocks_after'] for row in per_stadium), diagnostics['summary']['total_turf_active_time_blocks_after'])
        self.assertEqual(sum(row['single_game_blocks_after'] for row in per_stadium), diagnostics['summary']['total_turf_single_game_blocks_after'])
        self.assertEqual(sum(row['two_game_blocks_after'] for row in per_stadium), diagnostics['summary']['total_turf_two_game_blocks_after'])
        date_diags = diagnostics['summary']['per_stadium_date_diagnostics']
        self.assertEqual(sum(row['repacked_active_blocks'] for row in date_diags), diagnostics['summary']['total_turf_active_time_blocks_after'])
        self.assertEqual(sum(row['repacked_single_game_blocks'] for row in date_diags), diagnostics['summary']['total_turf_single_game_blocks_after'])
        self.assertEqual(sum(row['repacked_two_game_blocks'] for row in date_diags), diagnostics['summary']['total_turf_two_game_blocks_after'])

if __name__ == '__main__':
    unittest.main()
