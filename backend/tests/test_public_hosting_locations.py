import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Field, HostLocation, Organization


class PublicHostingLocationsTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        active_org = Organization(id=uuid.uuid4(), name='Antioch', is_active=True)
        inactive_org = Organization(id=uuid.uuid4(), name='Retired Community', is_active=False)
        self.site = HostLocation(id=uuid.uuid4(), organization_id=active_org.id, name='Antioch Sports Complex', address_line1='100 Sports Way', city='Antioch', state='IL', zip_code='60002', public_location_notes='Park near the football fields.', notes='Private gate code', is_active=True)
        missing_address = HostLocation(id=uuid.uuid4(), organization_id=active_org.id, name='Address Pending Park', is_active=True)
        inactive_site = HostLocation(id=uuid.uuid4(), organization_id=active_org.id, name='Closed Park', is_active=False)
        retired_community_site = HostLocation(id=uuid.uuid4(), organization_id=inactive_org.id, name='Retired Park', is_active=True)
        self.db.add_all([active_org, inactive_org, self.site, missing_address, inactive_site, retired_community_site])
        self.db.flush()
        self.db.add_all([Field(host_location_id=self.site.id, name='Field 1', layout_type='SMALL', is_active=True), Field(host_location_id=self.site.id, name='Field 2', layout_type='LARGE', is_active=True)])
        self.db.commit()

        def override_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()
        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def test_public_endpoint_is_unauthenticated_safe_and_canonical(self):
        response = self.client.get('/api/public/hosting-locations')
        self.assertEqual(response.status_code, 200)
        rows = response.json()
        self.assertEqual([row['name'] for row in rows], ['Address Pending Park', 'Antioch Sports Complex'])
        self.assertEqual(sum(row['id'] == str(self.site.id) for row in rows), 1)
        site = next(row for row in rows if row['id'] == str(self.site.id))
        self.assertEqual(site['community'], 'Antioch')
        self.assertEqual(site['address_line_1'], '100 Sports Way')
        self.assertEqual(site['public_notes'], 'Park near the football fields.')
        self.assertNotIn('notes', site)
        self.assertNotIn('is_active', site)


if __name__ == '__main__':
    unittest.main()
