import unittest
import uuid
from datetime import date, time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Division, Game, GameStatus, Organization, OrganizationDivisionParticipation, Season, Team, TurfWave, Week
from app.routes.api import get_schedule_readiness


class ScheduleReadinessTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        self.org = Organization(id=uuid.uuid4(), name='Org', is_active=True)
        self.db.add(self.org)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def add_division_with_teams(self, label: str, team_count: int) -> Division:
        division = Division(
            id=uuid.uuid4(),
            division_group='test',
            name=label,
            sort_order=team_count,
            required_field_layout_type='THIRTY_YARD_WIDTH',
            is_active=True,
        )
        participation = OrganizationDivisionParticipation(
            id=uuid.uuid4(),
            organization_id=self.org.id,
            division_id=division.id,
            is_participating=True,
            team_count=team_count,
            is_active=True,
        )
        teams = [
            Team(
                id=uuid.uuid4(),
                organization_id=self.org.id,
                division_id=division.id,
                name=f'{label} Team {number}',
                is_active=True,
            )
            for number in range(1, team_count + 1)
        ]
        self.db.add_all([division, participation, *teams])
        self.db.commit()
        return division

    def test_minimum_unique_matchups_use_single_round_robin_formula(self):
        expected_counts = {
            'Six Teams': 15,
            'Five Teams': 10,
            'Four Teams': 6,
        }
        for label, team_count in [('Six Teams', 6), ('Five Teams', 5), ('Four Teams', 4)]:
            self.add_division_with_teams(label, team_count)

        response = get_schedule_readiness(current_user=None, db=self.db)
        rows_by_label = {row.division_label: row for row in response.rows}

        for label, expected_count in expected_counts.items():
            row = rows_by_label[f'Test {label}']
            self.assertEqual(row.minimum_unique_matchups, expected_count)

    def test_target_scheduled_games_counts_existing_division_games(self):
        division = self.add_division_with_teams('Scheduled', 4)
        teams = self.db.query(Team).filter(Team.division_id == division.id).order_by(Team.name).all()
        status = GameStatus(id=uuid.uuid4(), code='SCHEDULED', label='Scheduled', is_active=True)
        season = Season(id=uuid.uuid4(), name='Spring', start_date=date(2026, 4, 1), end_date=date(2026, 7, 1), is_active=True)
        week = Week(id=uuid.uuid4(), season_id=season.id, week_number=1, start_date=date(2026, 5, 1), end_date=date(2026, 5, 7))
        self.db.add_all([status, season, week])
        self.db.add(Game(
            id=uuid.uuid4(),
            season_id=season.id,
            week_id=week.id,
            home_team_id=teams[0].id,
            away_team_id=teams[1].id,
            game_status_id=status.id,
            game_date=week.start_date,
            kickoff_time=time(9, 0),
        ))
        self.db.commit()

        response = get_schedule_readiness(current_user=None, db=self.db)
        scheduled_row = next(row for row in response.rows if row.division_id == division.id)

        self.assertEqual(scheduled_row.minimum_unique_matchups, 6)
        self.assertEqual(scheduled_row.target_scheduled_games, 1)

class MultiLocationHostingAvailabilityTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        self.org = Organization(id=uuid.uuid4(), name='Dual Surface Community', is_active=True)
        self.db.add(self.org)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_same_community_date_combines_grass_and_auto_turf_capacity(self):
        from app.models import Field, HostLocation, HostLocationConfiguration, HostingAvailability
        from app.routes.api import _regenerate_generated_slots

        host_date = date(2026, 9, 6)
        grass_host = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Community Grass', surface_type='GRASS_FIELD', is_active=True)
        turf_host = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Community Turf', surface_type='TURF_STADIUM', is_active=True)
        grass_field = Field(id=uuid.uuid4(), host_location_id=grass_host.id, name='Grass Small', layout_type='SMALL', is_active=True)
        turf_large = HostLocationConfiguration(id=uuid.uuid4(), host_location_id=turf_host.id, configuration_name='TWO_LARGE', is_active=True)
        turf_small = HostLocationConfiguration(id=uuid.uuid4(), host_location_id=turf_host.id, configuration_name='THREE_SMALL', is_active=True)
        grass_availability = HostingAvailability(
            id=uuid.uuid4(), organization_id=self.org.id, host_location_id=grass_host.id,
            available_date=host_date, start_time=time(9, 0), end_time=time(11, 0), is_available=True,
        )
        turf_availability = HostingAvailability(
            id=uuid.uuid4(), organization_id=self.org.id, host_location_id=turf_host.id,
            selected_configuration_id=None, auto_select_turf_layout=True, lock_selected_layout=False,
            available_date=host_date, start_time=time(9, 0), end_time=time(11, 0), is_available=True,
        )
        self.db.add_all([grass_host, turf_host, grass_field, turf_large, turf_small, grass_availability, turf_availability])
        self.db.commit()

        _regenerate_generated_slots(self.db, grass_availability, grass_host.id)
        _regenerate_generated_slots(self.db, turf_availability, turf_host.id)
        self.db.commit()

        response = get_schedule_readiness(current_user=None, db=self.db)
        host_day = next(row for row in response.host_dates if row.host_date == host_date)

        self.assertEqual(host_day.community_name, 'Dual Surface Community')
        self.assertCountEqual(host_day.selected_host_locations, ['Community Grass', 'Community Turf'])
        self.assertEqual(sum(host_day.field_counts_by_size.values()), 3)
        grass_site = next(site for site in host_day.host_sites if site.host_location_name == 'Community Grass')
        turf_site = next(site for site in host_day.host_sites if site.host_location_name == 'Community Turf')
        self.assertEqual(grass_site.grass_field_capacity, 1)
        self.assertIsNotNone(turf_site.selected_turf_layout)

class TurfMixedLayoutPlanningTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        self.org = Organization(id=uuid.uuid4(), name='Turf Community', is_active=True)
        self.status = GameStatus(id=uuid.uuid4(), code='SCHEDULED', label='Scheduled', is_active=True)
        self.host = None
        self.db.add_all([self.org, self.status])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _division(self, name: str, required_layout: str, team_count: int) -> tuple[Division, list[Team]]:
        division = Division(
            id=uuid.uuid4(),
            division_group='turf',
            name=name,
            sort_order=team_count,
            required_field_layout_type=required_layout,
            is_active=True,
        )
        teams = [
            Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=division.id, name=f'{name} Team {index}', is_active=True)
            for index in range(1, team_count + 1)
        ]
        self.db.add_all([division, *teams])
        self.db.commit()
        return division, teams

    def _add_games(self, division: Division, teams: list[Team], game_date: date, count: int) -> None:
        games = []
        for index in range(count):
            games.append(Game(
                id=uuid.uuid4(),
                home_team_id=teams[index % len(teams)].id,
                away_team_id=teams[(index + 1) % len(teams)].id,
                game_status_id=self.status.id,
                game_date=game_date,
                kickoff_time=time(9, 0),
            ))
        self.db.add_all(games)
        self.db.commit()

    def _add_turf_host_with_availability(self, host_date: date, *, lock_layout: bool = False, selected_layout: str | None = None):
        from app.models import HostLocation, HostLocationConfiguration, HostingAvailability
        from app.routes.api import _apply_turf_configuration_metadata

        host = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Main Turf', surface_type='TURF_STADIUM', is_active=True)
        self.db.add(host)
        self.db.flush()
        configurations = []
        selected_config = None
        for layout in ('TWO_LARGE', 'ONE_MEDIUM_TWO_SMALL', 'ONE_LARGE_ONE_MEDIUM', 'TWO_MEDIUM', 'THREE_SMALL', 'ONE_LARGE_ONE_SMALL', 'ONE_MEDIUM_ONE_SMALL'):
            config = HostLocationConfiguration(id=uuid.uuid4(), host_location_id=host.id, configuration_name=layout, is_active=True)
            _apply_turf_configuration_metadata(config, layout)
            configurations.append(config)
            if selected_layout == layout:
                selected_config = config
        availability = HostingAvailability(
            id=uuid.uuid4(),
            organization_id=self.org.id,
            host_location_id=host.id,
            selected_configuration_id=selected_config.id if selected_config else None,
            auto_select_turf_layout=not lock_layout,
            lock_selected_layout=lock_layout,
            available_date=host_date,
            start_time=time(9, 0),
            end_time=time(17, 0),
            is_available=True,
        )
        self.db.add_all([*configurations, availability])
        self.db.commit()
        return host, availability

    def test_auto_turf_planning_uses_mixed_small_medium_before_large(self):
        from app.models import GameSlot
        from app.routes.api import _regenerate_generated_slots

        host_date = date(2026, 9, 12)
        small_division, small_teams = self._division('Small', 'THIRTY_YARD_WIDTH', 12)
        medium_division, medium_teams = self._division('Medium', 'MEDIUM', 8)
        large_division, large_teams = self._division('Large', 'FIFTY_THREE_YARD_WIDTH', 10)
        self._add_games(small_division, small_teams, host_date, 4)
        self._add_games(medium_division, medium_teams, host_date, 2)
        self._add_games(large_division, large_teams, host_date, 6)
        host, availability = self._add_turf_host_with_availability(host_date)

        metrics = _regenerate_generated_slots(self.db, availability, host.id)
        self.db.commit()

        slots = self.db.query(GameSlot).join(GameSlot.field_instance).filter(GameSlot.host_location_id == host.id).order_by(GameSlot.start_time, GameSlot.field_type).all()
        early_field_names = {slot.field_instance.field_name for slot in slots if slot.start_time < time(11, 0)}
        late_field_names = {slot.field_instance.field_name for slot in slots if slot.start_time >= time(11, 0)}
        self.assertGreater(metrics['new_slots_created'], 0)
        self.assertTrue(all(name.startswith('Wave 1 ONE_MEDIUM_TWO_SMALL') for name in early_field_names))
        self.assertTrue(all(name.startswith('Wave 2 TWO_LARGE') for name in late_field_names))
        self.assertEqual({slot.field_type for slot in slots if slot.start_time == time(9, 0)}, {'SMALL', 'MEDIUM'})
        self.assertEqual({slot.field_type for slot in slots if slot.start_time == time(11, 0)}, {'LARGE'})
        waves = self.db.query(TurfWave).filter(TurfWave.host_location_id == host.id).order_by(TurfWave.sequence_number).all()
        self.assertEqual([wave.wave_intent for wave in waves], ['SMALL_MEDIUM', 'LARGE'])
        self.assertEqual([wave.preferred_layout_code for wave in waves], ['ONE_MEDIUM_TWO_SMALL', 'TWO_LARGE'])
        self.assertTrue(all(slot.turf_wave_id for slot in slots))

        readiness = get_schedule_readiness(current_user=None, db=self.db)
        turf_site = next(site for day in readiness.host_dates for site in day.host_sites if site.host_location_id == host.id)
        self.assertEqual([wave.preferred_layout_code for wave in turf_site.turf_wave_plan], ['ONE_MEDIUM_TWO_SMALL', 'TWO_LARGE'])
        self.assertEqual(turf_site.turf_wave_plan[0].slot_level_configurations[0].slot_level_configuration, 'ONE_MEDIUM_TWO_SMALL')

    def test_locked_turf_layout_does_not_create_mixed_dynamic_blocks(self):
        from app.models import GameSlot
        from app.routes.api import _regenerate_generated_slots

        host_date = date(2026, 9, 13)
        small_division, small_teams = self._division('Locked Small', 'THIRTY_YARD_WIDTH', 4)
        medium_division, medium_teams = self._division('Locked Medium', 'MEDIUM', 4)
        self._add_games(small_division, small_teams, host_date, 2)
        self._add_games(medium_division, medium_teams, host_date, 2)
        host, availability = self._add_turf_host_with_availability(host_date, lock_layout=True, selected_layout='THREE_SMALL')

        _regenerate_generated_slots(self.db, availability, host.id)
        self.db.commit()

        slots = self.db.query(GameSlot).join(GameSlot.field_instance).filter(GameSlot.host_location_id == host.id).all()
        self.assertEqual({slot.field_type for slot in slots}, {'SMALL'})
        self.assertTrue(all(not slot.field_instance.field_name.startswith('Wave 1 ONE_MEDIUM_TWO_SMALL') for slot in slots))
