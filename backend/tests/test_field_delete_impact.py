import unittest
import uuid
from datetime import date, time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import ROLE_COMMUNITY_ADMIN, ROLE_SCHEDULING_ADMIN
from app.database import Base, get_db
from app.main import app
from app.models import Division, Field, FieldInstance, Game, GameScore, GameSlot, GameStatus, HostLocation, HostingAvailability, Organization, Role, ScoreHistory, Season, Team, User, Week
from app.security import create_access_token, hash_password


class FieldDeleteImpactTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool, future=True)
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.db = self.SessionLocal()

        self.scheduling_role = Role(id=uuid.uuid4(), name=ROLE_SCHEDULING_ADMIN, is_active=True)
        self.community_role = Role(id=uuid.uuid4(), name=ROLE_COMMUNITY_ADMIN, is_active=True)
        self.home_org = Organization(id=uuid.uuid4(), name='Home Community', is_active=True)
        self.other_org = Organization(id=uuid.uuid4(), name='Other Community', is_active=True)
        self.division = Division(id=uuid.uuid4(), name='K-1', division_group='COED', sort_order=1, required_field_layout_type='SMALL', is_active=True)
        self.host = HostLocation(id=uuid.uuid4(), organization_id=self.home_org.id, name='Home Grass', surface_type='GRASS_FIELD', is_active=True)
        self.other_host = HostLocation(id=uuid.uuid4(), organization_id=self.other_org.id, name='Other Grass', surface_type='GRASS_FIELD', is_active=True)
        self.season = Season(id=uuid.uuid4(), name='Fall 2026', start_date=date(2026, 8, 1), end_date=date(2026, 11, 1), is_active=True, schedule_status='saved')
        self.week = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=1, label='Week 1', start_date=date(2026, 9, 1), end_date=date(2026, 9, 7), primary_game_date=date(2026, 9, 5), date_type='REGULAR_SEASON')
        self.status = GameStatus(id=uuid.uuid4(), code='scheduled', label='Scheduled', is_active=True)
        self.home_team = Team(id=uuid.uuid4(), organization_id=self.home_org.id, division_id=self.division.id, name='Home 1', coach_name='Coach H', coach_email='h@example.com', is_active=True)
        self.away_team = Team(id=uuid.uuid4(), organization_id=self.other_org.id, division_id=self.division.id, name='Other 1', coach_name='Coach O', coach_email='o@example.com', is_active=True)
        self.field = Field(id=uuid.uuid4(), host_location_id=self.host.id, name='Small Field 1', layout_type='SMALL', is_active=True)
        self.unused_field = Field(id=uuid.uuid4(), host_location_id=self.host.id, name='Small Field 2', layout_type='SMALL', is_active=True)
        self.other_field = Field(id=uuid.uuid4(), host_location_id=self.other_host.id, name='Other Small 1', layout_type='SMALL', is_active=True)
        self.availability = HostingAvailability(id=uuid.uuid4(), season_id=self.season.id, week_id=self.week.id, organization_id=self.home_org.id, host_location_id=self.host.id, field_id=self.field.id, available_date=date(2026, 9, 5), primary_game_date=date(2026, 9, 5), start_time=time(9, 0), end_time=time(12, 0), active=True, is_available=True)
        self.field_instance = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=self.availability.id, instance_date=date(2026, 9, 5), field_name='Small Field 1', field_type='SMALL', is_active=True)
        self.game = Game(id=uuid.uuid4(), season_id=self.season.id, week_id=self.week.id, home_team_id=self.home_team.id, away_team_id=self.away_team.id, field_id=self.field.id, host_location_id=self.host.id, field_instance_id=self.field_instance.id, game_status_id=self.status.id, game_date=date(2026, 9, 5), kickoff_time=time(9, 0))
        self.slot = GameSlot(id=uuid.uuid4(), field_instance_id=self.field_instance.id, host_location_id=self.host.id, season_id=self.season.id, week_id=self.week.id, slot_date=date(2026, 9, 5), start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='ASSIGNED', assigned_game_id=self.game.id)
        self.score = GameScore(id=uuid.uuid4(), game_id=self.game.id, home_score=14, away_score=7, score_status='APPROVED')
        self.history = ScoreHistory(id=uuid.uuid4(), game_id=self.game.id, action='APPROVED', previous_home_score=14, previous_away_score=7, new_home_score=14, new_away_score=7, previous_status='SUBMITTED', new_status='APPROVED')
        self.scheduling_user = User(id=uuid.uuid4(), email='scheduler@example.com', full_name='Scheduler', password_hash=hash_password('Password123!'), role_id=self.scheduling_role.id, organization_id=None, is_active=True)
        self.home_user = User(id=uuid.uuid4(), email='home@example.com', full_name='Home Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.home_org.id, is_active=True)
        self.other_user = User(id=uuid.uuid4(), email='other@example.com', full_name='Other Admin', password_hash=hash_password('Password123!'), role_id=self.community_role.id, organization_id=self.other_org.id, is_active=True)
        self.db.add_all([self.scheduling_role, self.community_role, self.home_org, self.other_org, self.division, self.host, self.other_host, self.season, self.week, self.status, self.home_team, self.away_team, self.field, self.unused_field, self.other_field, self.availability, self.field_instance, self.game, self.slot, self.score, self.history, self.scheduling_user, self.home_user, self.other_user])
        self.db.commit()

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()
        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def _token(self, user):
        return {'Authorization': f'Bearer {create_access_token(str(user.id))}'}

    def test_scheduling_admin_deletes_assigned_field_and_preserves_game_score_history(self):
        impact = self.client.get(f'/api/fields/{self.field.id}/delete-impact', headers=self._token(self.scheduling_user))
        self.assertEqual(impact.status_code, 200, impact.text)
        self.assertEqual(impact.json()['affected_scheduled_games_count'], 1)

        response = self.client.delete(f'/api/fields/{self.field.id}', headers=self._token(self.scheduling_user))
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload['affected_scheduled_games_count'], 1)
        self.assertEqual(payload['affected_game_ids'], [str(self.game.id)])

        db = self.SessionLocal()
        try:
            field = db.get(Field, self.field.id)
            game = db.get(Game, self.game.id)
            self.assertIsNotNone(field.deleted_at)
            self.assertFalse(field.is_active)
            self.assertIsNone(game.field_id)
            self.assertIsNone(game.field_instance_id)
            self.assertTrue(game.missing_field_assignment)
            self.assertTrue(game.needs_schedule_review)
            self.assertEqual(game.field_assignment_status, 'MISSING_FIELD')
            self.assertEqual(db.query(GameScore).filter(GameScore.game_id == self.game.id).count(), 1)
            self.assertEqual(db.query(ScoreHistory).filter(ScoreHistory.game_id == self.game.id).count(), 1)
            self.assertEqual(db.query(Game).filter(Game.id == self.game.id).count(), 1)
            self.assertFalse(db.get(HostingAvailability, self.availability.id).is_available)
            self.assertFalse(db.get(FieldInstance, self.field_instance.id).is_active)
        finally:
            db.close()

        fields = self.client.get(f'/api/fields?host_location_id={self.host.id}&page_size=50', headers=self._token(self.scheduling_user))
        self.assertEqual(fields.status_code, 200, fields.text)
        self.assertNotIn(str(self.field.id), [item['id'] for item in fields.json()['items']])

        diagnostics = self.client.get(f'/api/schedule-management/publish-diagnostics?season_id={self.season.id}', headers=self._token(self.scheduling_user))
        self.assertEqual(diagnostics.status_code, 200, diagnostics.text)
        self.assertGreater(diagnostics.json()['publish_blocking_issue_count'], 0)
        self.assertIn('SCHEDULED_GAME_MISSING_FIELD', diagnostics.text)

        export = self.client.get(f'/api/schedule-management/export.csv?season_id={self.season.id}', headers=self._token(self.scheduling_user))
        self.assertEqual(export.status_code, 200, export.text)
        self.assertIn('Field Not Assigned', export.text)
        self.assertNotIn('Small Field 1', export.text)

    def test_community_admin_can_delete_own_field_but_not_other_community_field(self):
        own = self.client.delete(f'/api/fields/{self.unused_field.id}', headers=self._token(self.home_user))
        self.assertEqual(own.status_code, 200, own.text)
        self.assertEqual(own.json()['affected_scheduled_games_count'], 0)

        forbidden = self.client.delete(f'/api/fields/{self.other_field.id}', headers=self._token(self.home_user))
        self.assertEqual(forbidden.status_code, 403, forbidden.text)

    def test_delete_rolls_back_when_cleanup_fails(self):
        original_commit = self.SessionLocal.class_.commit

        def failing_commit(session):
            raise RuntimeError('forced commit failure')

        self.SessionLocal.class_.commit = failing_commit
        try:
            response = self.client.delete(f'/api/fields/{self.field.id}', headers=self._token(self.scheduling_user))
            self.assertEqual(response.status_code, 500, response.text)
        finally:
            self.SessionLocal.class_.commit = original_commit

        db = self.SessionLocal()
        try:
            field = db.get(Field, self.field.id)
            game = db.get(Game, self.game.id)
            self.assertIsNone(field.deleted_at)
            self.assertTrue(field.is_active)
            self.assertEqual(game.field_instance_id, self.field_instance.id)
            self.assertFalse(game.missing_field_assignment)
        finally:
            db.close()


if __name__ == '__main__':
    unittest.main()
