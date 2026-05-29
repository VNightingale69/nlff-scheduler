import unittest
import uuid
from datetime import date, time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Division, FieldInstance, Game, GameStatus, Organization, OrganizationDivisionParticipation, Season, Team, Week
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
        self.org = Organization(id=uuid.uuid4(), name='Westosha', is_active=True)
        self.status = GameStatus(id=uuid.uuid4(), code='SCHEDULED', label='Scheduled', is_active=True)
        self.season = Season(id=uuid.uuid4(), name='Fall', start_date=date(2026, 9, 1), end_date=date(2026, 11, 1), is_active=True)
        self.week = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=1, start_date=date(2026, 9, 13), end_date=date(2026, 9, 19))
        self.small_division = Division(id=uuid.uuid4(), division_group='coed', name='K 1st', sort_order=1, required_field_layout_type='THIRTY_YARD_WIDTH', is_active=True)
        self.medium_division = Division(id=uuid.uuid4(), division_group='coed', name='4th 5th', sort_order=2, required_field_layout_type='FORTY_YARD_WIDTH', is_active=True)
        self.large_division = Division(id=uuid.uuid4(), division_group='coed', name='8th', sort_order=3, required_field_layout_type='FIFTY_THREE_YARD_WIDTH', is_active=True)
        self.db.add_all([self.org, self.status, self.season, self.week, self.small_division, self.medium_division, self.large_division])
        self.db.flush()
        self.small_teams = self._teams(self.small_division, 20)
        self.medium_teams = self._teams(self.medium_division, 10)
        self.large_teams = self._teams(self.large_division, 14)
        self.db.add_all([*self.small_teams, *self.medium_teams, *self.large_teams])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _teams(self, division: Division, count: int):
        return [Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=division.id, name=f'{division.name} Team {index}', is_active=True) for index in range(count)]

    def _add_games(self, teams, game_count: int):
        for index in range(game_count):
            self.db.add(Game(
                id=uuid.uuid4(),
                season_id=self.season.id,
                week_id=self.week.id,
                home_team_id=teams[(index * 2) % len(teams)].id,
                away_team_id=teams[(index * 2 + 1) % len(teams)].id,
                game_status_id=self.status.id,
                game_date=date(2026, 9, 13),
                kickoff_time=time(9, 0),
            ))
        self.db.commit()

    def test_grass_forecast_generates_fixed_field_instances_by_size(self):
        from app.models import HostLocation, HostingAvailability
        from app.routes.api import _regenerate_generated_slots

        self._add_games(self.small_teams, 10)
        self._add_games(self.medium_teams, 5)
        self._add_games(self.large_teams, 7)
        grass_host = HostLocation(
            id=uuid.uuid4(), organization_id=self.org.id, name='Westosha Grass Fields', surface_type='GRASS_FIELD',
            max_small_fields=2, max_medium_fields=1, max_large_fields=1, max_total_fields=4, is_active=True,
        )
        availability = HostingAvailability(
            id=uuid.uuid4(), organization_id=self.org.id, host_location_id=grass_host.id,
            available_date=date(2026, 9, 13), start_time=time(9, 0), end_time=time(17, 0), is_available=True,
        )
        self.db.add_all([grass_host, availability]); self.db.commit()

        metrics = _regenerate_generated_slots(self.db, availability, grass_host.id)
        self.db.commit()

        self.assertEqual(metrics['new_slots_created'], 32)
        instances = self.db.query(FieldInstance).filter_by(host_location_id=grass_host.id).order_by(FieldInstance.field_name).all()
        self.assertEqual(sorted((instance.field_name, instance.field_type) for instance in instances), [
            ('Grass Large Field 1', 'LARGE'),
            ('Grass Medium Field 1', 'MEDIUM'),
            ('Grass Small Field 1', 'SMALL'),
            ('Grass Small Field 2', 'SMALL'),
        ])
        response = get_schedule_readiness(current_user=None, db=self.db)
        site = response.host_dates[0].host_sites[0]
        self.assertEqual(site.grass_setup_forecast.capacity_status, 'Valid')
        self.assertEqual(site.grass_setup_forecast.small_fields_to_line, 2)
        self.assertEqual(site.grass_setup_forecast.medium_fields_to_line, 1)
        self.assertEqual(site.grass_setup_forecast.large_fields_to_line, 1)

    def test_grass_forecast_blocks_slots_when_capacity_exceeded(self):
        from app.models import HostLocation, HostingAvailability
        from app.routes.api import _regenerate_generated_slots

        self._add_games(self.small_teams, 10)
        grass_host = HostLocation(
            id=uuid.uuid4(), organization_id=self.org.id, name='Tiny Grass', surface_type='GRASS_FIELD',
            max_small_fields=1, max_medium_fields=0, max_large_fields=0, max_total_fields=1, is_active=True,
        )
        availability = HostingAvailability(
            id=uuid.uuid4(), organization_id=self.org.id, host_location_id=grass_host.id,
            available_date=date(2026, 9, 13), start_time=time(9, 0), end_time=time(17, 0), is_available=True,
        )
        self.db.add_all([grass_host, availability]); self.db.commit()

        metrics = _regenerate_generated_slots(self.db, availability, grass_host.id)

        self.assertEqual(metrics['new_slots_created'], 0)
