import io

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (Base, Division, GameStatus, HostLocation,
                        HostLocationConfiguration, Organization,
                        OrganizationDivisionParticipation, Season, Team, Week)
from app.services.schedule_import import build_preview, parse_schedule_file, _date, _time, _week_number


HEADERS = 'Week,Date,Kickoff,Site,Field,Field Type,Division,Home Team,Away Team,Notes\n'


def test_csv_header_normalization_and_optional_notes():
    rows = parse_schedule_file('week.csv', (' WEEK ,DATE,Kickoff,Site,Field,"Field Type,",Division,Home Team,Away Team,Notes\n1,2026-08-09,8:00 AM,North,1,Small,1st,Blue,Red,test\n').encode())
    assert rows[0]['week'] == '1'
    assert rows[0]['fieldtype'] == 'Small'


def test_xlsx_native_date_and_time_are_preserved_for_validation():
    book = Workbook(); sheet = book.active
    sheet.append(HEADERS.strip().split(','))
    sheet.append([1, '2026-08-09', 8 / 24, 'North', '1', 'Small', '1st', 'Blue', 'Red', None])
    stream = io.BytesIO(); book.save(stream)
    row = parse_schedule_file('week.xlsx', stream.getvalue())[0]
    assert _date(row['date']).isoformat() == '2026-08-09'
    assert _time(row['kickoff']).strftime('%H:%M') == '08:00'


def test_missing_required_column_is_blocking():
    with pytest.raises(ValueError, match='Missing required columns'):
        parse_schedule_file('week.csv', b'Week,Date\n1,2026-08-09\n')


@pytest.mark.parametrize('value', ['8:00 AM', '08:00', '8:00'])
def test_common_kickoff_formats(value):
    assert _time(value).strftime('%H:%M') == '08:00'


@pytest.mark.parametrize('value', [1, '1', 'Week 1', 'week 1', 'WEEK 1', ' Week   1 '])
def test_week_number_accepts_numeric_and_friendly_values(value):
    assert _week_number(value) == 1


@pytest.mark.parametrize(('site_name', 'field_name', 'field_type', 'layout'), [
    ('Hiller Park', ' Field 1 ', 'Small', 'FOUR_SMALL'),
    ('Johnsburg Stadium', 'field 1', 'Large', 'ONE_LARGE_ONE_MEDIUM'),
    ('Johnsburg Stadium', 'Field 3', 'Medium', 'ONE_LARGE_ONE_MEDIUM'),
    ('Hiller Stadium', 'Field 1', 'Medium', 'TWO_MEDIUM'),
    ('Hiller Stadium', 'Field 3', 'Medium', 'TWO_MEDIUM'),
])
def test_week_one_scenario_resolves_canonical_teams_and_facility_layout(site_name, field_name, field_type, layout):
    engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    johnsburg = Organization(name='Johnsburg', is_active=True)
    antioch = Organization(name='Antioch', is_active=True)
    division = Division(division_group='Coed', name='K-1', is_active=True)
    season = Season(name='2026', start_date=_date('2026-08-01'), end_date=_date('2026-11-01'), is_active=True)
    db.add_all([johnsburg, antioch, division, season]); db.flush()
    week = Week(season_id=season.id, week_number=1, start_date=_date('2026-08-09'),
                end_date=_date('2026-08-09'), primary_game_date=_date('2026-08-09'))
    site = HostLocation(organization_id=johnsburg.id, name=site_name, surface_type='TURF_STADIUM', is_active=True)
    db.add_all([week, site]); db.flush()
    db.add(HostLocationConfiguration(host_location_id=site.id, configuration_name=layout, is_active=True))
    for organization in (johnsburg, antioch):
        db.add(OrganizationDivisionParticipation(organization_id=organization.id, division_id=division.id,
                                                 is_participating=True, team_count=1, is_active=True))
    db.add_all([
        Team(organization_id=johnsburg.id, division_id=division.id, name='Black', is_active=True),
        Team(organization_id=antioch.id, division_id=division.id, name='Black', is_active=True),
        GameStatus(code='SCHEDULED', label='Scheduled', is_active=True),
    ])
    db.commit()

    preview, staged = build_preview(db, season.id, [{
        'week': 'Week 1', 'date': '2026-08-09', 'kickoff': '9:00 AM',
        'site': site_name, 'field': field_name, 'fieldtype': field_type,
        'division': 'Coed K-1', 'hometeam': 'Johnsburg Coed K-1 Black',
        'awayteam': 'Antioch Coed K-1 Black',
    }])

    assert preview['rows'][0]['week'] == 'Week 1'
    assert preview['rows'][0]['status'] == 'VALID'
    assert preview['blocking_errors'] == 0
    assert staged[0]['week_number'] == 1
    db.close()


