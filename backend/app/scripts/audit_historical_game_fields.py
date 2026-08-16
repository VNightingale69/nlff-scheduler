"""Audit/repair historical field display evidence for a season.

Usage: ``python -m app.scripts.audit_historical_game_fields 2026 [--repair]``.
Repairs copy only stable referenced records; unresolved rows are reported and
never guessed from division or facility configuration.
"""
import argparse
import csv
import sys

from app.database import SessionLocal
from app.models import Game, GameSlot, GameStatus, Season
from app.services.field_resolution import resolve_game_field_display, snapshot_game_field_display


def run(year: int, repair: bool = False, output=sys.stdout) -> int:
    db = SessionLocal()
    try:
        season = db.query(Season).filter(Season.start_date >= f'{year}-01-01', Season.start_date < f'{year + 1}-01-01').first()
        if not season:
            raise SystemExit(f'No {year} season found')
        games = db.query(Game).join(GameStatus).filter(Game.season_id == season.id, GameStatus.code != 'UNSCHEDULED').all()
        slots = {slot.assigned_game_id: slot for slot in db.query(GameSlot).filter(GameSlot.assigned_game_id.in_([g.id for g in games])).all()}
        writer = csv.DictWriter(output, fieldnames=[
            'game_id', 'date', 'division', 'home', 'away', 'host_location', 'field_id',
            'field_status', 'physical_area_id', 'generated_slot_id',
            'recoverable_historical_field_name', 'reason_current_ui_fails'])
        writer.writeheader()
        unresolved = 0
        for game in games:
            slot = slots.get(game.id)
            resolved = resolve_game_field_display(game, db, generated_slot=slot)
            field = game.field
            if repair and resolved.name:
                snapshot_game_field_display(game, resolved, getattr(game.host_location or getattr(slot, 'host_location', None), 'name', None))
            if not resolved.name:
                unresolved += 1
            writer.writerow({
                'game_id': game.id, 'date': game.game_date,
                'division': getattr(getattr(game.home_team, 'division', None), 'name', None),
                'home': game.home_team.name, 'away': game.away_team.name,
                'host_location': getattr(game.host_location or getattr(slot, 'host_location', None), 'name', None),
                'field_id': game.field_id, 'field_status': ('missing' if game.field_id and not field else
                    'soft-deleted' if field and field.deleted_at else 'inactive' if field and not field.is_active else 'active' if field else 'null'),
                'physical_area_id': getattr(field, 'physical_field_area_id', None),
                'generated_slot_id': getattr(slot, 'id', None),
                'recoverable_historical_field_name': resolved.name,
                'reason_current_ui_fails': ('no stable assignment or snapshot' if not resolved.name else
                    'legacy serializer ignored ' + resolved.source if resolved.source != 'generated_slot' else ''),
            })
        if repair:
            db.commit()
        return unresolved
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('year', type=int)
    parser.add_argument('--repair', action='store_true')
    args = parser.parse_args()
    raise SystemExit(1 if run(args.year, args.repair) else 0)
