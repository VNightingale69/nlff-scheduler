import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import GameStatus, Organization, Role, User


class UserOrganizationRelationshipMappingTest(unittest.TestCase):
    def test_all_model_mappers_configure_without_ambiguous_user_organization_foreign_keys(self):
        configure_mappers()

    def test_user_organization_relationship_uses_user_organization_id(self):
        configure_mappers()

        foreign_keys = User.organization.property._calculated_foreign_keys
        self.assertEqual(foreign_keys, {User.organization_id.property.columns[0]})

    def test_organization_users_relationship_uses_user_organization_id(self):
        configure_mappers()

        foreign_keys = Organization.users.property._calculated_foreign_keys
        self.assertEqual(foreign_keys, {User.organization_id.property.columns[0]})

    def test_logo_uploaded_by_user_relationship_uses_logo_uploader_id(self):
        configure_mappers()

        foreign_keys = Organization.logo_uploaded_by_user.property._calculated_foreign_keys
        self.assertEqual(foreign_keys, {Organization.logo_uploaded_by_user_id.property.columns[0]})


class StartupSeedMapperQueryTest(unittest.TestCase):
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

    def tearDown(self):
        self.db.close()

    def test_auth_seed_can_query_role_without_mapper_initialization_failure(self):
        self.assertIsNone(self.db.query(Role).filter(Role.name == 'LEAGUE_ADMIN').first())

    def test_game_status_seed_can_query_status_without_mapper_initialization_failure(self):
        self.assertIsNone(self.db.query(GameStatus).filter(GameStatus.code == 'SCHEDULED').first())


if __name__ == '__main__':
    unittest.main()