def _hiller_import_context():
    engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    home_org = Organization(name='Johnsburg', is_active=True)
    away_org = Organization(name='Antioch', is_active=True)
    division = Division(division_group='Girls', name='6-8', is_active=True,
                        required_field_layout_type='LARGE')
    season = Season(name='2026', start_date=_date('2026-08-01'),
                    end_date=_date('2026-11-01'), is_active=True)
    db.add_all([home_org, away_org, division, season]); db.flush()
    db.add(Week(season_id=season.id, week_number=1, start_date=_date('2026-08-16'),
                end_date=_date('2026-08-16'), primary_game_date=_date('2026-08-16')))
    site = HostLocation(organization_id=home_org.id, name='Hiller Stadium',
                        surface_type='TURF_STADIUM', is_active=True)
    db.add(site); db.flush()
    medium = HostLocationConfiguration(host_location_id=site.id,
                                       configuration_name='TWO_MEDIUM', is_active=True)
    large = HostLocationConfiguration(host_location_id=site.id,
                                      configuration_name='ONE_LARGE', is_active=True)
    db.add_all([medium, large])
    teams = []
    for index in range(1, 7):
        organization = home_org if index % 2 else away_org
        teams.append(Team(organization_id=organization.id, division_id=division.id,
                          name=f'Team {index}', is_active=True))
    db.add_all(teams + [GameStatus(code='SCHEDULED', label='Scheduled', is_active=True)])
    db.commit()
    return db, season, teams


def _hiller_row(kickoff, field, field_type, home, away):
    home_community = 'Johnsburg' if home.name in {'Team 1', 'Team 3', 'Team 5'} else 'Antioch'
    away_community = 'Johnsburg' if away.name in {'Team 1', 'Team 3', 'Team 5'} else 'Antioch'
    return {'week': 1, 'date': '2026-08-16', 'kickoff': kickoff,
            'site': 'Hiller Stadium', 'field': field, 'fieldtype': field_type,
            'division': 'Girls 6-8',
            'hometeam': f'{home_community} Girls 6-8 {home.name}',
            'awayteam': f'{away_community} Girls 6-8 {away.name}'}


def test_hiller_large_reconfiguration_is_valid_and_records_selected_layout():
    db, season, teams = _hiller_import_context()
    preview, staged = build_preview(db, season.id, [
        _hiller_row('12:00 PM', 'Field 1', 'Large', teams[0], teams[1])])

    assert preview['valid_games'] == 1
    assert preview['rows'][0]['status'] == 'VALID'
    assert staged[0]['configuration_name'] == 'ONE_LARGE'
    assert 'will use its One Large configuration' in preview['rows'][0]['message']


def test_hiller_large_layout_rejects_overlapping_adjacent_medium_assignment():
    db, season, teams = _hiller_import_context()
    preview, staged = build_preview(db, season.id, [
        _hiller_row('12:00 PM', 'Field 1', 'Large', teams[0], teams[1]),
        _hiller_row('12:00 PM', 'Field 2', 'Medium', teams[2], teams[3]),
    ])

    assert not staged
    assert preview['invalid_rows'] == 2
    assert all(row['status'] == 'ERROR' for row in preview['rows'])
    assert 'cannot be supported by any configured field layout' in preview['rows'][0]['message']


def test_hiller_layout_is_selected_independently_for_each_kickoff():
    db, season, teams = _hiller_import_context()
    preview, staged = build_preview(db, season.id, [
        _hiller_row('11:00 AM', 'Field 1', 'Medium', teams[0], teams[1]),
        _hiller_row('11:00 AM', 'Field 2', 'Medium', teams[2], teams[3]),
        _hiller_row('12:00 PM', 'Field 1', 'Large', teams[4], teams[5]),
    ])

    assert preview['valid_games'] == 3
    assert preview['invalid_rows'] == 0
    assert [row['configuration_name'] for row in staged] == [
        'TWO_MEDIUM', 'TWO_MEDIUM', 'ONE_LARGE']


def test_hiller_unsupported_field_layout_is_an_error():
    db, season, teams = _hiller_import_context()
    preview, staged = build_preview(db, season.id, [
        _hiller_row('12:00 PM', 'Field 2', 'Large', teams[0], teams[1])])

    assert not staged
    assert preview['rows'][0]['status'] == 'ERROR'
    assert 'every configured site layout' in preview['rows'][0]['message']


