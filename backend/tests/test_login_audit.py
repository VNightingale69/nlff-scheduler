import unittest
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import LoginAuditLog, Organization, Role, User
from app.security import create_access_token, hash_password


class LoginAuditTest(unittest.TestCase):
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

        self.scheduling_role = Role(id=uuid.uuid4(), name='SCHEDULING_ADMIN', description='Scheduling Admin', is_active=True)
        self.community_role = Role(id=uuid.uuid4(), name='COMMUNITY_ADMIN', description='Community Admin', is_active=True)
        self.community = Organization(id=uuid.uuid4(), name='Westosha', is_active=True)
        self.scheduling_admin = User(
            id=uuid.uuid4(),
            email='scheduler@example.com',
            full_name='Scheduling Admin',
            password_hash=hash_password('StrongPass123!'),
            role=self.scheduling_role,
            organization=self.community,
            is_active=True,
        )
        self.community_admin = User(
            id=uuid.uuid4(),
            email='community@example.com',
            full_name='Community Admin',
            password_hash=hash_password('StrongPass123!'),
            role=self.community_role,
            organization=self.community,
            is_active=True,
        )
        self.db.add_all([self.scheduling_role, self.community_role, self.community, self.scheduling_admin, self.community_admin])
        self.db.commit()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def auth_header(self, user):
        return {'Authorization': f'Bearer {create_access_token(str(user.id))}'}

    def test_successful_login_creates_audit_record_without_password_or_token(self):
        response = self.client.post(
            '/api/auth/login',
            json={'email': 'scheduler@example.com', 'password': 'StrongPass123!'},
            headers={'user-agent': 'AuditTestBrowser/1.0', 'x-forwarded-for': '203.0.113.10'},
        )

        self.assertEqual(200, response.status_code)
        self.assertIn('access_token', response.json())
        audit = self.db.query(LoginAuditLog).one()
        self.assertEqual(self.scheduling_admin.id, audit.user_id)
        self.assertEqual('scheduler@example.com', audit.email_attempted)
        self.assertEqual('SCHEDULING_ADMIN', audit.user_role)
        self.assertEqual(self.community.id, audit.community_id)
        self.assertEqual('Westosha', audit.community_name)
        self.assertTrue(audit.success)
        self.assertIsNone(audit.failure_reason)
        self.assertEqual('203.0.113.10', audit.ip_address)
        self.assertEqual('AuditTestBrowser/1.0', audit.user_agent)
        audit_payload = {column.name: getattr(audit, column.name) for column in LoginAuditLog.__table__.columns}
        self.assertNotIn('password', audit_payload)
        self.assertNotIn('password_hash', audit_payload)
        self.assertNotIn('access_token', audit_payload)
        self.assertNotIn('refresh_token', audit_payload)

    def test_failed_login_creates_audit_record(self):
        response = self.client.post(
            '/api/auth/login',
            json={'email': 'scheduler@example.com', 'password': 'WrongPass123!'},
            headers={'user-agent': 'AuditTestBrowser/2.0', 'x-forwarded-for': '198.51.100.5'},
        )

        self.assertEqual(401, response.status_code)
        self.assertEqual({'detail': 'Invalid credentials'}, response.json())
        audit = self.db.query(LoginAuditLog).one()
        self.assertIsNone(audit.user_id)
        self.assertEqual('scheduler@example.com', audit.email_attempted)
        self.assertFalse(audit.success)
        self.assertEqual('invalid_credentials', audit.failure_reason)
        self.assertEqual('198.51.100.5', audit.ip_address)
        self.assertEqual('AuditTestBrowser/2.0', audit.user_agent)

    def test_scheduling_admin_can_access_login_audit_endpoint_newest_first(self):
        older = LoginAuditLog(email_attempted='old@example.com', success=True, login_at=datetime.now(UTC) - timedelta(minutes=5))
        newer = LoginAuditLog(email_attempted='new@example.com', success=False, failure_reason='missing_user', login_at=datetime.now(UTC))
        self.db.add_all([older, newer])
        self.db.commit()

        response = self.client.get('/api/admin/login-audit', headers=self.auth_header(self.scheduling_admin))

        self.assertEqual(200, response.status_code)
        emails = [row['email_attempted'] for row in response.json()]
        self.assertEqual(['new@example.com', 'old@example.com'], emails)

    def test_community_admin_cannot_access_global_login_audit_endpoint(self):
        response = self.client.get('/api/admin/login-audit', headers=self.auth_header(self.community_admin))

        self.assertEqual(403, response.status_code)

    def test_failed_audit_insert_does_not_expose_raw_error_to_user(self):
        class BrokenAuditLog:
            def __init__(self, *_, **__):
                raise RuntimeError('raw audit insert failure')

        with patch('app.routes.api.LoginAuditLog', BrokenAuditLog):
            response = self.client.post('/api/auth/login', json={'email': 'scheduler@example.com', 'password': 'StrongPass123!'})

        self.assertEqual(200, response.status_code)
        self.assertNotIn('raw audit insert failure', response.text)
        self.assertIn('access_token', response.json())


if __name__ == '__main__':
    unittest.main()
