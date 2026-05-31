import unittest
import uuid
from datetime import date, time
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.auth import ROLE_LEAGUE_ADMIN
from app.database import Base
from app.models import Division, FieldInstance, Game, GameSlot, GameStatus, HostLocation, HostPlanSelection, HostingAvailability, Organization, Role, Season, Team, Week
from app.routes.api import GENERATED_SLOTS_CLEAR_WARNING, clear_generated_game_slots, _regenerate_and_validate_slots_for_weeks


class GeneratedSlotsClearTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()

        self.org = Organization(id=uuid.uuid4(), name='Org A', is_active=True)
        self.other_org = Organization(id=uuid.uuid4(), name='Org B', is_active=True)
        self.host = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Host A', is_active=True)
        self.other_host = HostLocation(id=uuid.uuid4(), organization_id=self.other_org.id, name='Host B', is_active=True)
        self.availability = HostingAvailability(id=uuid.uuid4(), organization_id=self.org.id, host_location_id=self.host.id, available_date=date(2026, 6, 6), start_time=time(9, 0), end_time=time(11, 0), is_available=True)
        self.other_availability = HostingAvailability(id=uuid.uuid4(), organization_id=self.other_org.id, host_location_id=self.other_host.id, available_date=date(2026, 6, 6), start_time=time(9, 0), end_time=time(10, 0), is_available=True)
        self.open_instance = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=self.availability.id, instance_date=date(2026, 6, 6), field_name='Open Field', field_type='SMALL', is_active=True)
        self.scheduled_instance = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=self.availability.id, instance_date=date(2026, 6, 6), field_name='Scheduled Field', field_type='SMALL', is_active=True)
        self.other_instance = FieldInstance(id=uuid.uuid4(), host_location_id=self.other_host.id, hosting_availability_id=self.other_availability.id, instance_date=date(2026, 6, 6), field_name='Other Field', field_type='SMALL', is_active=True)
        self.open_slot = GameSlot(id=uuid.uuid4(), field_instance_id=self.open_instance.id, host_location_id=self.host.id, slot_date=date(2026, 6, 6), start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='OPEN')
        self.scheduled_slot = GameSlot(id=uuid.uuid4(), field_instance_id=self.scheduled_instance.id, host_location_id=self.host.id, slot_date=date(2026, 6, 6), start_time=time(10, 0), end_time=time(11, 0), field_type='SMALL', status='OPEN')
        self.other_slot = GameSlot(id=uuid.uuid4(), field_instance_id=self.other_instance.id, host_location_id=self.other_host.id, slot_date=date(2026, 6, 6), start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='OPEN')
        self.division = Division(id=uuid.uuid4(), name='K/1st', division_group='COED', sort_order=1, required_field_layout_type='SMALL', is_active=True)
        self.status = GameStatus(id=uuid.uuid4(), code='scheduled', label='Scheduled', is_active=True)
        self.home = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='Home', is_active=True)
        self.away = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='Away', is_active=True)
        self.game = Game(id=uuid.uuid4(), home_team_id=self.home.id, away_team_id=self.away.id, host_location_id=self.host.id, field_instance_id=self.scheduled_instance.id, game_status_id=self.status.id, game_date=date(2026, 6, 6), kickoff_time=time(10, 0))
        self.scheduled_slot.assigned_game_id = self.game.id

        self.db.add_all([
            self.org, self.other_org, self.host, self.other_host, self.availability, self.other_availability,
            self.open_instance, self.scheduled_instance, self.other_instance, self.open_slot, self.scheduled_slot,
            self.other_slot, self.division, self.status, self.home, self.away, self.game,
        ])
        self.db.commit()
        self.current_user = SimpleNamespace(role=Role(name=ROLE_LEAGUE_ADMIN), organization_id=None)

    def test_clear_deletes_only_selected_host_unassigned_slots_and_unused_instances(self):
        result = clear_generated_game_slots(host_location_id=self.host.id, current_user=self.current_user, db=self.db)

        self.assertEqual(result.slots_deleted, 1)
        self.assertEqual(result.field_instances_deleted, 1)
        self.assertEqual(result.field_instances_preserved, 1)
        self.assertEqual(result.games_preserved, 1)
        self.assertEqual(result.warning, GENERATED_SLOTS_CLEAR_WARNING)
        self.assertIsNone(self.db.get(GameSlot, self.open_slot.id))
        self.assertIsNone(self.db.get(FieldInstance, self.open_instance.id))
        self.assertIsNotNone(self.db.get(GameSlot, self.scheduled_slot.id))
        self.assertIsNotNone(self.db.get(Game, self.game.id))
        self.assertFalse(self.db.get(FieldInstance, self.scheduled_instance.id).is_active)
        self.assertIsNotNone(self.db.get(GameSlot, self.other_slot.id))
        self.assertIsNotNone(self.db.get(FieldInstance, self.other_instance.id))


class HostPlanGeneratedSlotsTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        self.season = Season(id=uuid.uuid4(), name='Fall 2026', start_date=date(2026, 8, 1), end_date=date(2026, 11, 1), is_active=True)
        self.week6 = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=6, start_date=date(2026, 9, 13), end_date=date(2026, 9, 19), primary_game_date=date(2026, 9, 13), date_type='REGULAR_SEASON')
        self.org = Organization(id=uuid.uuid4(), name='Westosha', is_active=True)
        self.host = HostLocation(
            id=uuid.uuid4(),
            organization_id=self.org.id,
            name='Westosha Stadium',
            surface_type='GRASS_FIELD',
            max_small_fields=1,
            max_medium_fields=1,
            max_large_fields=1,
            max_total_fields=3,
            is_active=True,
        )
        self.availability = HostingAvailability(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week6.id,
            organization_id=self.org.id,
            host_location_id=self.host.id,
            available_date=date(2026, 9, 13),
            primary_game_date=date(2026, 9, 13),
            start_time=time(9, 0),
            end_time=time(12, 0),
            is_available=True,
            active=True,
        )
        self.selection = HostPlanSelection(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week6.id,
            game_date=date(2026, 9, 13),
            community_id=self.org.id,
            host_location_id=self.host.id,
            availability_id=self.availability.id,
            status='SELECTED',
        )
        self.divisions = [
            Division(id=uuid.uuid4(), division_group='COED', name='K-1', sort_order=1, required_field_layout_type='SMALL', is_active=True),
            Division(id=uuid.uuid4(), division_group='COED', name='4-5', sort_order=2, required_field_layout_type='MEDIUM', is_active=True),
            Division(id=uuid.uuid4(), division_group='COED', name='6-7', sort_order=3, required_field_layout_type='LARGE', is_active=True),
        ]
        teams = []
        for division in self.divisions:
            for index in range(2):
                teams.append(Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=division.id, name=f'{division.name} Team {index}', is_active=True))
        self.db.add_all([self.season, self.week6, self.org, self.host, self.availability, self.selection, *self.divisions, *teams])
        self.db.commit()

    def test_selected_host_availability_generates_all_required_field_sizes(self):
        result = _regenerate_and_validate_slots_for_weeks(
            self.db,
            [self.week6],
            [('COED', 'K-1'), ('COED', '4-5'), ('COED', '6-7')],
        )

        field_types = {field_type for (field_type,) in self.db.query(GameSlot.field_type).filter(GameSlot.slot_date == date(2026, 9, 13)).distinct().all()}
        self.assertIn('SMALL', field_types)
        self.assertIn('MEDIUM', field_types)
        self.assertIn('LARGE', field_types)
        validation_row = result['validation_rows'][0]
        self.assertEqual(validation_row['missing_field_sizes'], [])
        self.assertEqual(validation_row['host_locations_evaluated'], ['Westosha Stadium'])
        diagnostics = validation_row['selected_host_generated_slot_diagnostics']
        self.assertEqual(1, len(diagnostics))
        self.assertEqual(str(self.host.id), diagnostics[0]['host_location_id'])
        self.assertEqual('Westosha Stadium', diagnostics[0]['host_location_name'])
        self.assertEqual(str(self.week6.id), diagnostics[0]['season_week_id'])
        self.assertEqual('2026-09-13', diagnostics[0]['primary_game_date'])
        self.assertEqual(str(self.selection.id), diagnostics[0]['host_plan_selection_id'])
        self.assertEqual(str(self.availability.id), diagnostics[0]['hosting_availability_id'])
        self.assertEqual('season_id_week_id_host_location_id_primary_game_date', diagnostics[0]['lookup_method_used'])
        self.assertGreater(diagnostics[0]['generated_slots_by_size']['SMALL'], 0)
        self.assertGreater(diagnostics[0]['generated_slots_by_size']['MEDIUM'], 0)
        self.assertGreater(diagnostics[0]['generated_slots_by_size']['LARGE'], 0)
        self.assertIsNone(diagnostics[0]['zero_slot_reason'])


    def test_selected_host_repairs_utc_shifted_hosting_availability_date(self):
        self.availability.available_date = date(2026, 9, 12)
        self.availability.primary_game_date = date(2026, 9, 12)
        self.availability.week_id = None
        self.selection.availability_id = None
        self.db.commit()

        result = _regenerate_and_validate_slots_for_weeks(
            self.db,
            [self.week6],
            [('COED', 'K-1'), ('COED', '4-5'), ('COED', '6-7')],
        )

        self.db.refresh(self.availability)
        self.assertEqual(self.week6.id, self.availability.week_id)
        self.assertEqual(date(2026, 9, 13), self.availability.primary_game_date)
        self.assertEqual(date(2026, 9, 13), self.availability.available_date)
        diagnostics = result['validation_rows'][0]['selected_host_generated_slot_diagnostics']
        self.assertEqual(str(self.availability.id), diagnostics[0]['hosting_availability_id'])
        self.assertEqual('season_id_utc_shifted_date_host_location_id', diagnostics[0]['lookup_method_used'])
        self.assertGreater(diagnostics[0]['generated_slots_by_size']['SMALL'], 0)
        self.assertGreater(diagnostics[0]['generated_slots_by_size']['MEDIUM'], 0)
        self.assertGreater(diagnostics[0]['generated_slots_by_size']['LARGE'], 0)

    def test_selected_host_warns_when_hosting_availability_record_missing(self):
        self.selection.availability_id = None
        self.db.delete(self.availability)
        self.db.commit()

        result = _regenerate_and_validate_slots_for_weeks(
            self.db,
            [self.week6],
            [('COED', 'K-1'), ('COED', '4-5'), ('COED', '6-7')],
        )

        diagnostics = result['validation_rows'][0]['selected_host_generated_slot_diagnostics']
        self.assertEqual(1, len(diagnostics))
        self.assertIsNone(diagnostics[0]['hosting_availability_id'])
        self.assertEqual('not_found', diagnostics[0]['lookup_method_used'])
        self.assertEqual('Host selected but no Hosting Availability record exists.', diagnostics[0]['zero_slot_reason'])
        self.assertTrue(any('Host selected but no Hosting Availability record exists.' in reason for reason in result['validation_rows'][0]['generation_reasons']))

    def test_playoff_selected_host_does_not_generate_regular_season_slots(self):
        self.week6.date_type = 'PLAYOFF'
        self.db.commit()

        result = _regenerate_and_validate_slots_for_weeks(
            self.db,
            [self.week6],
            [('COED', 'K-1'), ('COED', '4-5'), ('COED', '6-7')],
        )

        self.assertEqual(self.db.query(GameSlot).count(), 0)
        self.assertEqual(result['validation_rows'], [])


if __name__ == '__main__':
    unittest.main()
