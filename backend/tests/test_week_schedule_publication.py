import uuid
from types import SimpleNamespace
from unittest.mock import patch

from app.routes.api import _season_publication_rollup, _week_publish_readiness


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


def test_season_rollup_reports_partial_and_complete_publication():
    assert _season_publication_rollup([SimpleNamespace(publication_status='PUBLISHED'), SimpleNamespace(publication_status='UNPUBLISHED')]) == 'partially_published'
    assert _season_publication_rollup([SimpleNamespace(publication_status='PUBLISHED'), SimpleNamespace(publication_status='PUBLISHED')]) == 'published'
