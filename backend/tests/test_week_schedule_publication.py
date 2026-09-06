import uuid
from datetime import date, time
from types import SimpleNamespace
from unittest.mock import patch

from app.routes.api import (_is_publishable_schedule_week, _publication_week_payload,
                            _season_publication_rollup, _week_publish_readiness,
                            _normalize_public_schedule_payload, _public_schedule_differences,
                            _week_public_schedule_hash, compare_week_to_published_snapshot,
                            get_week_publication_state)


def _game(week_id, *, game_id=None, home_id=None, away_id=None, field_id=None):
    division_id = uuid.uuid4()
    home_id = home_id or uuid.uuid4()
    away_id = away_id or uuid.uuid4()
    game = SimpleNamespace(
        id=game_id or uuid.uuid4(), week_id=week_id, home_team_id=home_id, away_team_id=away_id,
        game_date=SimpleNamespace(isoformat=lambda: '2026-08-16'), kickoff_time=SimpleNamespace(isoformat=lambda: '10:00:00'),
        field_id=field_id or uuid.uuid4(), field_instance_id=None,
        field=SimpleNamespace(name='Hiller Park SW', layout_type='SMALL'),
        host_location_id=uuid.uuid4(),
    )
    home = SimpleNamespace(id=home_id, division_id=division_id, is_active=True, name='Home Team')
    away = SimpleNamespace(id=away_id, division_id=division_id, is_active=True, name='Away Team')
    division = SimpleNamespace(id=division_id, name='K-1')
    return (game, None, None, SimpleNamespace(name='Hiller Park'), home, away, division, None, None)


def _valid_shared_layout(*field_ids):
    return {
        'valid': True, 'is_valid': True, 'blocking_issues': [], 'issue_code': None,
        'available_layouts': [], 'compatible_configuration': 'ONE_LARGE_ONE_SMALL',
        'supported_layouts': ['ONE_LARGE_ONE_SMALL'],
        'configuration_basis': 'Named configuration membership (field IDs)',
        'assigned_field_ids': [str(value) for value in field_ids],
        'conflicting_pairs': [], 'active_configurations': [],
        'reason': 'Assigned physical fields coexist in the persisted configuration.',
    }


def test_readiness_validates_only_selected_week_and_ignores_future_week_error():
    selected_id, future_id = uuid.uuid4(), uuid.uuid4()
    selected = _game(selected_id)
    future = _game(future_id)
    future[0].away_team_id = future[0].home_team_id
    future[5].id = future[4].id
    with patch('app.routes.api.get_scheduled_games_for_season', return_value=[selected, future]):
        result = _week_publish_readiness(SimpleNamespace(), SimpleNamespace(id=uuid.uuid4()), [SimpleNamespace(id=selected_id)])
    assert result['games'] == 1
    assert result['blocking_errors'] == []
    assert result['status'] == 'Ready to Publish'


def test_selected_week_hard_error_blocks_publication():
    week_id = uuid.uuid4()
    row = _game(week_id)
    row[0].away_team_id = row[0].home_team_id
    row[5].id = row[4].id
    with patch('app.routes.api.get_scheduled_games_for_season', return_value=[row]):
        result = _week_publish_readiness(SimpleNamespace(), SimpleNamespace(id=uuid.uuid4()), [SimpleNamespace(id=week_id)])
    assert any(issue['issue_code'] == 'SAME_TEAM' for issue in result['blocking_errors'])
    assert result['status'] == 'Blocked'


def test_twenty_one_canonical_fields_have_no_missing_field_errors():
    week_id = uuid.uuid4()
    rows = [_game(week_id) for _ in range(21)]
    # Avoid manufacturing unrelated team/field conflicts in this focused test.
    for index, row in enumerate(rows):
        row[0].game_date = SimpleNamespace(isoformat=lambda index=index: f'2026-08-{16 + index:02d}')
    with patch('app.routes.api.get_scheduled_games_for_season', return_value=rows):
        result = _week_publish_readiness(SimpleNamespace(), SimpleNamespace(id=uuid.uuid4()), [SimpleNamespace(id=week_id)])
    assert not [issue for issue in result['blocking_errors'] if issue['issue_code'] == 'MISSING_FIELD']


