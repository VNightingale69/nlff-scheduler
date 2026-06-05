from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models import Division, Field, FieldInstance, Game, GameSlot, HostLocation, HostingAvailability, Team
from app.schemas import GameCreate, GameValidationResponse, ValidationMessage

GAME_DURATION_MINUTES = 60

TURF_CONFIGURATION_ALIASES: dict[str, str] = {}


def _normalize_turf_configuration_name(value: str | None) -> str | None:
    normalized = str(value or '').strip().upper().replace('-', '_').replace(' ', '_')
    return TURF_CONFIGURATION_ALIASES.get(normalized, normalized) or None


TURF_APPROVED_LAYOUTS_BY_SMALL_MEDIUM_LARGE = {
    (2, 1, 0): 'TWO_SMALL_ONE_MEDIUM',
    (0, 2, 0): 'TWO_MEDIUM',
    (3, 0, 0): 'THREE_SMALL',
    (1, 0, 1): 'ONE_SMALL_ONE_LARGE',
    (0, 0, 2): 'TWO_LARGE',
    (0, 1, 1): 'ONE_LARGE_ONE_MEDIUM',
}


def _turf_slot_layout_code(slots: list[GameSlot], proposed_slot: GameSlot | None = None) -> str | None:
    counts = {'SMALL': 0, 'MEDIUM': 0, 'LARGE': 0}
    seen_slot_ids = set()
    for slot in slots:
        seen_slot_ids.add(slot.id)
        size = _normalize_field_size(slot.field_type)
        if size in counts:
            counts[size] += 1
    if proposed_slot and proposed_slot.id not in seen_slot_ids:
        proposed_size = _normalize_field_size(proposed_slot.field_type)
        if proposed_size in counts:
            counts[proposed_size] += 1
    return _normalize_turf_configuration_name(TURF_APPROVED_LAYOUTS_BY_SMALL_MEDIUM_LARGE.get((counts['SMALL'], counts['MEDIUM'], counts['LARGE'])))


def _normalize_field_size(value: str | None) -> str | None:
    normalized = str(value or '').strip().upper().replace('-', '_').replace(' ', '_')
    if not normalized:
        return None
    if normalized in {'SMALL', 'THIRTY_YARD_WIDTH', '30', '30_YARD', '30_YARDS'} or 'THIRTY' in normalized:
        return 'SMALL'
    if normalized in {'MEDIUM', 'FORTY_YARD_WIDTH', '40', '40_YARD', '40_YARDS'} or 'MEDIUM' in normalized or '40' in normalized:
        return 'MEDIUM'
    if normalized in {'LARGE', 'FIFTY_THREE_YARD_WIDTH', '53', '53_YARD', '53_YARDS', 'FULL'} or 'FIFTY_THREE' in normalized or '53' in normalized or 'LARGE' in normalized:
        return 'LARGE'
    return normalized if normalized in {'SMALL', 'MEDIUM', 'LARGE'} else None


def _normalized_division_key(division: Division | None) -> str:
    if not division:
        return ''
    label = f"{division.division_group or ''} {division.name or ''}"
    compact = ''.join(ch.lower() if ch.isalnum() else '_' for ch in label.strip())
    while '__' in compact:
        compact = compact.replace('__', '_')
    return compact.strip('_')


