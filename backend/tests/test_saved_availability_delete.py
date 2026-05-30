import unittest
import uuid
from datetime import date, time
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.auth import ROLE_LEAGUE_ADMIN
from app.database import Base
from app.models import Division, FieldInstance, Game, GameSlot, GameStatus, HostLocation, HostingAvailability, Organization, Role, Team, TurfWave
from app.routes.api import delete_saved_hosting_availability


class SavedAvailabilityDeleteTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()

        self.org = Organization(id=uuid.uuid4(), name='Org A', is_active=True)
        self.host = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Johnsburg Stadium', is_active=True)
        self.availability = HostingAvailability(
            id=uuid.uuid4(),
            organization_id=self.org.id,
            host_location_id=self.host.id,
            available_date=date(2026, 6, 6),
            start_time=time(9, 0),
            end_time=time(12, 0),
            is_available=True,
        )
        self.instance = FieldInstance(
            id=uuid.uuid4(),
            host_location_id=self.host.id,
            hosting_availability_id=self.availability.id,
            instance_date=date(2026, 6, 6),
            field_name='Turf Small 1',
            field_type='SMALL',
            is_active=True,
        )
        self.wave = TurfWave(
            id=uuid.uuid4(),
            host_location_id=self.host.id,
            hosting_availability_id=self.availability.id,
            host_date=date(2026, 6, 6),
            sequence_number=1,
            wave_intent='SMALL_FIELDS',
            preferred_layout_code='THREE_SMALL',
            start_time=time(9, 0),
            end_time=time(12, 0),
        )
        self.slot = GameSlot(
            id=uuid.uuid4(),
            field_instance_id=self.instance.id,
            host_location_id=self.host.id,
            slot_date=date(2026, 6, 6),
            start_time=time(9, 0),
            end_time=time(10, 0),
            field_type='SMALL',
            status='OPEN',
            turf_wave_id=self.wave.id,
        )
        self.db.add_all([self.org, self.host, self.availability, self.instance, self.wave, self.slot])
        self.db.commit()
        self.current_user = SimpleNamespace(role=Role(name=ROLE_LEAGUE_ADMIN), organization_id=None)

    def test_deletes_turf_waves_before_saved_availability_when_no_games_reference_it(self):
        result = delete_saved_hosting_availability(str(self.availability.id), current_user=self.current_user, db=self.db)

        self.assertEqual({'ok': True, 'deleted': 1}, result)
        self.assertIsNone(self.db.get(GameSlot, self.slot.id))
        self.assertIsNone(self.db.get(TurfWave, self.wave.id))
        self.assertIsNone(self.db.get(FieldInstance, self.instance.id))
        self.assertIsNone(self.db.get(HostingAvailability, self.availability.id))

    def test_blocks_delete_when_game_references_availability_field_instance(self):
        division = Division(id=uuid.uuid4(), name='K/1st', division_group='COED', sort_order=1, required_field_layout_type='SMALL', is_active=True)
        status = GameStatus(id=uuid.uuid4(), code='scheduled', label='Scheduled', is_active=True)
        home = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=division.id, name='Home', is_active=True)
        away = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=division.id, name='Away', is_active=True)
        game = Game(
            id=uuid.uuid4(),
            home_team_id=home.id,
            away_team_id=away.id,
            host_location_id=self.host.id,
            field_instance_id=self.instance.id,
            game_status_id=status.id,
            game_date=date(2026, 6, 6),
            kickoff_time=time(9, 0),
        )
        self.db.add_all([division, status, home, away, game])
        self.db.commit()

        with self.assertRaises(HTTPException) as raised:
            delete_saved_hosting_availability(str(self.availability.id), current_user=self.current_user, db=self.db)

        self.assertEqual(409, raised.exception.status_code)
        self.assertIn('scheduled games exist', raised.exception.detail)
        self.assertIsNotNone(self.db.get(TurfWave, self.wave.id))
        self.assertIsNotNone(self.db.get(HostingAvailability, self.availability.id))


if __name__ == '__main__':
    unittest.main()