def test_hiller_sequential_publish_waves_use_resolved_authoritative_field_ids():
    """Generated-slot metadata cannot change the import-approved layout input."""
    week_id = uuid.uuid4()
    physical_field_id = uuid.uuid4()
    assignment = SimpleNamespace(
        physical_field_id=physical_field_id,
        physical_field=SimpleNamespace(
            id=physical_field_id, name='Hiller Stadium Small Field', layout_type='SMALL',
        ),
        field_instance_id=uuid.uuid4(), display_name='Hiller Stadium Small Field',
        issue_code=None,
    )
    validation = {
        'valid': True, 'is_valid': True, 'blocking_issues': [], 'issue_code': None,
        'available_layouts': [], 'compatible_configuration': '1 Large + 1 Small',
        'supported_layouts': ['1 Large + 1 Small'],
        'configuration_basis': 'Named configuration membership (field IDs)',
        'assigned_field_ids': [str(physical_field_id)], 'conflicting_pairs': [],
        'active_configurations': [], 'reason': 'Assigned physical fields coexist in the persisted configuration.',
    }

    for hour in (9, 10, 11):
        row = _game(week_id)
        row[0].field_id = None
        row[0].field = None
        row[0].field_instance_id = assignment.field_instance_id
        row[0].game_date = date(2026, 9, 20)
        row[0].kickoff_time = time(hour)
        with (patch('app.routes.api.get_scheduled_games_for_season', return_value=[row]),
              patch('app.routes.api.resolve_game_field_assignment', return_value=assignment),
              patch('app.routes.api.facility_layout_validation.validate_field_configuration',
                    return_value=validation) as shared_validator):
            result = _week_publish_readiness(
                SimpleNamespace(), SimpleNamespace(id=uuid.uuid4()), [SimpleNamespace(id=week_id)],
            )

        assert result['status'] == 'Ready to Publish'
        assert not [issue for issue in result['blocking_errors']
                    if issue['issue_code'] == 'FIELD_LAYOUT_CONFLICT']
        normalized = shared_validator.call_args.args[4]
        assert normalized == [{
            'field_id': physical_field_id,
            'field_name': 'Hiller Stadium Small Field',
            'required_field_size': 'SMALL',
            'configuration_id': None,
        }]


def test_publish_validates_complete_kickoff_wave_once_through_shared_validator():
    """A Large + Small wave cannot be reinterpreted game by game."""
    week_id, host_id = uuid.uuid4(), uuid.uuid4()
    rows = [_game(week_id), _game(week_id)]
    assignments = []
    for index, (row, required) in enumerate(zip(rows, ('LARGE', 'SMALL'))):
        row[0].host_location_id = host_id
        row[0].game_date = date(2026, 9, 20)
        row[0].kickoff_time = time(9)
        row[6].required_field_layout_type = required
        field_id = row[0].field_id
        assignment = SimpleNamespace(
            physical_field_id=field_id, physical_field=row[0].field,
            field_instance_id=None, display_name=f'Position {index + 1}', issue_code=None,
        )
        assignments.append(assignment)

    with (patch('app.routes.api.get_scheduled_games_for_season', return_value=rows),
          patch('app.routes.api.resolve_game_field_assignment', side_effect=assignments),
          patch('app.routes.api.facility_layout_validation.validate_field_configuration',
                return_value=_valid_shared_layout(*(row[0].field_id for row in rows))) as validator,
          patch('app.routes.api.select_supported_layout') as duplicate_validator):
        result = _week_publish_readiness(
            SimpleNamespace(), SimpleNamespace(id=uuid.uuid4()), [SimpleNamespace(id=week_id)],
        )

    assert result['blocking_errors'] == []
    assert result['status'] == 'Ready to Publish'
    assert validator.call_count == 1
    assert [item['required_field_size'] for item in validator.call_args.args[4]] == ['LARGE', 'SMALL']
    duplicate_validator.assert_not_called()


