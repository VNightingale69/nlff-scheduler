import unittest
import uuid
from datetime import date, time

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import ROLE_COMMUNITY_ADMIN, ROLE_LEAGUE_ADMIN
from app.database import Base
from app.models import Field, HostLocation, HostLocationConfiguration, HostingAvailability, Organization, Role, User
from app.routes.api import list_fields, list_host_location_configurations, list_host_locations, list_hosting_availabilities


class FieldAreaDataAccessTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()

        self.league_role = Role(id=uuid.uuid4(), name=ROLE_LEAGUE_ADMIN, is_active=True)
        self.community_role = Role(id=uuid.uuid4(), name=ROLE_COMMUNITY_ADMIN, is_active=True)
        self.org_with_data = Organization(id=uuid.uuid4(), name='Community With Data', is_active=True)
        self.org_without_data = Organization(id=uuid.uuid4(), name='Community Without Data', is_active=True)
        self.other_org = Organization(id=uuid.uuid4(), name='Other Community', is_active=True)
        self.league_admin = User(
            id=uuid.uuid4(),
            email='league@example.com',
            full_name='League Admin',
            password_hash='x',
            role=self.league_role,
            organization_id=None,
            is_active=True,
        )
        self.community_admin = User(
            id=uuid.uuid4(),
            email='community@example.com',
            full_name='Community Admin',
            password_hash='x',
            role=self.community_role,
            organization_id=self.org_with_data.id,
            is_active=True,
        )
        self.grass_host = HostLocation(
            id=uuid.uuid4(),
            organization_id=self.org_with_data.id,
            name='Community Grass Park',
            surface_type='GRASS_FIELD',
            is_active=True,
        )
        self.turf_host = HostLocation(
            id=uuid.uuid4(),
            organization_id=self.org_with_data.id,
            name='Community Turf Stadium',
            surface_type='TURF_STADIUM',
            is_active=True,
        )
        self.other_host = HostLocation(
            id=uuid.uuid4(),
            organization_id=self.other_org.id,
            name='Other Community Park',
            surface_type='GRASS_FIELD',
            is_active=True,
        )
        self.field = Field(
            id=uuid.uuid4(),
            host_location_id=self.grass_host.id,
            name='Grass Small 1',
            layout_type='SMALL',
            is_active=True,
        )
        self.other_field = Field(
            id=uuid.uuid4(),
            host_location_id=self.other_host.id,
            name='Other Small 1',
            layout_type='SMALL',
            is_active=True,
        )
        self.turf_config = HostLocationConfiguration(
            id=uuid.uuid4(),
            host_location_id=self.turf_host.id,
            configuration_name='TWO_LARGE',
            large_field_count=2,
            is_active=True,
        )
        self.availability = HostingAvailability(
            id=uuid.uuid4(),
            organization_id=self.org_with_data.id,
            host_location_id=self.grass_host.id,
            field_id=self.field.id,
            layout_type='SMALL',
            slot_index=1,
            available_date=date(2026, 6, 1),
            start_time=time(9, 0),
            end_time=time(10, 0),
            is_available=True,
        )
        self.other_availability = HostingAvailability(
            id=uuid.uuid4(),
            organization_id=self.other_org.id,
            host_location_id=self.other_host.id,
            field_id=self.other_field.id,
            layout_type='SMALL',
            slot_index=1,
            available_date=date(2026, 6, 1),
            start_time=time(9, 0),
            end_time=time(10, 0),
            is_available=True,
        )
        self.db.add_all([
            self.league_role,
            self.community_role,
            self.org_with_data,
            self.org_without_data,
            self.other_org,
            self.league_admin,
            self.community_admin,
            self.grass_host,
            self.turf_host,
            self.other_host,
            self.field,
            self.other_field,
            self.turf_config,
            self.availability,
            self.other_availability,
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_league_admin_selection_loads_community_with_data(self):
        hosts = list_host_locations(organization_id=self.org_with_data.id, page_size=50, current_user=self.league_admin, db=self.db)
        fields = list_fields(organization_id=self.org_with_data.id, page_size=50, current_user=self.league_admin, db=self.db)
        configs = list_host_location_configurations(organization_id=self.org_with_data.id, page_size=50, current_user=self.league_admin, db=self.db)

        self.assertEqual({self.grass_host.id, self.turf_host.id}, {host.id for host in hosts.items})
        self.assertEqual([self.field.id], [field.id for field in fields.items])
        self.assertIn(self.turf_config.id, {config.id for config in configs.items})

    def test_league_admin_selection_returns_empty_state_data_for_community_without_data(self):
        hosts = list_host_locations(organization_id=self.org_without_data.id, page_size=50, current_user=self.league_admin, db=self.db)
        fields = list_fields(organization_id=self.org_without_data.id, page_size=50, current_user=self.league_admin, db=self.db)
        configs = list_host_location_configurations(organization_id=self.org_without_data.id, page_size=50, current_user=self.league_admin, db=self.db)

        self.assertEqual([], hosts.items)
        self.assertEqual([], fields.items)
        self.assertEqual([], configs.items)

    def test_community_admin_is_scoped_to_assigned_community(self):
        hosts = list_host_locations(organization_id=self.other_org.id, page_size=50, current_user=self.community_admin, db=self.db)
        fields = list_fields(organization_id=self.other_org.id, page_size=50, current_user=self.community_admin, db=self.db)
        configs = list_host_location_configurations(organization_id=self.other_org.id, page_size=50, current_user=self.community_admin, db=self.db)
        availability = list_hosting_availabilities(organization_id=self.other_org.id, page_size=50, current_user=self.community_admin, db=self.db)

        self.assertEqual({self.grass_host.id, self.turf_host.id}, {host.id for host in hosts.items})
        self.assertEqual([self.field.id], [field.id for field in fields.items])
        self.assertIn(self.turf_config.id, {config.id for config in configs.items})
        self.assertEqual([self.availability.id], [item.id for item in availability.items])
        self.assertNotIn(self.other_host.id, {host.id for host in hosts.items})
        self.assertNotIn(self.other_field.id, {field.id for field in fields.items})
        self.assertNotIn(self.other_availability.id, {item.id for item in availability.items})

    def test_host_specific_selection_loads_only_that_location_configurations(self):
        fields = list_fields(host_location_id=self.grass_host.id, page_size=50, current_user=self.league_admin, db=self.db)
        configs = list_host_location_configurations(host_location_id=self.turf_host.id, page_size=50, current_user=self.league_admin, db=self.db)

        self.assertEqual([self.field.id], [field.id for field in fields.items])
        self.assertTrue(configs.items)
        self.assertTrue(all(config.host_location_id == self.turf_host.id for config in configs.items))


if __name__ == '__main__':
    unittest.main()
