import io
import json
import uuid
from types import SimpleNamespace

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (Base, Division, Field, Game, GameStatus, HostLocation,
                        HostLocationConfiguration, Organization,
                        OrganizationDivisionParticipation, ScheduleImport, Season, Team, Week)
from app.routes.api import confirm_schedule_import
from app.services.field_resolution import resolve_active_field
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
    db.add_all([
        Field(host_location_id=site.id, name='Field 1', layout_type='MEDIUM', is_active=True),
        Field(host_location_id=site.id, name='Field 2', layout_type='MEDIUM', is_active=True),
    ])
    medium = HostLocationConfiguration(host_location_id=site.id,
                                       configuration_name='TWO_MEDIUM', is_active=True)
    # ONE_LARGE is intentionally not persisted: it is a supported alternate
    # facility layout, not a duplicate permanent field/configuration record.
    db.add(medium)
    teams = []
    for index in range(1, 43):
        organization = home_org if index % 2 else away_org
        teams.append(Team(organization_id=organization.id, division_id=division.id,
                          name=f'Team {index}', is_active=True))
    db.add_all(teams + [GameStatus(code='SCHEDULED', label='Scheduled', is_active=True)])
    db.commit()
    return db, season, teams


def _hiller_row(kickoff, field, field_type, home, away):
    home_community = 'Johnsburg' if int(home.name.rsplit(' ', 1)[1]) % 2 else 'Antioch'
    away_community = 'Johnsburg' if int(away.name.rsplit(' ', 1)[1]) % 2 else 'Antioch'
    return {'week': 1, 'date': '2026-08-16', 'kickoff': kickoff,
            'site': 'Hiller Stadium', 'field': field, 'fieldtype': field_type,
            'division': 'Girls 6-8',
            'hometeam': f'{home_community} Girls 6-8 {home.name}',
            'awayteam': f'{away_community} Girls 6-8 {away.name}'}


def _canonical_hiller_park_context():
    db, season, teams = _hiller_import_context()
    site = db.query(HostLocation).filter_by(name='Hiller Stadium').one()
    site.name = 'Hiller Park'
    db.query(Field).delete()
    fields = [
        Field(host_location_id=site.id, name=f'Johnsburg - Hiller - Small - {identifier}',
              layout_type='SMALL', is_active=True)
        for identifier in ('SW', 'SE', 'North', 'NE', 'Middle')
    ]
    db.add_all(fields)
    db.commit()
    return db, season, teams, site, fields


@pytest.mark.parametrize('imported', ['SW', 'SE', 'North', 'NE', 'Middle'])
def test_hiller_park_short_field_names_resolve_to_canonical_active_fields(imported):
    db, season, teams, site, _fields = _canonical_hiller_park_context()
    row = _hiller_row('9:00 AM', imported, 'Small', teams[0], teams[1])
    row['site'] = site.name

    preview, staged = build_preview(db, season.id, [row])

    expected = db.query(Field).filter(Field.name.endswith(f' - {imported}')).one()
    assert preview['rows'][0]['status'] == 'VALID'
    assert preview['rows'][0]['message'] == 'Ready to import.'
    assert preview['blocking_errors'] == 0
    assert staged[0]['imported_field_name'] == imported
    assert staged[0]['resolved_field_id'] == str(expected.id)


@pytest.mark.parametrize('imported', ['sw', 'SW', 'Sw', '  sw  '])
def test_short_field_resolution_normalizes_case_and_whitespace(imported):
    db, _season, _teams, site, _fields = _canonical_hiller_park_context()

    resolved = resolve_active_field(db, site, imported)

    assert resolved.name == 'Johnsburg - Hiller - Small - SW'


def test_short_field_resolution_is_site_scoped_and_requires_unique_match():
    db, _season, _teams, hiller, _fields = _canonical_hiller_park_context()
    organization = db.query(Organization).filter_by(name='Johnsburg').one()
    other_site = HostLocation(organization_id=organization.id, name='Other Park', is_active=True)
    db.add(other_site); db.flush()
    other_sw = Field(host_location_id=other_site.id, name='Other - Small - SW',
                     layout_type='SMALL', is_active=True)
    db.add(other_sw); db.commit()

    resolved = resolve_active_field(db, hiller, 'SW')

    assert resolved.host_location_id == hiller.id
    assert resolved.name == 'Johnsburg - Hiller - Small - SW'


def test_unknown_hiller_park_short_field_remains_blocking():
    db, season, teams, site, _fields = _canonical_hiller_park_context()
    row = _hiller_row('9:00 AM', 'Field 99', 'Small', teams[0], teams[1])
    row['site'] = site.name

    preview, staged = build_preview(db, season.id, [row])

    assert staged == []
    assert preview['rows'][0]['status'] == 'ERROR'
    assert preview['rows'][0]['message'] == (
        'Field "Field 99" could not be found at site "Hiller Park".')