def test_group_configuration_allows_game_without_direct_field_id():
    """The saved kickoff layout, rather than a fabricated field, owns the wave."""
    week_id = uuid.uuid4()
    row = _game(week_id)
    row[0].field_id = None
    row[0].field = None
    row[0].game_date = date(2026, 9, 20)
    row[0].kickoff_time = time(10)
    configuration = SimpleNamespace(is_active=True, configuration_name='ONE_LARGE')
    row[0].timeslot_configuration = SimpleNamespace(
        host_location_id=row[0].host_location_id,
        configuration_date=row[0].game_date,
        kickoff_time=row[0].kickoff_time,
        configuration=configuration,
    )

    with (patch('app.routes.api.get_scheduled_games_for_season', return_value=[row]),
          patch('app.routes.api.resolve_game_field_assignment', return_value=None),
          patch('app.routes.api.facility_layout_validation.validate_field_configuration',
                return_value=_valid_shared_layout()) as validator):
        result = _week_publish_readiness(
            SimpleNamespace(), SimpleNamespace(id=uuid.uuid4()), [SimpleNamespace(id=week_id)],
        )

    assert result['blocking_errors'] == []
    assert result['status'] == 'Ready to Publish'
    assert validator.call_args.args[4][0]['field_id'] is None
    assert validator.call_args.args[4][0]['configuration_id'] is None


def test_publish_passes_physical_configuration_id_not_timeslot_row_id():
    """Layout resolution must not compare IDs from two different tables."""
    week_id = uuid.uuid4()
    row = _game(week_id)
    physical_configuration_id = uuid.uuid4()
    timeslot_row_id = uuid.uuid4()
    row[0].game_date = date(2026, 9, 20)
    row[0].kickoff_time = time(9)
    row[0].timeslot_configuration_id = timeslot_row_id
    row[0].timeslot_configuration = SimpleNamespace(
        id=timeslot_row_id,
        configuration_id=physical_configuration_id,
        host_location_id=row[0].host_location_id,
        configuration_date=row[0].game_date,
        kickoff_time=row[0].kickoff_time,
        configuration=SimpleNamespace(id=physical_configuration_id, is_active=True),
    )
    assignment = SimpleNamespace(
        physical_field_id=row[0].field_id, physical_field=row[0].field,
        field_instance_id=None, display_name=row[0].field.name, issue_code=None,
    )

    with (patch('app.routes.api.get_scheduled_games_for_season', return_value=[row]),
          patch('app.routes.api.resolve_game_field_assignment', return_value=assignment),
          patch('app.routes.api.facility_layout_validation.validate_field_configuration',
                return_value=_valid_shared_layout(row[0].field_id)) as validator):
        result = _week_publish_readiness(
            SimpleNamespace(), SimpleNamespace(id=uuid.uuid4()), [SimpleNamespace(id=week_id)],
        )

    assert result['status'] == 'Ready to Publish'
    normalized = validator.call_args.args[4][0]
    assert normalized['configuration_id'] == physical_configuration_id
    assert normalized['configuration_id'] != timeslot_row_id


def test_invalid_shared_field_configuration_is_returned_as_readiness_data():
    """A validator blocker must not crash Schedule Readiness tuple projection."""
    week_id = uuid.uuid4()
    row = _game(week_id)
    field_id = row[0].field_id
    assignment = SimpleNamespace(
        physical_field_id=field_id,
        physical_field=row[0].field,
        field_instance_id=None,
        display_name=row[0].field.name,
        issue_code=None,
    )
    validation = {
        'valid': False,
        'is_valid': False,
        'is_blocking': True,
        'blocking_issues': [{
            'issue_code': 'FIELD_LAYOUT_CONFLICT',
            'reason': 'Assigned fields do not form a valid active physical layout.',
            'conflicting_fields': [row[0].field.name],
        }],
        'issue_code': 'FIELD_LAYOUT_CONFLICT',
        'available_layouts': [{'code': 'TWO_SMALL', 'capacity': {
            'SMALL': 2, 'MEDIUM': 0, 'LARGE': 0,
        }}],
        'compatible_configuration': None,
        'supported_layouts': [],
        'configuration_basis': 'Named configuration membership (field IDs)',
        'assigned_field_ids': [str(field_id)],
        'conflicting_pairs': [],
        'active_configurations': [],
        'reason': 'Assigned fields do not form a valid active physical layout.',
    }

    with (patch('app.routes.api.get_scheduled_games_for_season', return_value=[row]),
          patch('app.routes.api.resolve_game_field_assignment', return_value=assignment),
          patch('app.routes.api.facility_layout_validation.validate_field_configuration',
                return_value=validation)):
        result = _week_publish_readiness(
            SimpleNamespace(), SimpleNamespace(id=uuid.uuid4()), [SimpleNamespace(id=week_id)],
        )

    assert result['status'] == 'Blocked'
    assert result['blocking_errors'][0]['issue_code'] == 'FIELD_LAYOUT_CONFLICT'
    assert result['blocking_errors'][0]['summary'] == validation['reason']
    assert result['blocking_errors'][0]['field'] == 'Hiller Park SW'
    assert result['blocking_errors'][0]['required_field_type'] == '1 Small'
    assert result['blocking_errors'][0]['current_layout'] == 'Unresolved assignment'