def _required_field_type_for_division(division: Division | None) -> str:
    key = _normalized_division_key(division)
    if key in {'coed_k_1st', 'girls_k_1st', 'coed_k1st', 'girls_k1st', 'coed_k_1', 'girls_k_2', 'coed_2nd_3rd', 'girls_2nd_3rd', 'coed_2_3'}:
        return 'SMALL'
    if key in {'coed_4th_5th', 'girls_4th_5th', 'coed_4_5', 'girls_3_5'}:
        return 'MEDIUM'
    if key in {'coed_6th_7th', 'girls_6th_7th', 'girls_6th_7th_8th', 'coed_6_7', 'girls_6_8', 'coed_8th', 'girls_8th', 'coed_8'}:
        return 'LARGE'
    return _normalize_field_size(division.required_field_layout_type if division else None) or 'SMALL'


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
    field = db.query(Field).filter(Field.id == payload.field_id).first() if payload.field_id else None
    field_instance = db.query(FieldInstance).filter(FieldInstance.id == payload.field_instance_id).first() if payload.field_instance_id else None
    host = None
    if payload.host_location_id:
        host = db.query(HostLocation).filter(HostLocation.id == payload.host_location_id).first()
    elif field_instance:
        host = field_instance.host_location
    elif field:
        host = db.query(HostLocation).filter(HostLocation.id == field.host_location_id).first()

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

    if not field and not field_instance:
        hard_conflicts.append(ValidationMessage(code='field_not_found', message='Field or generated field instance must exist.'))
    elif field:
        if not field.is_active:
            hard_conflicts.append(ValidationMessage(code='field_inactive', message='Field must be active.'))
        division = db.query(Division).filter(Division.id == home_team.division_id).first() if home_team else None
        if division and _required_field_type_for_division(division) != _normalize_field_size(field.layout_type):
            hard_conflicts.append(
                ValidationMessage(
                    code='layout_mismatch',
                    message='Division required field size must match selected field capability.',
                )
            )

    if not host:
        hard_conflicts.append(ValidationMessage(code='host_not_found', message='Host location must exist for field.'))
    else:
        if not host.is_active:
            hard_conflicts.append(ValidationMessage(code='host_inactive', message='Host location must be active.'))

    if field_instance and host:
        if not field_instance.is_active:
            hard_conflicts.append(ValidationMessage(code='field_inactive', message='Generated field instance must be active.'))
        division = db.query(Division).filter(Division.id == home_team.division_id).first() if home_team else None
        if division and _required_field_type_for_division(division) != _normalize_field_size(field_instance.field_type):
            hard_conflicts.append(ValidationMessage(code='layout_mismatch', message='Division required field size must match generated slot field type.'))
        availability = (
            db.query(GameSlot)
            .filter(
                GameSlot.field_instance_id == field_instance.id,
                GameSlot.slot_date == payload.game_date,
            )
            .all()
        )
        slot_match = False
        matching_slot = None
        for slot in availability:
            slot_start = datetime.combine(slot.slot_date, slot.start_time)
            slot_end = datetime.combine(slot.slot_date, slot.end_time)
            if game_start >= slot_start and game_end <= slot_end:
                slot_match = True
                matching_slot = slot
                break
        if matching_slot and host and (host.surface_type or 'GRASS_FIELD') == 'TURF_STADIUM':
            host_time_slots = db.query(GameSlot).filter(
                GameSlot.host_location_id == host.id,
                GameSlot.slot_date == matching_slot.slot_date,
                GameSlot.start_time == matching_slot.start_time,
            ).all()
            if not _turf_slot_layout_code(host_time_slots, matching_slot):
                hard_conflicts.append(ValidationMessage(code='unsupported_turf_slot_configuration', message='Manual turf assignment must resolve to an approved slot-level configuration within the 120-yard footprint.'))
            if matching_slot.turf_wave:
                duplicate_component_query = db.query(GameSlot).filter(
                    GameSlot.turf_wave_id == matching_slot.turf_wave_id,
                    GameSlot.field_instance_id == matching_slot.field_instance_id,
                    GameSlot.id != matching_slot.id,
                    GameSlot.assigned_game_id.isnot(None),
                )
                if game_id:
                    duplicate_component_query = duplicate_component_query.filter(GameSlot.assigned_game_id != game_id)
                if duplicate_component_query.first() is not None:
                    hard_conflicts.append(ValidationMessage(code='duplicate_turf_wave_field_component', message='Generated turf field component is already assigned within the selected wave.'))
                wave_start = datetime.combine(matching_slot.slot_date, matching_slot.turf_wave.start_time)
                wave_end = datetime.combine(matching_slot.slot_date, matching_slot.turf_wave.end_time)
                transition_start = wave_start - timedelta(minutes=matching_slot.turf_wave.transition_before_minutes or 0)
                transition_end = wave_end + timedelta(minutes=matching_slot.turf_wave.transition_after_minutes or 0)
                if game_start < wave_start or game_end > wave_end or (game_start < transition_start or game_end > transition_end):
                    hard_conflicts.append(ValidationMessage(code='outside_turf_wave', message='Game must be inside the selected turf wave and outside transition periods.'))
        if not slot_match:
            hard_conflicts.append(
                ValidationMessage(code='outside_availability', message='Game must be within a generated field instance slot.')
            )
    elif field and host:
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

    # Overlap policy:
    # - Allowed: same kickoff window across different host locations.
    # - Allowed: same kickoff window on different fields at the same host location.
    # - Rejected: same team overlap and same field overlap.
    # Shared-resource and officiating-crew overlap checks are intentionally not enforced yet.
    game_filters = [Game.game_date == payload.game_date]
    if game_id:
        game_filters.append(Game.id != game_id)
    existing_games = db.query(Game).filter(and_(*game_filters)).all()
    for existing in existing_games:
        existing_start = datetime.combine(existing.game_date, existing.kickoff_time)
        existing_end = existing_start + timedelta(minutes=GAME_DURATION_MINUTES)
        if not _windows_overlap(game_start, game_end, existing_start, existing_end):
            continue
        if payload.field_instance_id and existing.field_instance_id == payload.field_instance_id:
            hard_conflicts.append(ValidationMessage(code='field_overlap', message='Field instance cannot be double-booked.'))
        elif payload.field_id and existing.field_id == payload.field_id:
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
