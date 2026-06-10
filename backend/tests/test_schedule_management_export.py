import csv
import io
import unittest
import uuid
from datetime import date, time
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import ROLE_LEAGUE_ADMIN
from app.database import Base, get_db
from app.main import app
from app.models import Division, FieldInstance, Game, GameSlot, GameStatus, HostLocation, Organization, Role, Season, Team, User, Week
from app.security import create_access_token, hash_password

from app.routes.api import (
    _format_schedule_export_date,
    _format_schedule_export_status,
    _format_schedule_export_time,
    _schedule_export_row_values,
    _field_export_display_issue,
    _turf_field_export_label,
)


class ScheduleManagementExportTest(unittest.TestCase):
    def test_export_formats_match_spreadsheet_columns(self):
        self.assertEqual(_format_schedule_export_date(date(2026, 8, 9)), '8/9/2026')
        self.assertEqual(_format_schedule_export_time(time(9, 0)), '9:00')
        self.assertEqual(_format_schedule_export_time(time(13, 5)), '13:05')
        self.assertEqual(_format_schedule_export_status('scheduled'), 'SCHEDULED')

    def test_export_row_uses_compact_schedule_shape(self):
        values = _schedule_export_row_values(
            SimpleNamespace(game_date=date(2026, 8, 9), kickoff_time=time(9, 0)),
            SimpleNamespace(field_type='small'),
            SimpleNamespace(field_name='Wave 1 TWO_SMALL_ONE_MEDIUM Small Field 2'),
            SimpleNamespace(name='Westosha Stadium'),
            SimpleNamespace(name='Westosha Coed 2-3 Maroon'),
            SimpleNamespace(name='LCS Coed 2-3 Red'),
            SimpleNamespace(division_group='Coed', name='2-3'),
            SimpleNamespace(code='scheduled'),
        )

        self.assertEqual(
            values,
            [
                '8/9/2026',
                '9:00',
                'coed_2_3',
                'Westosha Coed 2-3 Maroon',
                'LCS Coed 2-3 Red',
                'Westosha Stadium',
                'Small Field 2',
                'SMALL',
                'SCHEDULED',
            ],
        )

    def test_turf_export_label_strips_wave_metadata_from_stored_field_name(self):
        wave = SimpleNamespace(sequence_number=1, preferred_layout_code='TWO_SMALL_ONE_MEDIUM')
        slot = SimpleNamespace(field_type='SMALL', turf_wave_id='wave-id', turf_wave=wave)
        field = SimpleNamespace(field_name='Wave 2 TWO_SMALL_ONE_MEDIUM Small Field 1')

        self.assertEqual(_turf_field_export_label(slot, field), 'Small Field 1')

    def test_turf_export_label_preserves_non_sequential_explicit_slot(self):
        slot = SimpleNamespace(field_type='MEDIUM', turf_wave_id='wave-id', turf_wave=SimpleNamespace(slots=[]))
        field = SimpleNamespace(field_name='Wave 5 TWO_MEDIUM Medium Field 2')

        self.assertEqual(_turf_field_export_label(slot, field), 'Medium Field 2')

    def test_export_field_values_do_not_include_wave_or_layout_codes(self):
        cases = [
            ('Wave 1 Small Field 1', 'Small Field 1'),
            ('Wave 2 Large Field 1', 'Large Field 1'),
            ('Wave 5 Medium Field 2', 'Medium Field 2'),
            ('THREE_SMALL Small Field 1', 'Small Field 1'),
            ('TWO_MEDIUM Medium Field 2', 'Medium Field 2'),
            ('ONE_SMALL_ONE_LARGE Large Field 1', 'Large Field 1'),
        ]
        for stored, expected in cases:
            values = _schedule_export_row_values(
                SimpleNamespace(game_date=date(2026, 8, 9), kickoff_time=time(9, 0)),
                SimpleNamespace(field_type='MEDIUM' if 'Medium' in stored else ('LARGE' if 'Large' in stored else 'SMALL')),
                SimpleNamespace(field_name=stored),
                SimpleNamespace(name='Westosha Stadium'),
                SimpleNamespace(name='Home'),
                SimpleNamespace(name='Away'),
                SimpleNamespace(division_group='Coed', name='2-3'),
                SimpleNamespace(code='scheduled'),
            )
            self.assertEqual(values[6], expected)
            self.assertNotIn('Wave', values[6])
            self.assertNotRegex(values[6], r'THREE_SMALL|TWO_MEDIUM|ONE_SMALL_ONE_LARGE')


    def test_schedule_management_ui_does_not_render_or_call_quality_report(self):
        root = __import__('pathlib').Path(__file__).parents[2]
        schedule_management = (root / 'frontend' / 'src' / 'app' / '(dashboard)' / 'admin' / 'schedule-management' / 'page.tsx').read_text()
        manual_builder = (root / 'frontend' / 'src' / 'app' / '(dashboard)' / 'admin' / 'manual-schedule-builder' / 'page.tsx').read_text()
        combined = schedule_management + manual_builder

        self.assertNotIn('Schedule Quality Report', combined)
        self.assertNotIn('/schedule-management/quality-report', combined)
        self.assertNotIn('Export Quality Report', combined)
        self.assertNotIn('Download full diagnostics JSON', combined)
        self.assertNotIn('Safe compact diagnostics preview', combined)


    def test_normal_export_rows_are_games_only_not_diagnostics(self):
        values = _schedule_export_row_values(
            SimpleNamespace(game_date=date(2026, 8, 9), kickoff_time=time(9, 0)),
            SimpleNamespace(field_type='SMALL'),
            SimpleNamespace(field_name='Small Field 1'),
            SimpleNamespace(name='Westosha Stadium'),
            SimpleNamespace(name='Home'),
            SimpleNamespace(name='Away'),
            SimpleNamespace(division_group='Coed', name='2-3'),
            SimpleNamespace(code='scheduled'),
        )

        self.assertFalse(any('EXPORT VALIDATION' in value for value in values))
        self.assertEqual(values[6], 'Small Field 1')


    def test_grass_export_preserves_host_specific_label_with_field_words(self):
        grass_host = SimpleNamespace(name='Hiller Park', surface_type='GRASS_FIELD')
        values = _schedule_export_row_values(
            SimpleNamespace(game_date=date(2026, 8, 9), kickoff_time=time(9, 0)),
            SimpleNamespace(field_type='SMALL', turf_wave_id=None, host_location=grass_host),
            SimpleNamespace(field_name="J'burg Hiller Small Field 1", field_type='SMALL', host_location=grass_host),
            grass_host,
            SimpleNamespace(name='Home'),
            SimpleNamespace(name='Away'),
            SimpleNamespace(division_group='Coed', name='2-3'),
            SimpleNamespace(code='scheduled'),
        )

        self.assertEqual(values[6], "J'burg Hiller Small Field 1")

    def test_grass_export_strips_internal_terms_without_turf_normalizing(self):
        grass_host = SimpleNamespace(name='Hiller Park', surface_type='GRASS_FIELD')
        values = _schedule_export_row_values(
            SimpleNamespace(game_date=date(2026, 8, 9), kickoff_time=time(9, 0)),
            SimpleNamespace(field_type='SMALL', turf_wave_id='legacy-wave', host_location=grass_host),
            SimpleNamespace(field_name="Wave 1 TWO_SMALL_ONE_MEDIUM J'burg Hiller Small Field 1", field_type='SMALL', host_location=grass_host),
            grass_host,
            SimpleNamespace(name='Home'),
            SimpleNamespace(name='Away'),
            SimpleNamespace(division_group='Coed', name='2-3'),
            SimpleNamespace(code='scheduled'),
        )

        self.assertEqual(values[6], "J'burg Hiller Small Field 1")

    def test_export_display_issue_detects_visible_internal_terms(self):
        self.assertEqual(_field_export_display_issue('Wave 1 Small Field 1'), 'Export display issue: Field column contains Wave terminology.')
        self.assertEqual(_field_export_display_issue('TWO_MEDIUM Medium Field 2'), 'Export display issue: Field column should show explicit field slot only.')