def test_one_truly_null_canonical_field_is_a_descriptive_blocking_error():
    week_id = uuid.uuid4()
    row = _game(week_id)
    row[0].field_id = None
    row[0].field = None
    with patch('app.routes.api.get_scheduled_games_for_season', return_value=[row]):
        result = _week_publish_readiness(SimpleNamespace(), SimpleNamespace(id=uuid.uuid4()), [SimpleNamespace(id=week_id)])
    issues = [issue for issue in result['blocking_errors'] if issue['issue_code'] == 'MISSING_FIELD']
    assert len(issues) == 1
    assert issues[0]['scheduled_game_display_name'] == 'Home Team vs Away Team'
    assert issues[0]['location'] == 'Hiller Park'
    assert issues[0]['field'] == 'Not Assigned'
    assert issues[0]['recommended_action'] == 'Assign a field in Manual Schedule Builder.'
    assert result['status'] == 'Blocked'


def test_stale_field_from_an_inactive_layout_has_distinct_configuration_error():
    week_id = uuid.uuid4()
    row = _game(week_id)
    row[0].field.is_active = False
    row[0].field.deleted_at = None
    with patch('app.routes.api.get_scheduled_games_for_season', return_value=[row]):
        result = _week_publish_readiness(SimpleNamespace(), SimpleNamespace(id=uuid.uuid4()), [SimpleNamespace(id=week_id)])
    issue = next(item for item in result['blocking_errors'] if item['issue_code'] == 'FIELD_CONFIGURATION_INVALID')
    assert issue['scheduled_game_display_name'] == 'Home Team vs Away Team'
    assert issue['field'] == 'Hiller Park SW'
    assert issue['required_field_type'] == 'SMALL'
    assert issue['reason'] == 'The saved field or field configuration does not exist or is inactive.'
    assert issue['recommended_action'] == 'Correct the game in Manual Schedule Builder.'
    assert result['status'] == 'Blocked'


def test_season_rollup_reports_partial_and_complete_publication():
    assert _season_publication_rollup([SimpleNamespace(publication_status='PUBLISHED'), SimpleNamespace(publication_status='UNPUBLISHED')]) == 'partially_published'
    assert _season_publication_rollup([SimpleNamespace(publication_status='PUBLISHED'), SimpleNamespace(publication_status='PUBLISHED')]) == 'published'


def _configured_week(number, game_date, date_type='REGULAR_SEASON', status='active', label=None):
    return SimpleNamespace(id=uuid.uuid4(), week_number=number, primary_game_date=game_date,
                           date_type=date_type, status=status, label=label)


def test_standard_sequential_publication_weeks_keep_configured_numbers_and_dates():
    date = __import__('datetime').date
    weeks = [_configured_week(index, date(2026, 8, day)) for index, day in enumerate((9, 16, 23), 1)]
    assert [(week.week_number, week.primary_game_date) for week in weeks if _is_publishable_schedule_week(week)] == [
        (1, date(2026, 8, 9)), (2, date(2026, 8, 16)), (3, date(2026, 8, 23)),
    ]


