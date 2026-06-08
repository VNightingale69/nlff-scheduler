import os
import unittest
import uuid
from datetime import date, time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Division, FieldInstance, Game, GameSlot, GameStatus, HostLocation, Organization, Season, Team, Week
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
        self.db.add_all([self.season, self.week, self.status, self.org, self.host, self.division])
        self.fields = {}
        for label in ('Small Field 1', 'Small Field 2', 'Small Field 3'):
            field = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=date(2026, 8, 9), field_name=label, field_type='SMALL', is_active=True)
            self.fields[label] = field
            self.db.add(field)
        self.teams = []
        for idx in range(10):
            team = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name=f'Team {idx}', is_active=True)
            self.teams.append(team)
            self.db.add(team)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        for key in ('SCHEDULE_OPTIMIZATION_MAX_RUNTIME_SECONDS', 'SCHEDULE_OPTIMIZATION_MAX_CANDIDATES_EVALUATED', 'SCHEDULE_OPTIMIZATION_MAX_ACCEPTED_MOVES', 'SCHEDULE_OPTIMIZATION_MAX_CANDIDATES_PER_SINGLE_BLOCK'):
            os.environ.pop(key, None)

    def _slot(self, label, start, assigned_game_id=None):
        end = time(start.hour + 1, start.minute)
        slot = GameSlot(
            id=uuid.uuid4(),
            field_instance_id=self.fields[label].id,
            host_location_id=self.host.id,
            season_id=self.season.id,
            week_id=self.week.id,
            slot_date=date(2026, 8, 9),
            start_time=start,
            end_time=end,
            field_type='SMALL',
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

        self.assertEqual(diagnostics['summary']['optimization_scope'], 'TARGETED_TURF_STADIUM_COMPACTION_ONLY')
        self.assertGreaterEqual(diagnostics['summary']['optimization_candidates_evaluated'], 1)
        self.assertEqual(diagnostics['summary']['accepted_optimization_moves'], 1)
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
        self.assertIn('team-time conflict', diagnostics['summary']['rejected_moves_by_reason'])
        self.assertIn('No turf compaction moves were accepted.', diagnostics['summary']['no_safe_moves_message'])

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

    def test_candidate_evaluations_are_capped(self):
        os.environ['SCHEDULE_OPTIMIZATION_MAX_CANDIDATES_EVALUATED'] = '1'
        target_booked = self._slot('Small Field 1', time(9, 0))
        self._slot('Small Field 2', time(9, 0))
        source_slot = self._slot('Small Field 1', time(11, 0))
        self._game(0, 1, target_booked)
        self._game(2, 3, source_slot)
        self.db.commit()

        diagnostics = run_post_schedule_repair_pass(self.db, self.season.id)

        self.assertLessEqual(diagnostics['summary']['optimization_candidates_evaluated'], 1)
        self.assertEqual(diagnostics['summary']['stop_reason'], 'candidate evaluation limit reached')


if __name__ == '__main__':
    unittest.main()
