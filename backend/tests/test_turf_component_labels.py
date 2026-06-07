import unittest
import uuid
from datetime import date, time
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import ROLE_LEAGUE_ADMIN
from app.database import Base, get_db
from app.main import app
from app.models import Division, FieldInstance, Game, GameSlot, GameStatus, HostLocation, HostingAvailability, Organization, Role, Season, Team, TurfWave, User, Week
from app.routes.api import _canonical_turf_field_export_label, _schedule_export_row_values, _to_game_read, _validate_turf_component_labels
from app.security import create_access_token, hash_password
from app.turf_configurations import approved_turf_configuration_metadata


LAYOUTS = (
    'THREE_SMALL',
    'TWO_SMALL_ONE_MEDIUM',
    'TWO_MEDIUM',
    'ONE_SMALL_ONE_LARGE',
    'ONE_LARGE',
)


class TurfComponentLabelSourceOfTruthTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            'sqlite+pysqlite:///:memory:',
            connect_args={'check_same_thread': False},
            poolclass=StaticPool,
            future=True,
        )
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.db: Session = self.SessionLocal()
        self.season = Season(id=uuid.UUID(int=1), name='Season', start_date=date(2026, 9, 1), end_date=date(2026, 11, 1), is_active=True)
        self.week = Week(id=uuid.UUID(int=2), season_id=self.season.id, week_number=1, start_date=date(2026, 9, 5), end_date=date(2026, 9, 11), primary_game_date=date(2026, 9, 5))
        self.org = Organization(id=uuid.UUID(int=3), name='Org', is_active=True)
        self.status = GameStatus(id=uuid.UUID(int=4), code='SCHEDULED', label='Scheduled', is_active=True)
        self.league_role = Role(id=uuid.UUID(int=40), name=ROLE_LEAGUE_ADMIN, is_active=True)
        self.league_user = User(
            id=uuid.UUID(int=41),
            email='league@example.com',
            full_name='League Admin',
            password_hash=hash_password('Password123!'),
            role_id=self.league_role.id,
            organization_id=None,
            is_active=True,
        )
        self.host = HostLocation(id=uuid.UUID(int=5), organization_id=self.org.id, name='Turf Host', surface_type='TURF_STADIUM', is_active=True)
        self.availability = HostingAvailability(
            id=uuid.UUID(int=6), season_id=self.season.id, week_id=self.week.id, organization_id=self.org.id,
            host_location_id=self.host.id, available_date=date(2026, 9, 5), start_time=time(9, 0), end_time=time(16, 0),
            active=True, is_available=True,
        )
        self.db.add_all([self.season, self.week, self.org, self.status, self.league_role, self.league_user, self.host, self.availability])
        self.db.flush()

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.divisions = {}
        for offset, field_type in enumerate(('SMALL', 'MEDIUM', 'LARGE'), start=10):
            division = Division(id=uuid.UUID(int=offset), division_group='Test', name=field_type, required_field_layout_type=field_type, is_active=True)
            self.divisions[field_type] = division
            self.db.add(division)
        self.db.flush()
        self.team_counter = 100
        self.object_counter = 1000

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def _token(self):
        return {'Authorization': f'Bearer {create_access_token(str(self.league_user.id))}'}

    def _uuid(self):
        self.object_counter += 1
        return uuid.UUID(int=self.object_counter)

    def _team(self, field_type: str, name: str) -> Team:
        self.team_counter += 1
        team = Team(id=uuid.UUID(int=self.team_counter), organization_id=self.org.id, division_id=self.divisions[field_type].id, name=name, is_active=True)
        self.db.add(team)
        return team

    def _build_wave(self, layout: str, *, sequence: int = 1, host=None, game_date=date(2026, 9, 5), start=time(9, 0)):
        host = host or self.host
        metadata = approved_turf_configuration_metadata(layout)
        wave = TurfWave(
            id=self._uuid(), host_location_id=host.id, hosting_availability_id=self.availability.id, week_id=self.week.id,
            host_date=game_date, sequence_number=sequence, wave_intent='TEST', preferred_layout_code=layout,
            start_time=start, end_time=time(start.hour + 1, 0),
        )
        self.db.add(wave)
        rows = []
        stale_counts = {'SMALL': 0, 'MEDIUM': 0, 'LARGE': 0}
        for index, field_type in enumerate(metadata['availableFields'], start=1):
            stale_counts[field_type] += 1
            stale_ordinal = 1 if metadata['availableFields'].count(field_type) > 1 else stale_counts[field_type]
            fi = FieldInstance(
                id=self._uuid(), host_location_id=host.id, hosting_availability_id=self.availability.id, instance_date=game_date,
                field_name=f'Wave {sequence} {layout} {field_type.title()} Field {stale_ordinal} stale-{index}',
                field_type=field_type, is_active=True, is_generated=True,
            )
            slot = GameSlot(
                id=self._uuid(), field_instance_id=fi.id, host_location_id=host.id, season_id=self.season.id, week_id=self.week.id,
                slot_date=game_date, start_time=start, end_time=time(start.hour + 1, 0), field_type=field_type, status='ASSIGNED', turf_wave_id=wave.id,
            )
            home = self._team(field_type, f'{layout} Home {index}')
            away = self._team(field_type, f'{layout} Away {index}')
            game = Game(
                id=self._uuid(), season_id=self.season.id, week_id=self.week.id, home_team_id=home.id, away_team_id=away.id,
                host_location_id=host.id, field_instance_id=fi.id, game_status_id=self.status.id, game_date=game_date, kickoff_time=start,
            )
            slot.assigned_game_id = game.id
            rows.append((game, slot, fi, host, home, away, self.divisions[field_type], self.org, self.status))
            self.db.add_all([fi, slot, game])
        self.db.commit()
        return rows

    def test_canonical_labels_are_unique_for_every_turf_layout_and_exports_use_them(self):
        for wave_index, layout in enumerate(LAYOUTS, start=1):
            with self.subTest(layout=layout):
                rows = self._build_wave(layout, sequence=wave_index, start=time(8 + wave_index, 0))
                labels = [_canonical_turf_field_export_label(self.db, slot, fi) for _g, slot, fi, *_ in rows]
                self.assertEqual(len(labels), len(set(labels)))
                for label in labels:
                    self.assertTrue(label.startswith(f'Wave {wave_index} {layout} '))
                exported = [
                    _schedule_export_row_values(g, slot, fi, host, home, away, div, status, self.db)[6]
                    for g, slot, fi, host, home, away, div, _org, status in rows
                ]
                self.assertEqual(exported, labels)

    def test_valid_separate_components_with_duplicate_legacy_labels_are_label_collisions_not_field_conflicts(self):
        rows = self._build_wave('TWO_MEDIUM')
        diagnostics = _validate_turf_component_labels(self.db, rows)

        self.assertEqual(diagnostics['turf_component_label_collisions_count'], 1)
        collision = diagnostics['turf_component_label_collisions'][0]
        self.assertEqual(collision['failure_code'], 'TURF_COMPONENT_LABEL_COLLISION')
        self.assertTrue(collision['repair_success'])
        self.assertEqual(len(set(collision['affected_game_slot_ids'])), 2)
        self.assertEqual(collision['expected_labels'], ['Wave 1 TWO_MEDIUM Medium Field 1', 'Wave 1 TWO_MEDIUM Medium Field 2'])

    def test_ordinals_reset_by_wave_date_host_and_field_type(self):
        first = self._build_wave('TWO_MEDIUM', sequence=1, start=time(9, 0))
        second = self._build_wave('TWO_MEDIUM', sequence=2, start=time(10, 0))
        small_mixed = self._build_wave('TWO_SMALL_ONE_MEDIUM', sequence=3, start=time(11, 0))

        self.assertEqual(
            [_canonical_turf_field_export_label(self.db, slot, fi) for _g, slot, fi, *_ in first],
            ['Wave 1 TWO_MEDIUM Medium Field 1', 'Wave 1 TWO_MEDIUM Medium Field 2'],
        )
        self.assertEqual(
            [_canonical_turf_field_export_label(self.db, slot, fi) for _g, slot, fi, *_ in second],
            ['Wave 2 TWO_MEDIUM Medium Field 1', 'Wave 2 TWO_MEDIUM Medium Field 2'],
        )
        labels = [_canonical_turf_field_export_label(self.db, slot, fi) for _g, slot, fi, *_ in small_mixed]
        self.assertIn('Wave 3 TWO_SMALL_ONE_MEDIUM Small Field 1', labels)
        self.assertIn('Wave 3 TWO_SMALL_ONE_MEDIUM Small Field 2', labels)
        self.assertIn('Wave 3 TWO_SMALL_ONE_MEDIUM Medium Field 1', labels)

    def test_game_read_accepts_db_and_uses_canonical_turf_component_label(self):
        rows = self._build_wave('TWO_MEDIUM')
        game, slot, fi, host, home, away, division, _org, _status = rows[1]

        serialized = _to_game_read(
            game,
            db=self.db,
            generated_slot=slot,
            field_instance_name=fi.field_name,
            host_location_name=host.name,
            home_team_name=home.name,
            away_team_name=away.name,
            division_name=division.name,
            division_group=division.division_group,
        )

        self.assertEqual(serialized.field_instance_name, 'Medium Field 2')

    def test_game_read_without_db_does_not_crash_for_turf_slot(self):
        game, slot, fi, host, home, away, division, _org, _status = self._build_wave('TWO_MEDIUM')[0]

        serialized = _to_game_read(
            game,
            generated_slot=slot,
            field_instance_name=fi.field_name,
            host_location_name=host.name,
            home_team_name=home.name,
            away_team_name=away.name,
            division_name=division.name,
            division_group=division.division_group,
        )

        self.assertRegex(serialized.field_instance_name, r'^Medium Field [12]$')

    def test_list_games_returns_200_and_uses_canonical_turf_component_labels(self):
        self._build_wave('TWO_MEDIUM')

        response = self.client.get('/api/games?page_size=300', headers=self._token())

        self.assertEqual(response.status_code, 200, response.text)
        labels = sorted(item['field_instance_name'] for item in response.json()['items'])
        self.assertEqual(labels, ['Medium Field 1', 'Medium Field 2'])


if __name__ == '__main__':
    unittest.main()