def test_publication_scope_uses_configured_playable_dates_across_blackouts():
    date = __import__('datetime').date
    weeks = [
        _configured_week(1, date(2026, 8, 9)),
        _configured_week(2, date(2026, 8, 16)),
        _configured_week(3, date(2026, 8, 23)),
        _configured_week(4, date(2026, 8, 30)),
        _configured_week(99, date(2026, 9, 6), 'BLACKOUT'),
        _configured_week(5, date(2026, 9, 13)),
    ]
    publishable = [week for week in weeks if _is_publishable_schedule_week(week)]
    assert [(week.week_number, week.primary_game_date.isoformat()) for week in publishable] == [
        (1, '2026-08-09'), (2, '2026-08-16'), (3, '2026-08-23'),
        (4, '2026-08-30'), (5, '2026-09-13'),
    ]


def test_multiple_blackouts_do_not_become_publication_weeks():
    date = __import__('datetime').date
    weeks = [_configured_week(7, date(2026, 9, 27)),
             _configured_week(8, date(2026, 10, 4), 'BLACKOUT'),
             _configured_week(8, date(2026, 10, 11), 'BLACKOUT'),
             _configured_week(8, date(2026, 10, 18))]
    assert [week.primary_game_date for week in weeks if _is_publishable_schedule_week(week)] == [date(2026, 9, 27), date(2026, 10, 18)]


def test_postseason_payload_preserves_configured_date_only_value_and_identity():
    week = _configured_week(9, __import__('datetime').date(2026, 10, 10), 'PLAYOFF', label='Tournament Day 1')
    state = {'is_published': False, 'has_pending_changes': False, 'publication_status': 'DRAFT'}
    with patch('app.routes.api.get_week_publication_state', return_value=state):
        payload = _publication_week_payload(SimpleNamespace(), SimpleNamespace(), week)
    assert payload['season_week_id'] == str(week.id)
    assert payload['game_date'] == '2026-10-10'
    assert payload['week_type'] == 'postseason'
    assert payload['is_playable'] is True


def test_cancelled_or_date_less_week_is_not_publishable():
    date = __import__('datetime').date
    assert not _is_publishable_schedule_week(_configured_week(1, date(2026, 8, 9), status='cancelled'))
    assert not _is_publishable_schedule_week(_configured_week(1, None))


def test_public_fingerprint_ignores_game_identity_and_implementation_metadata():
    first = {'scheduled_game_id': 'a', 'game_date': '2026-08-16', 'start_time': '09:00:00',
             'host_location_id': 'host', 'field_id': 'field', 'home_team_id': 'home',
             'away_team_id': 'away', 'division_id': 'division', 'canonical_field_label': 'Old',
             'timeslot_configuration_id': 'config-a'}
    second = {**first, 'scheduled_game_id': 'b', 'canonical_field_label': 'New',
              'timeslot_configuration_id': 'config-b'}
    with patch('app.routes.api._week_schedule_payload', side_effect=[[first], [second]]):
        old_hash = _week_public_schedule_hash(SimpleNamespace(), uuid.uuid4(), uuid.uuid4())
        new_hash = _week_public_schedule_hash(SimpleNamespace(), uuid.uuid4(), uuid.uuid4())
    assert old_hash == new_hash


def _public_game(**changes):
    game = {'scheduled_game_id': 'current-row', 'game_date': '2026-08-30', 'start_time': '09:00:00',
            'host_location_id': 'host', 'field_id': 'field', 'home_team_id': 'home',
            'away_team_id': 'away', 'division_id': 'division', 'field_name': 'Hiller - Small - NE',
            'division_name': 'Coed K-1', 'home_team_name': 'Johnsburg K-1 Black',
            'updated_at': '2026-08-20T12:00:00Z', 'notes': None}
    game.update(changes)
    return game


def test_canonical_comparison_ignores_ids_display_names_order_metadata_and_empty_notes():
    first = _public_game()
    second = _public_game(scheduled_game_id='other-current-row', start_time='10:30:00', home_team_id='home-2')
    published = [
        _public_game(scheduled_game_id='published-row-2', start_time='10:30', home_team_id='home-2',
                     field_name='Hiller / Small / NE', division_name='K-1', updated_at='yesterday', notes=''),
        _public_game(scheduled_game_id='published-row-1', start_time='9:00 AM',
                     field_name='Hiller – Small – NE', home_team_name='Jbrg K-1 Black', updated_at='last-week', notes=''),
    ]
    differences = _public_schedule_differences(
        _normalize_public_schedule_payload([first, second]),
        _normalize_public_schedule_payload(published),
    )
    assert differences == {'added_games': [], 'removed_games': [], 'modified_games': []}


