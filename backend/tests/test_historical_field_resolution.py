import uuid

from app.models import Field, Game
from app.services.field_resolution import resolve_game_field_display


def _game(**values):
    defaults = dict(id=uuid.uuid4(), field_id=None, field_instance_id=None)
    defaults.update(values)
    return Game(**defaults)


def test_historical_game_can_display_inactive_field():
    field = Field(id=uuid.uuid4(), host_location_id=uuid.uuid4(), name='Field 1',
                  layout_type='SMALL', is_active=False)
    game = _game(field_id=field.id)
    game.field = field
    resolved = resolve_game_field_display(game)
    assert resolved.name == 'Field 1'
    assert resolved.source == 'field'


def test_historical_game_can_display_soft_deleted_field():
    field = Field(id=uuid.uuid4(), host_location_id=uuid.uuid4(),
                  name='Johnsburg - Hiller - Small - NE', layout_type='SMALL',
                  is_active=False)
    field.deleted_at = object()
    game = _game(field_id=field.id)
    game.field = field
    assert resolve_game_field_display(game).name == 'Johnsburg - Hiller - Small - NE'


def test_retired_field_display_name_is_clean():
    game = _game(field_display_name_snapshot='__retired_generated__abc123__Medium Field 1')
    assert resolve_game_field_display(game).name == 'Medium Field 1'


def test_historical_field_snapshot_survives_field_deletion():
    game = _game(previous_field_name='Johnsburg - Hiller - Small - SW')
    resolved = resolve_game_field_display(game)
    assert resolved.name == 'Johnsburg - Hiller - Small - SW'
    assert resolved.source == 'snapshot'


def test_genuinely_unassigned_game_remains_unassigned():
    assert resolve_game_field_display(_game()).name is None
