import unittest
import uuid
from datetime import date, time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Division, FieldInstance, Game, GameSlot, GameStatus, HostLocation, Organization, Season, Team, Week
from app.routes.api import auto_fill_apply, auto_fill_preview


class AutoFillPreviewTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        self.season = Season(id=uuid.uuid4(), name='Spring', start_date=date(2026, 4, 1), end_date=date(2026, 7, 1), is_active=True)
        self.division = Division(id=uuid.uuid4(), name='4th Grade', required_field_layout_type='THIRTY_YARD_WIDTH', is_active=True)
        self.status = GameStatus(id=uuid.uuid4(), code='SCHEDULED', label='Scheduled', is_active=True)
        self.week1 = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=1, start_date=date(2026, 5, 1), end_date=date(2026, 5, 7))
        self.week2 = Week(id=uuid.uuid4(), season_id=self.season.id, week_number=2, start_date=date(2026, 5, 8), end_date=date(2026, 5, 14))
        self.org_w = Organization(id=uuid.uuid4(), name='Westosha', is_active=True)
        self.org_a = Organization(id=uuid.uuid4(), name='Antioch', is_active=True)
        self.host = HostLocation(id=uuid.uuid4(), organization_id=self.org_w.id, name='Westosha Park', is_active=True)
        self.fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Small Field 1', field_type='SMALL', is_active=True)
        self.slot = GameSlot(id=uuid.uuid4(), field_instance_id=self.fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(9, 0), end_time=time(10, 0), field_type='SMALL', status='OPEN')
        self.wm = Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=self.division.id, name='Westosha Maroon', is_active=True)
        self.wg = Team(id=uuid.uuid4(), organization_id=self.org_w.id, division_id=self.division.id, name='Westosha Gold', is_active=True)
        self.ab = Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=self.division.id, name='Antioch Black', is_active=True)
        self.as_ = Team(id=uuid.uuid4(), organization_id=self.org_a.id, division_id=self.division.id, name='Antioch Silver', is_active=True)
        self.db.add_all([self.season, self.division, self.status, self.week1, self.week2, self.org_w, self.org_a, self.host, self.fi, self.slot, self.wm, self.wg, self.ab, self.as_])
        self.db.add(Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week1.id,
            home_team_id=self.wm.id,
            away_team_id=self.ab.id,
            game_status_id=self.status.id,
            game_date=self.week1.start_date,
            kickoff_time=time(10, 0),
        ))
        self.db.commit()

    def test_avoids_prior_week_exact_matchup_when_alternatives_exist(self):
        result = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)
        self.assertEqual(result['proposed_game_count'], 1)
        matchup = result['proposals'][0]['proposed_matchup']
        self.assertNotEqual(matchup, 'Westosha Maroon vs Antioch Black')
        self.assertIn('Avoids prior-week team repeat', result['proposals'][0]['reason'])
        self.assertIn('Avoids prior-week community repeat', result['proposals'][0]['reason'])




    def test_apply_skips_duplicate_matchup_with_friendly_message(self):
        # existing week 2 scheduled game in reverse order to ensure order-insensitive duplicate detection
        self.db.add(Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            home_team_id=self.ab.id,
            away_team_id=self.wm.id,
            game_status_id=self.status.id,
            game_date=self.week2.start_date,
            kickoff_time=time(11, 0),
        ))

        slot2 = GameSlot(
            id=uuid.uuid4(),
            field_instance_id=self.fi.id,
            host_location_id=self.host.id,
            slot_date=self.week2.start_date,
            start_time=time(10, 0),
            end_time=time(11, 0),
            field_type='SMALL',
            status='OPEN',
        )
        self.db.add(slot2)
        self.db.commit()

        payload = {
            'season_id': self.season.id,
            'week_id': self.week2.id,
            'division_id': self.division.id,
            'proposals': [
                {
                    'slot_id': str(self.slot.id),
                    'home_team_id': str(self.wm.id),
                    'away_team_id': str(self.ab.id),
                },
                {
                    'slot_id': str(slot2.id),
                    'home_team_id': str(self.wg.id),
                    'away_team_id': str(self.as_.id),
                },
            ],
        }

        result = auto_fill_apply(payload, db=self.db)

        self.assertEqual(result['created_games'], 1)
        self.assertEqual(result['skipped_count'], 1)
        skipped_message = result['skipped'][0]['reason']
        self.assertIn('Skipped Westosha Maroon vs Antioch Black because that matchup is already scheduled in Week 2.', skipped_message)
        self.assertIn('Date:', skipped_message)
        self.assertIn('Time:', skipped_message)
        self.assertNotIn(str(self.slot.id), skipped_message)

    def test_eight_team_week_creates_four_games_from_preview(self):
        org_c = Organization(id=uuid.uuid4(), name='Bristol', is_active=True)
        org_d = Organization(id=uuid.uuid4(), name='Salem', is_active=True)
        self.db.add_all([org_c, org_d])
        extra_teams = [
            Team(id=uuid.uuid4(), organization_id=org_c.id, division_id=self.division.id, name='Bristol Blue', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_c.id, division_id=self.division.id, name='Bristol White', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_d.id, division_id=self.division.id, name='Salem Green', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_d.id, division_id=self.division.id, name='Salem Orange', is_active=True),
        ]
        self.db.add_all(extra_teams)
        slots = []
        for hour in (10, 11, 12):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Small Field {hour}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
            slots.extend([fi, slot])
        self.db.add_all(slots)
        self.db.commit()

        preview = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)
        self.assertEqual(preview['max_allowed_game_count'], 4)
        self.assertEqual(preview['proposed_game_count'], 4)
        proposal_team_ids = set()
        for row in preview['proposals']:
            proposal_team_ids.add(row['home_team_id'])
            proposal_team_ids.add(row['away_team_id'])
        self.assertEqual(len(proposal_team_ids), 8)

        applied = auto_fill_apply({
            'season_id': self.season.id,
            'week_id': self.week2.id,
            'division_id': self.division.id,
            'proposals': preview['proposals'],
        }, db=self.db)
        self.assertEqual(applied['proposed_count'], 4)
        self.assertEqual(applied['created_count'], 4)
        self.assertEqual(applied['skipped_count'], 0)

    def test_same_community_prefers_home_slot_over_away_slot(self):
        away_host = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Antioch Park', is_active=True)
        away_fi = FieldInstance(id=uuid.uuid4(), host_location_id=away_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Small Field 2', field_type='SMALL', is_active=True)
        away_slot = GameSlot(id=uuid.uuid4(), field_instance_id=away_fi.id, host_location_id=away_host.id, slot_date=self.week2.start_date, start_time=time(10, 0), end_time=time(11, 0), field_type='SMALL', status='OPEN')
        self.db.add_all([away_host, away_fi, away_slot])
        self.db.commit()

        # consume Antioch teams in existing week-2 game so the remaining valid matchup is same-community Westosha
        self.db.add(Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            home_team_id=self.ab.id,
            away_team_id=self.as_.id,
            game_status_id=self.status.id,
            game_date=self.week2.start_date,
            kickoff_time=time(8, 0),
        ))
        self.db.commit()

        result = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)
        self.assertEqual(result['proposed_game_count'], 1)
        self.assertEqual(result['proposals'][0]['host_location'], 'Westosha Park')
        self.assertIn('same-community at home host field (+60)', result['proposals'][0]['reason'])

    def test_consolidates_to_single_host_when_capacity_exists(self):
        away_host = HostLocation(id=uuid.uuid4(), organization_id=self.org_a.id, name='Antioch Park', is_active=True)
        away_fi = FieldInstance(id=uuid.uuid4(), host_location_id=away_host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name='Away Field 1', field_type='SMALL', is_active=True)
        away_slot = GameSlot(id=uuid.uuid4(), field_instance_id=away_fi.id, host_location_id=away_host.id, slot_date=self.week2.start_date, start_time=time(10, 0), end_time=time(11, 0), field_type='SMALL', status='OPEN')
        self.db.add_all([away_host, away_fi, away_slot])
        # add enough slots at primary host to support all games
        for hour in (10, 11):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Primary {hour}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
            self.db.add_all([fi, slot])
        self.db.commit()

        result = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id}, db=self.db)
        self.assertGreaterEqual(result['proposed_game_count'], 2)
        used_hosts = {p['host_location'] for p in result['proposals']}
        self.assertEqual(used_hosts, {'Westosha Park'})
        self.assertTrue(result['audit']['single_site_possible'])
        self.assertTrue(result['audit']['consolidation_achieved'])

    def test_apply_ignores_unscheduled_games_for_duplicate_check(self):
        unscheduled_status = GameStatus(id=uuid.uuid4(), code='UNSCHEDULED', label='Unscheduled', is_active=True)
        self.db.add(unscheduled_status)
        self.db.add(Game(
            id=uuid.uuid4(),
            season_id=self.season.id,
            week_id=self.week2.id,
            home_team_id=self.ab.id,
            away_team_id=self.wm.id,
            game_status_id=unscheduled_status.id,
            game_date=self.week2.start_date,
            kickoff_time=time(11, 0),
        ))
        self.db.commit()

        result = auto_fill_apply({
            'season_id': self.season.id,
            'week_id': self.week2.id,
            'division_id': self.division.id,
            'proposals': [{
                'slot_id': str(self.slot.id),
                'home_team_id': str(self.wm.id),
                'away_team_id': str(self.ab.id),
            }],
        }, db=self.db)
        self.assertEqual(result['created_count'], 1)
        self.assertEqual(result['skipped_count'], 0)

    def test_nine_team_week_creates_five_games_with_one_double_header_team(self):
        org_c = Organization(id=uuid.uuid4(), name='Bristol', is_active=True)
        org_d = Organization(id=uuid.uuid4(), name='Salem', is_active=True)
        org_e = Organization(id=uuid.uuid4(), name='Kenosha', is_active=True)
        self.db.add_all([org_c, org_d, org_e])
        extra_teams = [
            Team(id=uuid.uuid4(), organization_id=org_c.id, division_id=self.division.id, name='Bristol Blue', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_c.id, division_id=self.division.id, name='Bristol White', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_d.id, division_id=self.division.id, name='Salem Green', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_d.id, division_id=self.division.id, name='Salem Orange', is_active=True),
            Team(id=uuid.uuid4(), organization_id=org_e.id, division_id=self.division.id, name='Kenosha Red', is_active=True),
        ]
        self.db.add_all(extra_teams)
        slots = []
        for hour in (10, 11, 12, 13):
            fi = FieldInstance(id=uuid.uuid4(), host_location_id=self.host.id, hosting_availability_id=uuid.uuid4(), instance_date=self.week2.start_date, field_name=f'Small Field {hour}', field_type='SMALL', is_active=True)
            slot = GameSlot(id=uuid.uuid4(), field_instance_id=fi.id, host_location_id=self.host.id, slot_date=self.week2.start_date, start_time=time(hour, 0), end_time=time(hour + 1, 0), field_type='SMALL', status='OPEN')
            slots.extend([fi, slot])
        self.db.add_all(slots)
        self.db.commit()

        preview = auto_fill_preview({'season_id': self.season.id, 'week_id': self.week2.id, 'division_id': self.division.id, 'no_byes': True}, db=self.db)
        self.assertEqual(preview['max_allowed_game_count'], 5)
        self.assertEqual(preview['proposed_game_count'], 5)
        team_counts: dict[str, int] = {}
        for row in preview['proposals']:
            team_counts[row['home_team_id']] = team_counts.get(row['home_team_id'], 0) + 1
            team_counts[row['away_team_id']] = team_counts.get(row['away_team_id'], 0) + 1
        doubles = [tid for tid, count in team_counts.items() if count == 2]
        self.assertEqual(len(doubles), 1)
        self.assertEqual(sum(team_counts.values()), 10)

if __name__ == '__main__':
    unittest.main()