def test_canonical_comparison_detects_field_and_matchup_changes():
    original = _normalize_public_schedule_payload([_public_game()])
    field_change = _normalize_public_schedule_payload([_public_game(field_id='different-field')])
    matchup_change = _normalize_public_schedule_payload([_public_game(away_team_id='different-away')])
    assert len(_public_schedule_differences(field_change, original)['modified_games']) == 1
    matchup_diff = _public_schedule_differences(matchup_change, original)
    assert len(matchup_diff['added_games']) == len(matchup_diff['removed_games']) == 1


def test_canonical_comparison_detects_added_removed_and_restored_games():
    original = _normalize_public_schedule_payload([_public_game()])
    added = _normalize_public_schedule_payload([_public_game(), _public_game(start_time='10:00')])
    assert len(_public_schedule_differences(added, original)['added_games']) == 1
    assert len(_public_schedule_differences([], original)['removed_games']) == 1
    assert not any(_public_schedule_differences(original, original).values())


def test_duplicate_publication_rows_are_reported_not_silently_deduplicated():
    game = _normalize_public_schedule_payload([_public_game()])[0]
    differences = _public_schedule_differences([game], [game, game])
    assert differences['removed_games'] == [game]


def test_migrated_week_uses_matching_season_snapshot_instead_of_null_false_positive():
    revision = 'a' * 64
    season = SimpleNamespace(id=uuid.uuid4(), last_published_schedule_hash=revision, last_published_game_count=2)
    week = SimpleNamespace(id=uuid.uuid4(), publication_status='PUBLISHED', last_published_schedule_hash=None,
                           last_published_game_count=None, publication_hash_version=1)
    with patch('app.routes.api._week_public_schedule_payload', return_value=[]), \
         patch('app.routes.api._week_schedule_hash', return_value=('week', 1)), \
         patch('app.routes.api._compute_schedule_hash', return_value=(revision, 2)):
        comparison = compare_week_to_published_snapshot(SimpleNamespace(), season, week)
    assert comparison['has_pending_changes'] is False
    assert comparison['publication_error'] is None


def test_missing_publication_snapshot_is_error_not_pending_changes():
    season = SimpleNamespace(id=uuid.uuid4(), last_published_schedule_hash=None, last_published_game_count=None)
    week = SimpleNamespace(id=uuid.uuid4(), publication_status='PUBLISHED', last_published_schedule_hash=None,
                           last_published_game_count=None, publication_hash_version=1)
    with patch('app.routes.api._week_public_schedule_payload', return_value=[]), \
         patch('app.routes.api._week_schedule_hash', return_value=('current', 1)):
        comparison = compare_week_to_published_snapshot(SimpleNamespace(), season, week)
    assert comparison['has_pending_changes'] is False
    assert comparison['publication_error']


def test_week_3_legacy_row_id_mismatch_is_not_a_material_pending_change():
    """Reproduce the production-equivalent Week 3 false positive.

    The v1 digest included scheduled_game_id, so an import/rebuild could change
    the digest while leaving every public field identical.
    """
    season = SimpleNamespace(id=uuid.uuid4(), last_published_schedule_hash=None, last_published_game_count=None)
    week = SimpleNamespace(id=uuid.uuid4(), week_number=3, primary_game_date=__import__('datetime').date(2026, 8, 30),
                           publication_status='PUBLISHED', published_at=None,
                           last_published_schedule_hash='legacy-before-rebuild', last_published_game_count=1,
                           last_published_schedule_payload=None, publication_hash_version=1)
    with patch('app.routes.api._week_public_schedule_payload', return_value=_normalize_public_schedule_payload([_public_game()])), \
         patch('app.routes.api._week_schedule_hash', return_value=('legacy-after-rebuild', 1)):
        state = get_week_publication_state(SimpleNamespace(), season, week)
    assert state['publication_status'] == 'PUBLISHED'
    assert state['has_pending_changes'] is False
    assert state['added_games'] == state['removed_games'] == state['modified_games'] == []


