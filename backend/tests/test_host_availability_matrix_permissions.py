import unittest
import uuid
from types import SimpleNamespace

from fastapi import HTTPException

from app.routes.api import (
    HOST_PLAN_SELECTION_PERMISSION_MESSAGE,
    clear_host_plan_selections,
    generate_suggested_host_plan,
    save_host_availability_matrix,
    set_host_plan_week_lock,
    auto_schedule_entire_season,
)
from app.schemas import HostAvailabilityMatrixSaveRequest


class HostAvailabilityMatrixPermissionTest(unittest.TestCase):
    def setUp(self):
        self.other_admin = SimpleNamespace(email='other-admin@example.com')
        self.season_id = uuid.uuid4()

    def assert_forbidden(self, callback):
        with self.assertRaises(HTTPException) as raised:
            callback()
        self.assertEqual(403, raised.exception.status_code)
        self.assertEqual(HOST_PLAN_SELECTION_PERMISSION_MESSAGE, raised.exception.detail)

    def test_rejects_matrix_save_for_non_designated_admin(self):
        payload = HostAvailabilityMatrixSaveRequest(season_id=self.season_id, selections=[])

        self.assert_forbidden(lambda: save_host_availability_matrix(payload, current_user=self.other_admin, db=None))

    def test_rejects_matrix_generation_for_non_designated_admin(self):
        payload = {'season_id': str(self.season_id), 'game_date': '2026-06-06'}

        self.assert_forbidden(lambda: generate_suggested_host_plan(payload, current_user=self.other_admin, db=None))

    def test_rejects_week_lock_for_non_designated_admin(self):
        payload = {'season_id': str(self.season_id), 'game_date': '2026-06-06', 'locked': True}

        self.assert_forbidden(lambda: set_host_plan_week_lock(payload, current_user=self.other_admin, db=None))

    def test_rejects_matrix_clear_for_non_designated_admin(self):
        self.assert_forbidden(lambda: clear_host_plan_selections(self.season_id, current_user=self.other_admin, db=None))

    def test_rejects_auto_schedule_with_host_plan_selections_for_non_designated_admin(self):
        payload = {'season_id': str(self.season_id), 'use_host_plan_selections': True}

        self.assert_forbidden(lambda: auto_schedule_entire_season(payload, current_user=self.other_admin, db=None))


if __name__ == '__main__':
    unittest.main()
