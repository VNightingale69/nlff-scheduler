"""Fail when active-season games retain obsolete generated field assignments."""

from app.database import SessionLocal
from app.models import FieldInstance, Game, Season
from app.services.generated_field_names import is_retired_generated_field


def current_game_field_violations(db) -> list[tuple[object, object, str]]:
    rows = (
        db.query(Game.id, FieldInstance.id, FieldInstance.field_name, FieldInstance.is_active)
        .join(Season, Season.id == Game.season_id)
        .join(FieldInstance, FieldInstance.id == Game.field_instance_id)
        .filter(Season.is_active.is_(True))
        .all()
    )
    return [
        (game_id, field_id, field_name)
        for game_id, field_id, field_name, is_active in rows
        if not is_active or is_retired_generated_field(field_name)
    ]


def main() -> int:
    with SessionLocal() as db:
        violations = current_game_field_violations(db)
    for game_id, field_id, field_name in violations:
        print(f'game_id={game_id} obsolete_field_instance_id={field_id} stored_name={field_name!r}')
    if violations:
        print(f'FAILED: {len(violations)} active-season game(s) reference obsolete generated fields.')
        return 1
    print('OK: active-season games have no obsolete generated field references.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