def test_canonical_publication_state_has_exactly_three_schedule_states():
    season = SimpleNamespace(id=uuid.uuid4(), last_published_schedule_hash=None, last_published_game_count=None)
    draft = SimpleNamespace(id=uuid.uuid4(), publication_status='UNPUBLISHED', last_published_schedule_hash=None,
                            last_published_game_count=None, publication_hash_version=2)
    assert get_week_publication_state(SimpleNamespace(), season, draft)['publication_status'] == 'DRAFT'

    published = SimpleNamespace(**{**draft.__dict__, 'publication_status': 'PUBLISHED',
                                  'last_published_schedule_hash': __import__('hashlib').sha256(b'[]').hexdigest()})
    with patch('app.routes.api._week_public_schedule_payload', return_value=[]):
        current = get_week_publication_state(SimpleNamespace(), season, published)
    assert (current['is_published'], current['has_pending_changes'], current['publication_status']) == (True, False, 'PUBLISHED')

    with patch('app.routes.api._week_public_schedule_payload', return_value=_normalize_public_schedule_payload([_public_game()])):
        pending = get_week_publication_state(SimpleNamespace(), season, published)
    assert (pending['is_published'], pending['has_pending_changes'], pending['publication_status']) == (True, True, 'PUBLISHED_CHANGES_PENDING')


def test_partially_published_season_keeps_week_publication_states_independent():
    season = SimpleNamespace(id=uuid.uuid4(), last_published_schedule_hash=None, last_published_game_count=None)
    draft = SimpleNamespace(id=uuid.uuid4(), publication_status='UNPUBLISHED', last_published_schedule_hash=None,
                            last_published_game_count=None, publication_hash_version=2)
    published = SimpleNamespace(id=uuid.uuid4(), publication_status='PUBLISHED',
                                last_published_schedule_hash=__import__('hashlib').sha256(b'[]').hexdigest(),
                                last_published_game_count=0, publication_hash_version=2)

    with patch('app.routes.api._week_public_schedule_payload', return_value=[]):
        states = [get_week_publication_state(SimpleNamespace(), season, week) for week in (published, draft)]

    assert [(state['is_published'], state['publication_status']) for state in states] == [
        (True, 'PUBLISHED'),
        (False, 'DRAFT'),
    ]


def test_hiller_saved_large_override_is_descriptive_nonblocking_warning():
    week_id = uuid.uuid4()
    row = _game(week_id)
    row[0].kickoff_time = __import__('datetime').time(12, 0)
    row[0].field = SimpleNamespace(name='Medium Field 1', layout_type='MEDIUM')
    row[0].field_layout_type_override = 'LARGE'
    row[0].timeslot_configuration_id = None
    row[4].name = 'Antioch Girls 6-8'
    row[5].name = 'Westosha Girls 6-8 Maroon'
    row[6].division_group = 'Girls'
    row[6].name = '6-8'
    row[6].required_field_layout_type = 'LARGE'
    row[3].name = 'Hiller Stadium'
    with patch('app.routes.api.get_scheduled_games_for_season', return_value=[row]), \
         patch('app.routes.api.facility_layout_validation.validate_field_configuration',
               return_value=_valid_shared_layout(row[0].field_id)):
        result = _week_publish_readiness(SimpleNamespace(), SimpleNamespace(id=uuid.uuid4()), [SimpleNamespace(id=week_id)])
    assert result['blocking_errors'] == []
    assert result['status'] == 'Ready to Publish'


def test_shared_validator_acceptance_is_not_overridden_by_field_type_logic():
    week_id = uuid.uuid4()
    row = _game(week_id)
    row[0].field = SimpleNamespace(name='Medium Field 1', layout_type='MEDIUM')
    row[6].division_group = 'Girls'; row[6].name = '6-8'; row[6].required_field_layout_type = 'LARGE'
    with patch('app.routes.api.get_scheduled_games_for_season', return_value=[row]), \
         patch('app.routes.api.facility_layout_validation.validate_field_configuration',
               return_value=_valid_shared_layout(row[0].field_id)), \
         patch('app.routes.api.select_supported_layout') as duplicate_validator:
        result = _week_publish_readiness(SimpleNamespace(), SimpleNamespace(id=uuid.uuid4()), [SimpleNamespace(id=week_id)])
    assert result['blocking_errors'] == []
    duplicate_validator.assert_not_called()
