import uuid
from datetime import date, time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import (
    Division,
    FieldInstance,
    GameSlot,
    HostLocation,
    HostingAvailability,
    Organization,
    Season,
    Team,
    Week,
)
from app.routes.api import (
    _host_availability_matrix_response,
    _regenerate_generated_slots,
    auto_schedule_entire_season,
    get_schedule_readiness,
)


def _db_session() -> Session:
    engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_fall_calendar(db: Session) -> Season:
    season = Season(id=uuid.uuid4(), name='2026 Fall Flag', start_date=date(2026, 8, 9), end_date=date(2026, 10, 11), is_active=True)
    weeks = [
        (1, 'Week 1', date(2026, 8, 9), 'REGULAR_SEASON'),
        (2, 'Week 2', date(2026, 8, 16), 'REGULAR_SEASON'),
        (3, 'Week 3', date(2026, 8, 23), 'REGULAR_SEASON'),
        (4, 'Week 4', date(2026, 8, 30), 'REGULAR_SEASON'),
        (5, 'Labor Day Blackout', date(2026, 9, 6), 'BLACKOUT'),
        (6, 'Week 5', date(2026, 9, 13), 'REGULAR_SEASON'),
        (7, 'Week 6', date(2026, 9, 20), 'REGULAR_SEASON'),
        (8, 'Week 7', date(2026, 9, 27), 'REGULAR_SEASON'),
        (9, 'Week 8', date(2026, 10, 4), 'REGULAR_SEASON'),
        (10, 'Playoff Saturday', date(2026, 10, 10), 'PLAYOFF'),
        (11, 'Playoff Sunday', date(2026, 10, 11), 'PLAYOFF'),
    ]
    db.add(season)
    db.add_all([
        Week(
            id=uuid.uuid4(),
            season_id=season.id,
            week_number=week_number,
            label=label,
            start_date=game_date,
            end_date=game_date,
            primary_game_date=game_date,
            date_type=date_type,
            status='active',
        )
        for week_number, label, game_date, date_type in weeks
    ])
    db.commit()
    return season


def test_fall_2026_calendar_has_eight_regular_dates_and_visible_special_dates():
    db = _db_session()
    try:
        season = _seed_fall_calendar(db)
        matrix = _host_availability_matrix_response(db, season.id)

        assert [row['game_date'] for row in matrix['dates']] == [
            date(2026, 8, 9),
            date(2026, 8, 16),
            date(2026, 8, 23),
            date(2026, 8, 30),
            date(2026, 9, 6),
            date(2026, 9, 13),
            date(2026, 9, 20),
            date(2026, 9, 27),
            date(2026, 10, 4),
            date(2026, 10, 10),
            date(2026, 10, 11),
        ]
        assert sum(1 for row in matrix['dates'] if row['date_type'] == 'REGULAR_SEASON') == 8
        assert next(row for row in matrix['dates'] if row['game_date'] == date(2026, 9, 6))['date_type'] == 'BLACKOUT'
        assert next(row for row in matrix['dates'] if row['game_date'] == date(2026, 10, 10))['date_type'] == 'PLAYOFF'
        assert next(row for row in matrix['dates'] if row['game_date'] == date(2026, 10, 11))['date_type'] == 'PLAYOFF'
    finally:
        db.close()


def test_auto_scheduler_counts_only_regular_season_weeks():
    db = _db_session()
    try:
        season = _seed_fall_calendar(db)
        org = Organization(id=uuid.uuid4(), name='League', is_active=True)
        division = Division(id=uuid.uuid4(), division_group='COED', name='K/1st', required_field_layout_type='THIRTY_YARD_WIDTH', is_active=True)
        teams = [Team(id=uuid.uuid4(), organization_id=org.id, division_id=division.id, name=f'Team {idx}', is_active=True) for idx in range(1, 5)]
        db.add_all([org, division, *teams])
        db.commit()

        result = auto_schedule_entire_season({'season_id': season.id}, current_user=None, db=db)

        diagnostics = result['auto_schedule_diagnostics']
        assert diagnostics['weeks_found'] == 11
        assert diagnostics['regular_season_weeks_found'] == 8
        assert diagnostics['expected_games_by_week'] == {str(week): 2 for week in range(1, 10) if week != 5}
        assert '5' not in diagnostics['expected_games_by_week']
        assert '10' not in diagnostics['expected_games_by_week']
        assert '11' not in diagnostics['expected_games_by_week']
    finally:
        db.close()


def test_blackout_slots_are_suppressed_without_override_and_playoffs_allowed():
    db = _db_session()
    try:
        season = _seed_fall_calendar(db)
        org = Organization(id=uuid.uuid4(), name='Host Org', is_active=True)
        blackout_host = HostLocation(id=uuid.uuid4(), organization_id=org.id, name='Blackout Park', surface_type='GRASS_FIELD', max_small_fields=1, is_active=True)
        playoff_host = HostLocation(id=uuid.uuid4(), organization_id=org.id, name='Playoff Park', surface_type='GRASS_FIELD', max_small_fields=1, is_active=True)
        blackout_week = db.query(Week).filter(Week.date_type == 'BLACKOUT').one()
        playoff_week = db.query(Week).filter(Week.label == 'Playoff Saturday').one()
        blackout_availability = HostingAvailability(id=uuid.uuid4(), season_id=season.id, week_id=blackout_week.id, organization_id=org.id, host_location_id=blackout_host.id, available_date=blackout_week.start_date, start_time=time(9, 0), end_time=time(11, 0), is_available=True)
        playoff_availability = HostingAvailability(id=uuid.uuid4(), season_id=season.id, week_id=playoff_week.id, organization_id=org.id, host_location_id=playoff_host.id, available_date=playoff_week.start_date, start_time=time(9, 0), end_time=time(11, 0), is_available=True)
        db.add_all([org, blackout_host, playoff_host, blackout_availability, playoff_availability])
        db.commit()

        blackout_result = _regenerate_generated_slots(db, blackout_availability, blackout_host.id)
        playoff_result = _regenerate_generated_slots(db, playoff_availability, playoff_host.id)
        db.commit()

        assert blackout_result['new_slots_created'] == 0
        assert playoff_result['new_slots_created'] > 0
        readiness = get_schedule_readiness(current_user=None, db=db)
        demand_by_date = {row.host_date: row for row in readiness.weekly_field_demand}
        assert demand_by_date[blackout_week.start_date].capacity_used == 0
        assert demand_by_date[playoff_week.start_date].capacity_used == 0
    finally:
        db.close()
