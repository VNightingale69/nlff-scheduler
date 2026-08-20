import uuid
from types import SimpleNamespace
from unittest.mock import patch

from app.routes.api import (_season_publication_rollup, _week_publish_readiness,
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
    configuration = SimpleNamespace(configuration_name='ONE_LARGE', small_field_count=0, medium_field_count=0, large_field_count=1)
    with patch('app.routes.api.get_scheduled_games_for_season', return_value=[row]), \
         patch('app.routes.api.select_supported_layout', return_value=(None, configuration, True)):
        result = _week_publish_readiness(SimpleNamespace(), SimpleNamespace(id=uuid.uuid4()), [SimpleNamespace(id=week_id)])
    assert result['blocking_errors'] == []
    assert len(result['warnings']) == 1
    warning = result['warnings'][0]
    assert warning['issue_code'] == 'FIELD_LAYOUT_RECONFIGURATION'
    assert warning['scheduled_game_display_name'] == 'Antioch Girls 6-8 vs Westosha Girls 6-8 Maroon'
    assert warning['location'] == 'Hiller Stadium'
    assert warning['field'] == 'Medium Field 1'
    assert warning['canonical_field_type'] == 'MEDIUM'
    assert warning['required_field_type'] == 'LARGE'


def test_hiller_large_game_without_saved_override_is_descriptive_error():
    week_id = uuid.uuid4()
    row = _game(week_id)
    row[0].field = SimpleNamespace(name='Medium Field 1', layout_type='MEDIUM')
    row[6].division_group = 'Girls'; row[6].name = '6-8'; row[6].required_field_layout_type = 'LARGE'
    configuration = SimpleNamespace(configuration_name='ONE_LARGE', small_field_count=0, medium_field_count=0, large_field_count=1)
    with patch('app.routes.api.get_scheduled_games_for_season', return_value=[row]), \
         patch('app.routes.api.select_supported_layout', return_value=(None, configuration, True)):
        result = _week_publish_readiness(SimpleNamespace(), SimpleNamespace(id=uuid.uuid4()), [SimpleNamespace(id=week_id)])
    issue = result['blocking_errors'][0]
    assert issue['issue_code'] == 'FIELD_TYPE_MISMATCH'
    assert issue['scheduled_game_id'] == str(row[0].id)
    assert issue['scheduled_game_display_name'] == 'Home Team vs Away Team'
    assert issue['date'] == '2026-08-16'
    assert issue['time'] == '10:00:00'
    assert issue['location'] == 'Hiller Park'
    assert issue['field'] == 'Medium Field 1'
