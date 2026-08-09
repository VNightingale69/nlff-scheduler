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
        field_instance_id=field_id or uuid.uuid4(),
    )
    home = SimpleNamespace(id=home_id, division_id=division_id, is_active=True)
    away = SimpleNamespace(id=away_id, division_id=division_id, is_active=True)
    division = SimpleNamespace(id=division_id)
    return (game, None, SimpleNamespace(), None, home, away, division, None, None)


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


def test_season_rollup_reports_partial_and_complete_publication():
    assert _season_publication_rollup([SimpleNamespace(publication_status='PUBLISHED'), SimpleNamespace(publication_status='UNPUBLISHED')]) == 'partially_published'
    assert _season_publication_rollup([SimpleNamespace(publication_status='PUBLISHED'), SimpleNamespace(publication_status='PUBLISHED')]) == 'published'

