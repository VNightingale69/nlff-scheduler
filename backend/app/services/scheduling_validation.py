from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models import Division, Field, Game, HostLocation, HostingAvailability, Team
from app.schemas import GameCreate, GameValidationResponse, ValidationMessage

GAME_DURATION_MINUTES = 60


def _game_window(payload: GameCreate) -> tuple[datetime, datetime]:
    start = datetime.combine(payload.game_date, payload.kickoff_time)
    return start, start + timedelta(minutes=GAME_DURATION_MINUTES)


def _windows_overlap(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and start_b < end_a


def validate_game(db: Session, payload: GameCreate, game_id: uuid.UUID | None = None) -> GameValidationResponse:
    hard_conflicts: list[ValidationMessage] = []
    soft_warnings: list[ValidationMessage] = []
    game_start, game_end = _game_window(payload)

    home_team = db.query(Team).filter(Team.id == payload.home_team_id).first()
    away_team = db.query(Team).filter(Team.id == payload.away_team_id).first()
    field = db.query(Field).filter(Field.id == payload.field_id).first()
    host = db.query(HostLocation).filter(HostLocation.id == field.host_location_id).first() if field else None

    if payload.home_team_id == payload.away_team_id:
        hard_conflicts.append(ValidationMessage(code='same_team', message='Home and away teams must be different.'))

    if not home_team or not away_team:
        hard_conflicts.append(ValidationMessage(code='team_not_found', message='Both teams must exist.'))
    else:
        if not home_team.is_active or not away_team.is_active:
            hard_conflicts.append(ValidationMessage(code='team_inactive', message='Both teams must be active.'))
        if home_team.division_id != away_team.division_id:
            hard_conflicts.append(
                ValidationMessage(code='team_division_mismatch', message='Home and away teams must be in same division.')
            )

        division_id = home_team.division_id
        division = db.query(Division).filter(Division.id == division_id).first()
        if division and payload.home_team_id and payload.away_team_id:
            if payload.home_team_id and payload.away_team_id and (
                home_team.division_id != division.id or away_team.division_id != division.id
            ):
                hard_conflicts.append(
                    ValidationMessage(code='game_division_mismatch', message='Game division must match both teams division.')
                )

    if not field:
        hard_conflicts.append(ValidationMessage(code='field_not_found', message='Field must exist.'))
    else:
        if not field.is_active:
            hard_conflicts.append(ValidationMessage(code='field_inactive', message='Field must be active.'))
        division = db.query(Division).filter(Division.id == home_team.division_id).first() if home_team else None
        if division and division.required_field_layout_type != field.layout_type:
            hard_conflicts.append(
                ValidationMessage(
                    code='layout_mismatch',
                    message='Division required field layout must match selected field layout capability.',
                )
            )

    if not host:
        hard_conflicts.append(ValidationMessage(code='host_not_found', message='Host location must exist for field.'))
    else:
        if not host.is_active:
            hard_conflicts.append(ValidationMessage(code='host_inactive', message='Host location must be active.'))

    if field and host:
        availability = (
            db.query(HostingAvailability)
            .filter(
                HostingAvailability.field_id == field.id,
                HostingAvailability.available_date == payload.game_date,
                HostingAvailability.is_available.is_(True),
            )
            .all()
        )
        slot_match = False
        for slot in availability:
            slot_start = datetime.combine(slot.available_date, slot.start_time)
            slot_end = datetime.combine(slot.available_date, slot.end_time)
            if game_start >= slot_start and game_end <= slot_end:
                slot_match = True
                break
        if not slot_match:
            hard_conflicts.append(
                ValidationMessage(code='outside_availability', message='Game must be within host location and field availability.')
            )
        if field.physical_field_area_id:
            area_slots = (
                db.query(HostingAvailability)
                .filter(
                    HostingAvailability.physical_field_area_id == field.physical_field_area_id,
                    HostingAvailability.available_date == payload.game_date,
                    HostingAvailability.is_available.is_(True),
                )
                .all()
            )
            matching_area_slots = []
            for slot in area_slots:
                slot_start = datetime.combine(slot.available_date, slot.start_time)
                slot_end = datetime.combine(slot.available_date, slot.end_time)
                if game_start >= slot_start and game_end <= slot_end:
                    matching_area_slots.append(slot)
            division = db.query(Division).filter(Division.id == home_team.division_id).first() if home_team else None
            needed_layout = division.required_field_layout_type if division else None
            if needed_layout:
                supported_count = len([s for s in matching_area_slots if s.layout_type == needed_layout])
                if supported_count == 0:
                    hard_conflicts.append(ValidationMessage(code='area_layout_unavailable', message='No compatible field layout slot is available in selected physical field area for this time block.'))
                overlapping_games = db.query(Game).join(Game.field).filter(
                    Game.game_date == payload.game_date,
                    Field.physical_field_area_id == field.physical_field_area_id,
                ).all()
                used = 0
                for existing in overlapping_games:
                    if game_id and existing.id == game_id:
                        continue
                    existing_start = datetime.combine(existing.game_date, existing.kickoff_time)
                    existing_end = existing_start + timedelta(minutes=GAME_DURATION_MINUTES)
                    if _windows_overlap(game_start, game_end, existing_start, existing_end):
                        existing_division = db.query(Division).filter(Division.id == existing.home_team.division_id).first()
                        if existing_division and existing_division.required_field_layout_type == needed_layout:
                            used += 1
                if used >= supported_count:
                    hard_conflicts.append(ValidationMessage(code='physical_field_area_capacity_exceeded', message='Selected physical field area capacity is exceeded for this layout and time block.'))

    game_filters = [Game.game_date == payload.game_date]
    if game_id:
        game_filters.append(Game.id != game_id)
    existing_games = db.query(Game).filter(and_(*game_filters)).all()
    for existing in existing_games:
        existing_start = datetime.combine(existing.game_date, existing.kickoff_time)
        existing_end = existing_start + timedelta(minutes=GAME_DURATION_MINUTES)
        if not _windows_overlap(game_start, game_end, existing_start, existing_end):
            continue
        if existing.field_id == payload.field_id:
            hard_conflicts.append(ValidationMessage(code='field_overlap', message='Field cannot be double-booked.'))
        if payload.home_team_id in {existing.home_team_id, existing.away_team_id} or payload.away_team_id in {
            existing.home_team_id,
            existing.away_team_id,
        }:
            hard_conflicts.append(
                ValidationMessage(code='team_overlap', message='Team cannot be scheduled for overlapping games.')
            )

    # Deduplicate while keeping order
    seen = set()
    deduped_hard = []
    for item in hard_conflicts:
        key = (item.code, item.message)
        if key not in seen:
            deduped_hard.append(item)
            seen.add(key)
    return GameValidationResponse(hard_conflicts=deduped_hard, soft_warnings=soft_warnings)
