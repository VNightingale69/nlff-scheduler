import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_SHELL = ROOT / 'frontend/src/components/DashboardShell.tsx'
ENTITIES = ROOT / 'frontend/src/config/entities.ts'
ADMIN_GAMES_PAGE = ROOT / 'frontend/src/app/(dashboard)/admin/games/page.tsx'
DASHBOARD_GAMES_PAGE = ROOT / 'frontend/src/app/(dashboard)/dashboard/games/page.tsx'
MANUAL_BUILDER_PAGE = ROOT / 'frontend/src/app/(dashboard)/admin/manual-schedule-builder/page.tsx'
SCHEDULE_MANAGEMENT_PAGE = ROOT / 'frontend/src/app/(dashboard)/admin/schedule-management/page.tsx'
PUBLISHED_SCHEDULE_PAGE = ROOT / 'frontend/src/app/schedule/page.tsx'
SCORE_MANAGEMENT_PAGE = ROOT / 'frontend/src/app/(dashboard)/admin/scores/page.tsx'
STANDINGS_PAGE = ROOT / 'frontend/src/app/(dashboard)/admin/standings/page.tsx'
AUTH_LIB = ROOT / 'frontend/src/lib/auth.ts'
API_ROUTES = ROOT / 'backend/app/routes/api.py'
MODELS = ROOT / 'backend/app/models.py'


class RetiredGamesFrontendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shell = DASHBOARD_SHELL.read_text()
        cls.entities = ENTITIES.read_text()
        cls.admin_games = ADMIN_GAMES_PAGE.read_text()
        cls.dashboard_games = DASHBOARD_GAMES_PAGE.read_text()
        cls.manual_builder = MANUAL_BUILDER_PAGE.read_text()
        cls.schedule_management = SCHEDULE_MANAGEMENT_PAGE.read_text()
        cls.published_schedule = PUBLISHED_SCHEDULE_PAGE.read_text()
        cls.score_management = SCORE_MANAGEMENT_PAGE.read_text()
        cls.standings = STANDINGS_PAGE.read_text()
        cls.auth = AUTH_LIB.read_text()
        cls.api = API_ROUTES.read_text()
        cls.models = MODELS.read_text()

    def test_games_tab_is_removed_from_left_navigation_for_all_roles(self):
        nav_section = re.search(r"const navOrder =.*?const communityTitles", self.shell, re.DOTALL).group(0)
        self.assertNotIn("'games'", nav_section)
        self.assertNotIn('games:', self.shell)
        self.assertNotIn("games: { title: 'Games'", self.entities)

    def test_legacy_games_routes_redirect_instead_of_rendering_builder(self):
        for source in [self.admin_games, self.dashboard_games]:
            self.assertIn("redirect('/admin/manual-schedule-builder')", source)
            self.assertNotIn("'use client'", source)
            self.assertNotIn('apiFetch', source)
            self.assertNotIn('Manual Game Schedule Builder', source)
            self.assertNotIn('Schedule Filters', source)
            self.assertNotIn('loadGames', source)
            self.assertNotIn('setEditingId', source)

    def test_current_manual_schedule_builder_still_loads_and_allows_schedule_admin_edits(self):
        self.assertIn('Manual Schedule Builder', self.manual_builder)
        self.assertIn("apiFetch('/manual-schedule-builder/options'", self.manual_builder)
        self.assertIn("apiFetch('/manual-schedule-builder/assign'", self.manual_builder)
        self.assertIn('canManageGeneratedGames = canManageSchedule(authUser)', self.manual_builder)
        self.assertIn('canBulkInlineEditScheduledGames = canManageSchedule(authUser)', self.manual_builder)

    def test_schedule_management_published_schedule_score_management_and_standings_still_load(self):
        self.assertIn('ScheduleManagementPage', self.schedule_management)
        self.assertIn("apiFetch(`/schedule-management/games", self.schedule_management)
        self.assertIn("/public/schedule", self.published_schedule)
        self.assertIn('ScoreManagementPage', self.score_management)
        self.assertIn('apiFetch(`/scores${query()}`', self.score_management)
        self.assertIn("apiFetch('/standings'", self.standings)
        self.assertIn('Results & Standings', self.entities)
        self.assertIn('Score Management', self.entities)

    def test_scheduled_games_and_score_data_apis_remain_for_active_workflows(self):
        required_routes = [
            "@router.get('/games'",
            "@router.post('/games'",
            "@router.put('/games/{game_id}'",
            "@router.delete('/games/{game_id}'",
            "@router.get('/schedule-management/games'",
            "@router.get('/public/schedule'",
            "@router.get('/scores'",
            "@router.post('/scores/{game_id}/approve'",
            "@router.post('/scores/{game_id}/publish'",
            "@router.get('/scores/{game_id}/history'",
        ]
        for route in required_routes:
            self.assertIn(route, self.api)

    def test_score_records_remain_tied_to_scheduled_games(self):
        for model_name in ['GameScore', 'ScoreSubmission', 'ScoreHistory']:
            model_block = re.search(rf'class {model_name}.*?(?=\nclass |\Z)', self.models, re.DOTALL).group(0)
            self.assertIn("ForeignKey('games.id'", model_block)
            self.assertIn('game_id', model_block)
        self.assertIn("score_history = relationship('ScoreHistory'", self.models)

    def test_community_admin_does_not_gain_schedule_edit_permissions(self):
        can_manage_schedule = re.search(r'export function canManageSchedule.*?\n}', self.auth, re.DOTALL).group(0)
        self.assertIn("role === 'LEAGUE_ADMIN'", can_manage_schedule)
        self.assertIn("role === 'SCHEDULING_ADMIN'", can_manage_schedule)
        self.assertNotIn('COMMUNITY_ADMIN', can_manage_schedule)

    def test_unrelated_feature_navigation_remains_present(self):
        for expected in [
            'Manual Schedule Builder',
            'Schedule Management',
            'Published Schedule',
            'Score Management',
            'Flagged Scores',
            'Missing Scores',
            'Game Statuses',
            'Results & Standings',
            'Teams',
            'Community Division Participation',
            'Seasons',
            'Host Locations',
            'Hosting Availability',
            'Rulebook',
        ]:
            self.assertIn(expected, self.shell + self.entities)


if __name__ == '__main__':
    unittest.main()
