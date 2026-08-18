from pathlib import Path


SOURCE = (Path(__file__).parents[1] / 'alembic' / 'versions' /
          '20260818_0073_repair_retired_game_fields.py').read_text()


def test_repair_is_current_season_relational_and_ambiguity_safe():
    assert 's.is_active IS TRUE' in SOURCE
    assert 'active.hosting_availability_id = retired.hosting_availability_id' in SOURCE
    assert 'active.instance_date = retired.instance_date' in SOURCE
    assert 'active.field_type = retired.field_type' in SOURCE
    assert 'HAVING count(*) = 1' in SOURCE


def test_repair_updates_relationship_without_recreating_games_or_scores():
    assert 'UPDATE games g' in SOURCE
    assert 'SET field_instance_id = replacement.active_id' in SOURCE
    assert 'INSERT INTO games' not in SOURCE
    assert 'game_scores' not in SOURCE