def test_confirm_persists_field_id_resolved_from_short_name():
    db, season, teams, site, _fields = _canonical_hiller_park_context()
    row = _hiller_row('9:00 AM', 'SW', 'Small', teams[0], teams[1])
    row['site'] = site.name
    preview, staged = build_preview(db, season.id, [row])
    canonical = db.query(Field).filter(Field.name.endswith(' - SW')).one()
    user_id = uuid.uuid4()
    record = ScheduleImport(
        season_id=season.id, imported_by_user_id=user_id, source_filename='short-fields.csv',
        weeks_replaced=json.dumps(preview['weeks']), status='PREVIEW',
        staged_rows=json.dumps(staged), preview_summary=json.dumps(preview),
    )
    db.add(record); db.commit()

    confirm_schedule_import(record.id, {'confirmation': 'Replace Existing Schedule Games'},
                            db, SimpleNamespace(id=user_id))

    game = db.query(Game).filter_by(season_id=season.id).one()
    assert game.field_id == canonical.id
    assert game.missing_field_assignment is False


def test_hiller_large_reconfiguration_is_warning_and_records_selected_layout():
    db, season, teams = _hiller_import_context()
    preview, staged = build_preview(db, season.id, [
        _hiller_row('12:00 PM', 'Field 1', 'Large', teams[0], teams[1])])

    assert preview['valid_games'] == 1
    assert preview['importable_games'] == 1
    assert preview['invalid_rows'] == 0
    assert preview['warning_count'] == 1
    assert preview['blocking_errors'] == 0
    assert preview['rows'][0]['status'] == 'WARNING'
    assert preview['rows'][0]['message'].startswith(
        'Field "Field 1" is being used as a Large field at Hiller Stadium for this '
        'timeslot. Verify the site will be reconfigured appropriately before game day.')
    assert staged[0]['configuration_name'] == 'ONE_LARGE'
    assert staged[0]['configuration_id'] is None
    assert 'will use its One Large configuration' in preview['rows'][0]['message']
    assert preview['diagnostics'][0]['category'] == 'Scheduling Integrity'
    assert preview['diagnostics'][0]['check'] == 'Field configuration mismatch'
    assert preview['diagnostics'][0]['blocking'] is False
    assert staged[0]['imported_field_name'] == 'Field 1'
    assert staged[0]['resolved_field_id'] == staged[0]['field_id']


@pytest.mark.parametrize(('site_name', 'field_names'), [
    ('Hiller Park', ('Field 1', 'Field 2', 'Field 3', 'Field 4')),
    ('Johnsburg Stadium', ('Field 1', 'Field 3')),
    ('Hiller Stadium', ('Field 1', 'Field 3')),
])
def test_preview_retains_original_and_canonical_field_references(site_name, field_names):
    db, season, teams = _hiller_import_context()
    site = db.query(HostLocation).filter_by(name='Hiller Stadium').one()
    site.name = site_name
    db.query(Field).delete()
    db.add_all([Field(host_location_id=site.id, name=name, layout_type='MEDIUM', is_active=True)
                for name in field_names])
    db.commit()
    rows = [_hiller_row(f'{10 + index}:00', name, 'Medium', teams[index * 2], teams[index * 2 + 1])
            for index, name in enumerate(field_names)]
    for row in rows:
        row['site'] = site_name

    preview, staged = build_preview(db, season.id, rows)

    assert preview['blocking_errors'] == 0
    assert [row['imported_field_name'] for row in staged] == list(field_names)
    assert all(row['resolved_field_id'] == row['field_id'] for row in staged)
    assert all(row['resolved_field_id'] for row in staged)


def test_confirm_persists_warning_field_and_replacement_assignments():
    db, season, teams = _hiller_import_context()
    week = db.query(Week).filter_by(season_id=season.id, week_number=1).one()
    site = db.query(HostLocation).filter_by(name='Hiller Stadium').one()
    fields = db.query(Field).order_by(Field.name).all()
    status = db.query(GameStatus).filter_by(code='SCHEDULED').one()
    old = Game(season_id=season.id, week_id=week.id, home_team_id=teams[4].id,
               away_team_id=teams[5].id, game_status_id=status.id,
               game_date=week.primary_game_date, kickoff_time=_time('9:00 AM'))
    db.add(old); db.flush()
    user_id = uuid.uuid4()
    staged = []
    for index, field in enumerate(fields):
        staged.append({
            'row': index + 2, 'status': 'WARNING' if index == 0 else 'VALID',
            'week_id': str(week.id), 'site_id': str(site.id),
            'imported_field_name': field.name, 'resolved_field_id': str(field.id),
            'field_id': str(field.id), 'field_instance_id': None,
            'home_team_id': str(teams[index * 2].id),
            'away_team_id': str(teams[index * 2 + 1].id),
            'game_status_id': str(status.id), 'date': week.primary_game_date.isoformat(),
            'kickoff': f'{10 + index}:00', 'notes': None,
        })
    record = ScheduleImport(
        season_id=season.id, imported_by_user_id=user_id, source_filename='test.csv',
        weeks_replaced='[1]', status='PREVIEW', staged_rows=json.dumps(staged),
        preview_summary=json.dumps({'blocking_errors': 0, 'weeks': [1], 'warning_count': 1}),
    )
    db.add(record); db.commit()

    result = confirm_schedule_import(record.id, {'confirmation': 'Replace Existing Schedule Games'},
                                     db, SimpleNamespace(id=user_id))

    games = db.query(Game).filter_by(season_id=season.id, week_id=week.id).order_by(Game.kickoff_time).all()
    assert result['existing_games_removed'] == 1
    assert [game.field_id for game in games] == [field.id for field in fields]
    assert all(not game.missing_field_assignment for game in games)


