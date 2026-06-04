import unittest
import uuid
from datetime import date, time

from sqlalchemy import create_engine, func
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


class GrassFieldForecastTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        self.org = Organization(id=uuid.uuid4(), name='Grass Community', is_active=True)
        self.status = GameStatus(id=uuid.uuid4(), code='SCHEDULED', label='Scheduled', is_active=True)
        self.db.add_all([self.org, self.status])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _division(self, name: str, required_layout: str, team_count: int = 8) -> tuple[Division, list[Team]]:
        division = Division(
            id=uuid.uuid4(),
            division_group='grass',
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
        self.db.add_all([
            Game(
                id=uuid.uuid4(),
                home_team_id=teams[index % len(teams)].id,
                away_team_id=teams[(index + 1) % len(teams)].id,
                game_status_id=self.status.id,
                game_date=game_date,
                kickoff_time=time(9, 0),
            )
            for index in range(count)
        ])
        self.db.commit()

    def test_grass_forecast_generates_fixed_fields_with_readiness_details(self):
        from app.models import Field, GameSlot, HostLocation, HostingAvailability
        from app.routes.api import _regenerate_generated_slots

        host_date = date(2026, 9, 19)
        small_division, small_teams = self._division('Small', 'THIRTY_YARD_WIDTH')
        medium_division, medium_teams = self._division('Medium', 'MEDIUM')
        large_division, large_teams = self._division('Large', 'FIFTY_THREE_YARD_WIDTH')
        self._add_games(small_division, small_teams, host_date, 4)
        self._add_games(medium_division, medium_teams, host_date, 2)
        self._add_games(large_division, large_teams, host_date, 2)
        host = HostLocation(
            id=uuid.uuid4(),
            organization_id=self.org.id,
            name='Fixed Grass',
            surface_type='GRASS_FIELD',
            max_small_fields=3,
            max_medium_fields=2,
            max_large_fields=1,
            max_total_fields=4,
            is_active=True,
        )
        availability = HostingAvailability(
            id=uuid.uuid4(),
            organization_id=self.org.id,
            host_location_id=host.id,
            available_date=host_date,
            start_time=time(9, 0),
            end_time=time(11, 0),
            is_available=True,
        )
        fields = [
            Field(id=uuid.uuid4(), host_location_id=host.id, name='Grass Small 1', layout_type='SMALL', is_active=True),
            Field(id=uuid.uuid4(), host_location_id=host.id, name='Grass Small 2', layout_type='SMALL', is_active=True),
            Field(id=uuid.uuid4(), host_location_id=host.id, name='Grass Medium 1', layout_type='MEDIUM', is_active=True),
            Field(id=uuid.uuid4(), host_location_id=host.id, name='Grass Large 1', layout_type='LARGE', is_active=True),
        ]
        self.db.add_all([host, availability, *fields])
        self.db.commit()

        metrics = _regenerate_generated_slots(self.db, availability, host.id)
        self.db.commit()

        slots = self.db.query(GameSlot).join(GameSlot.field_instance).filter(GameSlot.host_location_id == host.id).order_by(GameSlot.start_time, GameSlot.field_type).all()
        self.assertEqual(metrics['new_slots_created'], 8)
        self.assertEqual({slot.field_instance.field_name for slot in slots if slot.field_type == 'SMALL'}, {'Grass Small 1', 'Grass Small 2'})
        self.assertEqual({slot.field_instance.field_name for slot in slots if slot.field_type == 'MEDIUM'}, {'Grass Medium 1'})
        self.assertEqual({slot.field_instance.field_name for slot in slots if slot.field_type == 'LARGE'}, {'Grass Large 1'})
        names_by_type = {}
        for slot in slots:
            names_by_type.setdefault(slot.field_instance.field_name, set()).add(slot.field_type)
        self.assertTrue(all(len(field_types) == 1 for field_types in names_by_type.values()))

        readiness = get_schedule_readiness(current_user=None, db=self.db)
        grass_site = next(site for day in readiness.host_dates for site in day.host_sites if site.host_location_id == host.id)
        self.assertEqual(grass_site.small_fields_to_line, 2)
        self.assertEqual(grass_site.medium_fields_to_line, 1)
        self.assertEqual(grass_site.large_fields_to_line, 1)
        self.assertEqual(grass_site.total_fields_to_line, 4)
        self.assertEqual(grass_site.capacity_status, 'ok')
        self.assertEqual(grass_site.turf_wave_plan, [])

    def test_grass_forecast_is_capped_by_configured_capacity(self):
        from app.models import Field, HostLocation, HostingAvailability
        from app.routes.api import _grass_setup_forecast_for_availability

        host_date = date(2026, 9, 20)
        small_division, small_teams = self._division('Small Cap', 'THIRTY_YARD_WIDTH')
        self._add_games(small_division, small_teams, host_date, 5)
        host = HostLocation(
            id=uuid.uuid4(),
            organization_id=self.org.id,
            name='Capped Grass',
            surface_type='GRASS_FIELD',
            max_small_fields=1,
            max_medium_fields=0,
            max_large_fields=0,
            max_total_fields=1,
            is_active=True,
        )
        availability = HostingAvailability(
            id=uuid.uuid4(),
            organization_id=self.org.id,
            host_location_id=host.id,
            available_date=host_date,
            start_time=time(9, 0),
            end_time=time(11, 0),
            is_available=True,
        )
        field = Field(id=uuid.uuid4(), host_location_id=host.id, name='Only Small Grass', layout_type='SMALL', is_active=True)
        self.db.add_all([host, availability, field])
        self.db.commit()

        forecast = _grass_setup_forecast_for_availability(self.db, host, availability)

        self.assertEqual(forecast['requested']['SMALL'], 3)
        self.assertEqual(forecast['forecast']['SMALL'], 1)
        self.assertEqual(forecast['capacity_status'], 'capped')
        self.assertTrue(forecast['warnings'])


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
        for layout in ('TWO_LARGE', 'ONE_MEDIUM_TWO_SMALL', 'ONE_LARGE_ONE_MEDIUM', 'TWO_MEDIUM', 'THREE_SMALL', 'ONE_LARGE_ONE_SMALL'):
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


    def test_grass_forecast_without_existing_games_creates_medium_and_large_slots(self):
        from app.models import GameSlot, HostLocation, HostingAvailability
        from app.routes.api import _regenerate_generated_slots

        host_date = date(2026, 9, 13)
        medium_division = Division(id=uuid.uuid4(), division_group='COED', name='4th/5th', required_field_layout_type='MEDIUM', is_active=True)
        large_division = Division(id=uuid.uuid4(), division_group='COED', name='6th/7th', required_field_layout_type='LARGE', is_active=True)
        medium_participation = OrganizationDivisionParticipation(id=uuid.uuid4(), organization_id=self.org.id, division_id=medium_division.id, is_participating=True, team_count=4, is_active=True)
        large_participation = OrganizationDivisionParticipation(id=uuid.uuid4(), organization_id=self.org.id, division_id=large_division.id, is_participating=True, team_count=4, is_active=True)
        host = HostLocation(
            id=uuid.uuid4(),
            organization_id=self.org.id,
            name='Forecast Grass',
            surface_type='GRASS_FIELD',
            max_medium_fields=1,
            max_large_fields=1,
            max_total_fields=2,
            is_active=True,
        )
        availability = HostingAvailability(
            id=uuid.uuid4(),
            organization_id=self.org.id,
            host_location_id=host.id,
            available_date=host_date,
            start_time=time(9, 0),
            end_time=time(17, 0),
            is_available=True,
        )
        self.db.add_all([medium_division, large_division, medium_participation, large_participation, host, availability])
        self.db.commit()

        _regenerate_generated_slots(self.db, availability, host.id)
        self.db.commit()

        slots = self.db.query(GameSlot).filter(GameSlot.host_location_id == host.id).all()
        self.assertEqual({slot.field_type for slot in slots}, {'MEDIUM', 'LARGE'})
        self.assertEqual(sum(1 for slot in slots if slot.field_type == 'MEDIUM'), 8)
        self.assertEqual(sum(1 for slot in slots if slot.field_type == 'LARGE'), 8)

    def test_turf_participation_forecast_without_existing_games_creates_medium_and_large_slots(self):
        from app.models import GameSlot
        from app.routes.api import _regenerate_generated_slots

        host_date = date(2026, 9, 13)
        medium_division = Division(id=uuid.uuid4(), division_group='GIRLS', name='4th/5th', required_field_layout_type='MEDIUM', is_active=True)
        large_division = Division(id=uuid.uuid4(), division_group='GIRLS', name='6th/7th/8th', required_field_layout_type='LARGE', is_active=True)
        medium_participation = OrganizationDivisionParticipation(id=uuid.uuid4(), organization_id=self.org.id, division_id=medium_division.id, is_participating=True, team_count=4, is_active=True)
        large_participation = OrganizationDivisionParticipation(id=uuid.uuid4(), organization_id=self.org.id, division_id=large_division.id, is_participating=True, team_count=4, is_active=True)
        self.db.add_all([medium_division, large_division, medium_participation, large_participation])
        self.db.commit()
        host, availability = self._add_turf_host_with_availability(host_date)

        _regenerate_generated_slots(self.db, availability, host.id)
        self.db.commit()

        slots = self.db.query(GameSlot).filter(GameSlot.host_location_id == host.id).all()
        self.assertIn('MEDIUM', {slot.field_type for slot in slots})
        self.assertIn('LARGE', {slot.field_type for slot in slots})
        self.assertTrue(any(slot.field_instance.field_name.startswith('Wave 1 ONE_MEDIUM_TWO_SMALL') for slot in slots if slot.field_type == 'MEDIUM'))
        self.assertTrue(any(slot.field_instance.field_name.startswith('Wave 2 TWO_LARGE') for slot in slots if slot.field_type == 'LARGE'))

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


class WeekEightCommunityCapacityGenerationTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        self.season = Season(id=uuid.uuid4(), name='Fall', start_date=date(2026, 8, 1), end_date=date(2026, 11, 1), is_active=True)
        self.week8 = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=8, start_date=date(2026, 10, 3), end_date=date(2026, 10, 9))
        self.antioch = Organization(id=uuid.uuid4(), name='Antioch', is_active=True)
        self.johnsburg = Organization(id=uuid.uuid4(), name='Johnsburg', is_active=True)
        self.db.add_all([self.season, self.week8, self.antioch, self.johnsburg])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _division_with_teams(self, group: str, name: str, team_count: int) -> Division:
        division = Division(id=uuid.uuid4(), division_group=group, name=name, sort_order=team_count, is_active=True)
        orgs = [self.antioch, self.johnsburg]
        teams = [
            Team(
                id=uuid.uuid4(),
                organization_id=orgs[index % len(orgs)].id,
                division_id=division.id,
                name=f'{group} {name} Team {index + 1}',
                is_active=True,
            )
            for index in range(team_count)
        ]
        self.db.add_all([division, *teams])
        self.db.commit()
        return division

    def test_week8_demand_and_johnsburg_locations_are_aggregated(self):
        from app.models import GameSlot, HostLocation, HostingAvailability
        from app.routes.api import _regenerate_and_validate_slots_for_weeks

        division_order = [
            ('COED', 'K/1st'),
            ('COED', '2nd/3rd'),
            ('COED', '4th/5th'),
            ('COED', '6th/7th'),
            ('COED', '8th'),
            ('GIRLS', '6th/7th/8th'),
        ]
        self._division_with_teams('COED', 'K/1st', 8)
        self._division_with_teams('COED', '2nd/3rd', 12)
        self._division_with_teams('COED', '4th/5th', 10)
        self._division_with_teams('COED', '6th/7th', 6)
        self._division_with_teams('COED', '8th', 4)
        self._division_with_teams('GIRLS', '6th/7th/8th', 4)

        antioch_host = HostLocation(
            id=uuid.uuid4(), organization_id=self.antioch.id, name='Tim Osmond Sports Complex',
            surface_type='GRASS_FIELD', max_small_fields=3, max_medium_fields=2, max_large_fields=1, max_total_fields=6, is_active=True,
        )
        johnsburg_stadium = HostLocation(
            id=uuid.uuid4(), organization_id=self.johnsburg.id, name='Johnsburg Stadium',
            surface_type='TURF_STADIUM', is_active=True,
        )
        hiller = HostLocation(
            id=uuid.uuid4(), organization_id=self.johnsburg.id, name='Hiller Park',
            surface_type='GRASS_FIELD', max_large_fields=1, max_total_fields=1, is_active=True,
        )
        availability_rows = [
            HostingAvailability(id=uuid.uuid4(), organization_id=self.antioch.id, host_location_id=antioch_host.id, available_date=self.week8.start_date, start_time=time(9, 0), end_time=time(14, 0), is_available=True),
            HostingAvailability(id=uuid.uuid4(), organization_id=self.johnsburg.id, host_location_id=johnsburg_stadium.id, available_date=self.week8.start_date, start_time=time(9, 0), end_time=time(14, 0), is_available=True, auto_select_turf_layout=True),
            HostingAvailability(id=uuid.uuid4(), organization_id=self.johnsburg.id, host_location_id=hiller.id, available_date=self.week8.start_date, start_time=time(9, 0), end_time=time(14, 0), is_available=True),
        ]
        self.db.add_all([antioch_host, johnsburg_stadium, hiller, *availability_rows])
        self.db.commit()

        result = _regenerate_and_validate_slots_for_weeks(self.db, [self.week8], division_order)
        self.db.commit()

        validation = result['validation_rows'][0]
        self.assertEqual(validation['required_games_by_size'], {'SMALL': 10, 'MEDIUM': 5, 'LARGE': 7})
        self.assertGreaterEqual(validation['community_capacity_by_field_size']['Johnsburg']['LARGE'], 3)
        johnsburg_locations = {
            row['host_location']: row['capacity_by_size']
            for row in validation['host_location_capacity_by_community']['Johnsburg']
        }
        self.assertIn('Johnsburg Stadium', johnsburg_locations)
        self.assertIn('Hiller Park', johnsburg_locations)
        self.assertGreater(johnsburg_locations['Johnsburg Stadium']['LARGE'], 0)
        self.assertGreater(johnsburg_locations['Hiller Park']['LARGE'], 0)
        self.assertGreaterEqual(
            self.db.query(GameSlot).filter(GameSlot.slot_date == self.week8.start_date, GameSlot.field_type == 'LARGE').count(),
            7,
        )
        duplicate_field_times = self.db.query(
            GameSlot.slot_date, GameSlot.start_time, GameSlot.host_location_id, GameSlot.field_instance_id, func.count(GameSlot.id)
        ).filter(GameSlot.slot_date == self.week8.start_date).group_by(
            GameSlot.slot_date, GameSlot.start_time, GameSlot.host_location_id, GameSlot.field_instance_id
        ).having(func.count(GameSlot.id) > 1).all()
        self.assertEqual(duplicate_field_times, [])

    def test_week6_uses_league_wide_demand_for_selected_host_slot_generation(self):
        from app.models import GameSlot, HostLocation, HostPlanSelection, HostingAvailability
        from app.routes.api import _regenerate_and_validate_slots_for_weeks

        week6 = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=6, start_date=date(2026, 9, 13), end_date=date(2026, 9, 19), primary_game_date=date(2026, 9, 13), date_type='REGULAR_SEASON')
        self.db.add(week6)
        self.db.commit()
        division_order = [
            ('COED', 'K-1'),
            ('COED', '2-3'),
            ('GIRLS', 'K-2'),
            ('COED', '4-5'),
            ('GIRLS', '3-5'),
            ('COED', '6-7'),
            ('COED', '8'),
            ('GIRLS', '6-8'),
        ]
        for group, name, team_count in [
            ('COED', 'K-1', 5),
            ('COED', '2-3', 4),
            ('GIRLS', 'K-2', 3),
            ('COED', '4-5', 5),
            ('GIRLS', '3-5', 4),
            ('COED', '6-7', 5),
            ('COED', '8', 4),
            ('GIRLS', '6-8', 3),
        ]:
            self._division_with_teams(group, name, team_count)

        host = HostLocation(
            id=uuid.uuid4(), organization_id=self.antioch.id, name='Week 6 Full Demand Grass',
            surface_type='GRASS_FIELD', max_small_fields=3, max_medium_fields=3, max_large_fields=3, max_total_fields=9, is_active=True,
        )
        availability = HostingAvailability(
            id=uuid.uuid4(), season_id=self.season.id, week_id=week6.id, organization_id=self.antioch.id, host_location_id=host.id,
            available_date=week6.start_date, primary_game_date=week6.start_date, start_time=time(9, 0), end_time=time(16, 0), is_available=True,
        )
        selection = HostPlanSelection(
            id=uuid.uuid4(), season_id=self.season.id, week_id=week6.id, game_date=week6.start_date, community_id=self.antioch.id,
            host_location_id=host.id, availability_id=availability.id, status='SELECTED', locked=False,
        )
        self.db.add_all([host, availability, selection])
        self.db.commit()

        result = _regenerate_and_validate_slots_for_weeks(self.db, [week6], division_order)
        self.db.commit()

        validation = result['validation_rows'][0]
        self.assertEqual(validation['league_wide_demand_by_size'], {'SMALL': 7, 'MEDIUM': 5, 'LARGE': 7})
        self.assertEqual(validation['required_games_by_size'], {'SMALL': 7, 'MEDIUM': 5, 'LARGE': 7})
        self.assertEqual(validation['missing_field_sizes'], [])
        self.assertIsNone(validation['zero_slot_reason'])
        self.assertEqual(validation['selected_hosts'], ['Week 6 Full Demand Grass'])
        self.assertEqual(
            {row['division_name']: (row['team_count'], row['expected_games'], row['field_size']) for row in validation['active_divisions_included']},
            {
                'COED K-1': (5, 3, 'SMALL'),
                'COED 2-3': (4, 2, 'SMALL'),
                'GIRLS K-2': (3, 2, 'SMALL'),
                'COED 4-5': (5, 3, 'MEDIUM'),
                'GIRLS 3-5': (4, 2, 'MEDIUM'),
                'COED 6-7': (5, 3, 'LARGE'),
                'COED 8': (4, 2, 'LARGE'),
                'GIRLS 6-8': (3, 2, 'LARGE'),
            },
        )
        generated_sizes = {field_type for (field_type,) in self.db.query(GameSlot.field_type).filter(GameSlot.week_id == week6.id).distinct().all()}
        self.assertEqual(generated_sizes, {'SMALL', 'MEDIUM', 'LARGE'})

    def test_week7_girls_k2_generates_small_field_slots(self):
        from app.models import GameSlot, HostLocation, HostPlanSelection, HostingAvailability
        from app.routes.api import _regenerate_and_validate_slots_for_weeks

        week7 = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=7, start_date=date(2026, 9, 20), end_date=date(2026, 9, 26), primary_game_date=date(2026, 9, 20), date_type='REGULAR_SEASON')
        self.db.add(week7)
        self.db.commit()
        self._division_with_teams('GIRLS', 'K-2', 5)
        host = HostLocation(
            id=uuid.uuid4(), organization_id=self.johnsburg.id, name='Week 7 Small Grass',
            surface_type='GRASS_FIELD', max_small_fields=2, max_total_fields=2, is_active=True,
        )
        availability = HostingAvailability(
            id=uuid.uuid4(), season_id=self.season.id, week_id=week7.id, organization_id=self.johnsburg.id, host_location_id=host.id,
            available_date=week7.start_date, primary_game_date=week7.start_date, start_time=time(9, 0), end_time=time(12, 0), is_available=True,
        )
        selection = HostPlanSelection(
            id=uuid.uuid4(), season_id=self.season.id, week_id=week7.id, game_date=week7.start_date, community_id=self.johnsburg.id,
            host_location_id=host.id, availability_id=availability.id, status='SELECTED', locked=False,
        )
        self.db.add_all([host, availability, selection])
        self.db.commit()

        result = _regenerate_and_validate_slots_for_weeks(self.db, [week7], [('GIRLS', 'K-2')])
        self.db.commit()

        validation = result['validation_rows'][0]
        self.assertEqual(validation['league_wide_demand_by_size'], {'SMALL': 3, 'MEDIUM': 0, 'LARGE': 0})
        self.assertGreater(validation['generated_slots_by_size']['SMALL'], 0)
        self.assertEqual(validation['missing_field_sizes'], [])
        self.assertGreater(self.db.query(GameSlot).filter(GameSlot.week_id == week7.id, GameSlot.field_type == 'SMALL').count(), 0)
