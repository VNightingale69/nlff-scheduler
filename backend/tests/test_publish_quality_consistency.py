import unittest
import uuid
from datetime import date, time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Division, FieldInstance, Game, GameSlot, GameStatus, HostLocation, HostingAvailability, Organization, Season, Team, TurfWave, Week
from app.routes.api import build_schedule_quality_report, publish_schedule


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


    def test_quality_report_blocks_non_chronological_turf_wave_sequences(self):
        host = HostLocation(
            id=uuid.uuid4(),
            organization_id=self.org.id,
            name='Turf Host',
            surface_type='TURF_STADIUM',
            is_active=True,
        )
        availability = HostingAvailability(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week.id,
            organization_id=self.org.id,
            host_location_id=host.id,
            available_date=self.week.start_date,
            primary_game_date=self.week.start_date,
            start_time=time(9, 0),
            end_time=time(11, 0),
            is_available=True,
        )
        early_wave = TurfWave(
            id=uuid.uuid4(),
            host_location_id=host.id,
            hosting_availability_id=availability.id,
            week_id=self.week.id,
            host_date=self.week.start_date,
            sequence_number=2,
            wave_intent='SMALL_MEDIUM',
            preferred_layout_code='TWO_SMALL_ONE_MEDIUM',
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
        second_wave = TurfWave(
            id=uuid.uuid4(),
            host_location_id=host.id,
            hosting_availability_id=availability.id,
            week_id=self.week.id,
            host_date=self.week.start_date,
            sequence_number=4,
            wave_intent='MIXED',
            preferred_layout_code='ONE_SMALL_ONE_LARGE',
            start_time=time(10, 0),
            end_time=time(11, 0),
        )
        self.db.add_all([host, availability, early_wave, second_wave])
        self.db.commit()

        report = build_schedule_quality_report(self.db, self.season.id)

        self.assertEqual(report['metrics']['turf_wave_sequence_validation_failure_count'], 1)
        self.assertTrue(any(error['code'] == 'TURF_WAVE_SEQUENCE_GAP' for error in report['hard_errors']))
        diagnostic = report['turf_wave_sequence_diagnostics'][0]
        self.assertEqual(diagnostic['wave_sequence_numbers'], [2, 4])
        self.assertFalse(diagnostic['sequence_contiguous'])
        self.assertFalse(diagnostic['sequence_chronological'])

    def test_publish_uses_same_quality_report_source(self):
        report = build_schedule_quality_report(self.db, self.season.id)
        self.assertEqual(report['overall_health'], 'Excellent')
        self.assertEqual(report['hard_errors'], [])
        self.assertEqual(report['metrics']['conflicts'], 0)
        response = publish_schedule(self.season.id, db=self.db)
        self.assertTrue(response['ok'])
        self.assertEqual(response['overall_health'], 'Excellent')

