import unittest
import uuid
from datetime import date, time

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Division, Field, FieldConfigurationOption, FieldInstance, Game, GameStatus, GameSlot, HostLocation, HostingAvailability, Organization, OrganizationDivisionParticipation, PhysicalFieldArea, Team
from app.services.organization_cleanup import cleanup_organization_dependencies


class OrganizationCleanupTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()

        self.org = Organization(id=uuid.uuid4(), name='DeleteMe', is_active=True)
        self.division = Division(id=uuid.uuid4(), name='3rd', division_group='COED', sort_order=1, required_field_layout_type='THIRTY_YARD_WIDTH', is_active=True)
        self.status = GameStatus(id=uuid.uuid4(), code='scheduled', label='Scheduled', is_active=True)
        self.host = HostLocation(id=uuid.uuid4(), organization_id=self.org.id, name='Host A', is_active=True)
        self.area = PhysicalFieldArea(id=uuid.uuid4(), host_location_id=self.host.id, name='Area', field_space_type='grass', supports_dynamic_configuration=True, is_active=True)
        self.option = FieldConfigurationOption(id=uuid.uuid4(), physical_field_area_id=self.area.id, name='Option A', thirty_yard_capacity=1, fifty_three_yard_capacity=0, is_active=True)
        self.field = Field(id=uuid.uuid4(), host_location_id=self.host.id, physical_field_area_id=self.area.id, name='Field A', layout_type='THIRTY_YARD_WIDTH', is_active=True)
        self.availability = HostingAvailability(id=uuid.uuid4(), field_id=self.field.id, physical_field_area_id=self.area.id, field_configuration_option_id=self.option.id, layout_type='THIRTY_YARD_WIDTH', slot_index=1, available_date=date(2026, 5, 1), start_time=time(10, 0), end_time=time(11, 0), is_available=True)
        self.instance = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=self.availability.id, instance_date=date(2026, 5, 1), field_name='Field A', field_type='30', is_active=True)
        self.home = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='Home', is_active=True)
        self.away = Team(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, name='Away', is_active=True)
        self.game = Game(id=uuid.uuid4(), home_team_id=self.home.id, away_team_id=self.away.id, field_id=self.field.id, game_status_id=self.status.id, game_date=date(2026, 5, 1), kickoff_time=time(10, 0))
        self.slot = GameSlot(id=uuid.uuid4(), field_instance_id=self.instance.id, host_location_id=self.host.id, slot_date=date(2026, 5, 1), start_time=time(10, 0), end_time=time(11, 0), field_type='30', status='OPEN')
        self.participation = OrganizationDivisionParticipation(id=uuid.uuid4(), organization_id=self.org.id, division_id=self.division.id, is_participating=True, team_count=2, is_active=True)

        self.db.add_all([self.org, self.division, self.status, self.host, self.area, self.option, self.field, self.availability, self.instance, self.home, self.away, self.game, self.slot, self.participation])
        self.db.commit()

    def test_dry_run_reports_without_deleting(self):
        result = cleanup_organization_dependencies(self.db, self.org.id, dry_run=True)
        self.assertTrue(result['dry_run'])
        self.assertGreater(result['would_delete']['organization'], 0)
        self.assertEqual(self.db.query(Organization).filter(Organization.id == self.org.id).count(), 1)
        self.assertEqual(self.db.query(Game).count(), 1)

    def test_cleanup_deletes_dependencies_and_org(self):
        result = cleanup_organization_dependencies(self.db, self.org.id, dry_run=False)
        self.assertFalse(result['dry_run'])
        self.assertEqual(self.db.query(Organization).filter(Organization.id == self.org.id).count(), 0)
        self.assertEqual(self.db.query(Team).count(), 0)
        self.assertEqual(self.db.query(Game).count(), 0)
        self.assertEqual(self.db.query(GameSlot).count(), 0)

    def test_not_found_returns_user_friendly_error(self):
        with self.assertRaises(HTTPException) as ctx:
            cleanup_organization_dependencies(self.db, uuid.uuid4(), dry_run=False)
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, 'Organization not found')


if __name__ == '__main__':
    unittest.main()