def test_confirm_rolls_back_replacement_when_canonical_field_is_invalid():
    db, season, teams = _hiller_import_context()
    week = db.query(Week).filter_by(season_id=season.id, week_number=1).one()
    site = db.query(HostLocation).filter_by(name='Hiller Stadium').one()
    status = db.query(GameStatus).filter_by(code='SCHEDULED').one()
    old = Game(season_id=season.id, week_id=week.id, home_team_id=teams[0].id,
               away_team_id=teams[1].id, game_status_id=status.id,
               game_date=week.primary_game_date, kickoff_time=_time('9:00 AM'))
    db.add(old); db.flush()
    old_id = old.id
    user_id = uuid.uuid4()
    staged = [{
        'row': 2, 'week_id': str(week.id), 'site_id': str(site.id),
        'imported_field_name': 'Field 1', 'resolved_field_id': str(uuid.uuid4()),
        'home_team_id': str(teams[2].id), 'away_team_id': str(teams[3].id),
        'game_status_id': str(status.id), 'date': week.primary_game_date.isoformat(),
        'kickoff': '10:00', 'notes': None,
    }]
    record = ScheduleImport(
        season_id=season.id, imported_by_user_id=user_id, source_filename='test.csv',
        weeks_replaced='[1]', status='PREVIEW', staged_rows=json.dumps(staged),
        preview_summary=json.dumps({'blocking_errors': 0, 'weeks': [1], 'warning_count': 0}),
    )
    db.add(record); db.commit()

    with pytest.raises(Exception, match='Schedule import failed'):
        confirm_schedule_import(record.id, {'confirmation': 'Replace Existing Schedule Games'},
                                db, SimpleNamespace(id=user_id))

    assert db.get(Game, old_id) is not None
    assert db.query(Game).filter_by(season_id=season.id, week_id=week.id).count() == 1


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


def test_hiller_field_type_mismatch_without_determined_layout_is_warning():
    db, season, teams = _hiller_import_context()
    preview, staged = build_preview(db, season.id, [
        _hiller_row('12:00 PM', 'Field 2', 'Large', teams[0], teams[1])])

    assert len(staged) == 1
    assert preview['rows'][0]['status'] == 'WARNING'
    assert preview['blocking_errors'] == 0
    assert preview['invalid_rows'] == 0


def test_exact_configured_field_type_match_remains_valid():
    db, season, teams = _hiller_import_context()
    preview, staged = build_preview(db, season.id, [
        _hiller_row('12:00 PM', 'Field 1', 'Medium', teams[0], teams[1])])

    assert len(staged) == 1
    assert preview['rows'][0]['status'] == 'VALID'
    assert preview['warning_count'] == 0
    assert preview['blocking_errors'] == 0


def test_unknown_hiller_field_remains_a_blocking_error():
    db, season, teams = _hiller_import_context()
    preview, staged = build_preview(db, season.id, [
        _hiller_row('12:00 PM', 'Field 99', 'Large', teams[0], teams[1])])

    assert staged == []
    assert preview['importable_games'] == 0
    assert preview['invalid_rows'] == 1
    assert preview['blocking_errors'] == 1
    assert preview['rows'][0]['status'] == 'ERROR'
    assert preview['rows'][0]['message'] == (
        'Field "Field 99" could not be found at site "Hiller Stadium".')


def test_week_one_summary_counts_warning_as_importable():
    db, season, teams = _hiller_import_context()
    rows = [
        _hiller_row(f'{hour:02d}:00', 'Field 1', 'Medium',
                    teams[hour * 2], teams[hour * 2 + 1])
        for hour in range(20)
    ]
    rows.append(_hiller_row('20:00', 'Field 1', 'Large', teams[40], teams[41]))

    preview, staged = build_preview(db, season.id, rows)

    assert preview['rows_uploaded'] == 21
    assert preview['importable_games'] == 21
    assert preview['games_to_add'] == 21
    assert preview['warning_count'] == 1
    assert preview['blocking_errors'] == 0
    assert preview['invalid_rows'] == 0
    assert len(staged) == 21


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