class ScheduleManagementExportIntegrityGuardTest(unittest.TestCase):
    def test_export_row_downgrades_scheduled_without_complete_assignment(self):
        values = _schedule_export_row_values(
            SimpleNamespace(game_date=date(2026, 8, 9), kickoff_time=time(9, 0)),
            None,
            None,
            SimpleNamespace(name='Westosha Stadium'),
            SimpleNamespace(name='Home'),
            SimpleNamespace(name='Away'),
            SimpleNamespace(division_group='Coed', name='2-3'),
            SimpleNamespace(code='SCHEDULED'),
        )

        self.assertEqual(values[-1], 'VALIDATION_FAILED')
        self.assertEqual(values[6], '')
        self.assertEqual(values[7], '')



class ScheduleManagementExportSavedManualRowsTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            'sqlite+pysqlite:///:memory:',
            connect_args={'check_same_thread': False},
            poolclass=StaticPool,
            future=True,
        )
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.db = self.SessionLocal()
        self.role = Role(id=uuid.uuid4(), name=ROLE_LEAGUE_ADMIN, is_active=True)
        self.admin = User(id=uuid.uuid4(), email='league@example.com', full_name='League Admin', password_hash=hash_password('Password123!'), role_id=self.role.id, is_active=True)
        self.season = Season(id=uuid.uuid4(), name='Fall 2026', start_date=date(2026, 8, 1), end_date=date(2026, 11, 1), is_active=True, schedule_status='published')
        self.week = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=3, label='Week 3', start_date=date(2026, 8, 23), end_date=date(2026, 8, 29), primary_game_date=date(2026, 8, 23))
        self.status = GameStatus(id=uuid.uuid4(), code='SCHEDULED', label='Scheduled', is_active=True)
        self.host_org = Organization(id=uuid.uuid4(), name='Johnsburg', is_active=True)
        self.host = HostLocation(id=uuid.uuid4(), organization_id=self.host_org.id, name='Johnsburg Stadium', surface_type='TURF', is_active=True)
        self.db.add_all([self.role, self.admin, self.season, self.week, self.status, self.host_org, self.host])
        self.divisions = {}
        for group, name, required in [
            ('Girls', 'K-2', 'THIRTY_YARD_WIDTH'), ('Coed', '8', 'FIFTY_THREE_YARD_WIDTH'),
            ('Coed', 'K-1', 'THIRTY_YARD_WIDTH'), ('Coed', '6-7', 'FIFTY_THREE_YARD_WIDTH'),
            ('Girls', '6-8', 'FIFTY_THREE_YARD_WIDTH'), ('Coed', '2-3', 'THIRTY_YARD_WIDTH'),
            ('Girls', '3-5', 'FORTY_YARD_WIDTH'), ('Coed', '4-5', 'FORTY_YARD_WIDTH'),
        ]:
            div = Division(id=uuid.uuid4(), division_group=group, name=name, sort_order=len(self.divisions) + 1, required_field_layout_type=required, is_active=True)
            self.divisions[(group, name)] = div
            self.db.add(div)
        self.fields = {}
        for label, field_type in [('Small Field 1', 'SMALL'), ('Small Field 2', 'SMALL'), ('Medium Field 1', 'MEDIUM'), ('Medium Field 2', 'MEDIUM'), ('Large Field 1', 'LARGE')]:
            field = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=date(2026, 8, 23), field_name=f'Wave 1 TWO_SMALL_ONE_MEDIUM {label}', field_type=field_type, is_active=True)
            self.fields[label] = field
            self.db.add(field)
        self.orgs = {self.host_org.name: self.host_org}
        self.teams = {}
        for team_name, key in [
            ("J’Burg Girls K-2 Blue", ('Girls', 'K-2')), ("LCS Girls K-2 Red", ('Girls', 'K-2')),
            ("Antioch Coed 8 Black", ('Coed', '8')), ("LCS Coed 8 Red", ('Coed', '8')),
            ("J’Burg Coed K-1 Blue", ('Coed', 'K-1')), ("Westosha Coed K-1 Maroon", ('Coed', 'K-1')),
            ("Antioch Coed 6-7 Black", ('Coed', '6-7')), ("LCS Coed 6-7 Red", ('Coed', '6-7')),
            ("Prairie Ridge Girls 6-8 Gold", ('Girls', '6-8')), ("Woodstock Girls 6-8 Teal", ('Girls', '6-8')),
            ("J’Burg Coed 2-3 Blue", ('Coed', '2-3')), ("Westosha Coed 2-3 Maroon", ('Coed', '2-3')),
            ("Cary Girls K-2 Purple", ('Girls', 'K-2')), ("Westosha Girls K-2 Maroon", ('Girls', 'K-2')),
            ("J’Burg Girls 6-8 Blue", ('Girls', '6-8')), ("LCS Girls 6-8 Red", ('Girls', '6-8')),
            ("Antioch Coed 2-3 Black", ('Coed', '2-3')), ("LCS Coed 2-3 Red", ('Coed', '2-3')),
            ("J’Burg Girls 3-5 Blue", ('Girls', '3-5')), ("LCS Girls 3-5 Red", ('Girls', '3-5')),
            ("Antioch Coed 4-5 Black", ('Coed', '4-5')), ("LCS Coed 4-5 Red", ('Coed', '4-5')),
            ("Prairie Ridge Girls 3-5 Gold", ('Girls', '3-5')), ("Woodstock Girls 3-5 Teal", ('Girls', '3-5')),
        ]:
            org_name = team_name.split()[0].replace('J’Burg', 'Johnsburg')
            org = self.orgs.setdefault(org_name, Organization(id=uuid.uuid4(), name=org_name, is_active=True))
            if org not in self.db:
                self.db.add(org)
            team = Team(id=uuid.uuid4(), organization_id=org.id, division_id=self.divisions[key].id, name=team_name, is_active=True)
            self.teams[team_name] = team
            self.db.add(team)
        self.db.flush()
        self.games = {}
        saved_rows = [
            ('09:00', 'Girls', 'K-2', "J’Burg Girls K-2 Blue", "LCS Girls K-2 Red", 'Small Field 1'),
            ('09:00', 'Coed', '8', "Antioch Coed 8 Black", "LCS Coed 8 Red", 'Large Field 1'),
            ('10:00', 'Coed', 'K-1', "J’Burg Coed K-1 Blue", "Westosha Coed K-1 Maroon", 'Small Field 1'),
            ('10:00', 'Coed', '6-7', "Antioch Coed 6-7 Black", "LCS Coed 6-7 Red", 'Large Field 1'),
            ('11:00', 'Girls', '6-8', "Prairie Ridge Girls 6-8 Gold", "Woodstock Girls 6-8 Teal", 'Large Field 1'),
            ('11:00', 'Coed', '2-3', "J’Burg Coed 2-3 Blue", "Westosha Coed 2-3 Maroon", 'Small Field 1'),
            ('12:00', 'Girls', 'K-2', "Cary Girls K-2 Purple", "Westosha Girls K-2 Maroon", 'Small Field 1'),
            ('12:00', 'Girls', '6-8', "J’Burg Girls 6-8 Blue", "LCS Girls 6-8 Red", 'Large Field 1'),
            ('13:00', 'Coed', '2-3', "Antioch Coed 2-3 Black", "LCS Coed 2-3 Red", 'Small Field 1'),
            ('13:00', 'Girls', '3-5', "J’Burg Girls 3-5 Blue", "LCS Girls 3-5 Red", 'Medium Field 1'),
            ('14:00', 'Coed', '4-5', "Antioch Coed 4-5 Black", "LCS Coed 4-5 Red", 'Medium Field 1'),
            ('14:00', 'Girls', '3-5', "Prairie Ridge Girls 3-5 Gold", "Woodstock Girls 3-5 Teal", 'Medium Field 2'),
        ]
        for time_text, group, division_name, home, away, field_label in saved_rows:
            hour, minute = [int(part) for part in time_text.split(':')]
            game = Game(id=uuid.uuid4(), season_id=self.season.id, week_id=self.week.id, home_team_id=self.teams[home].id, away_team_id=self.teams[away].id, host_location_id=self.host.id, field_instance_id=self.fields[field_label].id, game_status_id=self.status.id, game_date=date(2026, 8, 23), kickoff_time=time(hour, minute), is_manual_edit=True)
            self.games[(home, away)] = game
            self.db.add(game)
        self.db.flush()
        # Legacy generated-slot assignments from the optimizer must not be used by export.
        self.db.add_all([
            GameSlot(id=uuid.uuid4(), field_instance_id=self.fields['Small Field 1'].id, host_location_id=self.host.id, season_id=self.season.id, week_id=self.week.id, slot_date=date(2026, 8, 23), start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='ASSIGNED', assigned_game_id=self.games[("J’Burg Coed 2-3 Blue", "Westosha Coed 2-3 Maroon")].id),
            GameSlot(id=uuid.uuid4(), field_instance_id=self.fields['Small Field 2'].id, host_location_id=self.host.id, season_id=self.season.id, week_id=self.week.id, slot_date=date(2026, 8, 23), start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='ASSIGNED', assigned_game_id=self.games[("Antioch Coed 2-3 Black", "LCS Coed 2-3 Red")].id),
        ])
        self.db.commit()

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def _headers(self):
        return {'Authorization': f'Bearer {create_access_token(str(self.admin.id))}'}

    def test_export_matches_saved_manual_schedule_builder_rows_for_2026_08_23_johnsburg(self):
        response = self.client.get('/api/schedule-management/export.csv?date=2026-08-23', headers=self._headers())
        self.assertEqual(response.status_code, 200, response.text)
        rows = list(csv.DictReader(io.StringIO(response.text)))
        exported = {(row['Home Team'], row['Away Team']): row for row in rows}

        expected = [
            ('9:00', 'girls_k_2', "J’Burg Girls K-2 Blue", "LCS Girls K-2 Red", 'Small Field 1'),
            ('9:00', 'coed_8', "Antioch Coed 8 Black", "LCS Coed 8 Red", 'Large Field 1'),
            ('10:00', 'coed_k_1', "J’Burg Coed K-1 Blue", "Westosha Coed K-1 Maroon", 'Small Field 1'),
            ('10:00', 'coed_6_7', "Antioch Coed 6-7 Black", "LCS Coed 6-7 Red", 'Large Field 1'),
            ('11:00', 'girls_6_8', "Prairie Ridge Girls 6-8 Gold", "Woodstock Girls 6-8 Teal", 'Large Field 1'),
            ('11:00', 'coed_2_3', "J’Burg Coed 2-3 Blue", "Westosha Coed 2-3 Maroon", 'Small Field 1'),
            ('12:00', 'girls_k_2', "Cary Girls K-2 Purple", "Westosha Girls K-2 Maroon", 'Small Field 1'),
            ('12:00', 'girls_6_8', "J’Burg Girls 6-8 Blue", "LCS Girls 6-8 Red", 'Large Field 1'),
            ('13:00', 'coed_2_3', "Antioch Coed 2-3 Black", "LCS Coed 2-3 Red", 'Small Field 1'),
            ('13:00', 'girls_3_5', "J’Burg Girls 3-5 Blue", "LCS Girls 3-5 Red", 'Medium Field 1'),
            ('14:00', 'coed_4_5', "Antioch Coed 4-5 Black", "LCS Coed 4-5 Red", 'Medium Field 1'),
            ('14:00', 'girls_3_5', "Prairie Ridge Girls 3-5 Gold", "Woodstock Girls 3-5 Teal", 'Medium Field 2'),
        ]
        self.assertEqual(len(rows), len(expected))
        for expected_time, division, home, away, field in expected:
            row = exported[(home, away)]
            self.assertEqual(row['Date'], '8/23/2026')
            self.assertEqual(row['Time'], expected_time)
            self.assertEqual(row['Normalized Division Key'], division)
            self.assertEqual(row['Host Location'], 'Johnsburg Stadium')
            self.assertEqual(row['Field'], field)
            self.assertNotIn('Wave', row['Field'])

        small_field_1_at_9 = [row for row in rows if row['Time'] == '9:00' and row['Field'] == 'Small Field 1']
        self.assertEqual(len(small_field_1_at_9), 1)
        self.assertEqual(exported[("J’Burg Coed 2-3 Blue", "Westosha Coed 2-3 Maroon")]['Time'], '11:00')
        self.assertEqual(exported[("Antioch Coed 2-3 Black", "LCS Coed 2-3 Red")]['Time'], '13:00')

if __name__ == '__main__':
    unittest.main()
