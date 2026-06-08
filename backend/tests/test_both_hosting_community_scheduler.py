import asyncio
import csv
import io
import unittest
import uuid
from datetime import date, time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Division, FieldInstance, Game, GameSlot, GameStatus, HostLocation, Organization, Role, Season, Team, User, Week
from app.routes.api import auto_fill_apply, auto_fill_preview, export_schedule_management_csv
from app.security import hash_password


class BothHostingCommunitySchedulerTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        self.season = Season(id=uuid.uuid4(), name='Fall', start_date=date(2026, 8, 1), end_date=date(2026, 11, 1), is_active=True)
        self.week1 = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=1, start_date=date(2026, 8, 8), end_date=date(2026, 8, 14), primary_game_date=date(2026, 8, 8))
        self.week2 = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=2, start_date=date(2026, 8, 15), end_date=date(2026, 8, 21), primary_game_date=date(2026, 8, 15))
        self.division = Division(id=uuid.uuid4(), division_group='Coed', name='K-1st', sort_order=1, required_field_layout_type='THIRTY_YARD_WIDTH', is_active=True)
        self.status = GameStatus(id=uuid.uuid4(), code='SCHEDULED', label='Scheduled', is_active=True)
        self.org_a = Organization(id=uuid.uuid4(), name='Community A', is_active=True)
        self.org_b = Organization(id=uuid.uuid4(), name='Community B', is_active=True)
        self.league_role = Role(id=uuid.uuid4(), name='League Admin', is_active=True)
        self.community_role = Role(id=uuid.uuid4(), name='Community Admin', is_active=True)
        self.league_admin = User(id=uuid.uuid4(), email='league@example.com', full_name='League Admin', password_hash=hash_password('Password123!'), role_id=self.league_role.id, is_active=True)
        self.community_admin = User(id=uuid.uuid4(), email='community@example.com', full_name='Community Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.org_a.id, is_active=True)
        self.team_a = Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=self.division.id, name='Community A One', is_active=True)
        self.team_b = Team(id=uuid.uuid4(), organization_id=self.org_b.id, division_id=self.division.id, name='Community B One', is_active=True)
        self.db.add_all([self.season, self.week1, self.week2, self.division, self.status, self.org_a, self.org_b, self.league_role, self.community_role, self.league_admin, self.community_admin, self.team_a, self.team_b])
        self.db.commit()

    def _add_host_slot(self, org, host_name, field_name, hour=9, surface='GRASS_FIELD'):
        host = HostLocation(id=uuid.uuid4(), organization_id=org.id, name=host_name, surface_type=surface, max_small_fields=1, max_total_fields=1, is_active=True)
        field = FieldInstance(id=uuid.uuid4(), host_location_id=host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.primary_game_date, field_name=field_name, field_type='SMALL', is_active=True)
        slot = GameSlot(id=uuid.uuid4(), field_instance_id=field.id, host_location_id=host.id, season_id=self.season.id, week_id=self.week2.id, slot_date=self.week2.primary_game_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
        self.db.add_all([host, field, slot])
        self.db.commit()
        return host, field, slot

    def _preview(self):
        return auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)

    def test_both_hosting_one_location_each_uses_home_equity_and_diagnostics(self):
        host_a, _, _ = self._add_host_slot(self.org_a, 'A Park', 'A Grass')
        host_b, _, _ = self._add_host_slot(self.org_b, 'B Park', 'B Grass')
        prior = Game(id=uuid.uuid4(), season_id=self.season.id, week_id=self.week1.id, home_team_id=self.team_a.id, away_team_id=self.team_b.id, game_status_id=self.status.id, game_date=self.week1.primary_game_date, kickoff_time=time(9, 0))
        self.db.add(prior)
        self.db.commit()

        preview = self._preview()

        self.assertEqual(preview['proposed_game_count'], 1)
        self.assertEqual(preview['proposals'][0]['host_location_id'], str(host_b.id))
        self.assertEqual(preview['proposals'][0]['home_team_id'], str(self.team_b.id))
        diagnostics = preview['diagnostics']['both_hosting_community_decisions']
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(set(diagnostics[0]['candidate_host_locations_considered']), {str(host_a.id), str(host_b.id)})
        self.assertEqual(diagnostics[0]['selected_host_location_id'], str(host_b.id))
        self.assertIn('home equity', diagnostics[0]['decision_drivers'])

    def test_both_hosting_multi_location_community_considers_all_home_locations(self):
        host_a1, _, _ = self._add_host_slot(self.org_a, 'A Stadium', 'Small Field 1', surface='TURF_STADIUM')
        host_a2, _, _ = self._add_host_slot(self.org_a, 'A Park', 'A Custom Grass', hour=10)
        host_b, _, _ = self._add_host_slot(self.org_b, 'B Park', 'B Custom Grass')

        preview = self._preview()

        diagnostics = preview['diagnostics']['both_hosting_community_decisions']
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(set(diagnostics[0]['candidate_host_locations_considered']), {str(host_a1.id), str(host_a2.id), str(host_b.id)})
        self.assertIn(preview['proposals'][0]['host_location_id'], {str(host_a1.id), str(host_a2.id), str(host_b.id)})
        if preview['proposals'][0]['host_location_id'] == str(host_a2.id):
            self.assertEqual(preview['proposals'][0]['field'], 'A Custom Grass')

    def test_equal_score_fallback_is_repeatable(self):
        self._add_host_slot(self.org_a, 'A Park', 'A Grass')
        self._add_host_slot(self.org_b, 'B Park', 'B Grass')

        first = self._preview()['proposals'][0]['host_location_id']
        second = self._preview()['proposals'][0]['host_location_id']

        self.assertEqual(first, second)

    def test_apply_export_has_saved_host_assignment_and_no_diagnostic_rows(self):
        host_a, _, _ = self._add_host_slot(self.org_a, 'A Park', 'A Grass')
        self._add_host_slot(self.org_b, 'B Park', 'B Grass')

        applied = auto_fill_apply({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)
        self.assertEqual(applied['created_count'], 1)
        saved_game = self.db.query(Game).one()
        self.assertIsNotNone(saved_game.host_location_id)

        response = export_schedule_management_csv(db=self.db, current_user=self.league_admin)

        async def _read_body():
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.encode() if isinstance(chunk, str) else chunk)
            return b''.join(chunks).decode()

        csv_text = asyncio.run(_read_body())
        rows = list(csv.reader(io.StringIO(csv_text)))
        self.assertEqual(len(rows), 2)
        self.assertNotIn('Both communities hosting', csv_text)
        self.assertIn(str(saved_game.game_date), csv_text)



if __name__ == '__main__':
    unittest.main()