@pytest.mark.parametrize(('community', 'division_group', 'division_name', 'color', 'stored_name'), [
    ('Johnsburg', 'Coed', 'K-1', 'Black', 'J’Burg Coed K-1 Black'),
    ('Johnsburg', 'Coed', 'K-1', 'Blue', 'J’Burg Coed K-1 Blue'),
    ('Johnsburg', 'Coed', 'K-1', 'Gold', 'J’Burg Coed K-1 Gold'),
    ('Johnsburg', 'Coed', 'K-1', 'White', 'J’Burg Coed K-1 White'),
    ('Johnsburg', 'Coed', '2-3', 'Blue', 'J’Burg Coed 2-3 Blue'),
    ('Johnsburg', 'Coed', '2-3', 'Gold', 'J’Burg Coed 2-3 Gold'),
    ('Johnsburg', 'Coed', '4-5', 'Blue', 'J’Burg Coed 4-5 Blue'),
    ('Johnsburg', 'Girls', '3-5', 'Blue', 'J’Burg Girls 3-5 Blue'),
    ('Johnsburg', 'Girls', '3-5', 'Gold', 'J’Burg Girls 3-5 Gold'),
    ('Johnsburg', 'Girls', '6-8', 'Blue', 'J’Burg Girls 6-8 Blue'),
    ('Johnsburg', 'Girls', '6-8', 'Gold', 'J’Burg Girls 6-8 Gold'),
    ('Antioch', 'Coed', 'K-1', 'Black', 'Black'),
    ('Westosha', 'Coed', 'K-1', 'Maroon', 'Westosha Coed K-1 Maroon'),
    ('Prairie Ridge', 'Coed', 'K-1', 'Orange', 'Orange'),
    ('Woodstock', 'Coed', 'K-1', 'Purple', 'Woodstock Coed K-1 Purple'),
])
def test_structured_team_resolution_supports_legacy_and_canonical_names(
        community, division_group, division_name, color, stored_name):
    engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    organization = Organization(name=community, is_active=True)
    opponent_org = Organization(name='Import Opponent', is_active=True)
    division = Division(division_group=division_group, name=division_name, is_active=True,
                        required_field_layout_type='SMALL')
    season = Season(name='2026 Fall Flag', start_date=_date('2026-08-01'),
                    end_date=_date('2026-11-01'), is_active=True)
    db.add_all([organization, opponent_org, division, season]); db.flush()
    week = Week(season_id=season.id, week_number=1, start_date=_date('2026-08-09'),
                end_date=_date('2026-08-09'), primary_game_date=_date('2026-08-09'))
    site = HostLocation(organization_id=organization.id, name='Hiller Park',
                        surface_type='TURF_STADIUM', is_active=True)
    db.add_all([week, site]); db.flush()
    db.add(HostLocationConfiguration(host_location_id=site.id,
                                     configuration_name='FOUR_SMALL', is_active=True))
    for org in (organization, opponent_org):
        db.add(OrganizationDivisionParticipation(
            organization_id=org.id, division_id=division.id, is_participating=True,
            team_count=1, is_active=True))
    expected = Team(organization_id=organization.id, division_id=division.id,
                    name=stored_name, is_active=True)
    opponent = Team(organization_id=opponent_org.id, division_id=division.id,
                    name='Silver', is_active=True)
    db.add_all([expected, opponent,
                GameStatus(code='SCHEDULED', label='Scheduled', is_active=True)])
    db.commit()

    imported_name = f'{community} {division_group} {division_name} {color}'
    preview, staged = build_preview(db, season.id, [{
        'week': 1, 'date': '2026-08-09', 'kickoff': '9:00 AM',
        'site': 'Hiller Park', 'field': 'Field 1', 'fieldtype': 'Small',
        'division': f'{division_group} {division_name}', 'hometeam': imported_name,
        'awayteam': f'Import Opponent {division_group} {division_name} Silver',
    }])

    assert preview['rows'][0]['status'] == 'VALID', preview['rows'][0]['message']
    assert staged[0]['home_team_id'] == str(expected.id)
    db.close()


def test_team_resolution_normalizes_formatting_but_not_different_colors():
    from app.teams import normalize_team_identity

    assert normalize_team_identity(' JOHNSBURG  COED K-1 BLACK ') == normalize_team_identity(
        'Johnsburg Coed K–1 Black')
    assert normalize_team_identity('Black') != normalize_team_identity('Blue')
