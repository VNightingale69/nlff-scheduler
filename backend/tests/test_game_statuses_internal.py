import re
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import GameStatus
from app.services.game_statuses import REQUIRED_GAME_STATUSES, ensure_required_game_statuses


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_SHELL = ROOT / 'frontend/src/components/DashboardShell.tsx'
ENTITIES = ROOT / 'frontend/src/config/entities.ts'
GAME_STATUSES_PAGE = ROOT / 'frontend/src/app/(dashboard)/admin/game-statuses/page.tsx'
MANUAL_BUILDER_PAGE = ROOT / 'frontend/src/app/(dashboard)/admin/manual-schedule-builder/page.tsx'
SCORE_MANAGEMENT_PAGE = ROOT / 'frontend/src/app/(dashboard)/admin/scores/page.tsx'
STANDINGS_PAGE = ROOT / 'frontend/src/app/(dashboard)/admin/standings/page.tsx'
PUBLISHED_SCHEDULE_PAGE = ROOT / 'frontend/src/app/schedule/page.tsx'
API_ROUTES = ROOT / 'backend/app/routes/api.py'
SERVICE = ROOT / 'backend/app/services/game_statuses.py'


class GameStatusesInternalFrontendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shell = DASHBOARD_SHELL.read_text()
        cls.entities = ENTITIES.read_text()
        cls.game_statuses_page = GAME_STATUSES_PAGE.read_text()
        cls.manual_builder = MANUAL_BUILDER_PAGE.read_text()
        cls.score_management = SCORE_MANAGEMENT_PAGE.read_text()
        cls.standings = STANDINGS_PAGE.read_text()
        cls.published_schedule = PUBLISHED_SCHEDULE_PAGE.read_text()
        cls.api = API_ROUTES.read_text()
        cls.service = SERVICE.read_text()

    def test_game_statuses_nav_item_is_not_rendered_for_admin_roles(self):
        nav_section = re.search(r"const navOrder =.*?const communityTitles", self.shell, re.DOTALL).group(0)
        self.assertNotIn("'game-statuses'", nav_section)
        self.assertNotIn("title: 'Game Statuses'", self.entities)
        self.assertNotIn("Game Statuses", nav_section)

    def test_game_statuses_direct_route_redirects_to_score_management(self):
        self.assertIn("redirect('/admin/scores')", self.game_statuses_page)
        self.assertNotIn("'use client'", self.game_statuses_page)
        self.assertNotIn('Ensure Required Statuses', self.game_statuses_page)
        self.assertNotIn("apiFetch('/game-statuses", self.game_statuses_page)

    def test_statuses_endpoint_remains_internal_for_builder_but_admin_protected(self):
        self.assertIn("apiFetch('/game-statuses?page_size=200'", self.manual_builder)
        self.assertIn("@router.get('/game-statuses', response_model=PagedResponse[dict], dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN, ROLE_SCHEDULING_ADMIN))])", self.api)
        self.assertIn("@router.post('/game-statuses/seed', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])", self.api)

    def test_status_seeding_remains_backend_internal_and_startup_driven(self):
        self.assertIn('seed_required_game_statuses(db)', (ROOT / 'backend/app/main.py').read_text())
        for code in ['SCHEDULED', 'COMPLETED', 'CANCELLED', 'POSTPONED', 'FORFEIT', 'UNSCHEDULED', 'RESCHEDULED']:
            self.assertIn(code, self.service)

    def test_score_standings_and_public_schedule_ui_still_use_active_apis(self):
        self.assertIn('ScoreManagementPage', self.score_management)
        self.assertIn('apiFetch(`/scores${query()}`', self.score_management)
        self.assertIn("apiFetch('/standings'", self.standings)
        self.assertIn('/public/schedule', self.published_schedule)


class GameStatusesSeedingTest(unittest.TestCase):
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

    def test_required_statuses_are_seeded_when_missing(self):
        changed = ensure_required_game_statuses(self.db)
        self.db.commit()

        expected_codes = {code for code, _ in REQUIRED_GAME_STATUSES}
        rows = self.db.query(GameStatus).all()
        self.assertEqual({row.code for row in rows}, expected_codes)
        self.assertEqual(set(changed), expected_codes)
        self.assertTrue(all(row.is_active for row in rows))

    def test_seeding_required_statuses_is_idempotent_and_does_not_duplicate_existing_rows(self):
        ensure_required_game_statuses(self.db)
        self.db.commit()
        first_ids = {row.code: row.id for row in self.db.query(GameStatus).all()}

        changed = ensure_required_game_statuses(self.db)
        self.db.commit()
        second_ids = {row.code: row.id for row in self.db.query(GameStatus).all()}

        self.assertEqual(changed, [])
        self.assertEqual(second_ids, first_ids)
        self.assertEqual(self.db.query(GameStatus).count(), len(REQUIRED_GAME_STATUSES))

    def test_existing_rows_are_reused_reactivated_and_corrected_without_deleting_unknown_statuses(self):
        scheduled = GameStatus(code='scheduled', label='Old Scheduled', is_active=False)
        completed = GameStatus(code='COMPLETED', label='Complete', is_active=True)
        unknown = GameStatus(code='WEATHER_DELAY', label='Weather Delay', is_active=True)
        self.db.add_all([scheduled, completed, unknown])
        self.db.commit()
        scheduled_id = scheduled.id
        completed_id = completed.id
        unknown_id = unknown.id

        changed = ensure_required_game_statuses(self.db)
        self.db.commit()

        scheduled = self.db.query(GameStatus).filter(GameStatus.code == 'SCHEDULED').one()
        completed = self.db.query(GameStatus).filter(GameStatus.code == 'COMPLETED').one()
        unknown = self.db.query(GameStatus).filter(GameStatus.code == 'WEATHER_DELAY').one()
        self.assertEqual(scheduled.id, scheduled_id)
        self.assertEqual(scheduled.label, 'Scheduled')
        self.assertTrue(scheduled.is_active)
        self.assertEqual(completed.id, completed_id)
        self.assertEqual(completed.label, 'Completed')
        self.assertIn('SCHEDULED', changed)
        self.assertIn('COMPLETED', changed)
        self.assertEqual(unknown.id, unknown_id)
        self.assertEqual(unknown.label, 'Weather Delay')

    def test_scheduled_completed_and_forfeit_statuses_remain_available(self):
        ensure_required_game_statuses(self.db)
        self.db.commit()

        for code in ['SCHEDULED', 'COMPLETED', 'FORFEIT']:
            status = self.db.query(GameStatus).filter(GameStatus.code == code).one()
            self.assertTrue(status.is_active)
            self.assertEqual(status.label, code.title())


if __name__ == '__main__':
    unittest.main()
