import unittest
import uuid
from datetime import date, time
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.auth import ROLE_LEAGUE_ADMIN
from app.database import Base
from app.models import Division, FieldInstance, Game, GameSlot, GameStatus, HostLocation, HostingAvailability, Organization, Role, Team
from app.routes.api import GENERATED_SLOTS_CLEAR_WARNING, clear_generated_game_slots


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


if __name__ == '__main__':
    unittest.main()
