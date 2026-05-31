import csv
import os
import io
import math
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
import logging
from datetime import date, datetime, time, timedelta

from sqlalchemy import String, and_, delete, func, inspect as sa_inspect, or_, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError, SQLAlchemyError
from sqlalchemy.orm import Session, aliased

from app.auth import ROLE_COMMUNITY_ADMIN, ROLE_LEAGUE_ADMIN, enforce_organization_scope, get_current_user, is_community_admin, is_league_admin, normalize_role_name, require_roles
from app.database import get_db
from app.models import Division, Field, FieldConfigurationOption, FieldInstance, Game, GameSlot, GameStatus, HostLocation, HostLocationConfiguration, HostPlanSelection, HostingAvailability, Organization, OrganizationDivisionParticipation, PhysicalFieldArea, Role, Season, Team, TurfWave, User, Week
from app.schemas import (
    DivisionCreate, DivisionRead, FieldConfigurationOptionCreate, FieldConfigurationOptionRead, FieldCreate, FieldRead, GameCreate, GameRead, GameSaveResponse,
    OrganizationDivisionParticipationBulkUpsertRequest, OrganizationDivisionParticipationRead,
    GeneratedSlotRead, GeneratedSlotsClearResponse, HostAvailabilityMatrixSaveRequest, HostAvailabilityMatrixSaveResponse, HostLocationCreate, HostLocationRead, HostLocationConfigurationCreate, HostLocationConfigurationRead, HostingAvailabilityCreate, HostingAvailabilityRead, HostingAvailabilityBulkUpsertRequest, HostingAvailabilityBulkUpsertResponse, HostingGenerationRunResult, HostingGenerationLocationResult, PhysicalFieldAreaCreate, PhysicalFieldAreaRead, SavedAvailabilityResponse,
    LoginRequest, OrganizationCreate, OrganizationRead, PagedResponse, PublicGameRead, RefreshRequest,
    TeamCreate, TeamRead, TeamUpdate, TokenResponse, UserCreate, UserRead,
    HOST_PLAN_SELECTION_STATUSES, ScheduleReadinessDivisionRow, ScheduleReadinessHostDateRow, ScheduleReadinessHostSiteRow, ScheduleReadinessResponse, ScheduleReadinessTotals, ScheduleReadinessTurfWaveRow, ScheduleReadinessTurfWaveSlotRow
)
from app.security import create_access_token, create_refresh_token, hash_password, validate_password_strength, verify_password, decode_token
from app.services.game_statuses import REQUIRED_GAME_STATUSES, ensure_required_game_statuses
from app.services.organization_cleanup import cleanup_organization_dependencies
from app.services.scheduling_validation import validate_game

router = APIRouter(prefix='/api')
logger = logging.getLogger(__name__)
HOST_PLAN_SELECTION_ADMIN_EMAIL = 'admin@example.com'
HOST_PLAN_SELECTION_PERMISSION_MESSAGE = 'Only admin@example.com can modify host plan selections.'


def _enforce_host_plan_selection_admin(current_user: User) -> None:
    if (current_user.email or '').strip().lower() != HOST_PLAN_SELECTION_ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail=HOST_PLAN_SELECTION_PERMISSION_MESSAGE)


ALLOWED_FIELD_SPACE_TYPES = {
    'STADIUM_SITE',
    'GRASS_PARK_SITE',
}


def _minutes_from_time(value):
    if value is None:
        return None

    try:
        if hasattr(value, 'hour') and hasattr(value, 'minute'):
            return value.hour * 60 + value.minute

        if isinstance(value, str):
            parts = value.split(':')
            if len(parts) >= 2:
                return int(parts[0]) * 60 + int(parts[1])
    except (TypeError, ValueError):
        logger.warning(f"Unable to parse slot time: {value}")
        raise

    logger.warning(f"Unable to parse slot time: {value}")
    raise ValueError(f"Unsupported time value: {value}")


def _canonical_division_suffix(name: str | None) -> str:
    normalized = ''.join(ch for ch in (name or '').upper() if ch.isalnum())
    suffix_map = {
        'K1ST': 'K_1',
        'K1': 'K_1',
        'K2': 'K_2',
        '2ND3RD': '2_3',
        '23': '2_3',
        '35': '3_5',
        '4TH5TH': '4_5',
        '45': '4_5',
        '6TH7TH': '6_7',
        '67': '6_7',
        '8TH': '8',
        '8': '8',
        '6TH7TH8TH': '6_7_8',
        '68': '6_8',
    }
    return suffix_map.get(normalized, normalized)


def canonical_division_id(division_group: str | None, division_name: str | None) -> str:
    group = ''.join(ch for ch in (division_group or '').upper() if ch.isalnum())
    suffix = _canonical_division_suffix(division_name)
    return f'{group}_{suffix}' if group and suffix else ''


def canonical_division_id_from_division(division: Division | None) -> str:
    if not division:
        return ''
    return canonical_division_id(division.division_group, division.name)


def normalize_division_name(value: str) -> str:
    """Normalize division labels while preserving category identity (e.g. girls/coed)."""
    if not value:
        return ''
    compact = ''.join(ch.lower() if ch.isalnum() else '_' for ch in value.strip())
    while '__' in compact:
        compact = compact.replace('__', '_')
    return compact.strip('_')


def normalized_division_key(division_group: str | None, division_name: str | None) -> str:
    return normalize_division_name(f"{division_group or ''} {division_name or ''}")

ALLOWED_SURFACE_TYPES = {'TURF_STADIUM', 'GRASS_FIELD'}
FIELD_SIZE_SMALL = 'SMALL'
FIELD_SIZE_MEDIUM = 'MEDIUM'
FIELD_SIZE_LARGE = 'LARGE'
FIELD_SIZE_ORDER = (FIELD_SIZE_SMALL, FIELD_SIZE_MEDIUM, FIELD_SIZE_LARGE)

WEEK_DATE_TYPES = {'REGULAR_SEASON', 'BLACKOUT', 'PLAYOFF'}
REGULAR_SEASON_DATE_TYPE = 'REGULAR_SEASON'
BLACKOUT_DATE_TYPE = 'BLACKOUT'
PLAYOFF_DATE_TYPE = 'PLAYOFF'


def _normalize_week_date_type(value: object | None) -> str:
    date_type = str(value or REGULAR_SEASON_DATE_TYPE).strip().upper()
    if date_type not in WEEK_DATE_TYPES:
        raise HTTPException(422, 'date_type must be one of REGULAR_SEASON, BLACKOUT, PLAYOFF')
    return date_type


def _week_date_type(week: Week | None) -> str:
    if not week:
        return REGULAR_SEASON_DATE_TYPE
    status_value = str(getattr(week, 'status', '') or '').strip().upper()
    if status_value in WEEK_DATE_TYPES:
        return status_value
    return _normalize_week_date_type(getattr(week, 'date_type', None))


def _is_regular_season_week(week: Week | None) -> bool:
    return _week_date_type(week) == REGULAR_SEASON_DATE_TYPE


def _week_label(week: Week | None) -> str | None:
    if not week:
        return None
    return week.label or f'Week {week.week_number}'


def _week_game_date(week: Week | None) -> date | None:
    if not week:
        return None
    return week.primary_game_date


def _date_only_iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _normalize_local_date_only(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # Treat ISO-ish date/time values as local date-only values. Do not convert
    # through UTC because admin-entered game dates are league-local calendar days.
    date_part = text.split('T', 1)[0].split(' ', 1)[0]
    try:
        return date.fromisoformat(date_part)
    except ValueError:
        return None

TURF_STADIUM_CONFIGURATIONS = {
    'TWO_LARGE': {
        'configuration_name': '2 Large',
        'space_used_yards': 120,
        'remaining_yards': 0,
        'counts': {FIELD_SIZE_LARGE: 2, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_SMALL: 0},
    },
    'ONE_MEDIUM_TWO_SMALL': {
        'configuration_name': '1 Medium + 2 Small',
        'space_used_yards': 120,
        'remaining_yards': 0,
        'counts': {FIELD_SIZE_LARGE: 0, FIELD_SIZE_MEDIUM: 1, FIELD_SIZE_SMALL: 2},
    },
    'ONE_LARGE_ONE_MEDIUM': {
        'configuration_name': '1 Large + 1 Medium',
        'space_used_yards': 115,
        'remaining_yards': 5,
        'counts': {FIELD_SIZE_LARGE: 1, FIELD_SIZE_MEDIUM: 1, FIELD_SIZE_SMALL: 0},
    },
    'TWO_MEDIUM': {
        'configuration_name': '2 Medium',
        'space_used_yards': 110,
        'remaining_yards': 10,
        'counts': {FIELD_SIZE_LARGE: 0, FIELD_SIZE_MEDIUM: 2, FIELD_SIZE_SMALL: 0},
    },
    'THREE_SMALL': {
        'configuration_name': '3 Small',
        'space_used_yards': 100,
        'remaining_yards': 20,
        'counts': {FIELD_SIZE_LARGE: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_SMALL: 3},
    },
    'ONE_LARGE_ONE_SMALL': {
        'configuration_name': '1 Large + 1 Small',
        'space_used_yards': 90,
        'remaining_yards': 30,
        'counts': {FIELD_SIZE_LARGE: 1, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_SMALL: 1},
    },
    'ONE_MEDIUM_ONE_SMALL': {
        'configuration_name': '1 Medium + 1 Small',
        'space_used_yards': 85,
        'remaining_yards': 35,
        'counts': {FIELD_SIZE_LARGE: 0, FIELD_SIZE_MEDIUM: 1, FIELD_SIZE_SMALL: 1},
    },
}
BACKWARD_COMPATIBLE_TURF_CONFIGURATION_ALIASES = {
    '2X53': 'TWO_LARGE',
    '3X30': 'THREE_SMALL',
}
CONFIGURATION_FIELD_TEMPLATES = {
    key: [(f'{field_type.title()} Field {index}', field_type) for field_type in FIELD_SIZE_ORDER for index in range(1, config['counts'][field_type] + 1)]
    for key, config in TURF_STADIUM_CONFIGURATIONS.items()
}

TURF_FOOTPRINT_YARDS = 120
TURF_WAVE_INTENT_SMALL_MEDIUM = 'SMALL_MEDIUM'
TURF_WAVE_INTENT_LARGE = 'LARGE'
TURF_WAVE_INTENT_MIXED = 'MIXED'
TURF_WAVE_INTENT_CUSTOM = 'CUSTOM'
TURF_APPROVED_LAYOUT_CODES = set(TURF_STADIUM_CONFIGURATIONS.keys())
TURF_LAYOUT_CODE_BY_COUNTS = {
    tuple(config['counts'][size] for size in FIELD_SIZE_ORDER): code
    for code, config in TURF_STADIUM_CONFIGURATIONS.items()
}


def _turf_layout_code_for_counts(counts: dict[str, int]) -> str | None:
    return TURF_LAYOUT_CODE_BY_COUNTS.get(tuple(int(counts.get(size, 0) or 0) for size in FIELD_SIZE_ORDER))


def _is_approved_turf_slot_counts(counts: dict[str, int]) -> bool:
    code = _turf_layout_code_for_counts(counts)
    if not code:
        return False
    metadata = TURF_STADIUM_CONFIGURATIONS[code]
    return int(metadata.get('space_used_yards') or 0) <= TURF_FOOTPRINT_YARDS


def _turf_wave_intent_for_layout(layout_code: str) -> str:
    normalized = _normalize_configuration_name(layout_code)
    if normalized == 'ONE_MEDIUM_TWO_SMALL' or normalized == 'ONE_MEDIUM_ONE_SMALL':
        return TURF_WAVE_INTENT_SMALL_MEDIUM
    if normalized == 'TWO_LARGE':
        return TURF_WAVE_INTENT_LARGE
    if normalized in {'ONE_LARGE_ONE_MEDIUM', 'ONE_LARGE_ONE_SMALL'}:
        return TURF_WAVE_INTENT_MIXED
    return TURF_WAVE_INTENT_CUSTOM


def _turf_slot_counts_from_slots(slots: list[GameSlot], *, assigned_only: bool = False) -> dict[str, int]:
    counts = {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0}
    for slot in slots:
        if assigned_only and not slot.assigned_game_id:
            continue
        size = _normalize_field_size(slot.field_type)
        if size in counts:
            counts[size] += 1
    return counts


def _turf_unused_compatible_capacity(slot_counts: dict[str, int], assigned_counts: dict[str, int]) -> dict[str, int]:
    return {
        size: max(int(slot_counts.get(size, 0) or 0) - int(assigned_counts.get(size, 0) or 0), 0)
        for size in FIELD_SIZE_ORDER
    }


def _normalize_configuration_name(value: str | None) -> str:
    normalized = str(value or '').strip().upper().replace('-', '_').replace(' ', '_')
    return BACKWARD_COMPATIBLE_TURF_CONFIGURATION_ALIASES.get(normalized, normalized)


def _normalize_field_size(value: str | None) -> str | None:
    normalized = str(value or '').strip().upper().replace('-', '_').replace(' ', '_')
    if not normalized:
        return None
    if normalized in {FIELD_SIZE_SMALL, 'THIRTY_YARD_WIDTH', '30', '30_YARD', '30_YARDS'} or 'THIRTY' in normalized:
        return FIELD_SIZE_SMALL
    if normalized in {FIELD_SIZE_MEDIUM, 'FORTY_YARD_WIDTH', '40', '40_YARD', '40_YARDS'} or 'MEDIUM' in normalized or '40' in normalized:
        return FIELD_SIZE_MEDIUM
    if normalized in {FIELD_SIZE_LARGE, 'FIFTY_THREE_YARD_WIDTH', '53', '53_YARD', '53_YARDS', 'FULL'} or 'FIFTY_THREE' in normalized or '53' in normalized or 'LARGE' in normalized:
        return FIELD_SIZE_LARGE
    return normalized if normalized in FIELD_SIZE_ORDER else None


def _turf_configuration_metadata(configuration_name: str | None) -> dict | None:
    return TURF_STADIUM_CONFIGURATIONS.get(_normalize_configuration_name(configuration_name))


def _configuration_field_templates(configuration_name: str | None, option: FieldConfigurationOption | None = None) -> list[tuple[str, str]]:
    if option:
        fields: list[tuple[str, str]] = []
        counts = {
            FIELD_SIZE_LARGE: int(getattr(option, 'large_field_count', None) or getattr(option, 'fifty_three_yard_capacity', 0) or 0),
            FIELD_SIZE_MEDIUM: int(getattr(option, 'medium_field_count', 0) or 0),
            FIELD_SIZE_SMALL: int(getattr(option, 'small_field_count', None) or getattr(option, 'thirty_yard_capacity', 0) or 0),
        }
        for field_type in FIELD_SIZE_ORDER:
            for index in range(1, counts[field_type] + 1):
                fields.append((f'{field_type.title()} Field {index}', field_type))
        return fields
    return CONFIGURATION_FIELD_TEMPLATES.get(_normalize_configuration_name(configuration_name), [])


def _capacity_for_layout(layout_name: str | None, option: FieldConfigurationOption | None) -> tuple[int, int, int]:
    templates = _configuration_field_templates(layout_name, option)
    if templates:
        small = sum(1 for _, field_type in templates if field_type == FIELD_SIZE_SMALL)
        medium = sum(1 for _, field_type in templates if field_type == FIELD_SIZE_MEDIUM)
        large = sum(1 for _, field_type in templates if field_type == FIELD_SIZE_LARGE)
        return small, medium, large
    return 0, 0, 0




def _grass_field_templates_for_host(db: Session, host_location_id: uuid.UUID) -> list[tuple[str, str]]:
    fields = db.query(Field).filter(
        Field.host_location_id == host_location_id,
        Field.is_active.is_(True),
    ).order_by(Field.name).all()
    templates: list[tuple[str, str]] = []
    for field in fields:
        field_size = _normalize_field_size(field.layout_type)
        if field_size:
            templates.append((field.name, field_size))
    return templates



def _grass_capacity_limits_for_host(db: Session, host: HostLocation) -> dict[str, int]:
    configured_limits = {
        FIELD_SIZE_SMALL: max(int(getattr(host, 'max_small_fields', 0) or 0), 0),
        FIELD_SIZE_MEDIUM: max(int(getattr(host, 'max_medium_fields', 0) or 0), 0),
        FIELD_SIZE_LARGE: max(int(getattr(host, 'max_large_fields', 0) or 0), 0),
    }
    max_total = max(int(getattr(host, 'max_total_fields', 0) or 0), 0)
    if any(configured_limits.values()) or max_total:
        if max_total:
            configured_limits = {size: (limit if limit > 0 else max_total) for size, limit in configured_limits.items()}
        configured_limits['TOTAL'] = max_total or sum(configured_limits.values())
        return configured_limits

    legacy_counts = {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0}
    for _field_name, field_size in _grass_field_templates_for_host(db, host.id):
        if field_size in legacy_counts:
            legacy_counts[field_size] += 1
    legacy_counts['TOTAL'] = sum(legacy_counts.values())
    return legacy_counts


def _estimated_games_from_team_count(team_count: int | None) -> int:
    return (max(int(team_count or 0), 0) + 1) // 2


def _empty_field_size_counts() -> dict[str, int]:
    return {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0}


def _normalized_demand_counts(demand_counts: dict[str, int] | None) -> dict[str, int]:
    counts = _empty_field_size_counts()
    for size in FIELD_SIZE_ORDER:
        counts[size] = max(int((demand_counts or {}).get(size, 0) or 0), 0)
    return counts


def _allocate_demand_to_location(full_week_demand: dict[str, int], host_index: int, host_count: int) -> dict[str, int]:
    """Allocate full weekly field-size demand across selected host locations.

    Slots are generated before games have host assignments, so this allocation must
    be based on the full week demand rather than games already assigned to a host.
    Remainders are spread by stable host ordering so every required size is present
    in early allocations when possible.
    """
    count = max(int(host_count or 0), 1)
    index = max(int(host_index or 0), 0)
    allocated = _empty_field_size_counts()
    for size in FIELD_SIZE_ORDER:
        total = max(int(full_week_demand.get(size, 0) or 0), 0)
        base, remainder = divmod(total, count)
        allocated[size] = base + (1 if index < remainder else 0)
    return allocated


def _capacity_from_field_counts(counts: dict[str, int], hours: int) -> dict[str, int]:
    return {
        size: max(int((counts or {}).get(size, 0) or 0), 0) * max(int(hours or 0), 1)
        for size in FIELD_SIZE_ORDER
    }


def _capacity_from_templates(templates: list[tuple[str, str]], hours: int) -> dict[str, int]:
    capacity = _empty_field_size_counts()
    for _field_name, field_type in templates:
        size = _normalize_field_size(field_type)
        if size in capacity:
            capacity[size] += max(int(hours or 0), 1)
    return capacity


def _host_availability_capacity_by_size(db: Session, host: HostLocation, availability: HostingAvailability) -> dict[str, int]:
    """Estimate game-slot capacity by size from the saved hosting availability.

    Host-plan decisions use hosting availability as the primary source because
    generated GameSlot rows may not exist yet when admins build or manually edit
    the Host Availability Matrix.
    """
    hours = _hours_between(availability.start_time, availability.end_time, availability.available_date)
    capacity = _empty_field_size_counts()
    field = availability.field
    option = availability.field_configuration_option

    if field and field.is_active:
        field_size = _normalize_field_size(field.layout_type)
        if field_size in capacity:
            capacity[field_size] = hours
        return capacity

    if option:
        if not option.is_active:
            return capacity
        configuration_name = availability.layout_type or option.configuration_name or option.name
        return _capacity_from_templates(_configuration_field_templates(configuration_name, option), hours)

    surface_type = (host.surface_type or 'GRASS_FIELD') if host else 'GRASS_FIELD'
    if surface_type == 'TURF_STADIUM':
        _ensure_approved_turf_configurations(db, host)
        db.flush()
        active_configs = db.query(HostLocationConfiguration).filter(
            HostLocationConfiguration.host_location_id == host.id,
            HostLocationConfiguration.is_active.is_(True),
        ).all()
        active_names = _available_turf_configuration_names(active_configs)
        if not active_names:
            return capacity

        if availability.auto_select_turf_layout and not availability.lock_selected_layout:
            demand_counts = _turf_demand_counts_for_date(db, host, availability.available_date)
            layout_blocks = _plan_turf_layout_blocks(demand_counts, hours, active_names)
            if layout_blocks:
                for layout_name, block_hours in layout_blocks:
                    metadata = _turf_configuration_metadata(layout_name)
                    if metadata:
                        for size in FIELD_SIZE_ORDER:
                            capacity[size] += int(metadata['counts'].get(size, 0) or 0) * max(int(block_hours or 0), 1)
                return capacity

        selected_configuration = _select_best_turf_configuration(db, availability, host)
        if selected_configuration and selected_configuration.is_active:
            metadata = _turf_configuration_metadata(selected_configuration.configuration_name)
            if metadata:
                return _capacity_from_field_counts(metadata['counts'], hours)

        for layout_name in active_names:
            metadata = _turf_configuration_metadata(layout_name)
            if not metadata:
                continue
            layout_capacity = _capacity_from_field_counts(metadata['counts'], hours)
            for size in FIELD_SIZE_ORDER:
                capacity[size] = max(capacity[size], layout_capacity[size])
        return capacity

    if surface_type == 'GRASS_FIELD' and host:
        forecast = _grass_setup_forecast_for_availability(db, host, availability)['forecast']
        if any(int(forecast.get(size, 0) or 0) for size in FIELD_SIZE_ORDER):
            return _capacity_from_field_counts(forecast, hours)
        limits = _grass_capacity_limits_for_host(db, host)
        return _capacity_from_field_counts(limits, hours)

    return capacity


def _allocate_community_demand_to_host_locations(
    db: Session,
    community_demand: dict[str, int],
    hosts_and_availabilities: list[tuple[HostLocation, HostingAvailability]],
) -> dict[uuid.UUID, dict[str, int]]:
    """Split one community demand pool across all locations for that community/date."""
    allocation = {availability.id: _empty_field_size_counts() for _host, availability in hosts_and_availabilities}
    capacity_by_availability = {
        availability.id: _host_availability_capacity_by_size(db, host, availability)
        for host, availability in hosts_and_availabilities
    }

    for size in FIELD_SIZE_ORDER:
        remaining = max(int((community_demand or {}).get(size, 0) or 0), 0)
        while remaining > 0:
            candidates = []
            for host, availability in hosts_and_availabilities:
                assigned = allocation[availability.id][size]
                available_capacity = capacity_by_availability[availability.id].get(size, 0)
                if assigned >= available_capacity:
                    continue
                surface_type = (host.surface_type or 'GRASS_FIELD') if host else 'GRASS_FIELD'
                if size == FIELD_SIZE_LARGE:
                    surface_priority = 0 if surface_type == 'TURF_STADIUM' else 1
                elif size == FIELD_SIZE_SMALL:
                    surface_priority = 0 if surface_type == 'GRASS_FIELD' else 1
                else:
                    surface_priority = 0
                candidates.append((assigned, surface_priority, (host.name or '').lower(), str(host.id), availability.id))
            if not candidates:
                break
            candidates.sort()
            selected_availability_id = candidates[0][4]
            allocation[selected_availability_id][size] += 1
            remaining -= 1
    return allocation

def _grass_demand_counts_for_date(db: Session, host: HostLocation, available_date: date) -> dict[str, int]:
    counts = {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0}
    game_rows = (
        db.query(Game, Division)
        .join(Team, Game.home_team_id == Team.id)
        .join(Division, Team.division_id == Division.id)
        .filter(
            Game.game_date == available_date,
            Team.organization_id == host.organization_id,
            Division.is_active.is_(True),
        )
        .all()
    )
    for _game, division in game_rows:
        required = _required_field_type_for_division(division)
        if required in counts:
            counts[required] += 1

    if not any(counts.values()):
        # Before auto-schedule creates games, forecast grass setups from active participation.
        # Count games, not teams, so Medium/Large divisions get compatible slots without
        # inflating the number of fixed grass field instances.
        participation_rows = (
            db.query(Division, OrganizationDivisionParticipation.team_count)
            .join(OrganizationDivisionParticipation, OrganizationDivisionParticipation.division_id == Division.id)
            .filter(
                OrganizationDivisionParticipation.organization_id == host.organization_id,
                OrganizationDivisionParticipation.is_active.is_(True),
                OrganizationDivisionParticipation.is_participating.is_(True),
                Division.is_active.is_(True),
            )
            .all()
        )
        for division, team_count in participation_rows:
            required = _required_field_type_for_division(division)
            if required in counts:
                counts[required] += _estimated_games_from_team_count(team_count)
    return counts


def _grass_setup_forecast_for_availability(
    db: Session,
    host: HostLocation,
    availability: HostingAvailability,
    demand_counts_override: dict[str, int] | None = None,
) -> dict[str, object]:
    slot_count_per_field = _hours_between(availability.start_time, availability.end_time, availability.available_date)
    demand_counts = _normalized_demand_counts(demand_counts_override) if demand_counts_override is not None else _grass_demand_counts_for_date(db, host, availability.available_date)
    requested = {
        size: math.ceil(max(int(demand_counts.get(size, 0) or 0), 0) / slot_count_per_field)
        for size in FIELD_SIZE_ORDER
    }
    capacity = _grass_capacity_limits_for_host(db, host)
    warnings: list[str] = []
    forecast = {size: min(requested[size], max(int(capacity.get(size, 0) or 0), 0)) for size in FIELD_SIZE_ORDER}

    for size in FIELD_SIZE_ORDER:
        if requested[size] > max(int(capacity.get(size, 0) or 0), 0):
            warnings.append(f'{size.title()} grass field forecast exceeds configured capacity; capped at {capacity.get(size, 0)}.')

    total_capacity = max(int(capacity.get('TOTAL', 0) or 0), 0)
    if total_capacity and sum(forecast.values()) > total_capacity:
        warnings.append(f'Grass field forecast exceeds total configured capacity; capped at {total_capacity}.')
        for size in (FIELD_SIZE_SMALL, FIELD_SIZE_MEDIUM, FIELD_SIZE_LARGE):
            while sum(forecast.values()) > total_capacity and forecast[size] > 0:
                forecast[size] -= 1

    if not any(requested.values()):
        # Legacy/no-demand setup: keep fixed active grass fields available for manually built schedules.
        legacy_counts = {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0}
        for _field_name, field_size in _grass_field_templates_for_host(db, host.id):
            if field_size in legacy_counts:
                legacy_counts[field_size] += 1
        if any(legacy_counts.values()):
            forecast = {size: min(legacy_counts[size], max(int(capacity.get(size, 0) or 0), 0)) for size in FIELD_SIZE_ORDER}

    requested_total = sum(requested.values())
    forecast_total = sum(forecast.values())
    if requested_total == 0 or forecast_total >= requested_total:
        capacity_status = 'ok'
    elif forecast_total > 0:
        capacity_status = 'capped'
    else:
        capacity_status = 'none_available'
        if any(demand_counts.values()):
            warnings.append('No grass field capacity is configured for forecasted grass demand.')

    return {
        'demand': demand_counts,
        'requested': requested,
        'forecast': forecast,
        'capacity': {size: max(int(capacity.get(size, 0) or 0), 0) for size in FIELD_SIZE_ORDER},
        'total_capacity': total_capacity,
        'capacity_status': capacity_status,
        'warnings': sorted(set(warnings)),
    }


def _grass_field_templates_from_forecast(forecast: dict[str, int]) -> list[tuple[str, str]]:
    templates: list[tuple[str, str]] = []
    for size in FIELD_SIZE_ORDER:
        for index in range(1, max(int(forecast.get(size, 0) or 0), 0) + 1):
            templates.append((f'Grass {size.title()} {index}', size))
    return templates

def _grass_capacity_for_community_date(db: Session, organization_id: uuid.UUID, available_date: date) -> dict[str, int]:
    capacity = {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0}
    grass_rows = (
        db.query(HostingAvailability, HostLocation)
        .join(HostLocation, HostingAvailability.host_location_id == HostLocation.id)
        .filter(
            HostLocation.organization_id == organization_id,
            HostLocation.surface_type == 'GRASS_FIELD',
            HostingAvailability.available_date == available_date,
            HostingAvailability.is_available.is_(True),
        )
        .all()
    )
    for availability, host in grass_rows:
        slot_count_per_field = _hours_between(availability.start_time, availability.end_time, availability.available_date)
        forecast = _grass_setup_forecast_for_availability(db, host, availability)['forecast']
        for field_size in FIELD_SIZE_ORDER:
            capacity[field_size] += int(forecast.get(field_size, 0) or 0) * slot_count_per_field
    return capacity


def _turf_demand_counts_for_date(db: Session, host: HostLocation, available_date: date, *, subtract_selected_grass: bool = True) -> dict[str, int]:
    counts = {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0}
    game_rows = (
        db.query(Game, Division)
        .join(Team, Game.home_team_id == Team.id)
        .join(Division, Team.division_id == Division.id)
        .filter(Game.game_date == available_date)
        .all()
    )
    for _game, division in game_rows:
        required = _required_field_type_for_division(division)
        if required in counts:
            counts[required] += 1

    if not any(counts.values()):
        # Before games exist, approximate demand from active teams in divisions the host community participates in.
        participation_rows = (
            db.query(Division, OrganizationDivisionParticipation.team_count)
            .join(OrganizationDivisionParticipation, OrganizationDivisionParticipation.division_id == Division.id)
            .filter(
                OrganizationDivisionParticipation.organization_id == host.organization_id,
                OrganizationDivisionParticipation.is_active.is_(True),
                OrganizationDivisionParticipation.is_participating.is_(True),
            )
            .all()
        )
        for division, team_count in participation_rows:
            required = _required_field_type_for_division(division)
            if required in counts:
                counts[required] += _estimated_games_from_team_count(team_count)

    if subtract_selected_grass:
        grass_capacity = _grass_capacity_for_community_date(db, host.organization_id, available_date)
        counts = {size: max(counts.get(size, 0) - grass_capacity.get(size, 0), 0) for size in FIELD_SIZE_ORDER}
    return counts


def _score_turf_layout_for_demand(layout_name: str, demand_counts: dict[str, int], slot_count_per_field: int) -> tuple[int, int, int]:
    metadata = _turf_configuration_metadata(layout_name)
    layout_counts = metadata['counts'] if metadata else {size: 0 for size in FIELD_SIZE_ORDER}
    compatible_capacity = sum(min(layout_counts[size] * max(slot_count_per_field, 1), demand_counts.get(size, 0)) for size in FIELD_SIZE_ORDER)
    exact_field_types = sum(1 for size in FIELD_SIZE_ORDER if layout_counts[size] and demand_counts.get(size, 0))
    unused_capacity = sum(max((layout_counts[size] * max(slot_count_per_field, 1)) - demand_counts.get(size, 0), 0) for size in FIELD_SIZE_ORDER)
    total_fields = sum(layout_counts.values())
    # Scheduled games and exact matches dominate; unused capacity and extra fields break ties.
    return (compatible_capacity * 100 + exact_field_types * 25 - unused_capacity * 20, -unused_capacity, -total_fields)


def _available_turf_configuration_names(configs: list[HostLocationConfiguration]) -> set[str]:
    return {
        _normalize_configuration_name(config.configuration_name)
        for config in configs
        if config.is_active and _turf_configuration_metadata(config.configuration_name)
    }


def _hours_between(start_time, end_time, available_date: date) -> int:
    start_dt = datetime.combine(available_date, start_time)
    end_dt = datetime.combine(available_date, end_time)
    return max(math.ceil((end_dt - start_dt).total_seconds() / 3600), 1)


def _simulate_turf_layout_sequence(
    sequence: list[str],
    demand_counts: dict[str, int],
    total_hours: int,
    *,
    mixed_layout_available: bool,
) -> tuple[int, list[tuple[str, int]], dict[str, int]] | None:
    normalized_sequence = [_normalize_configuration_name(layout_name) for layout_name in sequence]
    if not normalized_sequence or total_hours <= 0:
        return None
    relevant_sequence = []
    for layout_name in normalized_sequence:
        metadata = _turf_configuration_metadata(layout_name)
        if not metadata:
            return None
        counts = metadata['counts']
        if any(counts[size] and demand_counts.get(size, 0) > 0 for size in FIELD_SIZE_ORDER):
            relevant_sequence.append(layout_name)
    if not relevant_sequence:
        return None

    best: tuple[int, list[tuple[str, int]], dict[str, int]] | None = None

    def _score_allocation(hours_by_layout: list[int]) -> tuple[int, list[tuple[str, int]], dict[str, int]]:
        remaining = {size: max(int(demand_counts.get(size, 0) or 0), 0) for size in FIELD_SIZE_ORDER}
        scheduled_together = False
        for layout_name, hours in zip(relevant_sequence, hours_by_layout):
            counts = _turf_configuration_metadata(layout_name)['counts']
            before_small = remaining[FIELD_SIZE_SMALL]
            before_medium = remaining[FIELD_SIZE_MEDIUM]
            for size in FIELD_SIZE_ORDER:
                remaining[size] = max(remaining[size] - counts[size] * hours, 0)
            if layout_name == 'ONE_MEDIUM_TWO_SMALL' and before_small > remaining[FIELD_SIZE_SMALL] and before_medium > remaining[FIELD_SIZE_MEDIUM]:
                scheduled_together = True
        unscheduled = sum(remaining.values())
        layout_changes = max(0, len(relevant_sequence) - 1)
        score = -10000 * unscheduled - 1000 * max(0, layout_changes - 1)
        if mixed_layout_available and demand_counts.get(FIELD_SIZE_SMALL, 0) > 0 and demand_counts.get(FIELD_SIZE_MEDIUM, 0) > 0:
            if 'ONE_MEDIUM_TWO_SMALL' in relevant_sequence:
                score += 500
                if scheduled_together:
                    score += 300
            has_small_only = any(_turf_configuration_metadata(layout)['counts'][FIELD_SIZE_SMALL] > 0 and _turf_configuration_metadata(layout)['counts'][FIELD_SIZE_MEDIUM] == 0 for layout in relevant_sequence)
            has_medium_only = any(_turf_configuration_metadata(layout)['counts'][FIELD_SIZE_MEDIUM] > 0 and _turf_configuration_metadata(layout)['counts'][FIELD_SIZE_SMALL] == 0 for layout in relevant_sequence)
            if has_small_only and has_medium_only:
                score -= 500
        if demand_counts.get(FIELD_SIZE_LARGE, 0) > 0 and 'TWO_LARGE' in relevant_sequence:
            score += 300
        if layout_changes == 1:
            score += 250
        if 'TWO_LARGE' in relevant_sequence:
            large_index = relevant_sequence.index('TWO_LARGE')
            later_layouts = relevant_sequence[large_index + 1:]
            if any(
                _turf_configuration_metadata(layout)['counts'][FIELD_SIZE_SMALL] > 0
                or _turf_configuration_metadata(layout)['counts'][FIELD_SIZE_MEDIUM] > 0
                for layout in later_layouts
            ):
                score -= 750
        scheduled = {size: max(int(demand_counts.get(size, 0) or 0), 0) - remaining[size] for size in FIELD_SIZE_ORDER}
        return score, list(zip(relevant_sequence, hours_by_layout)), scheduled

    def _allocate(index: int, hours_left: int, prefix: list[int]) -> None:
        nonlocal best
        remaining_blocks = len(relevant_sequence) - index
        if remaining_blocks == 1:
            candidate = _score_allocation(prefix + [hours_left])
            if best is None or candidate[0] > best[0]:
                best = candidate
            return
        max_hours = hours_left - (remaining_blocks - 1)
        for hours in range(1, max_hours + 1):
            _allocate(index + 1, hours_left - hours, prefix + [hours])

    if len(relevant_sequence) > total_hours:
        return None
    _allocate(0, total_hours, [])
    return best


def _plan_turf_layout_blocks(
    demand_counts: dict[str, int],
    total_hours: int,
    active_configuration_names: set[str],
) -> list[tuple[str, int]]:
    if not any(demand_counts.get(size, 0) > 0 for size in FIELD_SIZE_ORDER):
        return []
    mixed_layout_available = 'ONE_MEDIUM_TWO_SMALL' in active_configuration_names
    sequence_candidates: list[list[str]] = []
    if demand_counts.get(FIELD_SIZE_SMALL, 0) > 0 and demand_counts.get(FIELD_SIZE_MEDIUM, 0) > 0 and mixed_layout_available:
        if demand_counts.get(FIELD_SIZE_LARGE, 0) > 0 and 'TWO_LARGE' in active_configuration_names:
            sequence_candidates.append(['ONE_MEDIUM_TWO_SMALL', 'TWO_LARGE'])
        sequence_candidates.append(['ONE_MEDIUM_TWO_SMALL'])
    if demand_counts.get(FIELD_SIZE_SMALL, 0) > 0 and demand_counts.get(FIELD_SIZE_MEDIUM, 0) > 0:
        if all(layout in active_configuration_names for layout in ('THREE_SMALL', 'TWO_MEDIUM')):
            pure_sequence = ['THREE_SMALL', 'TWO_MEDIUM']
            if demand_counts.get(FIELD_SIZE_LARGE, 0) > 0 and 'TWO_LARGE' in active_configuration_names:
                pure_sequence.append('TWO_LARGE')
            sequence_candidates.append(pure_sequence)
    for layout_name in ('TWO_LARGE', 'ONE_LARGE_ONE_MEDIUM', 'ONE_LARGE_ONE_SMALL', 'THREE_SMALL', 'TWO_MEDIUM', 'ONE_MEDIUM_ONE_SMALL'):
        if layout_name in active_configuration_names:
            sequence_candidates.append([layout_name])

    best_plan = None
    for sequence in sequence_candidates:
        if any(layout not in active_configuration_names for layout in sequence):
            continue
        candidate = _simulate_turf_layout_sequence(sequence, demand_counts, total_hours, mixed_layout_available=mixed_layout_available)
        if candidate and (best_plan is None or candidate[0] > best_plan[0]):
            best_plan = candidate
    return best_plan[1] if best_plan else []


def _select_best_turf_configuration(db: Session, availability: HostingAvailability, host: HostLocation) -> HostLocationConfiguration | None:
    _ensure_approved_turf_configurations(db, host)
    db.flush()
    active_configs = db.query(HostLocationConfiguration).filter(
        HostLocationConfiguration.host_location_id == host.id,
        HostLocationConfiguration.is_active.is_(True),
    ).all()
    active_configs = [config for config in active_configs if _turf_configuration_metadata(config.configuration_name)]
    if not active_configs:
        return None
    if availability.lock_selected_layout and availability.selected_configuration_id:
        return next((config for config in active_configs if config.id == availability.selected_configuration_id), None)
    if availability.selected_configuration_id and not availability.auto_select_turf_layout:
        return next((config for config in active_configs if config.id == availability.selected_configuration_id), None)

    start_dt = datetime.combine(availability.available_date, availability.start_time)
    end_dt = datetime.combine(availability.available_date, availability.end_time)
    slot_count_per_field = max(math.ceil((end_dt - start_dt).total_seconds() / 3600), 1)
    demand_counts = _turf_demand_counts_for_date(db, host, availability.available_date)
    return max(active_configs, key=lambda config: _score_turf_layout_for_demand(config.configuration_name, demand_counts, slot_count_per_field))


def _apply_turf_configuration_metadata(obj, configuration_name: str) -> None:
    metadata = _turf_configuration_metadata(configuration_name)
    if not metadata:
        raise HTTPException(400, f'Invalid turf stadium configuration_name: {configuration_name}')
    counts = metadata['counts']
    obj.configuration_name = _normalize_configuration_name(configuration_name)
    obj.surface_type = 'TURF_STADIUM'
    obj.space_used_yards = metadata['space_used_yards']
    obj.remaining_yards = metadata['remaining_yards']
    obj.large_field_count = counts[FIELD_SIZE_LARGE]
    obj.medium_field_count = counts[FIELD_SIZE_MEDIUM]
    obj.small_field_count = counts[FIELD_SIZE_SMALL]



def _ensure_approved_turf_configurations(db: Session, host: HostLocation) -> bool:
    if (host.surface_type or 'GRASS_FIELD') != 'TURF_STADIUM':
        return False
    existing = {
        _normalize_configuration_name(config.configuration_name): config
        for config in db.query(HostLocationConfiguration).filter(HostLocationConfiguration.host_location_id == host.id).all()
    }
    changed = False
    for config_name in TURF_STADIUM_CONFIGURATIONS:
        config = existing.get(config_name)
        if not config:
            config = HostLocationConfiguration(host_location_id=host.id, configuration_name=config_name, is_active=True)
            db.add(config)
            changed = True
        if not config.is_active:
            config.is_active = True
            changed = True
        before = (config.configuration_name, config.surface_type, config.space_used_yards, config.remaining_yards, config.large_field_count, config.medium_field_count, config.small_field_count)
        _apply_turf_configuration_metadata(config, config_name)
        after = (config.configuration_name, config.surface_type, config.space_used_yards, config.remaining_yards, config.large_field_count, config.medium_field_count, config.small_field_count)
        changed = changed or before != after
    return changed

def _attach_configuration_instances(config: HostLocationConfiguration) -> HostLocationConfiguration:
    config.field_instances = [field_name for field_name, _field_type in _configuration_field_templates(config.configuration_name)]
    return config

def _regenerate_generated_slots(
    db: Session,
    availability: HostingAvailability,
    host_location_id: uuid.UUID,
    demand_counts_override: dict[str, int] | None = None,
) -> dict[str, int]:
    slot_date = availability.primary_game_date or availability.available_date
    existing_slots = db.query(GameSlot).join(GameSlot.field_instance).filter(
        FieldInstance.hosting_availability_id == availability.id,
    ).all()
    # Remove stale unassigned slots for the same season/week/host/date key even
    # when they came from an older availability record.  This keeps generated
    # slot records aligned with the exact auto-schedule matching keys.
    stale_same_key_slots = []
    if availability.season_id and availability.week_id and availability.host_location_id and slot_date:
        stale_same_key_slots = db.query(GameSlot).filter(
            GameSlot.host_location_id == host_location_id,
            GameSlot.season_id == availability.season_id,
            GameSlot.week_id == availability.week_id,
            GameSlot.assigned_game_id.is_(None),
            ~GameSlot.field_instance_id.in_(
                db.query(FieldInstance.id).filter(FieldInstance.hosting_availability_id == availability.id)
            ),
        ).all()
        existing_slots.extend(stale_same_key_slots)
    locked_slots = [slot for slot in existing_slots if slot.assigned_game_id is not None]
    unlocked_slots = [slot for slot in existing_slots if slot.assigned_game_id is None]
    unlocked_field_instance_ids = {slot.field_instance_id for slot in unlocked_slots}

    removed_slots = 0
    if unlocked_field_instance_ids:
        removed_slots = db.query(GameSlot).filter(GameSlot.field_instance_id.in_(unlocked_field_instance_ids)).delete(synchronize_session=False)
        db.query(FieldInstance).filter(FieldInstance.id.in_(unlocked_field_instance_ids)).delete(synchronize_session=False)
    stale_slot_ids = [slot.id for slot in stale_same_key_slots if slot.field_instance_id not in unlocked_field_instance_ids]
    if stale_slot_ids:
        removed_slots += db.query(GameSlot).filter(GameSlot.id.in_(stale_slot_ids)).delete(synchronize_session=False)
    stale_wave_ids = [wave_id for (wave_id,) in db.query(TurfWave.id).filter(TurfWave.hosting_availability_id == availability.id).all()]
    if stale_wave_ids:
        referenced_wave_ids = {wave_id for (wave_id,) in db.query(GameSlot.turf_wave_id).filter(GameSlot.turf_wave_id.in_(stale_wave_ids)).distinct().all() if wave_id}
        removable_wave_ids = [wave_id for wave_id in stale_wave_ids if wave_id not in referenced_wave_ids]
        if removable_wave_ids:
            db.query(TurfWave).filter(TurfWave.id.in_(removable_wave_ids)).delete(synchronize_session=False)

    if not availability.is_available or not _availability_allows_generated_slots(db, availability):
        return {
            'total_slots_evaluated': len(existing_slots),
            'slots_regenerated': removed_slots,
            'locked_slots_skipped': len(locked_slots),
            'new_slots_created': 0,
            'obsolete_unused_slots_removed': removed_slots,
        }
    option = availability.field_configuration_option
    host_configuration = availability.selected_configuration
    field = availability.field
    host = availability.host_location or (field.host_location if field else None) or (availability.physical_field_area.host_location if availability.physical_field_area else None)
    surface_type = (host.surface_type if host else None) or 'GRASS_FIELD'
    templates: list[tuple[str, str]] = []
    turf_layout_blocks: list[tuple[str, int]] = []
    if surface_type == 'TURF_STADIUM':
        active_configs = []
        if host:
            _ensure_approved_turf_configurations(db, host)
            db.flush()
            active_configs = db.query(HostLocationConfiguration).filter(
                HostLocationConfiguration.host_location_id == host.id,
                HostLocationConfiguration.is_active.is_(True),
            ).all()
        active_configuration_names = _available_turf_configuration_names(active_configs)
        selected_configuration = _select_best_turf_configuration(db, availability, host) if host else None
        use_dynamic_layouts = bool(
            host
            and availability.auto_select_turf_layout
            and not availability.lock_selected_layout
            and active_configuration_names
        )
        if use_dynamic_layouts:
            demand_counts = _normalized_demand_counts(demand_counts_override) if demand_counts_override is not None else _turf_demand_counts_for_date(db, host, slot_date)
            total_hours = _hours_between(availability.start_time, availability.end_time, slot_date)
            turf_layout_blocks = _plan_turf_layout_blocks(demand_counts, total_hours, active_configuration_names)
        if turf_layout_blocks:
            first_layout = turf_layout_blocks[0][0]
            selected_configuration = next((config for config in active_configs if _normalize_configuration_name(config.configuration_name) == first_layout), selected_configuration)
        if selected_configuration and availability.selected_configuration_id != selected_configuration.id:
            availability.selected_configuration_id = selected_configuration.id
            host_configuration = selected_configuration
            logger.info('Selected turf layout %s for availability_id=%s host_location_id=%s', selected_configuration.configuration_name, availability.id, host_location_id)
        if turf_layout_blocks:
            templates = [
                (f'{layout_name} Block {block_index} {field_name}', field_type)
                for block_index, (layout_name, _hours) in enumerate(turf_layout_blocks, start=1)
                for field_name, field_type in _configuration_field_templates(layout_name)
            ]
        elif not host_configuration or not host_configuration.is_active:
            templates = []
        else:
            configuration_name = host_configuration.configuration_name
            templates = _configuration_field_templates(configuration_name)
    elif host and surface_type == 'GRASS_FIELD' and availability.host_location_id:
        forecast = _grass_setup_forecast_for_availability(db, host, availability, demand_counts_override)
        templates = _grass_field_templates_from_forecast(forecast['forecast'])
    elif field:
        field_size = _normalize_field_size(field.layout_type)
        if field.is_active and field_size:
            templates = [(field.name, field_size)]
    else:
        configuration_name = availability.layout_type or (option.name if option else None)
        if option and not option.is_active:
            templates = []
        else:
            templates = _configuration_field_templates(configuration_name, option)
    if not templates:
        return {
            'total_slots_evaluated': len(existing_slots),
            'slots_regenerated': removed_slots,
            'locked_slots_skipped': len(locked_slots),
            'new_slots_created': 0,
            'obsolete_unused_slots_removed': removed_slots,
        }
    instances: list[FieldInstance] = []
    created_slots = 0
    start_dt = datetime.combine(slot_date, availability.start_time)
    end_dt = datetime.combine(slot_date, availability.end_time)
    if turf_layout_blocks:
        block_start_dt = start_dt
        for block_index, (layout_name, block_hours) in enumerate(turf_layout_blocks, start=1):
            normalized_layout = _normalize_configuration_name(layout_name)
            metadata = _turf_configuration_metadata(normalized_layout)
            if not metadata or normalized_layout not in TURF_APPROVED_LAYOUT_CODES or int(metadata.get('space_used_yards') or 0) > TURF_FOOTPRINT_YARDS:
                logger.warning('Skipping unsupported turf wave layout %s for availability_id=%s', layout_name, availability.id)
                continue
            block_end_dt = min(block_start_dt + timedelta(hours=block_hours), end_dt)
            wave = TurfWave(
                host_location_id=host_location_id,
                hosting_availability_id=availability.id,
                week_id=availability.week_id,
                host_date=slot_date,
                sequence_number=block_index,
                wave_intent=_turf_wave_intent_for_layout(normalized_layout),
                preferred_layout_code=normalized_layout,
                start_time=block_start_dt.time(),
                end_time=block_end_dt.time(),
                transition_before_minutes=0,
                transition_after_minutes=0,
                notes='Generated from turf demand and approved slot-level layout rules.',
            )
            db.add(wave)
            db.flush()
            block_instances: list[FieldInstance] = []
            for field_name, field_type in _configuration_field_templates(normalized_layout):
                instance = FieldInstance(
                    host_location_id=host_location_id,
                    hosting_availability_id=availability.id,
                    instance_date=slot_date,
                    field_name=f'Wave {block_index} {normalized_layout} {field_name}',
                    field_type=field_type,
                    is_active=True,
                )
                block_instances.append(instance)
                instances.append(instance)
                db.add(instance)
            db.flush()
            slot_start_dt = block_start_dt
            while slot_start_dt < block_end_dt:
                next_dt = min(slot_start_dt + timedelta(hours=1), block_end_dt)
                slot_counts = {size: sum(1 for instance in block_instances if _normalize_field_size(instance.field_type) == size) for size in FIELD_SIZE_ORDER}
                if not _is_approved_turf_slot_counts(slot_counts):
                    logger.warning('Skipping unsupported turf slot-level configuration %s for wave_id=%s', slot_counts, wave.id)
                    slot_start_dt = next_dt
                    continue
                for instance in block_instances:
                    db.add(GameSlot(field_instance_id=instance.id, host_location_id=host_location_id, season_id=availability.season_id, week_id=availability.week_id, slot_date=slot_date, start_time=slot_start_dt.time(), end_time=next_dt.time(), field_type=instance.field_type, status='OPEN', turf_wave_id=wave.id))
                    created_slots += 1
                slot_start_dt = next_dt
            block_start_dt = block_end_dt
            if block_start_dt >= end_dt:
                break
    else:
        for field_name, field_type in templates:
            instances.append(FieldInstance(host_location_id=host_location_id, hosting_availability_id=availability.id, instance_date=slot_date, field_name=field_name, field_type=field_type, is_active=True))
        for instance in instances:
            db.add(instance)
        db.flush()
        slot_start_dt = start_dt
        while slot_start_dt < end_dt:
            next_dt = min(slot_start_dt + timedelta(hours=1), end_dt)
            for instance in instances:
                db.add(GameSlot(field_instance_id=instance.id, host_location_id=host_location_id, season_id=availability.season_id, week_id=availability.week_id, slot_date=slot_date, start_time=slot_start_dt.time(), end_time=next_dt.time(), field_type=instance.field_type, status='OPEN'))
                created_slots += 1
            slot_start_dt = next_dt
    logger.info('Generated %s field instances for availability_id=%s host_location_id=%s', len(instances), availability.id, host_location_id)
    logger.info('Generated %s game slots for availability_id=%s host_location_id=%s', created_slots, availability.id, host_location_id)
    return {
        'total_slots_evaluated': len(existing_slots),
        'slots_regenerated': removed_slots,
        'locked_slots_skipped': len(locked_slots),
        'new_slots_created': created_slots,
        'obsolete_unused_slots_removed': removed_slots,
    }


def _regenerate_hosting_day(
    db: Session,
    availability_rows: list[HostingAvailability],
    host: HostLocation,
    demand_by_availability_id: dict[uuid.UUID, dict[str, int]] | None = None,
) -> HostingGenerationLocationResult:
    result = HostingGenerationLocationResult(
        host_location_id=host.id,
        host_location_name=host.name,
        field_instances_created=0,
        slots_created=0,
        errors=[],
    )
    if not availability_rows:
        result.skipped_reason = 'No hosting availability records found.'
        logger.info('Skipping host location %s (%s): %s', host.name, host.id, result.skipped_reason)
        return result

    for availability in availability_rows:
        try:
            if not availability.host_location_id and not availability.physical_field_area and not availability.field_id:
                msg = 'Hosting setup missing for this location.'
                result.errors.append(msg)
                logger.error('Host %s (%s) availability %s error: %s', host.name, host.id, availability.id, msg)
                continue

            before_instances = db.query(FieldInstance).filter(FieldInstance.hosting_availability_id == availability.id).count()
            before_slots = db.query(GameSlot).join(GameSlot.field_instance).filter(FieldInstance.hosting_availability_id == availability.id).count()
            slot_metrics = _regenerate_generated_slots(db, availability, host.id, (demand_by_availability_id or {}).get(availability.id))
            after_instances = db.query(FieldInstance).filter(FieldInstance.hosting_availability_id == availability.id).count()
            after_slots = db.query(GameSlot).join(GameSlot.field_instance).filter(FieldInstance.hosting_availability_id == availability.id).count()
            result.field_instances_created += max(after_instances, before_instances)
            result.slots_created += max(after_slots, before_slots)
            result.total_slots_evaluated += slot_metrics['total_slots_evaluated']
            result.slots_regenerated += slot_metrics['slots_regenerated']
            result.locked_slots_skipped += slot_metrics['locked_slots_skipped']
            result.new_slots_created += slot_metrics['new_slots_created']
            result.obsolete_unused_slots_removed += slot_metrics['obsolete_unused_slots_removed']
            logger.info('Host %s (%s): availability %s regenerated, field_instances=%s slots=%s', host.name, host.id, availability.id, after_instances, after_slots)
        except HTTPException as exc:
            detail = str(exc.detail)
            if detail not in result.errors:
                result.errors.append(detail)
            result.hard_failures += 1
            logger.error('Host %s (%s): availability %s failed: %s', host.name, host.id, availability.id, detail)
        except Exception as exc:
            detail = str(exc)
            if detail not in result.errors:
                result.errors.append(detail)
            result.hard_failures += 1
            logger.exception('Host %s (%s): availability %s failed unexpectedly: %s', host.name, host.id, availability.id, detail)
    return result



def validate_hour_block(start_time, end_time):
    if end_time <= start_time:
        raise HTTPException(status_code=400, detail="Invalid hourly availability block")
    if (
        start_time.minute != 0
        or start_time.second != 0
        or start_time.microsecond != 0
        or end_time.minute != 0
        or end_time.second != 0
        or end_time.microsecond != 0
    ):
        raise HTTPException(status_code=400, detail="Invalid hourly availability block")
    if end_time.hour - start_time.hour != 1:
        raise HTTPException(status_code=400, detail="Invalid hourly availability block")
    if start_time < time(9, 0) or end_time > time(17, 0):
        raise HTTPException(status_code=400, detail="Invalid hourly availability block")

def paginate(query, page: int, page_size: int):
    total = query.count(); items = query.offset((page - 1) * page_size).limit(page_size).all()
    return PagedResponse(items=items, total=total, page=page, page_size=page_size)



def _host_location_dependency_summary(db: Session, host_location_id: uuid.UUID) -> list[tuple[str, int]]:
    field_ids_subquery = db.query(Field.id).filter(Field.host_location_id == host_location_id).subquery()
    area_ids_subquery = db.query(PhysicalFieldArea.id).filter(PhysicalFieldArea.host_location_id == host_location_id).subquery()
    return [
        ('Scheduled Games', db.query(Game).outerjoin(Game.field).filter(or_(Game.host_location_id == host_location_id, Field.host_location_id == host_location_id)).count()),
        ('Generated Slots Assigned to Games', db.query(GameSlot).filter(GameSlot.host_location_id == host_location_id, GameSlot.assigned_game_id.is_not(None)).count()),
        ('Generated Slots Unassigned', db.query(GameSlot).filter(GameSlot.host_location_id == host_location_id, GameSlot.assigned_game_id.is_(None)).count()),
        ('Field Instances', db.query(FieldInstance).filter(FieldInstance.host_location_id == host_location_id).count()),
        ('Hosting Availability', db.query(HostingAvailability).filter((HostingAvailability.host_location_id == host_location_id) | (HostingAvailability.field_id.in_(field_ids_subquery)) | (HostingAvailability.physical_field_area_id.in_(area_ids_subquery))).count()),
        ('Field Configuration Options', db.query(FieldConfigurationOption).filter(FieldConfigurationOption.physical_field_area_id.in_(area_ids_subquery)).count()),
        ('Host Location Configurations', db.query(HostLocationConfiguration).filter(HostLocationConfiguration.host_location_id == host_location_id).count()),
        ('Physical Field Areas', db.query(PhysicalFieldArea).filter(PhysicalFieldArea.host_location_id == host_location_id).count()),
    ]




def _host_location_effective_status(db: Session) -> dict[uuid.UUID, bool]:
    active_area_host_ids = {
        host_id for (host_id,) in db.query(PhysicalFieldArea.host_location_id)
        .filter(PhysicalFieldArea.is_active.is_(True))
        .distinct()
        .all()
    }
    active_field_host_ids = {
        host_id for (host_id,) in db.query(Field.host_location_id)
        .filter(Field.is_active.is_(True))
        .distinct()
        .all()
    }
    configured_host_ids = {
        host_id for (host_id,) in db.query(HostLocationConfiguration.host_location_id)
        .filter(HostLocationConfiguration.is_active.is_(True))
        .distinct()
        .all()
    }
    host_rows = db.query(HostLocation.id, HostLocation.is_active, HostLocation.surface_type).all()
    status: dict[uuid.UUID, bool] = {}
    for host_id, is_active, surface_type in host_rows:
        effective_surface = surface_type or 'GRASS_FIELD'
        if effective_surface == 'TURF_STADIUM':
            has_setup = host_id in configured_host_ids
        else:
            has_setup = host_id in active_field_host_ids or host_id in active_area_host_ids
        status[host_id] = bool(is_active and has_setup)
    return status


def _eligible_host_location_ids(db: Session) -> set[uuid.UUID]:
    status_by_host = _host_location_effective_status(db)
    return {host_id for host_id, is_ready in status_by_host.items() if is_ready}
def _format_delete_blockers(host_location_name: str, dependencies: list[tuple[str, int]]) -> str:
    blockers = [f"{count} {label}" for label, count in dependencies if count > 0]
    if not blockers:
        return ''
    return f"Cannot delete Host Location '{host_location_name}' because " + '; '.join(blockers) + '.'


def _safe_dependency_count(label: str, counter):
    try:
        return label, counter()
    except SQLAlchemyError as exc:
        if isinstance(exc, ProgrammingError) or 'does not exist' in str(exc).lower():
            logger.warning("Dependency count unavailable for %s because table is unavailable: %s", label, exc)
            return label, "Unavailable"
        raise
    except Exception as exc:
        logger.warning("Dependency count unavailable for %s: %s", label, exc)
        return label, "Unavailable"


def _organization_dependency_summary(db: Session, organization_id: uuid.UUID) -> list[tuple[str, int | str]]:
    team_ids_subquery = db.query(Team.id).filter(Team.organization_id == organization_id).subquery()
    host_location_ids_subquery = db.query(HostLocation.id).filter(HostLocation.organization_id == organization_id).subquery()
    field_ids_subquery = db.query(Field.id).filter(Field.host_location_id.in_(host_location_ids_subquery)).subquery()
    area_ids_subquery = db.query(PhysicalFieldArea.id).filter(PhysicalFieldArea.host_location_id.in_(host_location_ids_subquery)).subquery()
    today = date.today()
    return [
        _safe_dependency_count('Host Locations', lambda: db.query(HostLocation).filter(HostLocation.organization_id == organization_id).count()),
        _safe_dependency_count('Hosting Site Field Setups', lambda: db.query(PhysicalFieldArea).filter(PhysicalFieldArea.host_location_id.in_(host_location_ids_subquery)).count()),
        _safe_dependency_count('Field Configuration Options', lambda: db.query(FieldConfigurationOption).filter(FieldConfigurationOption.physical_field_area_id.in_(area_ids_subquery)).count()),
        _safe_dependency_count('Hosting Availability', lambda: db.query(HostingAvailability).filter((HostingAvailability.field_id.in_(field_ids_subquery)) | (HostingAvailability.physical_field_area_id.in_(area_ids_subquery))).count()),
        _safe_dependency_count('Organization Division Participation', lambda: db.query(OrganizationDivisionParticipation).filter(OrganizationDivisionParticipation.organization_id == organization_id).count()),
        _safe_dependency_count('Teams', lambda: db.query(Team).filter(Team.organization_id == organization_id).count()),
        _safe_dependency_count('Future Games', lambda: db.query(Game).filter(and_(Game.game_date >= today, (Game.home_team_id.in_(team_ids_subquery) | Game.away_team_id.in_(team_ids_subquery)))).count()),
        _safe_dependency_count('Published Games', lambda: db.query(Game).join(Game.status).filter(and_(GameStatus.code == 'published', (Game.home_team_id.in_(team_ids_subquery) | Game.away_team_id.in_(team_ids_subquery)))).count()),
    ]




def _organization_delete_inventory(db: Session, organization_id: uuid.UUID) -> dict[str, int]:
    host_location_ids = [host_id for (host_id,) in db.query(HostLocation.id).filter(HostLocation.organization_id == organization_id).all()]
    team_ids = [team_id for (team_id,) in db.query(Team.id).filter(Team.organization_id == organization_id).all()]
    field_ids = [field_id for (field_id,) in db.query(Field.id).filter(Field.host_location_id.in_(host_location_ids)).all()] if host_location_ids else []
    area_ids = [area_id for (area_id,) in db.query(PhysicalFieldArea.id).filter(PhysicalFieldArea.host_location_id.in_(host_location_ids)).all()] if host_location_ids else []
    availability_ids = [availability_id for (availability_id,) in db.query(HostingAvailability.id).filter((HostingAvailability.field_id.in_(field_ids)) | (HostingAvailability.physical_field_area_id.in_(area_ids))).all()] if (field_ids or area_ids) else []
    field_instance_ids = [instance_id for (instance_id,) in db.query(FieldInstance.id).filter(FieldInstance.host_location_id.in_(host_location_ids)).all()] if host_location_ids else []
    game_ids = [game_id for (game_id,) in db.query(Game.id).filter((Game.home_team_id.in_(team_ids)) | (Game.away_team_id.in_(team_ids)) | (Game.field_id.in_(field_ids))).all()] if (team_ids or field_ids) else []
    return {
        'teams': len(team_ids),
        'scheduled_games': len(game_ids),
        'generated_slots': db.query(GameSlot).filter((GameSlot.field_instance_id.in_(field_instance_ids)) | (GameSlot.host_location_id.in_(host_location_ids))).count() if host_location_ids else 0,
        'host_locations': len(host_location_ids),
        'fields': len(field_ids),
        'hosting_availability': len(availability_ids),
        'division_participation': db.query(OrganizationDivisionParticipation).filter(OrganizationDivisionParticipation.organization_id == organization_id).count(),
        'field_instances': len(field_instance_ids),
        'schedule_audit_records': 0,
    }


def _organization_orphan_cleanup(db: Session) -> dict[str, int]:
    stale_slot_assignments = db.query(GameSlot).filter(GameSlot.assigned_game_id.isnot(None), ~GameSlot.assigned_game_id.in_(db.query(Game.id).subquery())).update({'assigned_game_id': None}, synchronize_session=False)
    stale_game_home_team_refs = db.query(Game).filter(~Game.home_team_id.in_(db.query(Team.id).subquery())).delete(synchronize_session=False)
    stale_game_away_team_refs = db.query(Game).filter(~Game.away_team_id.in_(db.query(Team.id).subquery())).delete(synchronize_session=False)
    stale_slots_missing_host_location = db.query(GameSlot).filter(~GameSlot.host_location_id.in_(db.query(HostLocation.id).subquery())).delete(synchronize_session=False)
    return {
        'slot_id_missing_slot': stale_slot_assignments,
        'team_id_missing_team': stale_game_home_team_refs + stale_game_away_team_refs,
        'host_location_id_missing_location': stale_slots_missing_host_location,
    }
def _format_organization_blockers(org_name: str, dependencies: list[tuple[str, int | str]]) -> str:
    blockers = [f"- {count} {label} record{'s' if count != 1 else ''}" for label, count in dependencies if isinstance(count, int) and count > 0]
    if not blockers:
        return ''
    return f"{org_name} cannot be deleted because:\n" + '\n'.join(blockers)


def _organization_dependencies_payload(dependencies: list[tuple[str, int | str]]) -> dict[str, int | str]:
    key_map = {
        'Host Locations': 'host_locations',
        'Hosting Site Field Setups': 'hosting_site_setups',
        'Hosting Availability': 'hosting_availability',
        'Organization Division Participation': 'division_participation',
        'Teams': 'teams',
        'Future Games': 'future_games',
    }
    return {key_map[label]: count for label, count in dependencies if label in key_map}


def _safe_delete_count(label: str, deleter):
    try:
        return deleter(), None
    except Exception as exc:
        if isinstance(exc, ProgrammingError) or 'does not exist' in str(exc).lower():
            logger.warning("Skipping delete for %s because dependency table is unavailable: %s", label, exc)
            return 0, f'{label} table unavailable'
        raise

def _user_payload(user: User) -> dict:
    return {
        'id': user.id, 'email': user.email, 'full_name': user.full_name,
        'role_name': normalize_role_name(user.role.name), 'organization_id': user.organization_id,
    }

@router.post('/auth/login', response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).join(User.role).filter(func.lower(User.email) == payload.email.lower(), User.is_active.is_(True), Role.is_active.is_(True)).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail='Invalid credentials')
    return TokenResponse(access_token=create_access_token(str(user.id)), refresh_token=create_refresh_token(str(user.id)), token_type='bearer').model_dump() | {'user': _user_payload(user)}

@router.post('/auth/refresh', response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    token_data = decode_token(payload.refresh_token, 'refresh')
    user = db.query(User).join(User.role).filter(User.id == uuid.UUID(token_data['sub']), User.is_active.is_(True), Role.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=401, detail='Invalid refresh token')
    return TokenResponse(access_token=create_access_token(str(user.id)), refresh_token=create_refresh_token(str(user.id)), token_type='bearer').model_dump() | {'user': _user_payload(user)}

@router.get('/auth/me')
def me(current_user: User = Depends(get_current_user)):
    return {'user': _user_payload(current_user)}

@router.post('/users', response_model=UserRead, dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    role_name = normalize_role_name(payload.role_name)
    role = db.query(Role).filter(Role.name == role_name, Role.is_active.is_(True)).first()
    if not role: raise HTTPException(400, 'Invalid role')
    if role_name == ROLE_COMMUNITY_ADMIN and not payload.organization_id: raise HTTPException(400, 'Community administrator requires organization_id')
    validate_password_strength(payload.password)
    obj = User(email=payload.email.lower(), full_name=payload.full_name, password_hash=hash_password(payload.password), role_id=role.id, organization_id=payload.organization_id, is_active=payload.is_active)
    db.add(obj); db.commit(); db.refresh(obj)
    return UserRead(id=obj.id, created_at=obj.created_at, updated_at=obj.updated_at, email=obj.email, full_name=obj.full_name, role_name=normalize_role_name(obj.role.name), organization_id=obj.organization_id, is_active=obj.is_active)

@router.post('/organizations', response_model=OrganizationRead, dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def create_organization(payload: OrganizationCreate, db: Session = Depends(get_db)):
    obj = Organization(**payload.model_dump()); db.add(obj); db.commit(); db.refresh(obj); return obj

@router.get('/organizations', response_model=PagedResponse[OrganizationRead], dependencies=[Depends(get_current_user)])
def list_organizations(search: str | None = None, is_active: bool | None = None, page: int = 1, page_size: int = 20, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Organization)
    if is_community_admin(current_user): q = q.filter(Organization.id == current_user.organization_id)
    if search: q = q.filter(func.lower(Organization.name).like(f"%{search.lower()}%"))
    if is_active is not None: q = q.filter(Organization.is_active == is_active)
    return paginate(q.order_by(Organization.name), page, page_size)

@router.put('/organizations/{org_id}', response_model=OrganizationRead, dependencies=[Depends(get_current_user)])
def update_organization(org_id: uuid.UUID, payload: OrganizationCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    o = db.query(Organization).filter(Organization.id == org_id).first()
    if not o: raise HTTPException(404, 'Organization not found')
    enforce_organization_scope(o.id, current_user)
    data = payload.model_dump()
    if is_community_admin(current_user):
        data.pop('is_active', None)
    for k, v in data.items(): setattr(o, k, v)
    db.commit(); db.refresh(o); return o

@router.get('/organizations/{org_id}/delete-check', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def get_organization_delete_check(org_id: uuid.UUID, db: Session = Depends(get_db)):
    o = db.query(Organization).filter(Organization.id == org_id).first()
    if not o: raise HTTPException(404, 'Organization not found')
    try:
        dependencies = _organization_dependency_summary(db, org_id)
    except SQLAlchemyError:
        db.rollback()
        logger.exception('Organization dependency check failed for org_id=%s', org_id)
        raise HTTPException(
            status_code=500,
            detail={
                'error': 'organization_dependency_check_failed',
                'message': 'Unable to check organization dependencies due to a server error.',
            },
        )
    return {
        'organization_id': str(o.id),
        'organization_name': o.name,
        'can_delete': all((isinstance(count, int) and count == 0) for _, count in dependencies),
        'dependencies': [{'label': label, 'count': count} for label, count in dependencies],
    }

@router.delete('/organizations/{org_id}', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def delete_organization(org_id: uuid.UUID, force: bool = Query(False), dry_run: bool = Query(False), db: Session = Depends(get_db)):
    # `force` retained for backwards compatibility; centralized cleanup always runs in deterministic order.
    _ = force
    return cleanup_organization_dependencies(db=db, org_id=org_id, dry_run=dry_run)


@router.get('/admin/debug/org-delete/{org_id}', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def debug_org_delete_inventory(org_id: uuid.UUID, db: Session = Depends(get_db)):
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(404, 'Organization not found')
    inventory = _organization_delete_inventory(db, org_id)
    orphans = _organization_orphan_cleanup(db)
    return {'organization': org.name, **inventory, 'orphans': orphans}


@router.get('/admin/debug/organization/{org_id}/dependencies', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def debug_organization_dependencies(org_id: uuid.UUID, db: Session = Depends(get_db)):
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(404, 'Organization not found')
    host_location_ids = [host_id for (host_id,) in db.query(HostLocation.id).filter(HostLocation.organization_id == org_id).all()]
    team_ids = [team_id for (team_id,) in db.query(Team.id).filter(Team.organization_id == org_id).all()]
    field_ids = [field_id for (field_id,) in db.query(Field.id).filter(Field.host_location_id.in_(host_location_ids)).all()] if host_location_ids else []
    availability_ids = [availability_id for (availability_id,) in db.query(HostingAvailability.id).filter((HostingAvailability.field_id.in_(field_ids)) | (HostingAvailability.physical_field_area_id.in_(db.query(PhysicalFieldArea.id).filter(PhysicalFieldArea.host_location_id.in_(host_location_ids)).subquery()))).all()] if host_location_ids else []
    unresolved = _organization_dependency_summary(db, org_id)
    return {
        'organization_id': str(org.id),
        'organization_name': org.name,
        'teams': len(team_ids),
        'games': db.query(Game).filter((Game.home_team_id.in_(team_ids)) | (Game.away_team_id.in_(team_ids)) | (Game.field_id.in_(field_ids))).count() if (team_ids or field_ids) else 0,
        'slots': db.query(GameSlot).filter((GameSlot.field_instance_id.in_(db.query(FieldInstance.id).filter(FieldInstance.host_location_id.in_(host_location_ids)).subquery())) | (GameSlot.host_location_id.in_(host_location_ids))).count() if host_location_ids else 0,
        'host_locations': len(host_location_ids),
        'fields': len(field_ids),
        'availability': len(availability_ids),
        'division_participation': db.query(OrganizationDivisionParticipation).filter(OrganizationDivisionParticipation.organization_id == org_id).count(),
        'unresolved_references': [{'label': label, 'count': count} for label, count in unresolved if isinstance(count, int) and count > 0],
    }


LEAGUE_DIVISION_SEED = [
    {'name': 'K-1', 'division_group': 'COED', 'sort_order': 1, 'required_field_layout_type': FIELD_SIZE_SMALL, 'is_active': True},
    {'name': '2-3', 'division_group': 'COED', 'sort_order': 2, 'required_field_layout_type': FIELD_SIZE_SMALL, 'is_active': True},
    {'name': '4-5', 'division_group': 'COED', 'sort_order': 3, 'required_field_layout_type': FIELD_SIZE_MEDIUM, 'is_active': True},
    {'name': '6-7', 'division_group': 'COED', 'sort_order': 4, 'required_field_layout_type': FIELD_SIZE_LARGE, 'is_active': True},
    {'name': '8', 'division_group': 'COED', 'sort_order': 5, 'required_field_layout_type': FIELD_SIZE_LARGE, 'is_active': True},
    {'name': 'K-2', 'division_group': 'GIRLS', 'sort_order': 6, 'required_field_layout_type': FIELD_SIZE_SMALL, 'is_active': True},
    {'name': '3-5', 'division_group': 'GIRLS', 'sort_order': 7, 'required_field_layout_type': FIELD_SIZE_MEDIUM, 'is_active': True},
    {'name': '6-8', 'division_group': 'GIRLS', 'sort_order': 8, 'required_field_layout_type': FIELD_SIZE_LARGE, 'is_active': True},
]

COED_DIVISION_RENAMES = {
    'K/1st': 'K-1',
    '2nd/3rd': '2-3',
    '4th/5th': '4-5',
    '6th/7th': '6-7',
    '8th': '8',
}

OLD_GIRLS_DIVISION_NAMES = {'K/1st', '2nd/3rd', '4th/5th', '6th/7th/8th'}


def ensure_league_defined_divisions(db: Session) -> None:
    changed = False

    for old_name, new_name in COED_DIVISION_RENAMES.items():
        existing_old = db.query(Division).filter(Division.division_group == 'COED', Division.name == old_name).first()
        existing_new = db.query(Division).filter(Division.division_group == 'COED', Division.name == new_name).first()
        if existing_old and not existing_new:
            existing_old.name = new_name
            changed = True

    for old_name in OLD_GIRLS_DIVISION_NAMES:
        old_girls = db.query(Division).filter(Division.division_group == 'GIRLS', Division.name == old_name).first()
        if old_girls and old_girls.is_active:
            old_girls.is_active = False
            changed = True

    for item in LEAGUE_DIVISION_SEED:
        existing = db.query(Division).filter(
            Division.division_group == item['division_group'],
            Division.name == item['name'],
        ).first()
        if existing:
            if (
                existing.sort_order != item['sort_order']
                or existing.required_field_layout_type != item['required_field_layout_type']
                or existing.is_active != item['is_active']
            ):
                existing.sort_order = item['sort_order']
                existing.required_field_layout_type = item['required_field_layout_type']
                existing.is_active = item['is_active']
                changed = True
            continue
        db.add(Division(**item))
        changed = True
    if changed:
        db.commit()







def _field_size_sequence_rank(size: str | None) -> int:
    return {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 1, FIELD_SIZE_LARGE: 2}.get(_normalize_field_size(size) or '', 99)


def _scheduled_game_counts_by_host_community(db: Session, season_id: uuid.UUID | None = None, up_to_date: date | None = None) -> dict[uuid.UUID, int]:
    query = db.query(HostLocation.organization_id, func.count(Game.id)).select_from(Game).join(GameSlot, GameSlot.assigned_game_id == Game.id).join(
        HostLocation, HostLocation.id == GameSlot.host_location_id
    ).join(Game.status).filter(
        GameStatus.code == 'SCHEDULED',
        GameStatus.is_active.is_(True),
        HostLocation.organization_id.isnot(None),
    )
    if season_id:
        query = query.filter(Game.season_id == season_id)
    if up_to_date:
        query = query.filter(Game.game_date <= up_to_date)
    return {org_id: int(count or 0) for org_id, count in query.group_by(HostLocation.organization_id).all() if org_id}


def _hosting_equity_status(delta: float, expected_games_hosted: float) -> str:
    tolerance = abs(expected_games_hosted) * 0.10
    if expected_games_hosted <= 0:
        tolerance = 0.0
    if delta < -tolerance:
        return 'Underused'
    if delta > tolerance:
        return 'Overused'
    return 'Balanced'


def _hosting_share_warning_status(delta: float, expected_games_hosted: float) -> str | None:
    if expected_games_hosted <= 0:
        return None
    if delta > expected_games_hosted * 0.25:
        return 'above'
    if delta < -(expected_games_hosted * 0.25):
        return 'below'
    return None


def _scheduled_host_weeks_by_community(db: Session, season_id: uuid.UUID | None = None, up_to_date: date | None = None) -> dict[uuid.UUID, set[date]]:
    query = db.query(HostLocation.organization_id, GameSlot.slot_date).select_from(Game).join(
        GameSlot, GameSlot.assigned_game_id == Game.id
    ).join(HostLocation, HostLocation.id == GameSlot.host_location_id).join(Game.status).filter(
        GameStatus.code == 'SCHEDULED',
        GameStatus.is_active.is_(True),
        HostLocation.organization_id.isnot(None),
        GameSlot.slot_date.isnot(None),
    )
    if season_id:
        query = query.filter(Game.season_id == season_id)
    if up_to_date:
        query = query.filter(GameSlot.slot_date < up_to_date)
    result: dict[uuid.UUID, set[date]] = {}
    for org_id, slot_date in query.distinct().all():
        if org_id and slot_date:
            result.setdefault(org_id, set()).add(slot_date)
    return result


def _consecutive_host_count_before_date(host_dates: set[date], target_date: date | None) -> int:
    if not target_date or not host_dates:
        return 0
    count = 0
    cursor = target_date - timedelta(days=7)
    while cursor in host_dates:
        count += 1
        cursor = cursor - timedelta(days=7)
    return count


def _last_hosted_week_label(host_dates: set[date], weeks_by_date: dict[date, int]) -> str | None:
    if not host_dates:
        return None
    last_date = max(host_dates)
    week_number = weeks_by_date.get(last_date)
    return f'Week {week_number}' if week_number is not None else str(last_date)


def _days_since_last_hosted(host_dates: set[date], target_date: date | None) -> int:
    if not target_date or not host_dates:
        return 999_999
    previous_dates = [host_date for host_date in host_dates if host_date < target_date]
    if not previous_dates:
        return 999_999
    return (target_date - max(previous_dates)).days


def _field_size_blocks_from_slots(slots: list[GameSlot]) -> list[str]:
    ordered = sorted(slots, key=lambda slot: (slot.start_time, _field_size_sequence_rank(slot.field_type), str(slot.field_instance_id)))
    blocks: list[str] = []
    current_size: str | None = None
    block_start = None
    block_end = None
    for slot in ordered:
        slot_size = _normalize_field_size(slot.field_type) or str(slot.field_type or '')
        if current_size != slot_size:
            if current_size:
                blocks.append(f'{current_size} {block_start}-{block_end}')
            current_size = slot_size
            block_start = slot.start_time
        block_end = slot.end_time
    if current_size:
        blocks.append(f'{current_size} {block_start}-{block_end}')
    return blocks


def _build_turf_wave_plan_for_site(db: Session, host: HostLocation, host_date: date) -> list[ScheduleReadinessTurfWaveRow]:
    waves = db.query(TurfWave).filter(
        TurfWave.host_location_id == host.id,
        TurfWave.host_date == host_date,
    ).order_by(TurfWave.sequence_number, TurfWave.start_time).all()
    if not waves:
        return []

    unscheduled_demand = {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0}
    unscheduled_rows = db.query(Game, Division).join(Team, Game.home_team_id == Team.id).join(Division, Team.division_id == Division.id).outerjoin(
        GameSlot, GameSlot.assigned_game_id == Game.id
    ).filter(
        Game.game_date == host_date,
        GameSlot.id.is_(None),
    ).all()
    for _game, division in unscheduled_rows:
        required = _required_field_type_for_division(division)
        if required in unscheduled_demand:
            unscheduled_demand[required] += 1

    result: list[ScheduleReadinessTurfWaveRow] = []
    saw_large_wave = False
    for wave in waves:
        wave_slots = db.query(GameSlot).join(GameSlot.field_instance).filter(
            GameSlot.turf_wave_id == wave.id,
        ).order_by(GameSlot.start_time, FieldInstance.field_name).all()
        slots_by_time: dict[tuple[object, object], list[GameSlot]] = {}
        for slot in wave_slots:
            slots_by_time.setdefault((slot.start_time, slot.end_time), []).append(slot)
        slot_rows: list[ScheduleReadinessTurfWaveSlotRow] = []
        wave_warnings: list[str] = []
        assigned_count = 0
        for (slot_start, slot_end), slots in sorted(slots_by_time.items(), key=lambda item: item[0]):
            slot_counts = _turf_slot_counts_from_slots(slots)
            assigned_counts = _turf_slot_counts_from_slots(slots, assigned_only=True)
            assigned_count += sum(assigned_counts.values())
            config_code = _turf_layout_code_for_counts(slot_counts)
            unused_capacity = _turf_unused_compatible_capacity(slot_counts, assigned_counts)
            slot_warnings: list[str] = []
            rejected: list[str] = []
            if not config_code:
                slot_warnings.append('unsupported slot-level configuration')
                rejected.append('Generated field combination is not an approved turf configuration.')
            else:
                metadata = _turf_configuration_metadata(config_code)
                if metadata and int(metadata.get('space_used_yards') or 0) > TURF_FOOTPRINT_YARDS:
                    slot_warnings.append('physical turf footprint violation')
                    rejected.append('Generated field combination exceeds the 120-yard turf footprint.')
            for size in FIELD_SIZE_ORDER:
                if unused_capacity.get(size, 0) > 0 and unscheduled_demand.get(size, 0) > 0:
                    slot_warnings.append(f'compatible {size.lower()} capacity left unused while unscheduled games remain')
            if slot_warnings:
                wave_warnings.extend(slot_warnings)
            assigned_games = []
            for slot in slots:
                if slot.assigned_game:
                    assigned_games.append(f'{slot.field_type}: {slot.assigned_game.id}')
            inserted = []
            preferred = _turf_configuration_metadata(wave.preferred_layout_code)
            if preferred and config_code and config_code != wave.preferred_layout_code and any(assigned_counts.values()):
                inserted.append(f'Slot optimized to {config_code} within {wave.preferred_layout_code} wave intent.')
            slot_rows.append(ScheduleReadinessTurfWaveSlotRow(
                start_time=slot_start,
                end_time=slot_end,
                slot_level_configuration=config_code,
                field_instances_generated=[slot.field_instance.field_name for slot in slots if slot.field_instance],
                games_assigned_by_field_size=assigned_counts,
                unused_compatible_capacity=unused_capacity,
                inserted_through_slot_level_optimization=inserted,
                rejected_assignments=rejected,
                warnings=sorted(set(slot_warnings)),
            ))
        if wave.wave_intent == TURF_WAVE_INTENT_LARGE:
            saw_large_wave = True
        elif saw_large_wave and wave.wave_intent == TURF_WAVE_INTENT_SMALL_MEDIUM:
            wave_warnings.append('Small/Medium wave starts after Large wave; avoid switching back after Large games begin.')
        if len(waves) > 2:
            wave_warnings.append('excessive turf waves')
        if wave.wave_intent == TURF_WAVE_INTENT_CUSTOM and wave.preferred_layout_code in {'THREE_SMALL', 'TWO_MEDIUM'}:
            wave_warnings.append('Small/Medium games separated when mixed layout would work')
        result.append(ScheduleReadinessTurfWaveRow(
            host_location_id=host.id,
            host_location_name=host.name,
            host_date=host_date,
            sequence_number=wave.sequence_number,
            wave_intent=wave.wave_intent,
            preferred_layout_code=wave.preferred_layout_code,
            start_time=wave.start_time,
            end_time=wave.end_time,
            transition_before_minutes=wave.transition_before_minutes,
            transition_after_minutes=wave.transition_after_minutes,
            generated_field_instances=sorted({slot.field_instance.field_name for slot in wave_slots if slot.field_instance}),
            assigned_games=assigned_count,
            notes=wave.notes,
            slot_level_configurations=slot_rows,
            warnings=sorted(set(wave_warnings)),
        ))
    return result


def _build_host_date_readiness(db: Session) -> list[ScheduleReadinessHostDateRow]:
    week_by_date = {_week_game_date(week): week for week in db.query(Week).all() if _week_game_date(week)}
    slot_rows = (
        db.query(GameSlot, FieldInstance, HostLocation, HostingAvailability)
        .join(GameSlot.field_instance)
        .join(GameSlot.host_location)
        .outerjoin(HostingAvailability, FieldInstance.hosting_availability_id == HostingAvailability.id)
        .order_by(GameSlot.slot_date, HostLocation.name, GameSlot.start_time)
        .all()
    )
    games_by_slot_id = {slot_id: count for slot_id, count in db.query(GameSlot.id, func.count(Game.id)).outerjoin(Game, GameSlot.assigned_game_id == Game.id).group_by(GameSlot.id).all()}
    divisions_by_site_date: dict[tuple[date, uuid.UUID], set[str]] = {}
    incompatible_by_site_date: dict[tuple[date, uuid.UUID], int] = {}
    assigned_games = (
        db.query(Game, GameSlot, HostLocation, Division)
        .join(GameSlot, GameSlot.assigned_game_id == Game.id)
        .join(HostLocation, GameSlot.host_location_id == HostLocation.id)
        .join(Team, Game.home_team_id == Team.id)
        .join(Division, Team.division_id == Division.id)
        .all()
    )
    for game, slot, host, division in assigned_games:
        key = (game.game_date, host.id)
        divisions_by_site_date.setdefault(key, set()).add(f'{division.division_group.title()} {division.name}' if division.division_group else division.name)
        if slot.field_type != _required_field_type_for_division(division):
            incompatible_by_site_date[key] = incompatible_by_site_date.get(key, 0) + 1

    unscheduled_games_by_date: dict[date, int] = {}
    for game_date, count in db.query(Game.game_date, func.count(Game.id)).outerjoin(GameSlot, GameSlot.assigned_game_id == Game.id).filter(GameSlot.id.is_(None), Game.game_date.is_not(None)).group_by(Game.game_date).all():
        unscheduled_games_by_date[game_date] = int(count or 0)

    site_data: dict[tuple[date, uuid.UUID], dict] = {}
    date_data: dict[date, dict] = {}
    for slot, field_instance, host, availability in slot_rows:
        date_key = slot.slot_date
        site_key = (date_key, host.id)
        site = site_data.setdefault(site_key, {
            'host': host,
            'availability': availability,
            'field_names': set(),
            'field_counts': {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0},
            'slot_counts': {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0},
            'generated_slots': 0,
            'games_assigned': 0,
            'layouts': set(),
        })
        site['field_names'].add(field_instance.field_name)
        if slot.field_type in site['slot_counts']:
            site['slot_counts'][slot.field_type] += 1
        site['generated_slots'] += 1
        site['games_assigned'] += int(games_by_slot_id.get(slot.id, 0) or 0)
        if field_instance.field_type in site['field_counts'] and field_instance.field_name not in site.get('counted_fields', set()):
            site.setdefault('counted_fields', set()).add(field_instance.field_name)
            site['field_counts'][field_instance.field_type] += 1
        if availability and availability.selected_configuration:
            site['layouts'].add(availability.selected_configuration.configuration_name)
        date_row = date_data.setdefault(date_key, {'generated_slots': 0, 'games_assigned': 0, 'field_counts': {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0}, 'site_ids': set()})
        date_row['generated_slots'] += 1
        date_row['games_assigned'] += int(games_by_slot_id.get(slot.id, 0) or 0)
        date_row['site_ids'].add(host.id)

    division_sites: dict[tuple[date, str], set[uuid.UUID]] = {}
    for (date_key, host_id), divisions in divisions_by_site_date.items():
        for division_label in divisions:
            division_sites.setdefault((date_key, division_label), set()).add(host_id)

    result: list[ScheduleReadinessHostDateRow] = []
    for host_date in sorted(date_data.keys()):
        day = date_data[host_date]
        host_sites: list[ScheduleReadinessHostSiteRow] = []
        day_warnings: list[str] = []
        for host_id in sorted(day['site_ids'], key=lambda value: str(value)):
            site = site_data[(host_date, host_id)]
            host = site['host']
            availability = site['availability']
            warnings: list[str] = []
            open_slots = site['generated_slots'] - site['games_assigned']
            if open_slots > 0:
                warnings.append(f'{open_slots} unused generated slot(s).')
            if len(site['layouts']) > 1:
                warnings.append('Multiple turf layouts appear on this host date; avoid mid-day layout changes unless admin override is enabled.')
            if incompatible_by_site_date.get((host_date, host_id), 0):
                warnings.append(f"{incompatible_by_site_date[(host_date, host_id)]} incompatible field-size assignment(s).")
            if availability and availability.lock_selected_layout and unscheduled_games_by_date.get(host_date, 0):
                warnings.append('Locked turf layout may be preventing additional games from being assigned.')
            divisions_supported = sorted(divisions_by_site_date.get((host_date, host_id), set()))
            split_divisions = [label for label in divisions_supported if len(division_sites.get((host_date, label), set())) > 1]
            if split_divisions:
                warnings.append(f"Split division(s) across host sites: {', '.join(split_divisions)}.")
            selected_layout = ', '.join(sorted(site['layouts'])) if site['layouts'] else None
            is_grass_site = (host.surface_type or 'GRASS_FIELD') != 'TURF_STADIUM'
            turf_wave_plan = [] if is_grass_site else _build_turf_wave_plan_for_site(db, host, host_date)
            grass_forecast = None
            if is_grass_site and availability:
                grass_forecast = _grass_setup_forecast_for_availability(db, host, availability)
                warnings.extend(grass_forecast['warnings'])
            for wave in turf_wave_plan:
                warnings.extend(wave.warnings)
            forecast_counts = grass_forecast['forecast'] if grass_forecast else {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0}
            host_sites.append(ScheduleReadinessHostSiteRow(
                host_location_id=host.id,
                host_location_name=host.name,
                community_id=host.organization_id,
                community_name=host.organization.name if host.organization else None,
                surface_type=host.surface_type or 'GRASS_FIELD',
                selected_turf_layout=selected_layout if not is_grass_site else None,
                grass_field_capacity=sum(site['field_counts'].values()) if is_grass_site else 0,
                small_fields_to_line=int(forecast_counts.get(FIELD_SIZE_SMALL, 0) or 0) if is_grass_site else 0,
                medium_fields_to_line=int(forecast_counts.get(FIELD_SIZE_MEDIUM, 0) or 0) if is_grass_site else 0,
                large_fields_to_line=int(forecast_counts.get(FIELD_SIZE_LARGE, 0) or 0) if is_grass_site else 0,
                total_fields_to_line=sum(int(forecast_counts.get(size, 0) or 0) for size in FIELD_SIZE_ORDER) if is_grass_site else 0,
                capacity_status=grass_forecast['capacity_status'] if grass_forecast else ('not_applicable' if not is_grass_site else 'unknown'),
                active_fields=sorted(site['field_names']) if is_grass_site else [],
                field_counts_by_size=site['field_counts'],
                total_field_capacity_by_size=site['field_counts'],
                generated_slots=site['generated_slots'],
                games_assigned=site['games_assigned'],
                games_assigned_by_location=site['games_assigned'],
                games_unscheduled=unscheduled_games_by_date.get(host_date, 0),
                divisions_supported=divisions_supported,
                warnings=warnings,
                auto_select_turf_layout=bool(getattr(availability, 'auto_select_turf_layout', True)) if availability else True,
                lock_selected_layout=bool(getattr(availability, 'lock_selected_layout', False)) if availability else False,
                turf_wave_plan=turf_wave_plan,
            ))
            day_warnings.extend(warnings)
        communities = sorted({site_data[(host_date, hid)]['host'].organization.name for hid in day['site_ids'] if site_data[(host_date, hid)]['host'].organization})
        community_ids = sorted({site_data[(host_date, hid)]['host'].organization_id for hid in day['site_ids']}, key=lambda value: str(value))
        week = week_by_date.get(host_date)
        result.append(ScheduleReadinessHostDateRow(
            host_date=host_date,
            date_type=_week_date_type(week),
            label=_week_label(week),
            community_id=community_ids[0] if len(community_ids) == 1 else None,
            community_name=communities[0] if len(communities) == 1 else ', '.join(communities),
            selected_host_locations=sorted(site_data[(host_date, hid)]['host'].name for hid in day['site_ids']),
            host_sites_available=len(day['site_ids']),
            generated_slots=day['generated_slots'],
            games_assigned=day['games_assigned'],
            games_unscheduled=unscheduled_games_by_date.get(host_date, 0),
            field_counts_by_size={size: sum(site_data[(host_date, hid)]['field_counts'][size] for hid in day['site_ids']) for size in FIELD_SIZE_ORDER},
            host_sites=host_sites,
            warnings=sorted(set(day_warnings)),
        ))
    return result



def _build_hosting_balance_readiness(db: Session) -> list[dict[str, object]]:
    availability_rows = db.query(HostingAvailability.available_date, HostLocation.organization_id, Organization.name).join(
        HostLocation, HostingAvailability.host_location_id == HostLocation.id
    ).join(Organization, HostLocation.organization_id == Organization.id).filter(
        HostingAvailability.is_available.is_(True),
        HostingAvailability.active.is_(True),
        HostLocation.is_active.is_(True),
        Organization.is_active.is_(True),
    ).all()
    available_dates_by_org: dict[uuid.UUID, set[date]] = {}
    org_names: dict[uuid.UUID, str] = {}
    for available_date, org_id, org_name in availability_rows:
        if not org_id:
            continue
        available_dates_by_org.setdefault(org_id, set()).add(available_date)
        org_names[org_id] = org_name or 'Unknown community'
    if not available_dates_by_org:
        return []
    hosted_to_date = _scheduled_game_counts_by_host_community(db)
    host_weeks_by_org = _scheduled_host_weeks_by_community(db)
    weeks_by_date = {_week_game_date(week): week.week_number for week in db.query(Week).all() if _week_game_date(week)}
    host_locations_by_org: dict[uuid.UUID, list[dict[str, str]]] = {}
    for host_id, org_id, host_name in db.query(HostLocation.id, HostLocation.organization_id, HostLocation.name).filter(
        HostLocation.organization_id.in_(list(available_dates_by_org.keys())),
        HostLocation.is_active.is_(True),
    ).all():
        if org_id:
            host_locations_by_org.setdefault(org_id, []).append({
                'host_location_id': str(host_id),
                'host_location': host_name or str(host_id),
            })
    for host_rows in host_locations_by_org.values():
        host_rows.sort(key=lambda row: row['host_location'])
    hosted_this_week: dict[uuid.UUID, int] = {}
    active_host_dates = sorted({available_date for dates in available_dates_by_org.values() for available_date in dates})
    this_week_query = db.query(HostLocation.organization_id, func.count(Game.id)).select_from(Game).join(
        GameSlot, GameSlot.assigned_game_id == Game.id
    ).join(HostLocation, HostLocation.id == GameSlot.host_location_id).join(Game.status).filter(
        GameStatus.code == 'SCHEDULED',
        GameStatus.is_active.is_(True),
        HostLocation.organization_id.in_(list(available_dates_by_org.keys())),
    )
    if active_host_dates:
        this_week_query = this_week_query.filter(Game.game_date.in_(active_host_dates))
    for org_id, count in this_week_query.group_by(HostLocation.organization_id).all():
        hosted_this_week[org_id] = int(count or 0)
    expected_share = (sum(hosted_to_date.values()) / max(len(available_dates_by_org), 1)) if available_dates_by_org else 0.0
    compatible_unused_capacity_by_org: dict[uuid.UUID, int] = {org_id: 0 for org_id in available_dates_by_org}
    unused_capacity_rows = db.query(HostLocation.organization_id, func.count(GameSlot.id)).select_from(GameSlot).join(
        HostLocation, HostLocation.id == GameSlot.host_location_id
    ).filter(
        GameSlot.status == 'OPEN',
        GameSlot.assigned_game_id.is_(None),
        HostLocation.organization_id.in_(list(available_dates_by_org.keys())),
    ).group_by(HostLocation.organization_id).all()
    for org_id, count in unused_capacity_rows:
        if org_id:
            compatible_unused_capacity_by_org[org_id] = int(count or 0)
    projected_gap = (max((hosted_to_date.get(org_id, 0) for org_id in available_dates_by_org), default=0) - min((hosted_to_date.get(org_id, 0) for org_id in available_dates_by_org), default=0)) if available_dates_by_org else 0

    def _readiness_equity_reason(org_id: uuid.UUID, delta: float) -> str | None:
        if projected_gap > 10:
            if delta > 0:
                return 'Overused relative to season target; diagnostics indicate lower-hosted communities need compatible selected capacity in future weeks.'
            if delta < 0 and compatible_unused_capacity_by_org.get(org_id, 0) <= 0:
                return 'Underused relative to season target; no compatible unused generated capacity is currently available.'
            if delta < 0:
                return 'Underused relative to season target; use this community when host-week rotation selects it and rules allow.'
            return 'League-wide community game gap exceeds 10; review host-week selection and capacity constraints.'
        if delta > 0:
            return 'Above season target but within the 10-game target range.'
        if delta < 0:
            return 'Below season target but within the 10-game target range.'
        return 'On season target.'

    rows = []
    streak_target_date = (max(active_host_dates) + timedelta(days=7)) if active_host_dates else date.today()
    ordered_org_ids = sorted(available_dates_by_org, key=lambda org_id: (
        len(host_weeks_by_org.get(org_id, set())),
        -_days_since_last_hosted(host_weeks_by_org.get(org_id, set()), streak_target_date),
        int(hosted_to_date.get(org_id, 0) or 0),
        org_names.get(org_id, ''),
    ))
    rotation_rank_by_org = {org_id: index for index, org_id in enumerate(ordered_org_ids, start=1)}
    for org_id in sorted(available_dates_by_org, key=lambda value: org_names.get(value, '')):
        hosted = int(hosted_to_date.get(org_id, 0) or 0)
        host_dates = host_weeks_by_org.get(org_id, set())
        delta = hosted - expected_share
        available_dates = sorted(available_dates_by_org.get(org_id, set()))
        selected_dates = sorted(host_dates)
        rows.append({
            'community_id': org_id,
            'community': org_names.get(org_id, 'Unknown community'),
            'host_locations': host_locations_by_org.get(org_id, []),
            'available_host_dates': len(available_dates),
            'available_host_weeks': len(available_dates),
            'available_weeks': [f"Week {weeks_by_date.get(host_date)}" if weeks_by_date.get(host_date) is not None else str(host_date) for host_date in available_dates],
            'selected_weeks': [f"Week {weeks_by_date.get(host_date)}" if weeks_by_date.get(host_date) is not None else str(host_date) for host_date in selected_dates],
            'host_weeks_used': len(host_dates),
            'games_hosted_this_week': int(hosted_this_week.get(org_id, 0) or 0),
            'games_hosted_season_to_date': hosted,
            'games_hosted': hosted,
            'average_games_per_host_week': round(hosted / max(len(host_dates), 1), 2) if host_dates else 0.0,
            'expected_host_share': round(expected_share, 2),
            'expected_games_hosted': round(expected_share, 2),
            'season_target_games': round(expected_share, 2),
            'difference_from_target': round(delta, 2),
            'compatible_unused_capacity': compatible_unused_capacity_by_org.get(org_id, 0),
            'reason_if_overused_or_underused': _readiness_equity_reason(org_id, delta),
            'hosting_delta': round(delta, 2),
            'last_hosted_week': _last_hosted_week_label(host_dates, weeks_by_date),
            'consecutive_host_count': _consecutive_host_count_before_date(host_dates, streak_target_date) if host_dates else 0,
            'rotation_rank': rotation_rank_by_org.get(org_id),
            'diagnostic_label': 'Community Hosting Equity Summary',
            'status': _hosting_equity_status(delta, expected_share),
        })
    return rows


def _build_hosting_rotation_readiness(db: Session) -> list[dict[str, object]]:
    availability_rows = db.query(HostingAvailability.available_date, HostLocation.organization_id, Organization.name).join(
        HostLocation, HostingAvailability.host_location_id == HostLocation.id
    ).join(Organization, HostLocation.organization_id == Organization.id).filter(
        HostingAvailability.is_available.is_(True),
        HostingAvailability.active.is_(True),
        HostLocation.is_active.is_(True),
        Organization.is_active.is_(True),
    ).all()
    if not availability_rows:
        return []
    org_names: dict[uuid.UUID, str] = {}
    available_orgs_by_date: dict[date, set[uuid.UUID]] = {}
    for available_date, org_id, org_name in availability_rows:
        if available_date and org_id:
            available_orgs_by_date.setdefault(available_date, set()).add(org_id)
            org_names[org_id] = org_name or 'Unknown community'
    selected_by_date: dict[date, set[uuid.UUID]] = {}
    games_by_date_org: dict[tuple[date, uuid.UUID], int] = {}
    games_by_date_host: dict[tuple[date, uuid.UUID], int] = {}
    generated_host_locations_by_date_org: dict[tuple[date, uuid.UUID], dict[uuid.UUID, str]] = {}
    scheduled_rows = db.query(GameSlot.slot_date, HostLocation.organization_id, func.count(Game.id)).select_from(Game).join(
        GameSlot, GameSlot.assigned_game_id == Game.id
    ).join(HostLocation, HostLocation.id == GameSlot.host_location_id).join(Game.status).filter(
        GameStatus.code == 'SCHEDULED',
        GameStatus.is_active.is_(True),
        HostLocation.organization_id.isnot(None),
        GameSlot.slot_date.isnot(None),
    ).group_by(GameSlot.slot_date, HostLocation.organization_id).all()
    for slot_date, org_id, count in scheduled_rows:
        selected_by_date.setdefault(slot_date, set()).add(org_id)
        games_by_date_org[(slot_date, org_id)] = int(count or 0)
    scheduled_host_rows = db.query(GameSlot.slot_date, HostLocation.id, func.count(Game.id)).select_from(Game).join(
        GameSlot, GameSlot.assigned_game_id == Game.id
    ).join(HostLocation, HostLocation.id == GameSlot.host_location_id).join(Game.status).filter(
        GameStatus.code == 'SCHEDULED',
        GameStatus.is_active.is_(True),
        GameSlot.slot_date.isnot(None),
    ).group_by(GameSlot.slot_date, HostLocation.id).all()
    for slot_date, host_id, count in scheduled_host_rows:
        if slot_date and host_id:
            games_by_date_host[(slot_date, host_id)] = int(count or 0)
    generated_slot_hosts = db.query(GameSlot.slot_date, HostLocation.organization_id, HostLocation.id, HostLocation.name).join(
        HostLocation, HostLocation.id == GameSlot.host_location_id
    ).filter(
        GameSlot.slot_date.in_(list(available_orgs_by_date.keys())),
        HostLocation.organization_id.in_(list(org_names.keys())),
    ).distinct().all()
    for slot_date, org_id, host_id, host_name in generated_slot_hosts:
        if slot_date and org_id and host_id:
            generated_host_locations_by_date_org.setdefault((slot_date, org_id), {})[host_id] = host_name or str(host_id)

    rows: list[dict[str, object]] = []
    cumulative_games = {org_id: 0 for org_id in org_names}
    cumulative_host_weeks: dict[uuid.UUID, set[date]] = {org_id: set() for org_id in org_names}
    weeks_by_date = {_week_game_date(week): week.week_number for week in db.query(Week).all() if _week_game_date(week)}
    for host_date in sorted(available_orgs_by_date):
        available_orgs = available_orgs_by_date[host_date]
        expected = (sum(cumulative_games.values()) / max(len(available_orgs), 1)) if available_orgs else 0.0
        ranking = []
        capacity_by_org: dict[uuid.UUID, int] = {}
        capacity_by_size_by_org: dict[uuid.UUID, dict[str, int]] = {}
        for org_id, field_type, capacity in db.query(HostLocation.organization_id, GameSlot.field_type, func.count(GameSlot.id)).select_from(GameSlot).join(
            HostLocation, HostLocation.id == GameSlot.host_location_id
        ).filter(GameSlot.slot_date == host_date, HostLocation.organization_id.in_(list(available_orgs))).group_by(HostLocation.organization_id, GameSlot.field_type).all():
            slot_count = int(capacity or 0)
            capacity_by_org[org_id] = capacity_by_org.get(org_id, 0) + slot_count
            capacity_by_size_by_org.setdefault(org_id, {})[str(field_type or 'UNKNOWN')] = slot_count
        for org_id in available_orgs:
            host_dates = cumulative_host_weeks.get(org_id, set())
            days_since = _days_since_last_hosted(host_dates, host_date)
            last_hosted_date = max(host_dates) if host_dates else None
            last_hosted_week_number = weeks_by_date.get(last_hosted_date) if last_hosted_date else None
            delta = cumulative_games.get(org_id, 0) - expected
            capacity_score = capacity_by_org.get(org_id, 0)
            ranking.append({
                'community_id': str(org_id),
                'community': org_names.get(org_id, 'Unknown community'),
                'host_weeks_used': len(host_dates),
                'last_hosted_week_number': last_hosted_week_number,
                'weeks_since_last_hosted': None if days_since >= 999_999 else round(days_since / 7, 2),
                'days_since_last_hosted': days_since,
                'consecutive_host_weeks': _consecutive_host_count_before_date(host_dates, host_date),
                'games_hosted_season_to_date': cumulative_games.get(org_id, 0),
                'games_hosted': cumulative_games.get(org_id, 0),
                'expected_games_hosted': round(expected, 2),
                'hosting_delta': round(delta, 2),
                'available_field_capacity_by_size': capacity_by_size_by_org.get(org_id, {}),
                'capacity_score': capacity_score,
                'capacity_fit_result': 'valid generated slots available' if capacity_score > 0 else 'no generated slots available',
                'status': _hosting_equity_status(delta, expected),
            })
        ranking.sort(key=lambda item: (item['host_weeks_used'], -item['days_since_last_hosted'], item['consecutive_host_weeks'], item['games_hosted_season_to_date'], item['hosting_delta'], -item['capacity_score'], item['community']))
        for rank_number, item in enumerate(ranking, start=1):
            item['rotation_rank'] = rank_number
            item['available_this_week'] = True
        selected = selected_by_date.get(host_date, set())
        reason_selected = []
        reason_skipped = []
        skipped_communities = []
        available_names = [org_names.get(org_id, 'Unknown community') for org_id in sorted(available_orgs, key=lambda value: org_names.get(value, ''))]
        selected_names = [org_names.get(org_id, 'Unknown community') for org_id in sorted(selected, key=lambda value: org_names.get(value, ''))]
        selected_set = {str(org_id) for org_id in selected}
        selected_rank_numbers = [index for index, item in enumerate(ranking, start=1) if item['community_id'] in selected_set]
        best_selected_rank = min(selected_rank_numbers) if selected_rank_numbers else None
        for index, item in enumerate(ranking, start=1):
            if item['community_id'] in selected_set:
                reason_selected.append(
                    f"#{index} {item['community']}: selected by rotation profile; "
                    f"host weeks {item['host_weeks_used']}, games {item['games_hosted_season_to_date']}, "
                    f"delta {item['hosting_delta']}, capacity {item['capacity_score']}"
                )
            else:
                if item['capacity_score'] <= 0:
                    reason = 'skipped: no valid generated time slots/capacity for this host date'
                elif best_selected_rank is not None and index > best_selected_rank:
                    reason = 'skipped: higher-ranked rotation community/communities already selected'
                elif not selected_set:
                    reason = 'skipped: no scheduled games found on this host date'
                else:
                    reason = 'skipped: capacity or scheduling rules assigned games elsewhere; review auto-scheduler diagnostics'
                reason_skipped.append(f"#{index} {item['community']}: {reason}")
                skipped_communities.append({'community': item['community'], 'reason': reason})
        selected_ordered_by_rotation = [uuid.UUID(item['community_id']) for item in ranking if item['community_id'] in selected_set]
        total_games_on_date = sum(games_by_date_org.get((host_date, org_id), 0) for org_id in selected)
        demand_by_size = {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0}
        for game_date, required_size, count in db.query(Game.game_date, Division.required_field_layout_type, func.count(Game.id)).select_from(Game).join(
            Team, Game.home_team_id == Team.id
        ).join(Division, Team.division_id == Division.id).filter(Game.game_date == host_date).group_by(Game.game_date, Division.required_field_layout_type).all():
            demand_by_size[_normalize_field_size(required_size) or FIELD_SIZE_SMALL] += int(count or 0)
        first_selected_org = selected_ordered_by_rotation[0] if selected_ordered_by_rotation else None
        first_selected_capacity = capacity_by_org.get(first_selected_org, 0) if first_selected_org else 0
        first_selected_capacity_by_size = capacity_by_size_by_org.get(first_selected_org, {}) if first_selected_org else {}
        first_selected_can_host = bool(first_selected_org and first_selected_capacity >= total_games_on_date and all(
            int(first_selected_capacity_by_size.get(size, 0) or 0) >= int(demand or 0)
            for size, demand in demand_by_size.items()
        ))
        selected_host_locations_by_community = []
        for org_id in selected_ordered_by_rotation:
            host_locations = [
                {
                    'host_location_id': str(host_id),
                    'host_location': host_name,
                    'games_assigned': games_by_date_host.get((host_date, host_id), 0),
                }
                for host_id, host_name in sorted(
                    generated_host_locations_by_date_org.get((host_date, org_id), {}).items(),
                    key=lambda item: item[1],
                )
            ]
            selected_host_locations_by_community.append({
                'community_id': str(org_id),
                'community': org_names.get(org_id, 'Unknown community'),
                'host_locations': host_locations,
                'capacity': capacity_by_org.get(org_id, 0),
                'capacity_by_size': capacity_by_size_by_org.get(org_id, {}),
                'games_assigned': games_by_date_org.get((host_date, org_id), 0),
            })
        for item in ranking:
            item['selected_as_host'] = item['community_id'] in selected_set
            if item['selected_as_host']:
                item['reason_selected_or_skipped'] = 'selected as host for this week'
            elif item['capacity_score'] <= 0:
                item['reason_selected_or_skipped'] = 'skipped: no valid generated time slots/capacity for this host date'
            elif selected_set:
                item['reason_selected_or_skipped'] = 'skipped: selected rotation community capacity was sufficient'
            else:
                item['reason_selected_or_skipped'] = 'skipped: no scheduled games found on this host date'

        rows.append({
            'diagnostic_label': 'Weekly Community Host Plan',
            'week': f"Week {weeks_by_date.get(host_date)}" if weeks_by_date.get(host_date) is not None else str(host_date),
            'host_date': str(host_date),
            'available_communities': available_names,
            'selected_host_communities': selected_names,
            'selected_community_or_communities': selected_names,
            'community_capacity_by_field_size': {
                org_names.get(org_id, 'Unknown community'): capacity_by_size_by_org.get(org_id, {})
                for org_id in selected
            },
            'locations_used_under_each_community': selected_host_locations_by_community,
            'reason_additional_community_needed': (
                'Primary selected community lacked enough aggregate capacity, so the next rotation community was added.'
                if len(selected_ordered_by_rotation) > 1 else None
            ),
            'selected_host_locations_by_community': selected_host_locations_by_community,
            'combined_community_capacity': sum(capacity_by_org.get(org_id, 0) for org_id in selected),
            'selected_community_could_host_all_games': first_selected_can_host,
            'additional_communities_needed': len(selected_ordered_by_rotation) > 1,
            'skipped_communities': skipped_communities,
            'rotation_ranking': ranking,
            'reason_selected': reason_selected,
            'reason_skipped': reason_skipped,
        })
        for org_id in selected:
            cumulative_host_weeks.setdefault(org_id, set()).add(host_date)
            cumulative_games[org_id] = cumulative_games.get(org_id, 0) + games_by_date_org.get((host_date, org_id), 0)
    return rows


def _build_field_configuration_efficiency_readiness(db: Session) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    site_slots: dict[tuple[date, uuid.UUID], list[GameSlot]] = {}
    slots = db.query(GameSlot).join(GameSlot.field_instance).join(GameSlot.host_location).order_by(
        GameSlot.slot_date, HostLocation.name, GameSlot.start_time
    ).all()
    for slot in slots:
        if slot.host_location_id:
            site_slots.setdefault((slot.slot_date, slot.host_location_id), []).append(slot)
    for (host_date, host_id), grouped_slots in sorted(site_slots.items(), key=lambda item: (item[0][0], str(item[0][1]))):
        host = grouped_slots[0].host_location
        layouts = sorted({slot.field_instance.hosting_availability.selected_configuration.configuration_name for slot in grouped_slots if slot.field_instance and slot.field_instance.hosting_availability and slot.field_instance.hosting_availability.selected_configuration})
        sizes_by_time: list[str] = []
        sizes_for_time: dict[object, set[str]] = {}
        for slot in sorted(grouped_slots, key=lambda item: (item.start_time, _field_size_sequence_rank(item.field_type))):
            size = _normalize_field_size(slot.field_type) or str(slot.field_type or '')
            sizes_for_time.setdefault(slot.start_time, set()).add(size)
        for slot_time in sorted(sizes_for_time):
            size_set = sizes_for_time[slot_time]
            sizes_by_time.append('MIXED' if len(size_set) > 1 else next(iter(size_set)))
        layout_changes = max(0, len([size for index, size in enumerate(sizes_by_time) if index == 0 or size != sizes_by_time[index - 1]]) - 1)
        assigned_slots = [slot for slot in grouped_slots if slot.assigned_game_id]
        unused_capacity = max(0, len(grouped_slots) - len(assigned_slots))
        small_fields = len({slot.field_instance_id for slot in grouped_slots if _normalize_field_size(slot.field_type) == FIELD_SIZE_SMALL})
        medium_fields = len({slot.field_instance_id for slot in grouped_slots if _normalize_field_size(slot.field_type) == FIELD_SIZE_MEDIUM})
        large_fields = len({slot.field_instance_id for slot in grouped_slots if _normalize_field_size(slot.field_type) == FIELD_SIZE_LARGE})
        warnings: list[str] = []
        if (host.surface_type or 'GRASS_FIELD') == 'TURF_STADIUM' and len(layouts) > 1:
            warnings.append('Avoidable reconfiguration risk: multiple turf layouts are present for one host date.')
        if layout_changes > 0 and (host.surface_type or 'GRASS_FIELD') == 'TURF_STADIUM':
            warnings.append('Excessive field reconfiguration: group same-size games into continuous Small, Medium, then Large blocks or use one mixed layout concurrently.')
        rows.append({
            'host_location_id': host_id,
            'host_location': host.name if host else str(host_id),
            'host_date': host_date,
            'selected_turf_layout': ', '.join(layouts) if layouts and (host.surface_type or 'GRASS_FIELD') == 'TURF_STADIUM' else None,
            'small_fields': small_fields,
            'medium_fields': medium_fields,
            'large_fields': large_fields,
            'field_size_blocks': _field_size_blocks_from_slots(grouped_slots),
            'layout_changes': layout_changes,
            'transition_windows_required': layout_changes,
            'transition_windows': [str(size) for size in sizes_by_time],
            'unused_capacity': unused_capacity,
            'warnings': warnings,
        })
    return rows


def _build_weekly_field_demand_readiness(db: Session) -> list[dict[str, object]]:
    demand_by_date: dict[date, dict[str, int]] = {}
    regular_game_dates = {_week_game_date(week) for week in db.query(Week).all() if _is_regular_season_week(week) and _week_game_date(week)}
    for game_date in regular_game_dates:
        demand_by_date.setdefault(game_date, {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0})
    demand_query = db.query(Game.game_date, Division.required_field_layout_type, func.count(Game.id)).select_from(Game).join(
        Team, Game.home_team_id == Team.id
    ).join(Division, Team.division_id == Division.id).outerjoin(Week, Game.week_id == Week.id)
    if regular_game_dates:
        demand_query = demand_query.filter(or_(Week.date_type == REGULAR_SEASON_DATE_TYPE, and_(Game.week_id.is_(None), Game.game_date.in_(regular_game_dates))))
    else:
        demand_query = demand_query.filter(Week.date_type == REGULAR_SEASON_DATE_TYPE)
    for game_date, required_size, count in demand_query.group_by(Game.game_date, Division.required_field_layout_type).all():
        size = _normalize_field_size(required_size) or FIELD_SIZE_SMALL
        demand_by_date.setdefault(game_date, {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0})[size] += int(count or 0)
    for slot_date in [row[0] for row in db.query(GameSlot.slot_date).distinct().all()]:
        demand_by_date.setdefault(slot_date, {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0})
    capacity: dict[date, dict[uuid.UUID, dict[str, object]]] = {}
    for slot in db.query(GameSlot).join(GameSlot.host_location).all():
        host = slot.host_location
        if not host or not host.organization_id:
            continue
        day = capacity.setdefault(slot.slot_date, {})
        row = day.setdefault(host.organization_id, {
            'community_id': str(host.organization_id),
            'community': host.organization.name if host.organization else 'Unknown community',
            'host_locations': {},
            'small_capacity': 0,
            'medium_capacity': 0,
            'large_capacity': 0,
        })
        size = _normalize_field_size(slot.field_type)
        if size == FIELD_SIZE_SMALL:
            row['small_capacity'] += 1
        elif size == FIELD_SIZE_MEDIUM:
            row['medium_capacity'] += 1
        elif size == FIELD_SIZE_LARGE:
            row['large_capacity'] += 1
        host_locations = row['host_locations']
        loc = host_locations.setdefault(str(host.id), {'host_location': host.name, 'small_capacity': 0, 'medium_capacity': 0, 'large_capacity': 0})
        if size == FIELD_SIZE_SMALL:
            loc['small_capacity'] += 1
        elif size == FIELD_SIZE_MEDIUM:
            loc['medium_capacity'] += 1
        elif size == FIELD_SIZE_LARGE:
            loc['large_capacity'] += 1
    rows = []
    for host_date in sorted(demand_by_date):
        day_capacity = []
        for row in capacity.get(host_date, {}).values():
            row = dict(row)
            row['host_locations'] = list(row['host_locations'].values())
            day_capacity.append(row)
        demand = demand_by_date[host_date]
        capacity_available = sum(
            int(row.get('small_capacity') or 0) + int(row.get('medium_capacity') or 0) + int(row.get('large_capacity') or 0)
            for row in day_capacity
        )
        capacity_used = int(demand.get(FIELD_SIZE_SMALL, 0) or 0) + int(demand.get(FIELD_SIZE_MEDIUM, 0) or 0) + int(demand.get(FIELD_SIZE_LARGE, 0) or 0)
        rows.append({
            'host_date': host_date,
            'small_games_required': demand.get(FIELD_SIZE_SMALL, 0),
            'medium_games_required': demand.get(FIELD_SIZE_MEDIUM, 0),
            'large_games_required': demand.get(FIELD_SIZE_LARGE, 0),
            'capacity_available': capacity_available,
            'capacity_used': capacity_used,
            'available_capacity_by_community': sorted(day_capacity, key=lambda item: item.get('community') or ''),
        })
    return rows


@router.get('/schedule-readiness', response_model=ScheduleReadinessResponse, dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def get_schedule_readiness(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_league_defined_divisions(db)

    division_rows = db.query(
        Division.id.label('division_id'),
        Division.division_group,
        Division.name.label('division_name'),
        Division.sort_order,
        Division.required_field_layout_type,
        func.count(func.distinct(Team.id)).label('team_count'),
    ).outerjoin(
        OrganizationDivisionParticipation,
        OrganizationDivisionParticipation.division_id == Division.id,
    ).outerjoin(
        Team,
        and_(
            Team.division_id == Division.id,
            Team.organization_id == OrganizationDivisionParticipation.organization_id,
            Team.is_active.is_(True),
        ),
    ).filter(
        Division.is_active.is_(True),
    ).group_by(
        Division.id, Division.division_group, Division.name, Division.sort_order, Division.required_field_layout_type
    ).order_by(Division.sort_order, Division.division_group, Division.name).all()

    open_slot_counts = dict(
        db.query(GameSlot.field_type, func.count(GameSlot.id))
        .filter(GameSlot.status == 'OPEN')
        .group_by(GameSlot.field_type)
        .all()
    )

    small_slots = int(open_slot_counts.get('SMALL', 0) or 0)
    medium_slots = int(open_slot_counts.get('MEDIUM', 0) or 0)
    large_slots = int(open_slot_counts.get('LARGE', 0) or 0)

    scheduled_game_counts = dict(
        db.query(Team.division_id, func.count(Game.id))
        .select_from(Game)
        .join(Team, Game.home_team_id == Team.id)
        .group_by(Team.division_id)
        .all()
    )

    rows: list[ScheduleReadinessDivisionRow] = []
    total_teams = 0
    total_minimum_unique_matchups = 0
    total_target_scheduled_games = 0

    for row in division_rows:
        teams = int(row.team_count or 0)
        minimum_unique_matchups = (teams * (teams - 1)) // 2
        target_scheduled_games = int(scheduled_game_counts.get(row.division_id, 0) or 0)
        required_field_type = _required_field_type_for_division(row)
        available_matching_slots = {
            FIELD_SIZE_SMALL: small_slots,
            FIELD_SIZE_MEDIUM: medium_slots,
            FIELD_SIZE_LARGE: large_slots,
        }.get(required_field_type, 0)

        if teams == 0:
            status = 'NO TEAMS'
        elif available_matching_slots >= minimum_unique_matchups:
            status = 'READY'
        else:
            status = 'SHORT'

        rows.append(ScheduleReadinessDivisionRow(
            division_id=row.division_id,
            division_label=f"{row.division_group.title()} {row.division_name}",
            field_type_required=required_field_type,
            number_of_teams=teams,
            minimum_unique_matchups=minimum_unique_matchups,
            target_scheduled_games=target_scheduled_games,
            available_matching_slots=available_matching_slots,
            status=status,
        ))
        total_teams += teams
        total_minimum_unique_matchups += minimum_unique_matchups
        total_target_scheduled_games += target_scheduled_games

    active_host_ids = {host_id for (host_id,) in db.query(HostLocation.id).filter(HostLocation.is_active.is_(True)).all()}
    active_setup_host_ids = {host_id for host_id, is_ready in _host_location_effective_status(db).items() if is_ready}
    hosts_missing_setup = active_host_ids - active_setup_host_ids
    warnings = []
    if hosts_missing_setup:
        warnings.append(f"{len(hosts_missing_setup)} active host location(s) have no active compatible field setup and are unavailable for scheduling.")
    missing_surface_count = db.query(HostLocation).filter(or_(HostLocation.surface_type.is_(None), HostLocation.surface_type == '')).count()
    if missing_surface_count:
        warnings.append(f"{missing_surface_count} host location(s) are missing surface_type; Grass Field is used for backward compatibility.")
    unsupported_turf_configs = db.query(HostLocationConfiguration).join(HostLocationConfiguration.host_location).filter(
        HostLocation.surface_type == 'TURF_STADIUM',
        ~HostLocationConfiguration.configuration_name.in_(tuple(TURF_STADIUM_CONFIGURATIONS.keys())),
        HostLocationConfiguration.is_active.is_(True),
    ).count()
    if unsupported_turf_configs:
        warnings.append(f"{unsupported_turf_configs} active turf stadium configuration(s) are not approved.")
    missing_slot_type_count = db.query(GameSlot).filter(or_(GameSlot.field_type.is_(None), GameSlot.field_type == '')).count()
    if missing_slot_type_count:
        warnings.append(f"{missing_slot_type_count} generated slot(s) are missing field type.")
    inactive_field_used_count = db.query(Game).join(Game.field_instance).filter(FieldInstance.is_active.is_(False)).count()
    if inactive_field_used_count:
        warnings.append(f"{inactive_field_used_count} scheduled game(s) use inactive generated fields.")
    for row in _build_hosting_balance_readiness(db):
        share_warning = _hosting_share_warning_status(float(row.get('hosting_delta') or 0), float(row.get('expected_games_hosted') or row.get('expected_host_share') or 0))
        if share_warning == 'above':
            warnings.append(f"{row.get('community')} is more than 25% above expected hosting share.")
        elif share_warning == 'below':
            warnings.append(f"{row.get('community')} is more than 25% below expected hosting share.")
        if int(row.get('consecutive_host_count') or 0) > 2:
            warnings.append(f"{row.get('community')} has hosted more than 2 consecutive weeks.")
    for row in _build_hosting_rotation_readiness(db):
        selected_names = set(row.get('selected_host_communities') or [])
        ranking_rows = row.get('rotation_ranking') or []
        selected_host_weeks = [int(r.get('host_weeks_used') or 0) for r in ranking_rows if r.get('community') in selected_names]
        lowest_selected_host_weeks = min(selected_host_weeks, default=None)
        available_host_week_counts = [int(r.get('host_weeks_used') or 0) for r in ranking_rows]
        if available_host_week_counts and max(available_host_week_counts) - min(available_host_week_counts) > 1:
            warnings.append(f"{row.get('week')}: host-week imbalance greater than 1 between available communities.")
        if row.get('selected_community_could_host_all_games') and row.get('additional_communities_needed'):
            warnings.append(f"{row.get('week')}: selected community could host full week but another community was added unnecessarily.")
        for ranking in ranking_rows:
            if ranking.get('status') == 'Underused' and ranking.get('community') not in selected_names:
                warnings.append(f"{row.get('week')}: available underused community not selected: {ranking.get('community')}.")
            if (
                lowest_selected_host_weeks is not None
                and ranking.get('community') not in selected_names
                and int(ranking.get('host_weeks_used') or 0) < lowest_selected_host_weeks
                and int(ranking.get('capacity_score') or 0) > 0
            ):
                warnings.append(f"{row.get('week')}: community with fewer host weeks skipped: {ranking.get('community')}.")
            if ranking.get('community') in selected_names and int(ranking.get('consecutive_host_weeks') or 0) > 0:
                lower_available = any(
                    other.get('community') not in selected_names
                    and int(other.get('host_weeks_used') or 0) < int(ranking.get('host_weeks_used') or 0)
                    and int(other.get('capacity_score') or 0) > 0
                    for other in ranking_rows
                )
                if lower_available:
                    warnings.append(f"{row.get('week')}: {ranking.get('community')} selected in consecutive weeks while a lower-host-week community was available.")
    for row in _build_field_configuration_efficiency_readiness(db):
        if int(row.get('layout_changes') or 0) > 1:
            warnings.append(f"Excessive field reconfiguration at {row.get('host_location')} on {row.get('host_date')}.")
    invalid_field_size_rows = db.query(GameSlot.field_type, Division.required_field_layout_type).select_from(Game).join(
        GameSlot, GameSlot.assigned_game_id == Game.id
    ).join(Team, Game.home_team_id == Team.id).join(Division, Team.division_id == Division.id).filter(
        GameSlot.field_type.isnot(None),
        Division.required_field_layout_type.isnot(None),
    ).all()
    invalid_field_size_total = sum(
        1
        for slot_field_type, required_field_layout_type in invalid_field_size_rows
        if _normalize_field_size(slot_field_type) != _normalize_field_size(required_field_layout_type)
    )
    if invalid_field_size_total:
        warnings.append(f"{invalid_field_size_total} invalid field-size assignment(s) found.")

    return ScheduleReadinessResponse(
        rows=rows,
        totals=ScheduleReadinessTotals(
            total_teams=total_teams,
            total_minimum_unique_matchups=total_minimum_unique_matchups,
            total_target_scheduled_games=total_target_scheduled_games,
            total_small_field_slots=small_slots,
            total_medium_field_slots=medium_slots,
            total_large_field_slots=large_slots,
            total_open_slots=small_slots + medium_slots + large_slots,
        ),
        warnings=warnings,
        host_dates=_build_host_date_readiness(db),
        hosting_balance=_build_hosting_balance_readiness(db),
        hosting_rotation=_build_hosting_rotation_readiness(db),
        field_configuration_efficiency=_build_field_configuration_efficiency_readiness(db),
        weekly_field_demand=_build_weekly_field_demand_readiness(db),
    )

HOST_PLAN_SCHEDULABLE_STATUSES = {'SELECTED', 'LOCKED', 'OVERFLOW'}
HOST_PLAN_IGNORED_STATUSES = {'AVAILABLE', 'NOT_AVAILABLE', 'EXCLUDED', 'BLOCKED_CAPACITY', 'BLOCKED_ROTATION', 'BLOCKED_FIELD_SIZE'}
HOST_PLAN_REQUIRES_AVAILABILITY_STATUSES = HOST_PLAN_SCHEDULABLE_STATUSES
HOST_PLAN_MISSING_AVAILABILITY_MESSAGE = 'Missing Hosting Availability'
HOST_PLAN_SELECTED_MISSING_AVAILABILITY_MESSAGE = 'Selected host is missing Hosting Availability and cannot be used.'
HOST_PLAN_SKIPPED_MISSING_AVAILABILITY_MESSAGE = 'Host selected but no Hosting Availability record exists.'


def _base_host_plan_availability_query(
    db: Session,
    season_id: uuid.UUID | str,
    host_location_id: uuid.UUID | str,
):
    return db.query(HostingAvailability).filter(
        HostingAvailability.season_id == season_id,
        HostingAvailability.host_location_id == host_location_id,
        HostingAvailability.active.is_(True),
        HostingAvailability.is_available.is_(True),
    )


def _exact_host_plan_availability_query(
    db: Session,
    season_id: uuid.UUID | str,
    week_id: uuid.UUID | str,
    game_date: date,
    host_location_id: uuid.UUID | str,
):
    return _base_host_plan_availability_query(db, season_id, host_location_id).filter(
        HostingAvailability.week_id == week_id,
        HostingAvailability.primary_game_date == game_date,
    )


def _availability_normalized_dates(availability: HostingAvailability) -> set[date]:
    dates = {
        _normalize_local_date_only(availability.primary_game_date),
        _normalize_local_date_only(availability.available_date),
    }
    return {value for value in dates if value}


def _availability_matches_date(availability: HostingAvailability, expected_date: date) -> bool:
    return expected_date in _availability_normalized_dates(availability)


def _availability_matches_utc_shifted_date(availability: HostingAvailability, expected_date: date) -> bool:
    shifted_dates = {expected_date - timedelta(days=1), expected_date + timedelta(days=1)}
    return bool(_availability_normalized_dates(availability).intersection(shifted_dates))


def _availability_within_week_range(availability: HostingAvailability, week: Week) -> bool:
    for value in _availability_normalized_dates(availability):
        if week.start_date <= value <= week.end_date:
            return True
    return False


def _repair_hosting_availability_key(
    db: Session,
    availability: HostingAvailability,
    season_id: uuid.UUID | str,
    week: Week,
    game_date: date,
    host: HostLocation | None = None,
) -> list[str]:
    repairs: list[str] = []
    expected_season_id = week.season_id or season_id
    if str(availability.season_id) != str(expected_season_id):
        repairs.append(f'season_id:{availability.season_id}->{expected_season_id}')
        availability.season_id = expected_season_id
    if availability.week_id != week.id:
        repairs.append(f'season_week_id:{availability.week_id}->{week.id}')
        availability.week_id = week.id
    if _normalize_local_date_only(availability.primary_game_date) != game_date:
        repairs.append(f'primary_game_date:{availability.primary_game_date}->{game_date}')
        availability.primary_game_date = game_date
    if _normalize_local_date_only(availability.available_date) != game_date:
        repairs.append(f'available_date:{availability.available_date}->{game_date}')
        availability.available_date = game_date
    if host and availability.organization_id != host.organization_id:
        repairs.append(f'organization_id:{availability.organization_id}->{host.organization_id}')
        availability.organization_id = host.organization_id
    if repairs:
        logger.info(
            'Repaired Hosting Availability key availability_id=%s host_location_id=%s week_id=%s primary_game_date=%s repairs=%s',
            availability.id,
            availability.host_location_id,
            week.id,
            game_date,
            '; '.join(repairs),
        )
        db.flush()
    return repairs


def _resolve_hosting_availability(
    db: Session,
    season_id: uuid.UUID | str,
    week: Week | None,
    game_date: date | None,
    host_location_id: uuid.UUID | str,
    *,
    repair: bool = True,
    host: HostLocation | None = None,
) -> dict[str, object]:
    expected_date = _normalize_local_date_only(game_date or _week_game_date(week))
    result: dict[str, object] = {
        'availability': None,
        'lookup_method': 'not_found',
        'repair_actions': [],
        'found_record_id': None,
        'found_record_season_week_id': None,
        'found_record_primary_game_date': None,
        'found_record_available_date': None,
        'found_record_organization_id': None,
        'found_record_host_location_id': None,
        'requires_admin_action': 'Create Missing Hosting Availability Record',
    }
    if not week or not week.id or not expected_date:
        result['lookup_method'] = 'missing_week_or_primary_game_date'
        return result

    base_query = _base_host_plan_availability_query(db, season_id, host_location_id)

    week_rows = base_query.filter(HostingAvailability.week_id == week.id).order_by(HostingAvailability.start_time, HostingAvailability.end_time).all()
    week_match = next((row for row in week_rows if _availability_matches_date(row, expected_date)), None) or (week_rows[0] if week_rows else None)
    candidates: list[tuple[HostingAvailability | None, str, bool]] = [
        (
            week_match,
            'season_id_season_week_id_host_location_id',
            True,
        ),
        (
            base_query.filter(HostingAvailability.primary_game_date == expected_date).order_by(HostingAvailability.start_time, HostingAvailability.end_time).first(),
            'season_id_primary_game_date_host_location_id',
            True,
        ),
    ]

    broad_rows = base_query.order_by(HostingAvailability.start_time, HostingAvailability.end_time).all()
    normalized_match = next((row for row in broad_rows if _availability_matches_date(row, expected_date)), None)
    candidates.append((normalized_match, 'season_id_normalized_local_date_only_primary_game_date_host_location_id', True))
    shifted_match = next((row for row in broad_rows if _availability_matches_utc_shifted_date(row, expected_date)), None)
    candidates.append((shifted_match, 'season_id_utc_shifted_date_host_location_id', True))
    week_range_match = next((row for row in broad_rows if _availability_within_week_range(row, week)), None)
    candidates.append((week_range_match, 'season_id_host_location_id_date_within_same_season_week_range', True))

    for availability, lookup_method, can_repair in candidates:
        if not availability:
            continue
        if lookup_method == 'season_id_season_week_id_host_location_id' and _availability_matches_date(availability, expected_date):
            lookup_method = 'season_id_week_id_host_location_id_primary_game_date'
        result.update({
            'availability': availability,
            'lookup_method': lookup_method,
            'found_record_id': str(availability.id),
            'found_record_season_week_id': str(availability.week_id) if availability.week_id else None,
            'found_record_primary_game_date': str(_normalize_local_date_only(availability.primary_game_date)) if availability.primary_game_date else None,
            'found_record_available_date': str(_normalize_local_date_only(availability.available_date)) if availability.available_date else None,
            'found_record_organization_id': str(availability.organization_id) if availability.organization_id else None,
            'found_record_host_location_id': str(availability.host_location_id) if availability.host_location_id else None,
            'requires_admin_action': None,
        })
        if repair and can_repair:
            result['repair_actions'] = _repair_hosting_availability_key(db, availability, season_id, week, expected_date, host)
        return result

    return result


def _find_host_plan_availability(
    db: Session,
    season_id: uuid.UUID | str,
    week: Week | None,
    game_date: date | None,
    host_location_id: uuid.UUID | str,
) -> tuple[HostingAvailability | None, str]:
    resolved = _resolve_hosting_availability(db, season_id, week, game_date, host_location_id, repair=True)
    return resolved.get('availability'), str(resolved.get('lookup_method') or 'not_found')


def _sync_host_plan_selection_availability(db: Session, availability: HostingAvailability) -> int:
    if not availability.season_id or not availability.week_id or not availability.primary_game_date or not availability.host_location_id:
        return 0
    rows = db.query(HostPlanSelection).filter(
        HostPlanSelection.season_id == availability.season_id,
        HostPlanSelection.week_id == availability.week_id,
        HostPlanSelection.game_date == availability.primary_game_date,
        HostPlanSelection.host_location_id == availability.host_location_id,
    ).all()
    for row in rows:
        row.availability_id = availability.id
    return len(rows)


def _host_plan_selection_requires_availability(selection: HostPlanSelection) -> bool:
    return str(selection.status or '').upper() in HOST_PLAN_REQUIRES_AVAILABILITY_STATUSES or bool(selection.locked)


def _balanced_target_game_split(total_games: int, communities: list[str]) -> dict[str, int]:
    ordered_communities = sorted(dict.fromkeys(communities))
    if not ordered_communities:
        return {}
    base, remainder = divmod(max(int(total_games or 0), 0), len(ordered_communities))
    return {
        community: base + (1 if index < remainder else 0)
        for index, community in enumerate(ordered_communities)
    }


def _host_plan_capacity_sufficiency(
    capacity_by_size: dict[str, int],
    demand_by_size: dict[str, int],
    doubleheader_adjacency_available: bool = True,
    home_field_requirement_satisfied: bool = True,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    total_capacity = sum(int(capacity_by_size.get(size, 0) or 0) for size in FIELD_SIZE_ORDER)
    total_demand = sum(int(demand_by_size.get(size, 0) or 0) for size in FIELD_SIZE_ORDER)
    if total_capacity < total_demand:
        reasons.append(f'total game capacity is insufficient ({total_capacity} available for {total_demand} required)')
    for size in FIELD_SIZE_ORDER:
        capacity = int(capacity_by_size.get(size, 0) or 0)
        demand = int(demand_by_size.get(size, 0) or 0)
        if capacity < demand:
            reasons.append(f'{size.title()} field-size capacity is insufficient ({capacity} available for {demand} required)')
    if not doubleheader_adjacency_available:
        reasons.append('selected host communities cannot support same-location back-to-back doubleheaders')
    if not home_field_requirement_satisfied:
        reasons.append('selected host communities cannot support home-field requirements')
    return not reasons, reasons


def _host_plan_allowed_host_ids_for_week(db: Session, season_id: uuid.UUID | str | None, week_id: uuid.UUID | str | None = None, game_date: date | None = None) -> set[uuid.UUID] | None:
    """Return selected/locked/overflow hosts for the exact season/week/date key.

    Auto-schedule slot compatibility must use the same key generated-slot
    regeneration uses: season_id + season_week_id + game_date + host plan
    status.  A legacy date-only fallback is kept only for rows that have not
    been backfilled with week_id yet.
    """
    if not season_id or not game_date:
        return None
    query = db.query(HostPlanSelection).filter(
        HostPlanSelection.season_id == season_id,
        HostPlanSelection.game_date == game_date,
    )
    if week_id:
        query = query.filter(
            or_(
                HostPlanSelection.week_id == week_id,
                HostPlanSelection.week_id.is_(None),
            )
        )
    all_rows = query.all()
    if not all_rows:
        return None
    return {row.host_location_id for row in all_rows if row.status in HOST_PLAN_SCHEDULABLE_STATUSES or row.locked}


def _apply_host_plan_filter_to_slots(query, db: Session, season_id: uuid.UUID | str | None, week_id: uuid.UUID | str | None = None, game_date: date | None = None):
    allowed_host_ids = _host_plan_allowed_host_ids_for_week(db, season_id, week_id, game_date)
    if allowed_host_ids is None:
        return query
    if not allowed_host_ids:
        return query.filter(GameSlot.host_location_id.in_([]))
    return query.filter(GameSlot.host_location_id.in_(allowed_host_ids))


def _is_playoff_or_championship_week(week: Week) -> bool:
    if _week_date_type(week) == PLAYOFF_DATE_TYPE:
        return True
    text_value = ' '.join(str(v or '') for v in (week.label, week.status, week.notes)).lower()
    return 'playoff' in text_value or 'championship' in text_value or 'champion' in text_value




def _availability_date_type(db: Session, availability: HostingAvailability) -> str:
    week = availability.week if getattr(availability, 'week', None) else None
    if not week and availability.week_id:
        week = db.query(Week).filter(Week.id == availability.week_id).first()
    if not week and availability.season_id and availability.available_date:
        week = db.query(Week).filter(
            Week.season_id == availability.season_id,
            Week.primary_game_date == availability.available_date,
        ).order_by(Week.primary_game_date, Week.week_number).first()
    return _week_date_type(week)


def _availability_allows_generated_slots(db: Session, availability: HostingAvailability) -> bool:
    return _availability_date_type(db, availability) == REGULAR_SEASON_DATE_TYPE

def _field_capacity_from_host(host: HostLocation) -> dict[str, int]:
    return {
        FIELD_SIZE_SMALL: int(host.max_small_fields or 0),
        FIELD_SIZE_MEDIUM: int(host.max_medium_fields or 0),
        FIELD_SIZE_LARGE: int(host.max_large_fields or 0),
    }


def _aggregate_availability_capacity_by_size(db: Session, host: HostLocation, availability_rows: list[HostingAvailability]) -> dict[str, int]:
    capacity = _empty_field_size_counts()
    for availability in availability_rows:
        availability_capacity = _host_availability_capacity_by_size(db, host, availability)
        for size in FIELD_SIZE_ORDER:
            capacity[size] += int(availability_capacity.get(size, 0) or 0)
    return capacity


def _selected_capacity_source_detail(
    db: Session,
    host: HostLocation,
    community_name: str,
    availability: HostingAvailability | None,
    capacity_by_size: dict[str, int],
    capacity_source: str,
) -> dict:
    total_capacity = sum(int(capacity_by_size.get(size, 0) or 0) for size in FIELD_SIZE_ORDER)
    reason = None
    if availability and total_capacity <= 0:
        reason = 'Selected location has availability but capacity could not be calculated.'
    return {
        'community': community_name,
        'host_location': host.name if host else None,
        'availability_id': availability.id if availability else None,
        'date': availability.available_date if availability else None,
        'surface_type': (host.surface_type if host else None) or 'GRASS_FIELD',
        'time_window': f'{availability.start_time.strftime("%H:%M")}-{availability.end_time.strftime("%H:%M")}' if availability else None,
        'capacity_source': capacity_source,
        'small_capacity': int(capacity_by_size.get(FIELD_SIZE_SMALL, 0) or 0),
        'medium_capacity': int(capacity_by_size.get(FIELD_SIZE_MEDIUM, 0) or 0),
        'large_capacity': int(capacity_by_size.get(FIELD_SIZE_LARGE, 0) or 0),
        'calculated_total_capacity': total_capacity,
        'zero_capacity_reason': reason,
    }


def _weekly_required_games_by_size(db: Session, season_id: uuid.UUID | str | None = None) -> dict[str, int]:
    query = db.query(Division, func.count(Team.id)).outerjoin(Team, and_(Team.division_id == Division.id, Team.is_active.is_(True))).filter(Division.is_active.is_(True)).group_by(Division.id)
    required = {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0}
    for division, team_count in query.all():
        size = _required_field_type_for_division(division)
        if size in required:
            required[size] += math.ceil(int(team_count or 0) / 2)
    return required


def _host_availability_matrix_response(db: Session, season_id: uuid.UUID) -> dict:
    season = db.query(Season).filter(Season.id == season_id).first()
    if not season:
        raise HTTPException(404, 'Season not found')
    weeks = db.query(Week).filter(Week.season_id == season_id).order_by(Week.primary_game_date, Week.week_number).all()
    dates_by_value: dict[date, dict] = {}
    for week in weeks:
        game_date = week.primary_game_date
        if game_date:
            week_label = week.label or f'Week {week.week_number}'
            dates_by_value[game_date] = {
                'game_date': _date_only_iso(game_date),
                'primary_game_date': _date_only_iso(week.primary_game_date),
                'start_date': _date_only_iso(week.start_date),
                'end_date': _date_only_iso(week.end_date),
                'week_id': week.id,
                'week_number': week.week_number,
                'label': week_label,
                'week_label': week_label,
                'date_type': _week_date_type(week),
                'is_postseason': _is_playoff_or_championship_week(week),
                'status': week.status,
            }
    dates = [dates_by_value[key] for key in sorted(dates_by_value)]

    hosts = db.query(HostLocation, Organization).join(Organization, Organization.id == HostLocation.organization_id).filter(HostLocation.is_active.is_(True), Organization.is_active.is_(True)).order_by(Organization.name, HostLocation.name).all()
    host_by_id = {str(host.id): host for host, _org in hosts}
    host_ids = [host.id for host, _org in hosts]
    week_ids = [week.id for week in weeks]
    game_dates = [week.primary_game_date for week in weeks if week.primary_game_date]
    availability_rows = db.query(HostingAvailability).filter(
        HostingAvailability.season_id == season_id,
        HostingAvailability.host_location_id.in_(host_ids) if host_ids else False,
        HostingAvailability.active.is_(True),
        HostingAvailability.is_available.is_(True),
    ).all()
    availability_by_host_date: dict[tuple[uuid.UUID, uuid.UUID, date], list[HostingAvailability]] = {}
    for availability in availability_rows:
        if not availability.week_id or not availability.primary_game_date:
            continue
        availability_by_host_date.setdefault((availability.host_location_id, availability.week_id, availability.primary_game_date), []).append(availability)

    selection_rows = db.query(HostPlanSelection).filter(HostPlanSelection.season_id == season_id).all()
    source_game_dates = {date_info['game_date'] for date_info in dates}
    for selection in selection_rows:
        if str(selection.game_date) in source_game_dates and str(selection.host_location_id) not in host_by_id:
            logger.warning(
                'Host availability matrix skipping selection with missing host_location_id=%s season_id=%s game_date=%s',
                selection.host_location_id,
                season_id,
                selection.game_date,
            )
    selection_by_host_date = {(selection.host_location_id, selection.game_date): selection for selection in selection_rows}
    availability_by_id = {availability.id: availability for availability in availability_rows}

    slot_counts: dict[tuple[uuid.UUID, date], dict[str, int]] = {}
    slot_minutes_by_host_date: dict[tuple[uuid.UUID, date], set[int]] = {}
    slot_rows = db.query(GameSlot.host_location_id, GameSlot.slot_date, GameSlot.field_type, func.count(GameSlot.id)).filter(GameSlot.host_location_id.in_(host_ids) if host_ids else False).group_by(GameSlot.host_location_id, GameSlot.slot_date, GameSlot.field_type).all()
    for host_id, slot_date, field_type, count in slot_rows:
        slot_counts.setdefault((host_id, slot_date), {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0})[_normalize_field_size(field_type) or field_type] = int(count or 0)
    slot_time_rows = db.query(GameSlot.host_location_id, GameSlot.slot_date, GameSlot.start_time).filter(GameSlot.host_location_id.in_(host_ids) if host_ids else False).all()
    for host_id, slot_date, start_time in slot_time_rows:
        minute = _minutes_from_time(start_time)
        if minute is not None:
            slot_minutes_by_host_date.setdefault((host_id, slot_date), set()).add(minute)
    odd_division_requires_doubleheader = any(
        int(team_count or 0) % 2 == 1 and int(team_count or 0) > 1
        for (team_count,) in db.query(func.count(Team.id)).join(Division, Team.division_id == Division.id).filter(
            Team.is_active.is_(True),
            Division.is_active.is_(True),
        ).group_by(Division.id).all()
    )

    rows = []
    for host, org in hosts:
        cells = {}
        for date_info in dates:
            game_date = date.fromisoformat(date_info['game_date'])
            week = next((candidate for candidate in weeks if candidate.id == date_info['week_id']), None)
            resolved = _resolve_hosting_availability(db, season_id, week, game_date, host.id, repair=True, host=host)
            selected_availability = resolved.get('availability')
            if selected_availability:
                availability_list = _exact_host_plan_availability_query(db, season_id, date_info['week_id'], game_date, host.id).order_by(HostingAvailability.start_time, HostingAvailability.end_time).all()
                if selected_availability not in availability_list:
                    availability_list = [selected_availability]
            else:
                availability_list = []
            selection = selection_by_host_date.get((host.id, game_date))
            has_valid_availability = bool(selected_availability)
            if selection is None:
                status = 'AVAILABLE' if has_valid_availability else 'NOT_AVAILABLE'
                locked = False
            else:
                saved_status = str(selection.status or 'AVAILABLE').upper()
                if saved_status in HOST_PLAN_REQUIRES_AVAILABILITY_STATUSES and not has_valid_availability:
                    status = 'MISSING_AVAILABILITY'
                    locked = False
                else:
                    status = saved_status
                    locked = bool(selection.locked) or status == 'LOCKED'
                    if locked and not has_valid_availability:
                        status = 'MISSING_AVAILABILITY'
                        locked = False
            if availability_list:
                capacity = _aggregate_availability_capacity_by_size(db, host, availability_list)
                capacity_source = 'Hosting Availability records'
            else:
                capacity = _empty_field_size_counts()
                capacity_source = 'No Hosting Availability record'
            cells[str(game_date)] = {
                'status': status,
                'locked': locked,
                'reason': HOST_PLAN_SELECTED_MISSING_AVAILABILITY_MESSAGE if status == 'MISSING_AVAILABILITY' else (selection.reason if selection and status != 'NOT_AVAILABLE' else (HOST_PLAN_MISSING_AVAILABILITY_MESSAGE if selection else None)),
                'availability_id': selected_availability.id if selected_availability else None,
                'has_saved_availability': has_valid_availability,
                'available_slot_count': len(availability_list),
                'capacity_by_size': capacity,
                'capacity_source': capacity_source,
            }
        rows.append({
            'community_id': org.id,
            'community_name': org.name,
            'host_location_id': host.id,
            'host_location_name': host.name,
            'surface_type': host.surface_type,
            'capacity_by_size': _field_capacity_from_host(host),
            'cells': cells,
        })

    regular_required_by_size = _weekly_required_games_by_size(db, season_id)
    empty_required_by_size = {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0}
    summaries = []
    for date_info in dates:
        game_date = date.fromisoformat(date_info['game_date'])
        required_by_size = regular_required_by_size if date_info.get('date_type') == REGULAR_SEASON_DATE_TYPE else empty_required_by_size
        selected_rows = []
        excluded_rows = []
        selected_capacity_source_summary = []
        available_locations = []
        available_communities: set[str] = set()
        warnings = []
        capacity = {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0}
        community_split: dict[str, int] = {}
        for row in rows:
            cell = row['cells'][str(game_date)]
            if cell.get('has_saved_availability') or cell['status'] == 'OVERFLOW':
                available_communities.add(row['community_name'])
                available_locations.append({'community_name': row['community_name'], 'host_location_name': row['host_location_name']})
            if cell['status'] in HOST_PLAN_SCHEDULABLE_STATUSES or cell.get('locked'):
                host = host_by_id.get(str(row['host_location_id']))
                if host is None:
                    warning = f"Host availability matrix skipped selected row with missing host_location_id={row['host_location_id']} for game_date={game_date}."
                    logger.warning(warning)
                    warnings.append(warning)
                    continue
                selected_rows.append({'community_name': row['community_name'], 'host_location_name': row['host_location_name']})
                cell_capacity = cell.get('capacity_by_size') or {}
                for size in capacity:
                    capacity[size] += int(cell_capacity.get(size, 0) or 0)
                selected_capacity_source_summary.append(_selected_capacity_source_detail(
                    db,
                    host,
                    row['community_name'],
                    availability_by_id.get(cell.get('availability_id')) if cell.get('availability_id') else None,
                    cell_capacity,
                    cell.get('capacity_source') or 'Unknown',
                ))
                community_split[row['community_name']] = community_split.get(row['community_name'], 0) + 1
            elif cell['status'] == 'EXCLUDED':
                excluded_rows.append({'community_name': row['community_name'], 'host_location_name': row['host_location_name']})
        total_selected_capacity = sum(capacity.values())
        total_required = sum(required_by_size.values())
        for size, required in required_by_size.items():
            if capacity.get(size, 0) < required:
                warnings.append(f'{size.title()} capacity short by {required - capacity.get(size, 0)}. Add an overflow field or select more fields.')
        if total_selected_capacity < total_required:
            warnings.append(f'Total selected capacity short by {total_required - total_selected_capacity}. Add an overflow field.')
        for detail in selected_capacity_source_summary:
            if detail.get('zero_capacity_reason'):
                warnings.append(detail['zero_capacity_reason'])
        selected_community_names = sorted(community_split)
        selected_host_ids_for_date = {
            row['host_location_id']
            for row in rows
            if row['cells'][str(game_date)]['status'] in HOST_PLAN_SCHEDULABLE_STATUSES or row['cells'][str(game_date)].get('locked')
        }
        doubleheader_adjacency_available = (
            not odd_division_requires_doubleheader
            or not slot_time_rows
            or any(
                any((minute + 60) in slot_minutes_by_host_date.get((host_id, game_date), set()) for minute in slot_minutes_by_host_date.get((host_id, game_date), set()))
                for host_id in selected_host_ids_for_date
            )
        )
        home_field_requirement_satisfied = True
        additional_host_needed, additional_host_reasons = _host_plan_capacity_sufficiency(
            capacity,
            required_by_size,
            doubleheader_adjacency_available=doubleheader_adjacency_available,
            home_field_requirement_satisfied=home_field_requirement_satisfied,
        )
        additional_host_needed = not additional_host_needed
        summaries.append({
            **date_info,
            'total_games_required': total_required,
            'games_required_by_size': required_by_size,
            'available_communities': sorted(available_communities),
            'available_locations': available_locations,
            'selected_communities': selected_community_names,
            'expected_host_communities': selected_community_names,
            'selected_fields': selected_rows,
            'excluded_available_fields': excluded_rows,
            'estimated_capacity_by_field_size': capacity,
            'target_game_split': _balanced_target_game_split(total_required, selected_community_names),
            'validation_warnings': warnings,
            'weekly_host_plan_decision_summary': {
                'diagnostic_label': 'Weekly Host Plan Decision Summary',
                'selected_communities': selected_community_names,
                'excluded_communities': sorted({row['community_name'] for row in excluded_rows}),
                'total_games_required': total_required,
                'selected_total_capacity': total_selected_capacity,
                'selected_small_capacity': capacity.get(FIELD_SIZE_SMALL, 0),
                'selected_medium_capacity': capacity.get(FIELD_SIZE_MEDIUM, 0),
                'selected_large_capacity': capacity.get(FIELD_SIZE_LARGE, 0),
                'doubleheader_adjacency_available': doubleheader_adjacency_available,
                'home_field_requirement_satisfied': home_field_requirement_satisfied,
                'additional_host_needed': additional_host_needed,
                'reason_additional_host_was_added': '; '.join(additional_host_reasons) if additional_host_reasons else None,
                'selected_capacity_source_summary': selected_capacity_source_summary,
            },
        })
    return {'season': {'id': season.id, 'name': season.name}, 'dates': dates, 'rows': rows, 'summaries': summaries, 'status_options': sorted(HOST_PLAN_SELECTION_STATUSES)}


@router.get('/host-availability-matrix')
def get_host_availability_matrix(season_id: uuid.UUID, current_user: User = Depends(require_roles(ROLE_LEAGUE_ADMIN)), db: Session = Depends(get_db)):
    return _host_availability_matrix_response(db, season_id)


@router.post('/host-availability-matrix/save', response_model=HostAvailabilityMatrixSaveResponse)
def save_host_availability_matrix(payload: HostAvailabilityMatrixSaveRequest, current_user: User = Depends(require_roles(ROLE_LEAGUE_ADMIN)), db: Session = Depends(get_db)):
    _enforce_host_plan_selection_admin(current_user)
    saved_rows: list[HostPlanSelection] = []
    for item in payload.selections:
        status = item.status.upper()
        if status not in HOST_PLAN_SELECTION_STATUSES:
            raise HTTPException(400, f'Invalid host plan status: {item.status}')
        week = db.query(Week).filter(Week.id == item.week_id, Week.season_id == item.season_id).first() if item.week_id else db.query(Week).filter(Week.season_id == item.season_id, Week.primary_game_date == item.game_date).first()
        if not week or _week_game_date(week) != item.game_date:
            raise HTTPException(400, 'Host plan selection date must match a Season Week Primary Game Date.')
        availability, _lookup_method = _find_host_plan_availability(db, item.season_id, week, item.game_date, item.host_location_id)
        if (status in HOST_PLAN_REQUIRES_AVAILABILITY_STATUSES or bool(item.locked)) and not availability:
            raise HTTPException(400, HOST_PLAN_MISSING_AVAILABILITY_MESSAGE)
        row = db.query(HostPlanSelection).filter(
            HostPlanSelection.season_id == item.season_id,
            HostPlanSelection.game_date == item.game_date,
            HostPlanSelection.host_location_id == item.host_location_id,
        ).first()
        if not row:
            row = HostPlanSelection(season_id=item.season_id, game_date=item.game_date, host_location_id=item.host_location_id, community_id=item.community_id)
            db.add(row)
        row.week_id = week.id
        row.community_id = item.community_id
        row.availability_id = item.availability_id or (availability.id if availability else None)
        row.status = status
        row.locked = bool(item.locked or status == 'LOCKED')
        row.reason = item.reason
        saved_rows.append(row)
    db.commit()
    for row in saved_rows:
        db.refresh(row)
    return {'saved': len(saved_rows), 'selections': saved_rows}


@router.post('/host-availability-matrix/create-missing-hosting-availabilities')
def create_missing_hosting_availabilities(payload: dict, current_user: User = Depends(require_roles(ROLE_LEAGUE_ADMIN)), db: Session = Depends(get_db)):
    _enforce_host_plan_selection_admin(current_user)
    season_id = payload.get('season_id')
    game_date_value = payload.get('game_date')
    confirmed = bool(payload.get('confirmed'))
    if not season_id:
        raise HTTPException(400, 'season_id is required')
    if not confirmed:
        raise HTTPException(400, 'Admin confirmation is required before creating Hosting Availability records.')
    query = db.query(HostPlanSelection).filter(HostPlanSelection.season_id == season_id)
    if game_date_value:
        query = query.filter(HostPlanSelection.game_date == date.fromisoformat(str(game_date_value)))
    requested_host_ids = payload.get('host_location_ids') or []
    if requested_host_ids:
        query = query.filter(HostPlanSelection.host_location_id.in_(requested_host_ids))
    selections = query.order_by(HostPlanSelection.game_date, HostPlanSelection.created_at).all()
    created = 0
    updated = 0
    unchanged = 0
    repaired: list[dict[str, str]] = []
    for selection in selections:
        if not _host_plan_selection_requires_availability(selection):
            unchanged += 1
            continue
        week = db.query(Week).filter(Week.id == selection.week_id).first() if selection.week_id else db.query(Week).filter(Week.season_id == selection.season_id, Week.primary_game_date == selection.game_date).first()
        game_date = _normalize_local_date_only(_week_game_date(week) if week else selection.game_date)
        if not week or not week.id or not game_date:
            unchanged += 1
            continue
        host = db.query(HostLocation).filter(HostLocation.id == selection.host_location_id, HostLocation.is_active.is_(True)).first()
        if not host:
            unchanged += 1
            continue
        existing, _lookup_method = _find_host_plan_availability(db, selection.season_id, week, game_date, host.id)
        if existing:
            selection.availability_id = existing.id
            unchanged += 1
            continue
        legacy = _base_host_plan_availability_query(db, selection.season_id, host.id).filter(
            or_(
                HostingAvailability.week_id == week.id,
                HostingAvailability.available_date == game_date,
                HostingAvailability.primary_game_date == game_date,
            )
        ).order_by(HostingAvailability.start_time, HostingAvailability.end_time).first()
        if legacy:
            availability = legacy
            availability.week_id = week.id
            availability.available_date = game_date
            availability.primary_game_date = game_date
            availability.organization_id = host.organization_id
            updated += 1
        else:
            availability = HostingAvailability(
                season_id=selection.season_id,
                week_id=week.id,
                organization_id=host.organization_id,
                host_location_id=host.id,
                available_date=game_date,
                primary_game_date=game_date,
                start_time=time(9, 0),
                end_time=time(17, 0),
                active=True,
                is_available=True,
                notes='Created by admin repair action from selected Host Availability Matrix cell.',
            )
            db.add(availability)
            db.flush()
            created += 1
        selection.week_id = week.id
        selection.game_date = game_date
        selection.community_id = host.organization_id
        selection.availability_id = availability.id
        _regenerate_generated_slots(db, availability, host.id)
        repaired.append({
            'host_location_id': str(host.id),
            'host_location_name': host.name,
            'week_id': str(week.id),
            'primary_game_date': str(game_date),
            'hosting_availability_id': str(availability.id),
        })
    db.commit()
    return {'created': created, 'updated': updated, 'unchanged': unchanged, 'repaired': repaired}


@router.post('/host-availability-matrix/generate-suggested-plan')
def generate_suggested_host_plan(payload: dict, current_user: User = Depends(require_roles(ROLE_LEAGUE_ADMIN)), db: Session = Depends(get_db)):
    _enforce_host_plan_selection_admin(current_user)
    season_id = payload.get('season_id')
    game_date_value = payload.get('game_date')
    if not season_id or not game_date_value:
        raise HTTPException(400, 'season_id and game_date are required')
    game_date = date.fromisoformat(str(game_date_value))
    week = db.query(Week).filter(Week.season_id == season_id, Week.primary_game_date == game_date).first()
    if not week:
        raise HTTPException(400, 'game_date must match a Season Week Primary Game Date')
    if _week_date_type(week) == BLACKOUT_DATE_TYPE:
        raise HTTPException(400, 'Blackout dates are visible but excluded from scheduling plans')

    required = _weekly_required_games_by_size(db, season_id)
    total_required = sum(int(value or 0) for value in required.values())
    active_hosts = db.query(HostLocation).filter(HostLocation.is_active.is_(True)).order_by(HostLocation.name).all()
    availability_rows: list[tuple[HostingAvailability, HostLocation]] = []
    for host in active_hosts:
        resolved = _resolve_hosting_availability(db, season_id, week, game_date, host.id, repair=True, host=host)
        availability = resolved.get('availability')
        if availability and _availability_allows_generated_slots(db, availability):
            exact_rows = _exact_host_plan_availability_query(db, season_id, week.id, game_date, host.id).order_by(HostingAvailability.start_time, HostingAvailability.end_time).all()
            for row in exact_rows or [availability]:
                availability_rows.append((row, host))

    availability_by_host: dict[uuid.UUID, HostingAvailability] = {}
    host_by_id: dict[uuid.UUID, HostLocation] = {}
    capacity_by_host: dict[uuid.UUID, dict[str, int]] = {}
    generated_slot_capacity: dict[uuid.UUID, dict[str, int]] = {}
    generated_slot_minutes_by_host: dict[uuid.UUID, set[int]] = {}
    generated_slots = db.query(GameSlot).filter(
        GameSlot.season_id == season_id,
        GameSlot.week_id == week.id,
        GameSlot.slot_date == game_date,
        GameSlot.assigned_game_id.is_(None),
        GameSlot.status == 'OPEN',
    ).all()
    for slot in generated_slots:
        if not slot.host_location_id:
            continue
        size = _normalize_field_size(slot.field_type)
        if size not in FIELD_SIZE_ORDER:
            continue
        generated_slot_capacity.setdefault(slot.host_location_id, _empty_field_size_counts())[size] += 1
        minute = _minutes_from_time(slot.start_time)
        if minute is not None:
            generated_slot_minutes_by_host.setdefault(slot.host_location_id, set()).add(minute)

    availability_lists_by_host: dict[uuid.UUID, list[HostingAvailability]] = {}
    for availability, host in availability_rows:
        host_by_id.setdefault(host.id, host)
        availability_by_host.setdefault(host.id, availability)
        availability_lists_by_host.setdefault(host.id, []).append(availability)
    for host_id, host in host_by_id.items():
        availability_list = availability_lists_by_host.get(host_id, [])
        if availability_list:
            capacity_by_host[host_id] = _aggregate_availability_capacity_by_size(db, host, availability_list)
        elif host_id in generated_slot_capacity:
            capacity_by_host[host_id] = generated_slot_capacity.get(host_id) or _empty_field_size_counts()

    existing_rows = db.query(HostPlanSelection).filter(
        HostPlanSelection.season_id == season_id,
        HostPlanSelection.game_date == game_date,
    ).all()
    missing_selected_host_ids = {
        row.host_location_id
        for row in existing_rows
        if row.host_location_id not in host_by_id and (row.status in HOST_PLAN_SCHEDULABLE_STATUSES or row.locked)
    }
    if missing_selected_host_ids:
        logger.warning(
            'Suggested host plan ignored selected hosts without matching Hosting Availability season_id=%s game_date=%s host_location_ids=%s',
            season_id,
            game_date,
            ','.join(str(host_id) for host_id in sorted(missing_selected_host_ids, key=str)),
        )
    existing_by_host = {row.host_location_id: row for row in existing_rows}
    selected_host_ids: set[uuid.UUID] = {
        row.host_location_id
        for row in existing_rows
        if row.host_location_id in host_by_id and row.host_location_id in availability_by_host and (row.status in HOST_PLAN_SCHEDULABLE_STATUSES or row.locked)
    }
    excluded_host_ids: set[uuid.UUID] = {
        row.host_location_id
        for row in existing_rows
        if row.host_location_id in host_by_id and row.status == 'EXCLUDED' and not row.locked
    }

    def _combined_capacity(host_ids: set[uuid.UUID]) -> dict[str, int]:
        combined = _empty_field_size_counts()
        for host_id in host_ids:
            for size in FIELD_SIZE_ORDER:
                combined[size] += int((capacity_by_host.get(host_id) or {}).get(size, 0) or 0)
        return combined

    odd_division_requires_doubleheader = any(
        int(team_count or 0) % 2 == 1 and int(team_count or 0) > 1
        for (team_count,) in db.query(func.count(Team.id)).join(Division, Team.division_id == Division.id).filter(
            Team.is_active.is_(True),
            Division.is_active.is_(True),
        ).group_by(Division.id).all()
    )

    def _has_adjacent_doubleheader(host_ids: set[uuid.UUID]) -> bool:
        if not odd_division_requires_doubleheader:
            return True
        for host_id in host_ids:
            minutes = generated_slot_minutes_by_host.get(host_id, set())
            if any((minute + 60) in minutes for minute in minutes):
                return True
        # If slots have not been generated yet, do not treat missing slot rows as a hard
        # doubleheader failure; generated-slot validation will enforce adjacency later.
        return not generated_slots

    def _home_field_satisfied(host_ids: set[uuid.UUID]) -> bool:
        selected_orgs = {host_by_id[host_id].organization_id for host_id in host_ids if host_id in host_by_id}
        return all(any(host_by_id[host_id].organization_id == org_id and sum((capacity_by_host.get(host_id) or {}).values()) > 0 for host_id in host_ids) for org_id in selected_orgs)

    def _sufficiency(host_ids: set[uuid.UUID]) -> tuple[bool, list[str]]:
        return _host_plan_capacity_sufficiency(
            _combined_capacity(host_ids),
            required,
            doubleheader_adjacency_available=_has_adjacent_doubleheader(host_ids),
            home_field_requirement_satisfied=_home_field_satisfied(host_ids),
        )

    added_host_ids: set[uuid.UUID] = set()
    selected_sufficient = False
    insufficiency_reasons: list[str] = []
    additional_host_reason_reasons: list[str] = []
    if selected_host_ids:
        selected_sufficient, insufficiency_reasons = _sufficiency(selected_host_ids)

    if not selected_host_ids or not selected_sufficient:
        candidate_ids = [host_id for host_id in host_by_id if host_id in availability_by_host and host_id not in selected_host_ids and host_id not in excluded_host_ids]
        if not selected_host_ids:
            insufficiency_reasons = ['no host communities are currently selected']
        additional_host_reason_reasons = list(insufficiency_reasons)
        for host_id in sorted(candidate_ids, key=lambda hid: (host_by_id[hid].name or '', str(hid))):
            selected_host_ids.add(host_id)
            added_host_ids.add(host_id)
            selected_sufficient, insufficiency_reasons = _sufficiency(selected_host_ids)
            if selected_sufficient:
                break
        if not selected_sufficient:
            # Only when non-excluded capacity cannot satisfy the week, allow an excluded
            # location to become overflow. This is the capacity-failure exception to the
            # explicit exclusion rule.
            for host_id in sorted(excluded_host_ids - selected_host_ids, key=lambda hid: (host_by_id[hid].name or '', str(hid))):
                selected_host_ids.add(host_id)
                added_host_ids.add(host_id)
                selected_sufficient, insufficiency_reasons = _sufficiency(selected_host_ids)
                if selected_sufficient:
                    break

    selected_capacity = _combined_capacity(selected_host_ids)
    selected_capacity_source_summary = []
    for host_id in sorted(selected_host_ids, key=lambda hid: (host_by_id[hid].organization.name if host_by_id.get(hid) and host_by_id[hid].organization else '', host_by_id[hid].name if host_by_id.get(hid) else '', str(hid))):
        if host_id not in host_by_id:
            continue
        host = host_by_id[host_id]
        availability = availability_by_host.get(host_id)
        if availability:
            source = 'Hosting Availability records'
        elif host_id in generated_slot_capacity:
            source = 'Generated Slots'
        else:
            source = 'Saved Host Plan selection'
        selected_capacity_source_summary.append(_selected_capacity_source_detail(
            db,
            host,
            host.organization.name if host.organization else str(host.organization_id),
            availability,
            capacity_by_host.get(host_id) or _empty_field_size_counts(),
            source,
        ))
    selected_communities = sorted({host_by_id[host_id].organization.name if host_by_id[host_id].organization else str(host_by_id[host_id].organization_id) for host_id in selected_host_ids if host_id in host_by_id})
    excluded_communities = sorted({host_by_id[host_id].organization.name if host_by_id[host_id].organization else str(host_by_id[host_id].organization_id) for host_id in excluded_host_ids if host_id in host_by_id and host_id not in selected_host_ids})
    additional_host_needed = bool(added_host_ids)
    reason_additional = '; '.join(additional_host_reason_reasons or insufficiency_reasons) if additional_host_needed and (additional_host_reason_reasons or insufficiency_reasons) else None
    if selected_host_ids and not added_host_ids and selected_sufficient:
        decision_message = 'Selected host plan has sufficient capacity. No additional host community is needed.'
    elif additional_host_needed:
        decision_message = f'Additional host recommended because: {reason_additional or "selected capacity was insufficient"}.'
    else:
        decision_message = 'No compatible host locations found.'

    selected = 0
    for host_id, host in host_by_id.items():
        availability = availability_by_host.get(host_id)
        row = existing_by_host.get(host_id)
        if row and row.locked:
            continue
        if not row:
            row = HostPlanSelection(season_id=season_id, game_date=game_date, host_location_id=host.id, community_id=host.organization_id)
            db.add(row)
        row.week_id = week.id if week else (availability.week_id if availability else None)
        row.community_id = host.organization_id
        row.availability_id = availability.id if availability else row.availability_id
        if host_id in selected_host_ids:
            row.status = 'OVERFLOW' if host_id in added_host_ids and host_id in excluded_host_ids else 'SELECTED'
            row.reason = 'Generated suggested host plan' if host_id not in added_host_ids else f'Additional host recommended because: {reason_additional or "selected capacity was insufficient"}'
            selected += 1
        else:
            row.status = 'EXCLUDED'
            row.reason = 'Available but not needed by suggested plan'
        row.locked = False

    decision_summary = {
        'diagnostic_label': 'Weekly Host Plan Decision Summary',
        'selected_communities': selected_communities,
        'excluded_communities': excluded_communities,
        'total_games_required': total_required,
        'selected_total_capacity': sum(selected_capacity.values()),
        'selected_small_capacity': selected_capacity.get(FIELD_SIZE_SMALL, 0),
        'selected_medium_capacity': selected_capacity.get(FIELD_SIZE_MEDIUM, 0),
        'selected_large_capacity': selected_capacity.get(FIELD_SIZE_LARGE, 0),
        'doubleheader_adjacency_available': _has_adjacent_doubleheader(selected_host_ids),
        'home_field_requirement_satisfied': _home_field_satisfied(selected_host_ids),
        'additional_host_needed': additional_host_needed,
        'reason_additional_host_was_added': reason_additional,
        'selected_capacity_source_summary': selected_capacity_source_summary,
    }
    db.commit()
    response = _host_availability_matrix_response(db, uuid.UUID(str(season_id)))
    response['generated_selected_count'] = selected
    response['decision_message'] = decision_message
    response['weekly_host_plan_decision_summary'] = decision_summary
    return response


@router.post('/host-availability-matrix/week-lock')
def set_host_plan_week_lock(payload: dict, current_user: User = Depends(require_roles(ROLE_LEAGUE_ADMIN)), db: Session = Depends(get_db)):
    _enforce_host_plan_selection_admin(current_user)
    season_id = payload.get('season_id')
    game_date_value = payload.get('game_date')
    locked = bool(payload.get('locked', True))
    if not season_id or not game_date_value:
        raise HTTPException(400, 'season_id and game_date are required')
    game_date = date.fromisoformat(str(game_date_value))
    count = db.query(HostPlanSelection).filter(HostPlanSelection.season_id == season_id, HostPlanSelection.game_date == game_date).update({'locked': locked}, synchronize_session=False)
    db.commit()
    return {'updated': count, 'locked': locked}


@router.delete('/host-availability-matrix/selections')
def clear_host_plan_selections(season_id: uuid.UUID, game_date: str | None = None, current_user: User = Depends(require_roles(ROLE_LEAGUE_ADMIN)), db: Session = Depends(get_db)):
    _enforce_host_plan_selection_admin(current_user)
    query = db.query(HostPlanSelection).filter(HostPlanSelection.season_id == season_id)
    if game_date:
        query = query.filter(HostPlanSelection.game_date == date.fromisoformat(game_date))
    count = query.delete(synchronize_session=False)
    db.commit()
    return {'deleted': count}


@router.post('/host-availability-matrix/repair-selections')
def repair_host_plan_selections(payload: dict, current_user: User = Depends(require_roles(ROLE_LEAGUE_ADMIN)), db: Session = Depends(get_db)):
    _enforce_host_plan_selection_admin(current_user)
    season_id = payload.get('season_id')
    if not season_id:
        raise HTTPException(400, 'season_id is required')
    game_date_filter = _normalize_local_date_only(payload.get('game_date')) if payload.get('game_date') else None
    query = db.query(HostPlanSelection).filter(HostPlanSelection.season_id == season_id)
    if game_date_filter:
        query = query.filter(HostPlanSelection.game_date == game_date_filter)
    rows = query.order_by(HostPlanSelection.game_date, HostPlanSelection.created_at).all()
    repaired: list[dict[str, object]] = []
    unchanged = 0
    for row in rows:
        if not _host_plan_selection_requires_availability(row):
            unchanged += 1
            continue
        week = row.week if row.week_id else db.query(Week).filter(
            Week.season_id == row.season_id,
            Week.primary_game_date == row.game_date,
        ).first()
        availability, lookup_method = _find_host_plan_availability(db, row.season_id, week, row.game_date, row.host_location_id)
        if availability:
            if row.availability_id != availability.id:
                old_availability_id = row.availability_id
                row.availability_id = availability.id
                repaired.append({
                    'host_plan_selection_id': str(row.id),
                    'host_location_id': str(row.host_location_id),
                    'game_date': str(row.game_date),
                    'old_status': row.status,
                    'new_status': row.status,
                    'old_availability_id': str(old_availability_id) if old_availability_id else None,
                    'new_availability_id': str(availability.id),
                    'correction': 'linked_matching_hosting_availability',
                    'lookup_method': lookup_method,
                })
            else:
                unchanged += 1
            continue
        old_availability_id = row.availability_id
        row.availability_id = None
        row.reason = HOST_PLAN_SELECTED_MISSING_AVAILABILITY_MESSAGE
        correction = {
            'host_plan_selection_id': str(row.id),
            'host_location_id': str(row.host_location_id),
            'game_date': str(row.game_date),
            'old_status': row.status,
            'new_status': row.status,
            'old_locked': row.locked,
            'new_locked': row.locked,
            'old_availability_id': str(old_availability_id) if old_availability_id else None,
            'new_availability_id': None,
            'correction': 'create_missing_hosting_availability_required',
            'admin_action': 'Create Missing Hosting Availability Record',
            'reason': HOST_PLAN_SELECTED_MISSING_AVAILABILITY_MESSAGE,
        }
        logger.info('Repair Host Plan Selections correction: %s', correction)
        repaired.append(correction)
    db.commit()
    return {'repaired': len(repaired), 'unchanged': unchanged, 'corrections': repaired}


@router.post('/divisions', response_model=DivisionRead, dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def create_division(payload: DivisionCreate, db: Session = Depends(get_db)):
    d = Division(**payload.model_dump()); db.add(d); db.commit(); db.refresh(d); return d

@router.get('/divisions', response_model=PagedResponse[DivisionRead], dependencies=[Depends(get_current_user)])
def list_divisions(search: str | None = None, page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    ensure_league_defined_divisions(db)
    q = db.query(Division)
    if search: q = q.filter(func.lower(Division.name).like(f"%{search.lower()}%"))
    return paginate(q.order_by(Division.division_group, Division.sort_order, Division.name), page, page_size)

@router.put('/divisions/{item_id}', response_model=DivisionRead, dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def upd_div(item_id: uuid.UUID, payload: DivisionCreate, db: Session = Depends(get_db)):
    x = db.query(Division).filter(Division.id == item_id).first()
    if not x: raise HTTPException(404, 'Division not found')
    for k, v in payload.model_dump().items(): setattr(x, k, v)
    db.commit(); db.refresh(x); return x

@router.delete('/divisions/{item_id}', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def del_div(item_id: uuid.UUID, db: Session = Depends(get_db)):
    x = db.query(Division).filter(Division.id == item_id).first()
    if not x: raise HTTPException(404, 'Division not found')
    db.delete(x); db.commit(); return {'ok': True}


@router.get('/organization-division-participation', response_model=list[OrganizationDivisionParticipationRead], dependencies=[Depends(get_current_user)])
def list_organization_division_participation(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enforce_organization_scope(organization_id, current_user)
    ensure_league_defined_divisions(db)
    rows = (
        db.query(OrganizationDivisionParticipation)
        .filter(OrganizationDivisionParticipation.organization_id == organization_id)
        .all()
    )
    return rows


@router.put('/organization-division-participation', response_model=list[OrganizationDivisionParticipationRead], dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def upsert_organization_division_participation(
    payload: OrganizationDivisionParticipationBulkUpsertRequest,
    current_user: User = Depends(require_roles(ROLE_LEAGUE_ADMIN)),
    db: Session = Depends(get_db),
):
    enforce_organization_scope(payload.organization_id, current_user)
    ensure_league_defined_divisions(db)
    for item in payload.items:
        if item.team_count < 0:
            raise HTTPException(400, 'Team count must be zero or greater')
        normalized_team_count = int(item.team_count) if item.team_count > 0 else 0
        is_participating = normalized_team_count > 0
        existing = db.query(OrganizationDivisionParticipation).filter(
            OrganizationDivisionParticipation.organization_id == payload.organization_id,
            OrganizationDivisionParticipation.division_id == item.division_id,
        ).first()
        if existing:
            existing.is_participating = is_participating
            existing.team_count = normalized_team_count
            existing.is_active = True
        else:
            db.add(OrganizationDivisionParticipation(
                organization_id=payload.organization_id,
                division_id=item.division_id,
                is_participating=is_participating,
                team_count=normalized_team_count,
                is_active=True,
            ))
    db.commit()
    return db.query(OrganizationDivisionParticipation).filter(OrganizationDivisionParticipation.organization_id == payload.organization_id).all()

@router.post('/host-locations', response_model=HostLocationRead, dependencies=[Depends(get_current_user)])
def create_host_location(payload: HostLocationCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enforce_organization_scope(payload.organization_id, current_user)
    surface_type = payload.surface_type or 'GRASS_FIELD'
    if surface_type not in ALLOWED_SURFACE_TYPES:
        raise HTTPException(400, f'Invalid surface type: {surface_type}')
    x = HostLocation(**{**payload.model_dump(), 'surface_type': surface_type}); db.add(x); db.flush()
    _ensure_approved_turf_configurations(db, x)
    db.commit(); db.refresh(x); return x

@router.get('/host-locations', response_model=PagedResponse[HostLocationRead], dependencies=[Depends(get_current_user)])
def list_host_locations(search: str | None = None, organization_id: uuid.UUID | None = None, is_active: bool | None = None, page: int = 1, page_size: int = 20, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    role_name = normalize_role_name(current_user.role.name)
    q = db.query(HostLocation)
    selected_organization_id = organization_id
    if is_community_admin(current_user):
        selected_organization_id = current_user.organization_id
        q = q.filter(HostLocation.organization_id == current_user.organization_id)
    elif organization_id: q = q.filter(HostLocation.organization_id == organization_id)
    if search: q = q.filter(func.lower(HostLocation.name).like(f"%{search.lower()}%"))
    if is_active is not None: q = q.filter(HostLocation.is_active == is_active)
    page_data = paginate(q.order_by(HostLocation.name), page, page_size)
    ensured_any = False
    for item in page_data.items:
        ensured_any = _ensure_approved_turf_configurations(db, item) or ensured_any
    if ensured_any:
        db.commit()
    active_area_host_ids = {host_id for (host_id,) in db.query(PhysicalFieldArea.host_location_id).filter(PhysicalFieldArea.is_active.is_(True)).distinct().all()}
    active_field_host_ids = {host_id for (host_id,) in db.query(Field.host_location_id).filter(Field.is_active.is_(True)).distinct().all()}
    active_config_host_ids = {host_id for (host_id,) in db.query(HostLocationConfiguration.host_location_id).filter(HostLocationConfiguration.is_active.is_(True)).distinct().all()}
    logger.info(
        'Host locations API diagnostics: role=%s user_organization_id=%s selected_organization_id=%s returned_count=%s',
        role_name,
        current_user.organization_id,
        selected_organization_id,
        len(page_data.items),
    )
    for item in page_data.items:
        effective_surface = item.surface_type or 'GRASS_FIELD'
        has_active_field_setup = item.id in active_config_host_ids if effective_surface == 'TURF_STADIUM' else item.id in active_area_host_ids or item.id in active_field_host_ids
        effective_is_active = bool(item.is_active and has_active_field_setup)
        item.has_active_field_setup = has_active_field_setup
        item.effective_is_active = effective_is_active
        item.status_label = 'Active' if effective_is_active else 'Inactive/Unavailable'
        warnings = []
        if item.is_active and not has_active_field_setup:
            warnings.append('No active field setup')
        if not item.surface_type:
            warnings.append('Surface type missing; defaulting to Grass Field')
            item.surface_type = 'GRASS_FIELD'
        item.status_warning = '; '.join(warnings) if warnings else None
    return page_data

@router.put('/host-locations/{item_id}', response_model=HostLocationRead, dependencies=[Depends(get_current_user)])
def upd_host_location(item_id: uuid.UUID, payload: HostLocationCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(HostLocation).filter(HostLocation.id == item_id).first()
    if not x: raise HTTPException(404, 'Host location not found')
    enforce_organization_scope(x.organization_id, current_user)
    enforce_organization_scope(payload.organization_id, current_user)
    surface_type = payload.surface_type or 'GRASS_FIELD'
    if surface_type not in ALLOWED_SURFACE_TYPES:
        raise HTTPException(400, f'Invalid surface type: {surface_type}')
    for k, v in {**payload.model_dump(), 'surface_type': surface_type}.items(): setattr(x, k, v)
    _ensure_approved_turf_configurations(db, x)
    db.commit(); db.refresh(x); return x


@router.post('/host-location-configurations', response_model=HostLocationConfigurationRead, dependencies=[Depends(get_current_user)])
def create_host_location_configuration(payload: HostLocationConfigurationCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    host = db.query(HostLocation).filter(HostLocation.id == payload.host_location_id).first()
    if not host: raise HTTPException(400, 'Invalid host location')
    enforce_organization_scope(host.organization_id, current_user)
    if (host.surface_type or 'GRASS_FIELD') != 'TURF_STADIUM':
        raise HTTPException(400, 'Host location configurations are only available for turf stadium locations')
    config_name = _normalize_configuration_name(payload.configuration_name)
    x = HostLocationConfiguration(host_location_id=payload.host_location_id, configuration_name=config_name, is_active=payload.is_active)
    _apply_turf_configuration_metadata(x, config_name)
    db.add(x); db.commit(); db.refresh(x); return _attach_configuration_instances(x)


@router.get('/host-location-configurations', response_model=PagedResponse[HostLocationConfigurationRead], dependencies=[Depends(get_current_user)])
def list_host_location_configurations(host_location_id: uuid.UUID | None = None, organization_id: uuid.UUID | None = None, page: int = 1, page_size: int = 100, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    role_name = normalize_role_name(current_user.role.name)
    selected_organization_id = organization_id
    q = db.query(HostLocationConfiguration).join(HostLocationConfiguration.host_location)
    if is_community_admin(current_user):
        selected_organization_id = current_user.organization_id
        q = q.filter(HostLocation.organization_id == current_user.organization_id)
    elif organization_id:
        q = q.filter(HostLocation.organization_id == organization_id)
    turf_hosts_query = db.query(HostLocation)
    if is_community_admin(current_user):
        turf_hosts_query = turf_hosts_query.filter(HostLocation.organization_id == current_user.organization_id)
    elif organization_id:
        turf_hosts_query = turf_hosts_query.filter(HostLocation.organization_id == organization_id)
    if host_location_id:
        turf_hosts_query = turf_hosts_query.filter(HostLocation.id == host_location_id)
        q = q.filter(HostLocationConfiguration.host_location_id == host_location_id)
    turf_hosts = turf_hosts_query.filter(HostLocation.surface_type == 'TURF_STADIUM').all()
    ensured_any = False
    for host in turf_hosts:
        ensured_any = _ensure_approved_turf_configurations(db, host) or ensured_any
    if ensured_any:
        db.commit()
    page_data = paginate(q.order_by(HostLocation.name, HostLocationConfiguration.configuration_name), page, page_size)
    logger.info(
        'Host location configurations API diagnostics: role=%s user_organization_id=%s selected_organization_id=%s host_location_id=%s returned_count=%s',
        role_name,
        current_user.organization_id,
        selected_organization_id,
        host_location_id,
        len(page_data.items),
    )
    for config in page_data.items:
        _attach_configuration_instances(config)
    return page_data


@router.put('/host-location-configurations/{item_id}', response_model=HostLocationConfigurationRead, dependencies=[Depends(get_current_user)])
def upd_host_location_configuration(item_id: uuid.UUID, payload: HostLocationConfigurationCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(HostLocationConfiguration).filter(HostLocationConfiguration.id == item_id).first()
    if not x: raise HTTPException(404, 'Host location configuration not found')
    enforce_organization_scope(x.host_location.organization_id, current_user)
    host = db.query(HostLocation).filter(HostLocation.id == payload.host_location_id).first()
    if not host: raise HTTPException(400, 'Invalid host location')
    enforce_organization_scope(host.organization_id, current_user)
    if (host.surface_type or 'GRASS_FIELD') != 'TURF_STADIUM':
        raise HTTPException(400, 'Host location configurations are only available for turf stadium locations')
    config_name = _normalize_configuration_name(payload.configuration_name)
    x.host_location_id = payload.host_location_id
    _apply_turf_configuration_metadata(x, config_name)
    x.is_active = payload.is_active
    db.commit(); db.refresh(x); return _attach_configuration_instances(x)


@router.delete('/host-location-configurations/{item_id}', dependencies=[Depends(get_current_user)])
def del_host_location_configuration(item_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(HostLocationConfiguration).join(HostLocationConfiguration.host_location).filter(HostLocationConfiguration.id == item_id).first()
    if not x: raise HTTPException(404, 'Host location configuration not found')
    enforce_organization_scope(x.host_location.organization_id, current_user)
    in_use = db.query(HostingAvailability).filter(HostingAvailability.selected_configuration_id == item_id).count()
    if in_use:
        x.is_active = False
    else:
        db.delete(x)
    db.commit(); return {'ok': True}


@router.get('/host-locations/{item_id}/delete-check', dependencies=[Depends(get_current_user)])
def get_host_location_delete_check(item_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(HostLocation).filter(HostLocation.id == item_id).first()
    if not x: raise HTTPException(404, 'Host location not found')
    enforce_organization_scope(x.organization_id, current_user)
    dependencies = _host_location_dependency_summary(db, item_id)
    blocking_labels = {'Scheduled Games', 'Generated Slots Assigned to Games'}
    has_blocking_dependencies = any(count > 0 for label, count in dependencies if label in blocking_labels)
    return {
        'host_location_id': str(x.id),
        'host_location_name': x.name,
        'can_delete': not has_blocking_dependencies,
        'reason': None if not has_blocking_dependencies else 'Cannot permanently delete because scheduled games reference this location. Mark inactive instead.',
        'recommended_action': None if not has_blocking_dependencies else 'mark_inactive',
        'delete_message': 'Delete allowed. This will remove unused setup and generated slot records.' if not has_blocking_dependencies else None,
        'dependencies': [{'label': label, 'count': count} for label, count in dependencies],
    }


@router.delete('/host-locations/{item_id}', dependencies=[Depends(get_current_user)])
def del_host_location(item_id: uuid.UUID, force: bool = Query(False), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(HostLocation).filter(HostLocation.id == item_id).first()
    if not x: raise HTTPException(404, 'Host location not found')
    enforce_organization_scope(x.organization_id, current_user)
    dependencies = _host_location_dependency_summary(db, item_id)
    blocking_labels = {'Scheduled Games', 'Generated Slots Assigned to Games'}
    has_blocking_dependencies = any(count > 0 for label, count in dependencies if label in blocking_labels)

    if has_blocking_dependencies:
        return {
            'can_delete': False,
            'reason': 'Cannot permanently delete because scheduled games reference this location. Mark inactive instead.',
            'recommended_action': 'mark_inactive',
            'dependencies': [{'label': label, 'count': count} for label, count in dependencies],
        }
    deleted_game_slots = db.query(GameSlot).filter(
        GameSlot.host_location_id == item_id,
        GameSlot.assigned_game_id.is_(None),
    ).delete(synchronize_session=False)
    deleted_generated_slots = deleted_game_slots
    deleted_field_instances = db.query(FieldInstance).filter(FieldInstance.host_location_id == item_id).delete(synchronize_session=False)
    area_ids = [area_id for (area_id,) in db.query(PhysicalFieldArea.id).filter(PhysicalFieldArea.host_location_id == item_id).all()]
    field_ids = [field_id for (field_id,) in db.query(Field.id).filter(Field.host_location_id == item_id).all()]
    deleted_hosting_availabilities = db.query(HostingAvailability).filter(
        (HostingAvailability.host_location_id == item_id) | (HostingAvailability.field_id.in_(field_ids)) | (HostingAvailability.physical_field_area_id.in_(area_ids))
    ).delete(synchronize_session=False)
    deleted_host_location_configurations = db.query(HostLocationConfiguration).filter(HostLocationConfiguration.host_location_id == item_id).delete(synchronize_session=False)
    deleted_field_configuration_options = db.query(FieldConfigurationOption).filter(FieldConfigurationOption.physical_field_area_id.in_(area_ids)).delete(synchronize_session=False) if area_ids else 0
    deleted_physical_field_areas = db.query(PhysicalFieldArea).filter(PhysicalFieldArea.id.in_(area_ids)).delete(synchronize_session=False) if area_ids else 0
    deleted_fields = db.query(Field).filter(Field.id.in_(field_ids)).delete(synchronize_session=False) if field_ids else 0
    db.delete(x); db.commit()

    return {
        'ok': True,
        'message': 'Delete allowed. This will remove unused setup and generated slot records.',
        'deleted': {
            'host_locations': 1,
            'game_slots': deleted_game_slots,
            'generated_slots': deleted_generated_slots,
            'field_instances': deleted_field_instances,
            'hosting_availabilities': deleted_hosting_availabilities,
            'physical_field_areas': deleted_physical_field_areas,
            'field_configuration_options': deleted_field_configuration_options,
            'host_location_configurations': deleted_host_location_configurations,
            'fields': deleted_fields,
        }
    }

@router.post('/physical-field-areas', response_model=PhysicalFieldAreaRead, dependencies=[Depends(get_current_user)])
def create_physical_field_area(payload: PhysicalFieldAreaCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    host_location = db.query(HostLocation).filter(HostLocation.id == payload.host_location_id).first()
    if not host_location: raise HTTPException(400, 'Invalid host location')
    enforce_organization_scope(host_location.organization_id, current_user)
    if (host_location.surface_type or 'GRASS_FIELD') != 'GRASS_FIELD':
        raise HTTPException(400, 'Physical field areas are only allowed for grass field locations')
    if payload.field_space_type not in ALLOWED_FIELD_SPACE_TYPES:
        raise HTTPException(400, f"Invalid field space type: {payload.field_space_type}")
    x = PhysicalFieldArea(**payload.model_dump()); db.add(x); db.commit(); db.refresh(x); return x

@router.get('/physical-field-areas', response_model=PagedResponse[PhysicalFieldAreaRead], dependencies=[Depends(get_current_user)])
def list_physical_field_areas(host_location_id: uuid.UUID | None = None, page: int = 1, page_size: int = 50, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(PhysicalFieldArea).join(PhysicalFieldArea.host_location)
    if is_community_admin(current_user): q = q.filter(HostLocation.organization_id == current_user.organization_id)
    if host_location_id: q = q.filter(PhysicalFieldArea.host_location_id == host_location_id)
    return paginate(q.order_by(PhysicalFieldArea.name), page, page_size)

@router.put('/physical-field-areas/{item_id}', response_model=PhysicalFieldAreaRead, dependencies=[Depends(get_current_user)])
def upd_physical_field_area(item_id: uuid.UUID, payload: PhysicalFieldAreaCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(PhysicalFieldArea).filter(PhysicalFieldArea.id == item_id).first()
    if not x: raise HTTPException(404, 'Physical field area not found')
    enforce_organization_scope(x.host_location.organization_id, current_user)
    host_location = db.query(HostLocation).filter(HostLocation.id == payload.host_location_id).first()
    if not host_location: raise HTTPException(400, 'Invalid host location')
    enforce_organization_scope(host_location.organization_id, current_user)
    if (host_location.surface_type or 'GRASS_FIELD') != 'GRASS_FIELD':
        raise HTTPException(400, 'Physical field areas are only allowed for grass field locations')
    if payload.field_space_type not in ALLOWED_FIELD_SPACE_TYPES:
        raise HTTPException(400, f"Invalid field space type: {payload.field_space_type}")
    for k, v in payload.model_dump().items(): setattr(x, k, v)
    db.commit(); db.refresh(x); return x

@router.post('/field-configuration-options', response_model=FieldConfigurationOptionRead, dependencies=[Depends(get_current_user)])
def create_field_configuration_option(payload: FieldConfigurationOptionCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    area = db.query(PhysicalFieldArea).join(PhysicalFieldArea.host_location).filter(PhysicalFieldArea.id == payload.physical_field_area_id).first()
    if not area: raise HTTPException(400, 'Invalid physical field area')
    enforce_organization_scope(area.host_location.organization_id, current_user)
    counts = [payload.small_field_count, payload.medium_field_count, payload.large_field_count, payload.thirty_yard_capacity, payload.fifty_three_yard_capacity]
    if any(count < 0 for count in counts):
        raise HTTPException(400, 'Capacities must be non-negative')
    data = payload.model_dump()
    if data['surface_type'] not in ALLOWED_SURFACE_TYPES:
        raise HTTPException(400, f"Invalid surface type: {data['surface_type']}")
    if data['surface_type'] == 'TURF_STADIUM':
        raise HTTPException(400, 'Custom turf configurations are not supported')
    if data['small_field_count'] == 0 and data['thirty_yard_capacity']:
        data['small_field_count'] = data['thirty_yard_capacity']
    if data['large_field_count'] == 0 and data['fifty_three_yard_capacity']:
        data['large_field_count'] = data['fifty_three_yard_capacity']
    if not data['configuration_name']:
        data['configuration_name'] = data['name']
    x = FieldConfigurationOption(**data); db.add(x); db.commit(); db.refresh(x); return x

@router.get('/field-configuration-options', response_model=PagedResponse[FieldConfigurationOptionRead], dependencies=[Depends(get_current_user)])
def list_field_configuration_options(physical_field_area_id: uuid.UUID | None = None, page: int = 1, page_size: int = 50, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(FieldConfigurationOption).join(FieldConfigurationOption.physical_field_area).join(PhysicalFieldArea.host_location)
    if is_community_admin(current_user): q = q.filter(HostLocation.organization_id == current_user.organization_id)
    if physical_field_area_id: q = q.filter(FieldConfigurationOption.physical_field_area_id == physical_field_area_id)
    return paginate(q.order_by(FieldConfigurationOption.name), page, page_size)

@router.put('/field-configuration-options/{item_id}', response_model=FieldConfigurationOptionRead, dependencies=[Depends(get_current_user)])
def upd_field_configuration_option(item_id: uuid.UUID, payload: FieldConfigurationOptionCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(FieldConfigurationOption).filter(FieldConfigurationOption.id == item_id).first()
    if not x: raise HTTPException(404, 'Field configuration option not found')
    enforce_organization_scope(x.physical_field_area.host_location.organization_id, current_user)
    area = db.query(PhysicalFieldArea).join(PhysicalFieldArea.host_location).filter(PhysicalFieldArea.id == payload.physical_field_area_id).first()
    if not area: raise HTTPException(400, 'Invalid physical field area')
    enforce_organization_scope(area.host_location.organization_id, current_user)
    counts = [payload.small_field_count, payload.medium_field_count, payload.large_field_count, payload.thirty_yard_capacity, payload.fifty_three_yard_capacity]
    if any(count < 0 for count in counts):
        raise HTTPException(400, 'Capacities must be non-negative')
    data = payload.model_dump()
    if data['surface_type'] not in ALLOWED_SURFACE_TYPES:
        raise HTTPException(400, f"Invalid surface type: {data['surface_type']}")
    if data['surface_type'] == 'TURF_STADIUM':
        raise HTTPException(400, 'Custom turf configurations are not supported')
    if data['small_field_count'] == 0 and data['thirty_yard_capacity']:
        data['small_field_count'] = data['thirty_yard_capacity']
    if data['large_field_count'] == 0 and data['fifty_three_yard_capacity']:
        data['large_field_count'] = data['fifty_three_yard_capacity']
    if not data['configuration_name']:
        data['configuration_name'] = data['name']
    for k, v in data.items(): setattr(x, k, v)
    db.commit(); db.refresh(x); return x

@router.delete('/field-configuration-options/{item_id}', dependencies=[Depends(get_current_user)])
def del_field_configuration_option(item_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(FieldConfigurationOption).filter(FieldConfigurationOption.id == item_id).first()
    if not x: raise HTTPException(404, 'Field configuration option not found')
    enforce_organization_scope(x.physical_field_area.host_location.organization_id, current_user)
    db.delete(x); db.commit(); return {'ok': True}

@router.post('/fields', response_model=FieldRead, dependencies=[Depends(get_current_user)])
def create_field(payload: FieldCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    host_location = db.query(HostLocation).filter(HostLocation.id == payload.host_location_id).first()
    if not host_location: raise HTTPException(400, 'Invalid host location')
    enforce_organization_scope(host_location.organization_id, current_user)
    if (host_location.surface_type or 'GRASS_FIELD') != 'GRASS_FIELD':
        raise HTTPException(400, 'Manual fields are only allowed for grass field locations')
    if not _normalize_field_size(payload.layout_type):
        raise HTTPException(400, 'Field type must be Small, Medium, or Large')
    if payload.physical_field_area_id:
        area = db.query(PhysicalFieldArea).filter(PhysicalFieldArea.id == payload.physical_field_area_id, PhysicalFieldArea.host_location_id == payload.host_location_id).first()
        if not area: raise HTTPException(400, 'Invalid physical field area for host location')
    x = Field(**{**payload.model_dump(), 'layout_type': _normalize_field_size(payload.layout_type)}); db.add(x); db.commit(); db.refresh(x); return x

@router.get('/fields', response_model=PagedResponse[FieldRead], dependencies=[Depends(get_current_user)])
def list_fields(search: str | None = None, host_location_id: uuid.UUID | None = None, organization_id: uuid.UUID | None = None, page: int = 1, page_size: int = 20, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    role_name = normalize_role_name(current_user.role.name)
    selected_organization_id = organization_id
    q = db.query(Field).join(Field.host_location)
    if is_community_admin(current_user):
        selected_organization_id = current_user.organization_id
        q = q.filter(HostLocation.organization_id == current_user.organization_id)
    elif organization_id:
        q = q.filter(HostLocation.organization_id == organization_id)
    if host_location_id: q = q.filter(Field.host_location_id == host_location_id)
    if search: q = q.filter(func.lower(Field.name).like(f"%{search.lower()}%"))
    page_data = paginate(q.order_by(Field.name), page, page_size)
    logger.info(
        'Fields API diagnostics: role=%s user_organization_id=%s selected_organization_id=%s host_location_id=%s returned_count=%s',
        role_name,
        current_user.organization_id,
        selected_organization_id,
        host_location_id,
        len(page_data.items),
    )
    return page_data

@router.put('/fields/{item_id}', response_model=FieldRead, dependencies=[Depends(get_current_user)])
def upd_field(item_id: uuid.UUID, payload: FieldCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(Field).filter(Field.id == item_id).first()
    if not x: raise HTTPException(404, 'Field not found')
    enforce_organization_scope(x.host_location.organization_id, current_user)
    host_location = db.query(HostLocation).filter(HostLocation.id == payload.host_location_id).first()
    if not host_location: raise HTTPException(400, 'Invalid host location')
    enforce_organization_scope(host_location.organization_id, current_user)
    if (host_location.surface_type or 'GRASS_FIELD') != 'GRASS_FIELD':
        raise HTTPException(400, 'Manual fields are only allowed for grass field locations')
    if not _normalize_field_size(payload.layout_type):
        raise HTTPException(400, 'Field type must be Small, Medium, or Large')
    for k, v in {**payload.model_dump(), 'layout_type': _normalize_field_size(payload.layout_type)}.items(): setattr(x, k, v)
    db.commit(); db.refresh(x); return x

@router.delete('/fields/{item_id}', dependencies=[Depends(get_current_user)])
def del_field(item_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(Field).filter(Field.id == item_id).first()
    if not x: raise HTTPException(404, 'Field not found')
    enforce_organization_scope(x.host_location.organization_id, current_user)
    db.delete(x); db.commit(); return {'ok': True}

def _resolve_availability_host_and_validate(payload, current_user: User, db: Session) -> tuple[HostLocation, Field | None, PhysicalFieldArea | None, HostLocationConfiguration | None]:
    field = None
    area = None
    config = None
    host = None
    if payload.host_location_id:
        host = db.query(HostLocation).filter(HostLocation.id == payload.host_location_id).first()
        if not host: raise HTTPException(400, 'Invalid host location')
        enforce_organization_scope(host.organization_id, current_user)
        if payload.organization_id and payload.organization_id != host.organization_id:
            raise HTTPException(400, 'Host location does not belong to selected organization')
        surface_type = host.surface_type or 'GRASS_FIELD'
        if surface_type == 'TURF_STADIUM':
            if payload.lock_selected_layout and not payload.selected_configuration_id:
                raise HTTPException(400, 'selected_configuration_id is required when a turf layout is locked')
            if payload.selected_configuration_id:
                config = db.query(HostLocationConfiguration).filter(
                    HostLocationConfiguration.id == payload.selected_configuration_id,
                    HostLocationConfiguration.host_location_id == host.id,
                    HostLocationConfiguration.is_active.is_(True),
                ).first()
                if not config: raise HTTPException(400, 'Invalid host location configuration')
                if not _turf_configuration_metadata(config.configuration_name):
                    raise HTTPException(400, 'Unsupported turf stadium configuration')
            elif not payload.auto_select_turf_layout:
                raise HTTPException(400, 'selected_configuration_id is required when auto-select turf layout is disabled')
        else:
            active_grass_fields = _grass_field_templates_for_host(db, host.id)
            if not active_grass_fields:
                raise HTTPException(400, 'Grass field availability requires at least one active configured grass field')
            if payload.selected_configuration_id:
                raise HTTPException(400, 'Grass field availability does not use turf layout selection')
    elif payload.field_id:
        field = db.query(Field).join(Field.host_location).filter(Field.id == payload.field_id).first()
        if not field: raise HTTPException(400, 'Invalid field')
        host = field.host_location
        enforce_organization_scope(host.organization_id, current_user)
        if (host.surface_type or 'GRASS_FIELD') != 'GRASS_FIELD':
            raise HTTPException(400, 'Manual field availability is only available for grass field locations')
        if not field.is_active:
            raise HTTPException(400, 'Inactive fields cannot be used for availability')
        if not _normalize_field_size(field.layout_type):
            raise HTTPException(400, 'Configured grass field is missing a valid field type')
    elif payload.physical_field_area_id:
        area = db.query(PhysicalFieldArea).join(PhysicalFieldArea.host_location).filter(PhysicalFieldArea.id == payload.physical_field_area_id).first()
        if not area: raise HTTPException(400, 'Invalid physical field area')
        host = area.host_location
        enforce_organization_scope(host.organization_id, current_user)
        if not payload.field_configuration_option_id:
            raise HTTPException(400, 'field_configuration_option_id is required for physical field area slots')
        option = db.query(FieldConfigurationOption).filter(FieldConfigurationOption.id == payload.field_configuration_option_id, FieldConfigurationOption.physical_field_area_id == payload.physical_field_area_id, FieldConfigurationOption.is_active.is_(True)).first()
        if not option: raise HTTPException(400, f'Invalid field configuration option: {payload.field_configuration_option_id}')
        if (host.surface_type or 'GRASS_FIELD') != 'GRASS_FIELD':
            raise HTTPException(400, 'Physical field area availability is only available for grass field locations')
    else:
        raise HTTPException(400, 'host_location_id, field_id, or physical_field_area_id is required')
    return host, field, area, config


def _hosting_availability_has_week_id(db: Session) -> bool:
    return 'week_id' in {column['name'] for column in sa_inspect(db.bind).get_columns('hosting_availabilities')}


def _validate_availability_week(payload, db: Session) -> Week:
    week_id = getattr(payload, 'week_id', None)
    if not week_id:
        if _hosting_availability_has_week_id(db):
            raise HTTPException(400, 'week_id is required for hosting availability')
        legacy_week = db.query(Week).filter(Week.primary_game_date == payload.available_date).first()
        if not legacy_week or not legacy_week.primary_game_date:
            raise HTTPException(400, 'week_id is required for hosting availability')
        payload.week_id = legacy_week.id
        payload.season_id = legacy_week.season_id
        payload.primary_game_date = legacy_week.primary_game_date
        return legacy_week
    week = db.query(Week).filter(Week.id == week_id).first()
    if not week:
        raise HTTPException(400, 'Invalid weekId for hosting availability')
    if not week.primary_game_date:
        raise HTTPException(400, 'Hosting availability cannot be created because the week has no Primary Game Date')
    if getattr(payload, 'season_id', None) and payload.season_id != week.season_id:
        raise HTTPException(400, 'weekId does not belong to the selected season')
    if getattr(payload, 'available_date', None) and payload.available_date != week.primary_game_date:
        payload.available_date = week.primary_game_date
    payload.primary_game_date = week.primary_game_date
    payload.season_id = week.season_id
    return week

@router.post('/hosting-availabilities', response_model=HostingAvailabilityRead, dependencies=[Depends(get_current_user)])
def create_hosting_availability(payload: HostingAvailabilityCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    week = _validate_availability_week(payload, db)
    host, field, area, config = _resolve_availability_host_and_validate(payload, current_user, db)
    x = HostingAvailability(**payload.model_dump())
    x.organization_id = host.organization_id
    x.host_location_id = host.id
    db.add(x); db.flush()
    _sync_host_plan_selection_availability(db, x)
    _regenerate_generated_slots(db, x, host.id)
    db.commit(); db.refresh(x); return x

@router.get('/hosting-availabilities', response_model=PagedResponse[HostingAvailabilityRead], dependencies=[Depends(get_current_user)])
def list_hosting_availabilities(field_id: uuid.UUID | None = None, field_ids: str | None = None, host_location_id: uuid.UUID | None = None, organization_id: uuid.UUID | None = None, available_date: str | None = None, available_dates: str | None = None, page: int = 1, page_size: int = 20, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(HostingAvailability).outerjoin(HostingAvailability.host_location).outerjoin(HostingAvailability.field)
    if is_community_admin(current_user): q = q.filter(or_(HostLocation.organization_id == current_user.organization_id, HostingAvailability.organization_id == current_user.organization_id, HostingAvailability.field_id.in_(db.query(Field.id).join(Field.host_location).filter(HostLocation.organization_id == current_user.organization_id))))
    elif organization_id: q = q.filter(or_(HostLocation.organization_id == organization_id, HostingAvailability.organization_id == organization_id, HostingAvailability.field_id.in_(db.query(Field.id).join(Field.host_location).filter(HostLocation.organization_id == organization_id))))
    if host_location_id: q = q.filter(or_(HostingAvailability.host_location_id == host_location_id, Field.host_location_id == host_location_id))
    if field_id: q = q.filter(HostingAvailability.field_id == field_id)
    if field_ids:
        parsed = [uuid.UUID(x.strip()) for x in field_ids.split(',') if x.strip()]
        if parsed: q = q.filter(HostingAvailability.field_id.in_(parsed))
    if available_date: q = q.filter(func.cast(HostingAvailability.available_date, str) == available_date)
    if available_dates:
        q = q.filter(func.cast(HostingAvailability.available_date, str).in_([x.strip() for x in available_dates.split(',') if x.strip()]))
    return paginate(q.order_by(HostingAvailability.available_date, HostingAvailability.start_time), page, page_size)

@router.put('/hosting-availabilities/{item_id}', response_model=HostingAvailabilityRead, dependencies=[Depends(get_current_user)])
def upd_hosting_availability(item_id: uuid.UUID, payload: HostingAvailabilityCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(HostingAvailability).filter(HostingAvailability.id == item_id).first()
    if not x: raise HTTPException(404, 'Hosting availability not found')
    existing_host = x.host_location or (x.physical_field_area.host_location if x.physical_field_area else None) or (x.field.host_location if x.field else None)
    if not existing_host: raise HTTPException(400, 'Hosting availability is missing host location data')
    enforce_organization_scope(existing_host.organization_id, current_user)
    week = _validate_availability_week(payload, db)
    host, field, area, config = _resolve_availability_host_and_validate(payload, current_user, db)
    for k, v in payload.model_dump().items(): setattr(x, k, v)
    x.organization_id = host.organization_id
    x.host_location_id = host.id
    db.flush()
    _sync_host_plan_selection_availability(db, x)
    _regenerate_generated_slots(db, x, host.id)
    db.commit(); db.refresh(x); return x

@router.delete('/hosting-availabilities/{item_id}', dependencies=[Depends(get_current_user)])
def del_hosting_availability(item_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(HostingAvailability).filter(HostingAvailability.id == item_id).first()
    if not x: raise HTTPException(404, 'Hosting availability not found')
    host = x.host_location or (x.physical_field_area.host_location if x.physical_field_area else None) or (x.field.host_location if x.field else None)
    if not host: raise HTTPException(400, 'Hosting availability is missing host location data')
    enforce_organization_scope(host.organization_id, current_user)
    host_location_id = host.id
    _delete_availability_with_generated_slots_guard(db, [x.id], host_location_id, x.available_date)
    db.delete(x); db.commit(); return {'ok': True}



@router.post('/hosting-availabilities/bulk-upsert', response_model=HostingAvailabilityBulkUpsertResponse, dependencies=[Depends(get_current_user)])
def bulk_upsert_hosting_availabilities(payload: HostingAvailabilityBulkUpsertRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    created = 0
    updated = 0
    for slot in payload.slots:
        week = _validate_availability_week(slot, db)
        host, field, area, config = _resolve_availability_host_and_validate(slot, current_user, db)
        existing_query = db.query(HostingAvailability).filter(
            HostingAvailability.season_id == week.season_id,
            HostingAvailability.week_id == week.id,
            HostingAvailability.host_location_id == host.id,
            HostingAvailability.primary_game_date == week.primary_game_date,
            HostingAvailability.field_id == slot.field_id,
            HostingAvailability.physical_field_area_id == slot.physical_field_area_id,
            HostingAvailability.start_time == slot.start_time,
            HostingAvailability.end_time == slot.end_time,
            HostingAvailability.layout_type == slot.layout_type,
            HostingAvailability.slot_index == slot.slot_index,
        )
        is_turf_host_slot = (host.surface_type or 'GRASS_FIELD') == 'TURF_STADIUM' and slot.host_location_id is not None
        if not is_turf_host_slot:
            existing_query = existing_query.filter(HostingAvailability.selected_configuration_id == slot.selected_configuration_id)
        existing = existing_query.first()
        if existing:
            existing.season_id = week.season_id
            existing.week_id = week.id
            existing.available_date = week.primary_game_date
            existing.primary_game_date = week.primary_game_date
            existing.active = slot.active
            existing.is_available = slot.is_available
            existing.notes = slot.notes
            existing.selected_configuration_id = slot.selected_configuration_id
            existing.auto_select_turf_layout = slot.auto_select_turf_layout
            existing.lock_selected_layout = slot.lock_selected_layout
            existing.allow_turf_layout_changes = slot.allow_turf_layout_changes
            existing.admin_override_incompatible_field_size = slot.admin_override_incompatible_field_size
            _sync_host_plan_selection_availability(db, existing)
            updated += 1
            _regenerate_generated_slots(db, existing, host.id)
        else:
            availability = HostingAvailability(**slot.model_dump())
            availability.season_id = week.season_id
            availability.week_id = week.id
            availability.available_date = week.primary_game_date
            availability.primary_game_date = week.primary_game_date
            availability.organization_id = host.organization_id
            availability.host_location_id = host.id
            db.add(availability)
            db.flush()
            _sync_host_plan_selection_availability(db, availability)
            _regenerate_generated_slots(db, availability, host.id)
            created += 1
    db.commit()
    generated_field_instances = db.query(FieldInstance).join(FieldInstance.host_location)
    generated_slots = db.query(GameSlot).join(GameSlot.host_location)
    if is_community_admin(current_user):
        generated_field_instances = generated_field_instances.filter(HostLocation.organization_id == current_user.organization_id)
        generated_slots = generated_slots.filter(HostLocation.organization_id == current_user.organization_id)
    return HostingAvailabilityBulkUpsertResponse(
        created=created,
        updated=updated,
        generated_field_instances=generated_field_instances.count(),
        generated_slots=generated_slots.count(),
    )


def _availability_week_fields(row: HostingAvailability) -> dict:
    week = row.week
    effective_date = (week.primary_game_date if week and week.primary_game_date else row.primary_game_date or row.available_date)
    return {
        'season_id': week.season_id if week else row.season_id,
        'week_id': week.id if week else row.week_id,
        'week_number': week.week_number if week else None,
        'week_label': week.label if week else None,
        'week_status': week.status if week else None,
        'primary_game_date': effective_date,
        'available_date': effective_date,
    }

@router.get('/hosting-availabilities/saved', response_model=SavedAvailabilityResponse, dependencies=[Depends(get_current_user)])
def list_saved_hosting_availability(season_id: uuid.UUID | None = None, organization_id: uuid.UUID | None = None, host_location_id: uuid.UUID | None = None, site_type: str | None = None, layout: str | None = None, available_date: str | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    season_game_dates = {
        _week_game_date(week)
        for week in db.query(Week).filter(Week.season_id == season_id).all()
        if _week_game_date(week)
    } if season_id else set()
    q = db.query(HostingAvailability).join(HostingAvailability.physical_field_area).join(PhysicalFieldArea.host_location).outerjoin(HostingAvailability.field_configuration_option).filter(HostingAvailability.is_available.is_(True))
    if season_id:
        q = q.filter(HostingAvailability.season_id == season_id)
        if season_game_dates:
            q = q.filter(HostingAvailability.available_date.in_(list(season_game_dates)))
    if is_community_admin(current_user):
        q = q.filter(HostLocation.organization_id == current_user.organization_id)
    elif organization_id:
        q = q.filter(HostLocation.organization_id == organization_id)
    if host_location_id:
        q = q.filter(HostLocation.id == host_location_id)
    if site_type:
        q = q.filter(PhysicalFieldArea.field_space_type == site_type)
    if layout:
        q = q.filter(FieldConfigurationOption.name == layout)
    if available_date:
        q = q.filter(func.cast(HostingAvailability.available_date, str) == available_date)

    rows = q.order_by(HostingAvailability.available_date, HostLocation.name, PhysicalFieldArea.name, HostingAvailability.start_time).all()
    host_ids = {row.physical_field_area.host_location.id for row in rows if row.physical_field_area and row.physical_field_area.host_location}
    def _normalize_field_type(raw_layout_type: str | None) -> str | None:
        normalized = str(raw_layout_type or '').strip().lower()
        if not normalized:
            return None
        compact = normalized.replace('_', '').replace('-', '').replace(' ', '')
        if normalized in {'small'} or compact in {'small', '30', '30yard', '30yards', 'thirtyyard', 'thirtyyards', 'thirty'}:
            return 'small'
        if normalized in {'large'} or compact in {'large', '53', '53yard', '53yards', 'fiftythree', 'fiftythreeyard', 'fiftythreeyards'}:
            return 'large'
        tokenized = compact
        if ('small' in normalized or 'thirty' in normalized or '30' in normalized or 'youth' in normalized or 'k2' in tokenized):
            return 'small'
        if ('large' in normalized or 'fifty' in normalized or '53' in normalized or 'full' in normalized or 'adult' in normalized):
            return 'large'
        return None

    field_counts_by_layout: dict[tuple[str, str], dict[str, int | bool | list[dict[str, str | bool | int | None]]]] = {}
    if host_ids:
        host_lookup = {str(host.id): host.name for host in db.query(HostLocation).filter(HostLocation.id.in_(host_ids)).all()}
        field_rows = db.query(
            Field.host_location_id.label('host_location_id'),
            Field.name.label('field_name'),
            Field.layout_type.label('layout_type'),
            Field.is_active.label('is_active'),
        ).filter(Field.host_location_id.in_(host_ids)).all()
        for field_row in field_rows:
            logger.info(
                'Hosting field raw record host_location_id=%s field_name=%s raw_field_type_value=%s is_active=%s',
                str(field_row.host_location_id),
                str(field_row.field_name or ''),
                str(field_row.layout_type or ''),
                bool(field_row.is_active),
            )
    grouped: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        if not row.physical_field_area:
            continue
        area = row.physical_field_area
        host = area.host_location
        option = row.field_configuration_option
        layout_name = option.name if option else 'Custom Layout'
        host_id = str(host.id)
        key = (str(row.available_date), str(area.id), layout_name)
        if key not in grouped:
            layout_small = int((option.small_field_count or option.thirty_yard_capacity) if option and option.is_active else 0)
            layout_medium = int(option.medium_field_count if option and option.is_active else 0)
            layout_large = int((option.large_field_count or option.fifty_three_yard_capacity) if option and option.is_active else 0)
            layout_key = (host_id, layout_name)
            layout_counts = field_counts_by_layout.setdefault(
                layout_key,
                {'small': layout_small, 'medium': layout_medium, 'large': layout_large, 'total': layout_small + layout_medium + layout_large, 'inactive': 0, 'unmatched': 0, 'mismatch': False, 'fields': []},
            )
            layout_counts['small'] = layout_small
            layout_counts['medium'] = layout_medium
            layout_counts['large'] = layout_large
            layout_counts['total'] = layout_small + layout_medium + layout_large
            layout_counts['mismatch'] = layout_small + layout_medium + layout_large == 0
            grouped[key] = {
                'id': row.id,
                **_availability_week_fields(row),
                'organization_id': host.organization_id,
                'organization_name': host.organization.name if host.organization else None,
                'host_location_id': host.id,
                'host_location_name': host.name,
                'site_type': area.field_space_type,
                'available_layout': layout_name,
                'small_field_capacity': layout_counts['small'],
                'medium_field_capacity': layout_counts.get('medium', 0),
                'large_field_capacity': layout_counts['large'],
                'total_fields_found': layout_counts['total'],
                'inactive_field_count': layout_counts['inactive'],
                'unmatched_field_records': layout_counts['unmatched'],
                'has_field_inventory_mismatch': layout_counts['mismatch'],
                'fields': [
                    {
                        'configuration_option_id': str(option.id) if option else None,
                        'configuration_option_name': layout_name,
                        'raw_field_type_value': option.name if option else None,
                        'small_field_count': layout_counts['small'],
                        'medium_field_count': layout_counts.get('medium', 0),
                        'large_field_count': layout_counts['large'],
                        'is_active': bool(option.is_active) if option else False,
                    }
                ],
                'auto_select_turf_layout': bool(getattr(row, 'auto_select_turf_layout', True)),
                'lock_selected_layout': bool(getattr(row, 'lock_selected_layout', False)),
                'hours': []
            }
        grouped[key]['hours'].append(row.start_time.hour)


    direct_q = db.query(HostingAvailability).join(HostingAvailability.host_location).outerjoin(HostingAvailability.selected_configuration).filter(
        HostingAvailability.is_available.is_(True),
        HostingAvailability.host_location_id.is_not(None),
        HostingAvailability.field_id.is_(None),
        HostingAvailability.physical_field_area_id.is_(None),
    )
    if season_id:
        direct_q = direct_q.filter(HostingAvailability.season_id == season_id)
        if season_game_dates:
            direct_q = direct_q.filter(HostingAvailability.available_date.in_(list(season_game_dates)))
    if is_community_admin(current_user):
        direct_q = direct_q.filter(HostLocation.organization_id == current_user.organization_id)
    elif organization_id:
        direct_q = direct_q.filter(HostLocation.organization_id == organization_id)
    if host_location_id:
        direct_q = direct_q.filter(HostLocation.id == host_location_id)
    if site_type:
        direct_q = direct_q.filter(HostLocation.surface_type == site_type)
    if layout:
        direct_q = direct_q.filter(HostLocationConfiguration.configuration_name == _normalize_configuration_name(layout))
    if available_date:
        direct_q = direct_q.filter(func.cast(HostingAvailability.available_date, str) == available_date)
    for row in direct_q.order_by(HostingAvailability.available_date, HostLocation.name, HostingAvailability.start_time).all():
        host = row.host_location
        config = row.selected_configuration
        if (host.surface_type or 'GRASS_FIELD') == 'TURF_STADIUM':
            layout_name = config.configuration_name if config else 'Auto Select Best Layout'
            templates = _configuration_field_templates(config.configuration_name if config else None, None)
        else:
            layout_name = 'Active Grass Fields'
            templates = _grass_field_templates_for_host(db, host.id)
        small = sum(1 for _, field_type in templates if field_type == 'SMALL')
        medium = sum(1 for _, field_type in templates if field_type == 'MEDIUM')
        large = sum(1 for _, field_type in templates if field_type == 'LARGE')
        key = (str(row.available_date), str(host.id), layout_name)
        if key not in grouped:
            grouped[key] = {
                'id': row.id,
                **_availability_week_fields(row),
                'organization_id': host.organization_id,
                'organization_name': host.organization.name if host.organization else None,
                'host_location_id': host.id,
                'host_location_name': host.name,
                'site_type': host.surface_type,
                'available_layout': layout_name,
                'small_field_capacity': small,
                'medium_field_capacity': medium,
                'large_field_capacity': large,
                'total_fields_found': len(templates),
                'inactive_field_count': 0,
                'unmatched_field_records': 0,
                'has_field_inventory_mismatch': len(templates) == 0,
                'fields': [
                    {
                        'configuration_option_id': str(config.id) if config else None,
                        'configuration_option_name': layout_name,
                        'raw_field_type_value': layout_name,
                        'small_field_count': small,
                        'medium_field_count': medium,
                        'large_field_count': large,
                        'is_active': bool(config.is_active) if config else False,
                    }
                ],
                'auto_select_turf_layout': bool(getattr(row, 'auto_select_turf_layout', True)),
                'lock_selected_layout': bool(getattr(row, 'lock_selected_layout', False)),
                'hours': [],
            }
        grouped[key]['hours'].extend(range(row.start_time.hour, row.end_time.hour))

    field_q = db.query(HostingAvailability).join(HostingAvailability.field).join(Field.host_location).filter(
        HostingAvailability.is_available.is_(True),
        HostingAvailability.field_id.is_not(None),
    )
    if season_id:
        field_q = field_q.filter(HostingAvailability.season_id == season_id)
        if season_game_dates:
            field_q = field_q.filter(HostingAvailability.available_date.in_(list(season_game_dates)))
    if is_community_admin(current_user):
        field_q = field_q.filter(HostLocation.organization_id == current_user.organization_id)
    elif organization_id:
        field_q = field_q.filter(HostLocation.organization_id == organization_id)
    if host_location_id:
        field_q = field_q.filter(HostLocation.id == host_location_id)
    if site_type:
        field_q = field_q.filter(HostLocation.surface_type == site_type)
    if available_date:
        field_q = field_q.filter(func.cast(HostingAvailability.available_date, str) == available_date)
    for row in field_q.order_by(HostingAvailability.available_date, HostLocation.name, Field.name, HostingAvailability.start_time).all():
        host = row.field.host_location
        field_type = _normalize_field_size(row.field.layout_type)
        if not field_type:
            continue
        layout_name = row.field.name
        key = (str(row.available_date), str(row.field.id), layout_name)
        if key not in grouped:
            small = 1 if field_type == FIELD_SIZE_SMALL else 0
            medium = 1 if field_type == FIELD_SIZE_MEDIUM else 0
            large = 1 if field_type == FIELD_SIZE_LARGE else 0
            grouped[key] = {
                'id': row.id,
                **_availability_week_fields(row),
                'organization_id': host.organization_id,
                'organization_name': host.organization.name if host.organization else None,
                'host_location_id': host.id,
                'host_location_name': host.name,
                'site_type': host.surface_type,
                'available_layout': layout_name,
                'small_field_capacity': small,
                'medium_field_capacity': medium,
                'large_field_capacity': large,
                'total_fields_found': 1,
                'inactive_field_count': 0 if row.field.is_active else 1,
                'unmatched_field_records': 0,
                'has_field_inventory_mismatch': not row.field.is_active,
                'fields': [{'configuration_option_id': str(row.field.id), 'configuration_option_name': layout_name, 'raw_field_type_value': row.field.layout_type, 'small_field_count': small, 'medium_field_count': medium, 'large_field_count': large, 'is_active': bool(row.field.is_active)}],
                'auto_select_turf_layout': bool(getattr(row, 'auto_select_turf_layout', True)),
                'lock_selected_layout': bool(getattr(row, 'lock_selected_layout', False)),
                'hours': [],
            }
        grouped[key]['hours'].extend(range(row.start_time.hour, row.end_time.hour))

    items = []
    for data in grouped.values():
        hours = sorted(set(data['hours']))
        ranges = []
        if hours:
            start = hours[0]
            prev = hours[0]
            for hour in hours[1:]:
                if hour != prev + 1:
                    ranges.append({'start_time': time(start, 0), 'end_time': time(prev + 1, 0)})
                    start = hour
                prev = hour
            ranges.append({'start_time': time(start, 0), 'end_time': time(prev + 1, 0)})
        items.append({
            'id': data['id'],
            'season_id': data.get('season_id'),
            'week_id': data.get('week_id'),
            'week_number': data.get('week_number'),
            'week_label': data.get('week_label'),
            'week_status': data.get('week_status'),
            'primary_game_date': data.get('primary_game_date'),
            'available_date': data['available_date'],
            'organization_id': data['organization_id'],
            'organization_name': data['organization_name'],
            'host_location_id': data['host_location_id'],
            'host_location_name': data['host_location_name'],
            'site_type': data['site_type'],
            'available_layout': data['available_layout'],
            'small_field_capacity': data['small_field_capacity'],
            'medium_field_capacity': data.get('medium_field_capacity', 0),
            'large_field_capacity': data['large_field_capacity'],
            'total_fields_found': data['total_fields_found'],
            'inactive_field_count': data['inactive_field_count'],
            'unmatched_field_records': data['unmatched_field_records'],
            'has_field_inventory_mismatch': data['has_field_inventory_mismatch'],
            'time_ranges': ranges,
            'hostLocationId': data['host_location_id'],
            'hostLocationName': data['host_location_name'],
            'smallFieldCount': data['small_field_capacity'],
            'mediumFieldCount': data.get('medium_field_capacity', 0),
            'largeFieldCount': data['large_field_capacity'],
            'fields': data['fields'],
            'auto_select_turf_layout': data.get('auto_select_turf_layout', True),
            'lock_selected_layout': data.get('lock_selected_layout', False),
        })
    items.sort(key=lambda x: (x['available_date'], x['host_location_name']))
    return {'items': items}


@router.delete('/hosting-availabilities/saved/{item_id}', dependencies=[Depends(get_current_user)])
def delete_saved_hosting_availability(item_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        availability_id = uuid.UUID(item_id)
    except ValueError as exc:
        raise HTTPException(400, 'Invalid availability id.') from exc

    sample = db.query(HostingAvailability).filter(HostingAvailability.id == availability_id).first()
    if not sample:
        raise HTTPException(404, 'Saved availability not found')
    host = sample.host_location or (sample.physical_field_area.host_location if sample.physical_field_area else None)
    if not host:
        raise HTTPException(400, 'Saved availability is missing host location data')

    host_location_id = host.id
    date_value = sample.available_date
    enforce_organization_scope(host.organization_id, current_user)
    if sample.host_location_id:
        availability_ids = [
            row.id
            for row in db.query(HostingAvailability.id)
            .filter(
                HostingAvailability.host_location_id == host_location_id,
                HostingAvailability.available_date == date_value,
                HostingAvailability.selected_configuration_id == sample.selected_configuration_id,
            )
            .all()
        ]
    else:
        availability_ids = [
            row.id
            for row in db.query(HostingAvailability.id)
            .join(HostingAvailability.physical_field_area)
            .join(PhysicalFieldArea.host_location)
            .filter(HostLocation.id == host_location_id, HostingAvailability.available_date == date_value)
            .all()
        ]

    try:
        _delete_availability_with_generated_slots_guard(db, availability_ids, host_location_id, date_value)
        deleted = db.query(HostingAvailability).filter(HostingAvailability.id.in_(availability_ids)).delete(synchronize_session=False)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        logger.exception(
            'Availability delete blocked by integrity error availability_ids=%s host_location_id=%s date=%s outcome=integrity_error',
            availability_ids,
            host_location_id,
            date_value,
        )
        raise HTTPException(409, TURF_WAVE_DELETE_BLOCKED_MESSAGE) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception(
            'Availability delete failed availability_ids=%s host_location_id=%s date=%s outcome=db_error',
            availability_ids,
            host_location_id,
            date_value,
        )
        raise HTTPException(400, TURF_WAVE_DELETE_BLOCKED_MESSAGE) from exc

    logger.info(
        'Availability delete complete availability_ids=%s host_location_id=%s date=%s deleted_availability_count=%s outcome=success',
        availability_ids,
        host_location_id,
        date_value,
        deleted,
    )
    return {'ok': True, 'deleted': deleted}


def _delete_availability_with_generated_slots_guard(db: Session, availability_ids: list[uuid.UUID], host_location_id: uuid.UUID, available_date: date):
    if not availability_ids:
        return

    availability_field_instance_ids = select(FieldInstance.id).filter(FieldInstance.hosting_availability_id.in_(availability_ids))
    turf_wave_ids = select(TurfWave.id).filter(TurfWave.hosting_availability_id.in_(availability_ids))

    generated_slot_count = db.query(GameSlot).filter(
        or_(
            GameSlot.field_instance_id.in_(availability_field_instance_ids),
            GameSlot.turf_wave_id.in_(turf_wave_ids),
        )
    ).count()
    scheduled_slot_game_count = db.query(GameSlot).filter(
        or_(
            GameSlot.field_instance_id.in_(availability_field_instance_ids),
            GameSlot.turf_wave_id.in_(turf_wave_ids),
        ),
        GameSlot.assigned_game_id.isnot(None),
    ).count()
    scheduled_field_instance_game_count = db.query(Game).filter(
        Game.field_instance_id.in_(availability_field_instance_ids)
    ).count()
    scheduled_game_count = scheduled_slot_game_count + scheduled_field_instance_game_count

    logger.info(
        'Availability delete request availability_ids=%s host_location_id=%s date=%s generated_slot_count=%s scheduled_game_count=%s',
        availability_ids,
        host_location_id,
        available_date,
        generated_slot_count,
        scheduled_game_count,
    )

    if scheduled_game_count > 0:
        logger.info(
            'Availability delete blocked availability_ids=%s host_location_id=%s date=%s generated_slot_count=%s scheduled_game_count=%s outcome=blocked_scheduled_games',
            availability_ids,
            host_location_id,
            available_date,
            generated_slot_count,
            scheduled_game_count,
        )
        raise HTTPException(
            409,
            'Cannot delete this availability because scheduled games exist for this location/date. Unschedule or move those games first.',
        )

    deleted_slots = db.query(GameSlot).filter(
        or_(
            GameSlot.field_instance_id.in_(availability_field_instance_ids),
            GameSlot.turf_wave_id.in_(turf_wave_ids),
        )
    ).delete(synchronize_session=False)
    deleted_turf_waves = db.execute(
        delete(TurfWave).where(TurfWave.hosting_availability_id.in_(availability_ids))
    ).rowcount or 0
    deleted_field_instances = db.query(FieldInstance).filter(
        FieldInstance.hosting_availability_id.in_(availability_ids)
    ).delete(synchronize_session=False)
    logger.info(
        'Availability dependents removed availability_ids=%s host_location_id=%s date=%s generated_slot_count=%s scheduled_game_count=%s deleted_slots=%s deleted_turf_waves=%s deleted_field_instances=%s outcome=dependents_deleted',
        availability_ids,
        host_location_id,
        available_date,
        generated_slot_count,
        scheduled_game_count,
        deleted_slots,
        deleted_turf_waves,
        deleted_field_instances,
    )


@router.get('/hosting-availabilities/generated-slots', response_model=list[GeneratedSlotRead], dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def list_generated_slots(host_location_id: uuid.UUID, available_date: str | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    host = db.query(HostLocation).filter(HostLocation.id == host_location_id).first()
    if not host:
        raise HTTPException(404, 'Host location not found')
    enforce_organization_scope(host.organization_id, current_user)
    q = db.query(GameSlot, FieldInstance.field_name, HostLocation.name.label('host_location_name'), Week.season_id.label('season_id')).join(GameSlot.field_instance).join(GameSlot.host_location).outerjoin(Week, Week.id == GameSlot.week_id).filter(GameSlot.host_location_id == host_location_id)
    if available_date:
        q = q.filter(func.cast(GameSlot.slot_date, str) == available_date)
    weeks_by_date = {_week_game_date(week): week for week in db.query(Week).all() if _week_game_date(week)}
    if weeks_by_date:
        q = q.filter(GameSlot.slot_date.in_(list(weeks_by_date)))
    rows = q.order_by(GameSlot.slot_date, GameSlot.start_time, FieldInstance.field_name).all()
    weeks_by_id = {week.id: week for week in db.query(Week).filter(Week.id.in_({row.GameSlot.week_id for row in rows if row.GameSlot.week_id})).all()} if rows else {}
    return [{
        'id': row.GameSlot.id,
        'season_id': row.GameSlot.season_id or row.season_id or ((weeks_by_id.get(row.GameSlot.week_id) or weeks_by_date.get(row.GameSlot.slot_date)).season_id if (weeks_by_id.get(row.GameSlot.week_id) or weeks_by_date.get(row.GameSlot.slot_date)) else None),
        'season_week_id': row.GameSlot.week_id,
        'week_id': row.GameSlot.week_id,
        'game_date': row.GameSlot.slot_date,
        'available_date': row.GameSlot.slot_date,
        'date_type': _week_date_type(weeks_by_id.get(row.GameSlot.week_id) or weeks_by_date.get(row.GameSlot.slot_date)),
        'host_location_id': row.GameSlot.host_location_id,
        'host_location_name': row.host_location_name,
        'field_instance_id': row.GameSlot.field_instance_id,
        'field_instance_name': row.field_name,
        'field_size': _normalize_field_size(row.GameSlot.field_type) or row.GameSlot.field_type,
        'field_type': row.GameSlot.field_type,
        'start_time': row.GameSlot.start_time,
        'end_time': row.GameSlot.end_time,
        'status': row.GameSlot.status,
        'is_available': row.GameSlot.status == 'OPEN' and row.GameSlot.assigned_game_id is None,
        'is_locked': row.GameSlot.assigned_game_id is not None,
    } for row in rows]


@router.get('/field-instances', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def list_field_instances(host_location_id: uuid.UUID | None = None, available_date: str | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(FieldInstance, HostLocation.name.label('host_location_name')).join(FieldInstance.host_location)
    if is_community_admin(current_user):
        q = q.filter(HostLocation.organization_id == current_user.organization_id)
    if host_location_id:
        q = q.filter(FieldInstance.host_location_id == host_location_id)
    if available_date:
        q = q.filter(func.cast(FieldInstance.instance_date, str) == available_date)
    rows = q.order_by(FieldInstance.instance_date, HostLocation.name, FieldInstance.field_name).all()
    return [{'id': r.FieldInstance.id, 'date': r.FieldInstance.instance_date, 'host_location_name': r.host_location_name, 'field_instance_name': r.FieldInstance.field_name, 'field_type': r.FieldInstance.field_type, 'hosting_availability_id': r.FieldInstance.hosting_availability_id} for r in rows]


@router.get('/generated-game-slots', response_model=list[GeneratedSlotRead], dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def list_generated_game_slots(host_location_id: uuid.UUID | None = None, available_date: str | None = None, status: str | None = None, field_type: str | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(
        GameSlot,
        FieldInstance.field_name,
        HostLocation.name.label('host_location_name'),
        Week.season_id.label('season_id'),
    ).join(GameSlot.field_instance).join(GameSlot.host_location).outerjoin(Week, Week.id == GameSlot.week_id)
    if is_community_admin(current_user):
        q = q.filter(HostLocation.organization_id == current_user.organization_id)
    if host_location_id:
        q = q.filter(GameSlot.host_location_id == host_location_id)
    if available_date:
        q = q.filter(func.cast(GameSlot.slot_date, str) == available_date)
    if status:
        q = q.filter(GameSlot.status == status)
    if field_type:
        q = q.filter(GameSlot.field_type == field_type)
    weeks_by_date = {_week_game_date(week): week for week in db.query(Week).all() if _week_game_date(week)}
    if weeks_by_date:
        q = q.filter(GameSlot.slot_date.in_(list(weeks_by_date)))
    rows = q.order_by(GameSlot.slot_date, GameSlot.start_time, FieldInstance.field_name).all()
    weeks_by_id = {week.id: week for week in db.query(Week).filter(Week.id.in_({row.GameSlot.week_id for row in rows if row.GameSlot.week_id})).all()} if rows else {}
    return [{
        'id': row.GameSlot.id,
        'season_id': row.GameSlot.season_id or row.season_id or ((weeks_by_id.get(row.GameSlot.week_id) or weeks_by_date.get(row.GameSlot.slot_date)).season_id if (weeks_by_id.get(row.GameSlot.week_id) or weeks_by_date.get(row.GameSlot.slot_date)) else None),
        'season_week_id': row.GameSlot.week_id,
        'week_id': row.GameSlot.week_id,
        'game_date': row.GameSlot.slot_date,
        'available_date': row.GameSlot.slot_date,
        'date_type': _week_date_type(weeks_by_id.get(row.GameSlot.week_id) or weeks_by_date.get(row.GameSlot.slot_date)),
        'host_location_id': row.GameSlot.host_location_id,
        'host_location_name': row.host_location_name,
        'field_instance_id': row.GameSlot.field_instance_id,
        'field_instance_name': row.field_name,
        'field_size': _normalize_field_size(row.GameSlot.field_type) or row.GameSlot.field_type,
        'field_type': row.GameSlot.field_type,
        'start_time': row.GameSlot.start_time,
        'end_time': row.GameSlot.end_time,
        'status': row.GameSlot.status,
        'is_available': row.GameSlot.status == 'OPEN' and row.GameSlot.assigned_game_id is None,
        'is_locked': row.GameSlot.assigned_game_id is not None,
    } for row in rows]


GENERATED_SLOTS_CLEAR_WARNING = 'Some field instances were preserved because scheduled games reference them.'
TURF_WAVE_DELETE_BLOCKED_MESSAGE = 'Cannot delete this hosting availability because generated turf wave records still exist. Clear generated slots/waves first or use force delete if no games are scheduled.'


@router.delete('/generated-game-slots', response_model=GeneratedSlotsClearResponse, dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def clear_generated_game_slots(host_location_id: uuid.UUID = Query(...), current_user: User = Depends(require_roles(ROLE_LEAGUE_ADMIN)), db: Session = Depends(get_db)):
    host = db.query(HostLocation).filter(HostLocation.id == host_location_id).first()
    if not host:
        raise HTTPException(404, 'Host location not found')
    enforce_organization_scope(host.organization_id, current_user)

    field_instance_ids = [
        row[0]
        for row in db.query(FieldInstance.id)
        .filter(FieldInstance.host_location_id == host_location_id)
        .all()
    ]

    assigned_game_ids = {
        row[0]
        for row in db.query(GameSlot.assigned_game_id)
        .filter(
            GameSlot.host_location_id == host_location_id,
            GameSlot.assigned_game_id.isnot(None),
        )
        .all()
        if row[0] is not None
    }

    game_field_rows = []
    if field_instance_ids:
        game_field_rows = (
            db.query(Game.id, Game.field_instance_id)
            .filter(Game.field_instance_id.in_(field_instance_ids))
            .all()
        )
    referenced_field_instance_ids = {row.field_instance_id for row in game_field_rows if row.field_instance_id is not None}
    preserved_game_ids = assigned_game_ids | {row.id for row in game_field_rows}

    slots_deleted = db.query(GameSlot).filter(
        GameSlot.host_location_id == host_location_id,
        GameSlot.assigned_game_id.is_(None),
    ).delete(synchronize_session=False)

    remaining_slot_field_instance_ids = set()
    if field_instance_ids:
        remaining_slot_field_instance_ids = {
            row[0]
            for row in db.query(GameSlot.field_instance_id)
            .filter(
                GameSlot.host_location_id == host_location_id,
                GameSlot.field_instance_id.in_(field_instance_ids),
            )
            .distinct()
            .all()
        }

    preserved_field_instance_ids = referenced_field_instance_ids | remaining_slot_field_instance_ids
    field_instance_ids_to_delete = [field_id for field_id in field_instance_ids if field_id not in preserved_field_instance_ids]
    field_instances_deleted = 0
    if field_instance_ids_to_delete:
        field_instances_deleted = db.query(FieldInstance).filter(
            FieldInstance.id.in_(field_instance_ids_to_delete),
        ).delete(synchronize_session=False)

    if preserved_field_instance_ids:
        db.query(FieldInstance).filter(FieldInstance.id.in_(preserved_field_instance_ids)).update(
            {FieldInstance.is_active: False},
            synchronize_session=False,
        )

    db.commit()

    return GeneratedSlotsClearResponse(
        slots_deleted=slots_deleted or 0,
        field_instances_deleted=field_instances_deleted or 0,
        field_instances_preserved=len(preserved_field_instance_ids),
        games_preserved=len(preserved_game_ids),
        warning=GENERATED_SLOTS_CLEAR_WARNING if preserved_game_ids else None,
    )


@router.post('/generated-game-slots/regenerate', response_model=HostingGenerationRunResult, dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def regenerate_generated_game_slots(payload: dict | None = None, current_user: User = Depends(require_roles(ROLE_LEAGUE_ADMIN)), db: Session = Depends(get_db)):
    payload = payload or {}
    season_id = payload.get('season_id')
    if season_id:
        season_weeks = db.query(Week).filter(Week.season_id == season_id).order_by(Week.week_number.asc(), Week.primary_game_date.asc()).all()
    else:
        season_weeks = db.query(Week).filter(Week.season_id.isnot(None)).order_by(Week.week_number.asc(), Week.primary_game_date.asc()).all()
    regular_weeks = [week for week in season_weeks if _is_regular_season_week(week) and _week_game_date(week)]

    if regular_weeks:
        division_order = _auto_schedule_division_order(db)
        preflight = _regenerate_and_validate_slots_for_weeks(db, regular_weeks, division_order)
        generation_results = list(preflight.get('generation_results') or [])
        results: list[HostingGenerationLocationResult] = []
        processed = skipped = errors = 0
        total_field_instances = total_slots = total_slots_evaluated = 0
        total_slots_regenerated = total_locked_slots_skipped = total_new_slots_created = 0
        total_obsolete_unused_slots_removed = total_hard_failures = 0
        for row in generation_results:
            result = HostingGenerationLocationResult(
                host_location_id=uuid.UUID(str(row['host_location_id'])),
                host_location_name=str(row.get('host_location_name') or ''),
                slots_created=int(row.get('slots_created') or 0),
                new_slots_created=int(row.get('new_slots_created') or 0),
                slots_regenerated=int(row.get('slots_regenerated') or 0),
                locked_slots_skipped=int(row.get('locked_slots_skipped') or 0),
                errors=list(row.get('errors') or []),
            )
            results.append(result)
            processed += 1
            if result.errors:
                errors += 1
            total_slots += result.slots_created
            total_slots_regenerated += result.slots_regenerated
            total_locked_slots_skipped += result.locked_slots_skipped
            total_new_slots_created += result.new_slots_created
            total_obsolete_unused_slots_removed += result.obsolete_unused_slots_removed
            total_hard_failures += result.hard_failures

        db.commit()
        return HostingGenerationRunResult(
            message='League-wide slots regenerated from active host plan selections.' if processed > 0 else 'No selected host plan availability records found.',
            processed=processed,
            skipped=skipped,
            errors=errors,
            total_field_instances_created=total_field_instances,
            total_slots_created=total_slots,
            total_slots_evaluated=total_slots_evaluated,
            total_slots_regenerated=total_slots_regenerated,
            total_locked_slots_skipped=total_locked_slots_skipped,
            total_new_slots_created=total_new_slots_created,
            total_obsolete_unused_slots_removed=total_obsolete_unused_slots_removed,
            total_hard_failures=total_hard_failures,
            last_generated_at=datetime.utcnow(),
            results=results,
        )

    host_query = db.query(HostLocation).filter(HostLocation.is_active.is_(True))
    if is_community_admin(current_user):
        host_query = host_query.filter(HostLocation.organization_id == current_user.organization_id)
    hosts = host_query.order_by(HostLocation.name).all()

    if not hosts:
        raise HTTPException(400, 'No hosting availability records found.')

    results: list[HostingGenerationLocationResult] = []
    processed = 0
    skipped = 0
    errors = 0
    total_field_instances = 0
    total_slots = 0
    total_slots_evaluated = 0
    total_slots_regenerated = 0
    total_locked_slots_skipped = 0
    total_new_slots_created = 0
    total_obsolete_unused_slots_removed = 0
    total_hard_failures = 0
    for host in hosts:
        availabilities = db.query(HostingAvailability).outerjoin(HostingAvailability.physical_field_area).filter(
            or_(HostingAvailability.host_location_id == host.id, PhysicalFieldArea.host_location_id == host.id),
            HostingAvailability.is_available.is_(True),
        ).order_by(HostingAvailability.available_date, HostingAvailability.start_time).all()
        result = _regenerate_hosting_day(db, availabilities, host)
        results.append(result)
        if result.skipped_reason:
            skipped += 1
        else:
            processed += 1
        if result.errors:
            errors += 1
        total_field_instances += result.field_instances_created
        total_slots += result.slots_created
        total_slots_evaluated += result.total_slots_evaluated
        total_slots_regenerated += result.slots_regenerated
        total_locked_slots_skipped += result.locked_slots_skipped
        total_new_slots_created += result.new_slots_created
        total_obsolete_unused_slots_removed += result.obsolete_unused_slots_removed
        total_hard_failures += result.hard_failures

    db.commit()
    return HostingGenerationRunResult(
        message='Slots generated successfully' if processed > 0 else 'No hosting availability records found.',
        processed=processed,
        skipped=skipped,
        errors=errors,
        total_field_instances_created=total_field_instances,
        total_slots_created=total_slots,
        total_slots_evaluated=total_slots_evaluated,
        total_slots_regenerated=total_slots_regenerated,
        total_locked_slots_skipped=total_locked_slots_skipped,
        total_new_slots_created=total_new_slots_created,
        total_obsolete_unused_slots_removed=total_obsolete_unused_slots_removed,
        total_hard_failures=total_hard_failures,
        last_generated_at=datetime.utcnow(),
        results=results,
    )


@router.post('/teams', response_model=TeamRead, dependencies=[Depends(get_current_user)])
def create_team(payload: TeamCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enforce_organization_scope(payload.organization_id, current_user)
    division = db.query(Division).filter(Division.id == payload.division_id, Division.is_active.is_(True)).first()
    if not division:
        raise HTTPException(400, 'Division is inactive or does not exist')
    participation = db.query(OrganizationDivisionParticipation).filter(
        OrganizationDivisionParticipation.organization_id == payload.organization_id,
        OrganizationDivisionParticipation.division_id == payload.division_id,
        OrganizationDivisionParticipation.is_participating.is_(True),
    ).first()
    if not participation:
        raise HTTPException(400, 'Organization is not participating in this division')
    active_count = db.query(Team).filter(
        Team.organization_id == payload.organization_id,
        Team.division_id == payload.division_id,
        Team.is_active.is_(True),
    ).count()
    if payload.is_active and active_count >= participation.team_count and not is_league_admin(current_user):
        raise HTTPException(400, 'Cannot exceed participating team count for this division')
    x = Team(**payload.model_dump()); db.add(x); db.commit(); db.refresh(x); return x

@router.get('/teams', response_model=PagedResponse[TeamRead], dependencies=[Depends(get_current_user)])
def list_teams(search: str | None = None, organization_id: uuid.UUID | None = None, division_id: uuid.UUID | None = None, active_divisions_only: bool = True, page: int = 1, page_size: int = 20, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Team)
    if active_divisions_only:
        q = q.join(Team.division).filter(Division.is_active.is_(True))
    if is_community_admin(current_user): q = q.filter(Team.organization_id == current_user.organization_id)
    elif organization_id: q = q.filter(Team.organization_id == organization_id)
    if division_id: q = q.filter(Team.division_id == division_id)
    if search: q = q.filter(func.lower(Team.name).like(f"%{search.lower()}%"))
    return paginate(q.order_by(Team.name), page, page_size)

@router.put('/teams/{item_id}', response_model=TeamRead, dependencies=[Depends(get_current_user)])
def upd_team(item_id: uuid.UUID, payload: TeamCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(Team).filter(Team.id == item_id).first()
    if not x: raise HTTPException(404, 'Team not found')
    enforce_organization_scope(x.organization_id, current_user)
    enforce_organization_scope(payload.organization_id, current_user)
    division = db.query(Division).filter(Division.id == payload.division_id, Division.is_active.is_(True)).first()
    if not division:
        raise HTTPException(400, 'Division is inactive or does not exist')
    participation = db.query(OrganizationDivisionParticipation).filter(
        OrganizationDivisionParticipation.organization_id == payload.organization_id,
        OrganizationDivisionParticipation.division_id == payload.division_id,
        OrganizationDivisionParticipation.is_participating.is_(True),
    ).first()
    if not participation:
        raise HTTPException(400, 'Organization is not participating in this division')
    active_count = db.query(Team).filter(
        Team.organization_id == payload.organization_id,
        Team.division_id == payload.division_id,
        Team.is_active.is_(True),
        Team.id != item_id,
    ).count()
    if payload.is_active and active_count >= participation.team_count and not is_league_admin(current_user):
        raise HTTPException(400, 'Cannot exceed participating team count for this division')
    for k, v in payload.model_dump().items(): setattr(x, k, v)
    db.commit(); db.refresh(x); return x

@router.patch('/teams/{item_id}', response_model=TeamRead, dependencies=[Depends(get_current_user)])
def patch_team(item_id: uuid.UUID, payload: TeamUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(Team).filter(Team.id == item_id).first()
    if not x:
        raise HTTPException(404, 'Team not found')
    enforce_organization_scope(x.organization_id, current_user)

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return x

    if 'name' in updates and updates['name'] is not None:
        updates['name'] = updates['name'].strip()
        if not updates['name']:
            raise HTTPException(400, 'Team name is required')

    new_is_active = updates.get('is_active', x.is_active)
    if new_is_active:
        participation = db.query(OrganizationDivisionParticipation).filter(
            OrganizationDivisionParticipation.organization_id == x.organization_id,
            OrganizationDivisionParticipation.division_id == x.division_id,
            OrganizationDivisionParticipation.is_participating.is_(True),
        ).first()
        if not participation:
            raise HTTPException(400, 'Organization is not participating in this division')
        active_count = db.query(Team).filter(
            Team.organization_id == x.organization_id,
            Team.division_id == x.division_id,
            Team.is_active.is_(True),
            Team.id != item_id,
        ).count()
        if active_count >= participation.team_count and not is_league_admin(current_user):
            raise HTTPException(400, 'Cannot exceed participating team count for this division')

    for k, v in updates.items():
        setattr(x, k, v)
    db.commit(); db.refresh(x)
    return x


@router.delete('/teams/{item_id}', dependencies=[Depends(get_current_user)])
def del_team(item_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(Team).filter(Team.id == item_id).first()
    if not x: raise HTTPException(404, 'Team not found')
    enforce_organization_scope(x.organization_id, current_user)
    x.is_active = False
    db.commit()
    return {'ok': True}

# keep existing game/public routes omitted for brevity

@router.get('/game-statuses', response_model=PagedResponse[dict], dependencies=[Depends(get_current_user)])
def list_game_statuses(page:int=1,page_size:int=50, db:Session=Depends(get_db)):
    q=db.query(GameStatus).order_by(GameStatus.label)
    return PagedResponse(items=[{"id":x.id,"code":x.code,"label":x.label} for x in q.offset((page-1)*page_size).limit(page_size).all()], total=q.count(), page=page, page_size=page_size)


@router.post('/game-statuses/seed', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def seed_game_statuses_endpoint(db: Session = Depends(get_db)):
    changed = ensure_required_game_statuses(db)
    db.commit()
    return {'status': 'ok', 'ensured': changed, 'required': [code for code, _ in REQUIRED_GAME_STATUSES]}

@router.get('/seasons', response_model=PagedResponse[dict], dependencies=[Depends(get_current_user)])
def list_seasons(page:int=1,page_size:int=50, db:Session=Depends(get_db)):
    q=db.query(Season).order_by(Season.start_date.desc())
    return PagedResponse(items=[{"id":x.id,"name":x.name, "schedule_status": x.schedule_status} for x in q.offset((page-1)*page_size).limit(page_size).all()], total=q.count(), page=page, page_size=page_size)

WEEK_STATUSES = {'draft', 'active', 'locked', 'completed', 'cancelled'}


def _parse_week_date(payload: dict, field: str, required: bool = True) -> date | None:
    value = payload.get(field)
    if value in (None, ''):
        if required:
            raise HTTPException(422, f'{field} is required')
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise HTTPException(422, f'{field} must be a valid date')


def _normalize_week_payload(payload: dict, db: Session, week_id: uuid.UUID | None = None) -> dict:
    season_id = payload.get('season_id')
    if not season_id:
        raise HTTPException(422, 'season_id is required')
    season = db.query(Season).filter(Season.id == season_id).first()
    if not season:
        raise HTTPException(422, 'season_id must reference an existing season')

    week_number = payload.get('week_number')
    if week_number in (None, ''):
        raise HTTPException(422, 'week_number is required')
    try:
        week_number = int(week_number)
    except (TypeError, ValueError):
        raise HTTPException(422, 'week_number must be a number')

    duplicate = db.query(Week).filter(Week.season_id == season_id, Week.week_number == week_number)
    if week_id:
        duplicate = duplicate.filter(Week.id != week_id)
    if duplicate.first():
        raise HTTPException(422, 'Week numbers must be unique within a season')

    start_date = _parse_week_date(payload, 'start_date')
    end_date = _parse_week_date(payload, 'end_date')
    primary_game_date = _parse_week_date(payload, 'primary_game_date')
    if end_date < start_date:
        raise HTTPException(422, 'end_date cannot be before start_date')
    if primary_game_date < start_date or primary_game_date > end_date:
        raise HTTPException(422, 'primary_game_date must fall within the start/end date range')

    status = str(payload.get('status') or 'draft').lower()
    if status not in WEEK_STATUSES:
        raise HTTPException(422, 'status must be one of draft, active, locked, completed, cancelled')
    date_type = _normalize_week_date_type(payload.get('date_type'))

    return {
        'season_id': season_id,
        'week_number': week_number,
        'label': payload.get('label') or None,
        'start_date': start_date,
        'end_date': end_date,
        'primary_game_date': primary_game_date,
        'date_type': date_type,
        'notes': payload.get('notes') or None,
        'status': status,
    }


def _week_to_dict(week: Week, counts: dict[str, dict[uuid.UUID, int]] | None = None) -> dict:
    counts = counts or {}
    return {
        'id': week.id,
        'season_id': week.season_id,
        'week_number': week.week_number,
        'label': week.label,
        'week_label': week.label or f'Week {week.week_number}',
        'start_date': _date_only_iso(week.start_date),
        'end_date': _date_only_iso(week.end_date),
        'primary_game_date': _date_only_iso(week.primary_game_date),
        'date_type': _week_date_type(week),
        'notes': week.notes,
        'status': week.status or 'draft',
        'hosting_availability_count': counts.get('hosting_availability', {}).get(week.id, 0),
        'generated_slots_count': counts.get('generated_slots', {}).get(week.id, 0),
        'scheduled_games_count': counts.get('scheduled_games', {}).get(week.id, 0),
    }


@router.get('/weeks', response_model=PagedResponse[dict], dependencies=[Depends(get_current_user)])
def list_weeks(season_id:uuid.UUID|None=None, status:str|None=None, start_date:date|None=None, end_date:date|None=None, search:str|None=None, page:int=1,page_size:int=100, db:Session=Depends(get_db)):
    q=db.query(Week)
    if season_id: q=q.filter(Week.season_id==season_id)
    if status: q=q.filter(Week.status==status.lower())
    if start_date: q=q.filter(Week.end_date>=start_date)
    if end_date: q=q.filter(Week.start_date<=end_date)
    if search:
        q=q.filter(or_(Week.label.ilike(f'%{search}%'), func.cast(Week.week_number, String).ilike(f'%{search}%')))
    q=q.order_by(Week.primary_game_date, Week.week_number)
    total=q.count()
    weeks=q.offset((page-1)*page_size).limit(page_size).all()
    counts = {'hosting_availability': {}, 'generated_slots': {}, 'scheduled_games': {}}
    for week in weeks:
        counts['hosting_availability'][week.id] = db.query(func.count(func.distinct(HostingAvailability.host_location_id))).filter(HostingAvailability.week_id == week.id, HostingAvailability.is_available.is_(True)).scalar() or 0
        counts['generated_slots'][week.id] = db.query(func.count(GameSlot.id)).filter(GameSlot.slot_date == week.primary_game_date).scalar() or 0
        counts['scheduled_games'][week.id] = db.query(func.count(Game.id)).filter(Game.week_id == week.id).scalar() or 0
    return PagedResponse(items=[_week_to_dict(x, counts) for x in weeks], total=total, page=page, page_size=page_size)

@router.post('/seasons', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def create_season(payload: dict, db: Session = Depends(get_db)):
    season = Season(name=payload['name'], start_date=payload['start_date'], end_date=payload['end_date'], schedule_status=payload.get('schedule_status', 'draft'), is_active=bool(payload.get('is_active', True)))
    db.add(season); db.commit(); db.refresh(season)
    return {"id": season.id, "name": season.name}

@router.put('/seasons/{season_id}', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def update_season(season_id: uuid.UUID, payload: dict, db: Session = Depends(get_db)):
    season = db.query(Season).filter(Season.id == season_id).first()
    if not season: raise HTTPException(404, 'Season not found')
    season.name = payload.get('name', season.name); season.start_date = payload.get('start_date', season.start_date); season.end_date = payload.get('end_date', season.end_date); season.schedule_status = payload.get('schedule_status', season.schedule_status); season.is_active = bool(payload.get('is_active', season.is_active))
    db.commit(); db.refresh(season); return {"id": season.id, "name": season.name}


def build_schedule_quality_report(db: Session, season_id: uuid.UUID) -> dict[str, object]:
    rows = _schedule_management_rows(db, {'season_id': season_id})
    teams = db.query(Team).filter(Team.is_active.is_(True)).all()
    season_team_ids = {t.id for t in teams if db.query(Game).filter(Game.season_id == season_id, (Game.home_team_id == t.id) | (Game.away_team_id == t.id)).first() is not None}
    team_game_counts = {tid: 0 for tid in season_team_ids}
    required_field_errors: list[dict[str, object]] = []
    team_double_booking_errors: list[dict[str, object]] = []
    field_double_booking_errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    team_time_seen: dict[tuple[uuid.UUID, date, time], dict[str, object]] = {}
    field_time_seen: dict[tuple[uuid.UUID, date, time], dict[str, object]] = {}
    matchup_counts: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
    team_division_map: dict[uuid.UUID, uuid.UUID] = {}
    division_team_ids: dict[uuid.UUID, set[uuid.UUID]] = {}
    team_games_by_date: dict[tuple[uuid.UUID, date], list[time]] = {}

    for g, slot, fi, host, home, away, div, org, status in rows:
        for tid in (home.id, away.id):
            if tid in team_game_counts:
                team_game_counts[tid] += 1
            team_games_by_date.setdefault((tid, g.game_date), []).append(g.kickoff_time)
            team_division_map[tid] = div.id
            division_team_ids.setdefault(div.id, set()).add(tid)

        for team in (home, away):
            t_key = (team.id, g.game_date, g.kickoff_time)
            entry = {'game_id': str(g.id), 'team': team.name, 'date': g.game_date.isoformat(), 'time': g.kickoff_time.strftime('%H:%M:%S'), 'host_location': host.name if host else None, 'field': fi.field_name if fi else None}
            if t_key in team_time_seen:
                team_double_booking_errors.append({**entry, 'conflicting_games': [team_time_seen[t_key], entry]})
            else:
                team_time_seen[t_key] = entry

        if slot and fi:
            f_key = (fi.id, g.game_date, g.kickoff_time)
            f_entry = {'game_id': str(g.id), 'date': g.game_date.isoformat(), 'time': g.kickoff_time.strftime('%H:%M:%S'), 'host_location': host.name if host else None, 'field': fi.field_name}
            if f_key in field_time_seen:
                field_double_booking_errors.append({**f_entry, 'conflicting_games': [field_time_seen[f_key], f_entry]})
            else:
                field_time_seen[f_key] = f_entry
            if slot.field_type != _required_field_type_for_division(div):
                required_field_errors.append({'game_id': str(g.id), 'division': div.name, 'date': g.game_date.isoformat(), 'time': g.kickoff_time.strftime('%H:%M:%S'), 'host_location': host.name if host else None, 'field': fi.field_name, 'message': 'invalid field type'})

        pair = tuple(sorted([home.id, away.id], key=lambda x: str(x)))
        matchup_counts[pair] = matchup_counts.get(pair, 0) + 1

    teams_with_zero_games = sum(1 for count in team_game_counts.values() if count == 0)
    uneven_game_counts = (max(team_game_counts.values()) - min(team_game_counts.values())) if team_game_counts else 0
    odd_team_divisions = {division_id for division_id, team_ids in division_team_ids.items() if len(team_ids) % 2 == 1}
    non_back_to_back_double_headers = 0
    uneven_double_header_distribution = 0
    double_header_counts_by_team: dict[uuid.UUID, int] = {}
    # Double headers are expected in odd-team divisions and should not be a warning by default.
    # We still track distribution and adjacency for quality insights.
    for (team_id, _game_date), entries in team_games_by_date.items():
        if len(entries) <= 1:
            continue
        double_header_counts_by_team[team_id] = double_header_counts_by_team.get(team_id, 0) + 1
        entries = sorted(entries)
        for prev, cur in zip(entries, entries[1:]):
            if (datetime.combine(date.today(), cur) - datetime.combine(date.today(), prev)).seconds > 7200:
                non_back_to_back_double_headers += 1
                break

    if double_header_counts_by_team:
        high = max(double_header_counts_by_team.values())
        low = min(double_header_counts_by_team.values())
        uneven_double_header_distribution = high - low

    repeat_matchups = 0
    for (team_a, _team_b), count in matchup_counts.items():
        division_id = team_division_map.get(team_a)
        division_team_count = len(division_team_ids.get(division_id, set())) if division_id else 0
        if count >= 3 and division_team_count >= 4:
            repeat_matchups += 1
    if repeat_matchups > 0:
        warnings.append({'code': 'repeat_matchups', 'count': repeat_matchups, 'message': 'avoidable third-or-more repeat matchups detected'})

    if uneven_game_counts > 0 and not odd_team_divisions:
        warnings.append({'code': 'uneven_game_counts', 'count': uneven_game_counts, 'message': 'uneven game counts detected'})

    if uneven_double_header_distribution > 1:
        warnings.append({'code': 'uneven_double_headers', 'count': uneven_double_header_distribution, 'message': 'double headers are not evenly distributed'})

    if non_back_to_back_double_headers > 0:
        warnings.append({'code': 'non_back_to_back_double_headers', 'count': non_back_to_back_double_headers, 'message': 'non-back-to-back double headers detected'})

    missing_required_games = 1 if not rows else 0
    metrics = {
        'conflicts': len(team_double_booking_errors) + len(field_double_booking_errors),
        'team_double_bookings': len(team_double_booking_errors),
        'field_double_bookings': len(field_double_booking_errors),
        'teams_with_zero_games': teams_with_zero_games,
        'missing_required_games': missing_required_games,
        'uneven_game_counts': uneven_game_counts,
        'non_back_to_back_double_headers': non_back_to_back_double_headers,
        'odd_team_divisions': len(odd_team_divisions),
        'uneven_double_header_distribution': uneven_double_header_distribution,
    }
    hard_errors = (
        [{'code': 'team_double_bookings', 'issues': team_double_booking_errors}]
        + [{'code': 'field_double_bookings', 'issues': field_double_booking_errors}]
        + ([{'code': 'teams_with_zero_games', 'count': teams_with_zero_games}] if teams_with_zero_games > 0 else [])
        + ([{'code': 'missing_required_games', 'count': missing_required_games}] if missing_required_games > 0 else [])
        + [{'code': 'invalid_field_type', 'issues': required_field_errors}]
        + ([{'code': 'non_back_to_back_double_headers', 'count': non_back_to_back_double_headers}] if non_back_to_back_double_headers > 0 else [])
    )
    hard_errors = [e for e in hard_errors if not (isinstance(e, dict) and 'issues' in e and not e['issues'])]
    if hard_errors:
        overall_health = 'Blocked'
    elif warnings:
        overall_health = 'Good'
    else:
        overall_health = 'Excellent'
    return {'overall_health': overall_health, 'hard_errors': hard_errors, 'warnings': warnings, 'metrics': metrics}


@router.post('/seasons/{season_id}/publish-schedule', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def publish_schedule(season_id: uuid.UUID, db: Session = Depends(get_db)):
    season = db.query(Season).filter(Season.id == season_id).first()
    if not season: raise HTTPException(404, 'Season not found')
    validation = build_schedule_quality_report(db, season_id)
    if validation['hard_errors']:
        raise HTTPException(status_code=400, detail={'error': 'publish_validation_failed', **validation})
    season.schedule_status = 'published'
    db.commit()
    return {'ok': True, 'season_id': str(season_id), 'schedule_status': season.schedule_status, 'warnings': validation['warnings'], 'overall_health': validation['overall_health']}


@router.post('/seasons/{season_id}/unpublish-schedule', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def unpublish_schedule(season_id: uuid.UUID, db: Session = Depends(get_db)):
    season = db.query(Season).filter(Season.id == season_id).first()
    if not season: raise HTTPException(404, 'Season not found')
    season.schedule_status = 'draft'
    db.commit()
    return {'ok': True, 'season_id': str(season_id), 'schedule_status': season.schedule_status}

@router.post('/weeks', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def create_week(payload: dict, db: Session = Depends(get_db)):
    data = _normalize_week_payload(payload, db)
    week = Week(**data)
    db.add(week); db.commit(); db.refresh(week)
    return _week_to_dict(week)

@router.put('/weeks/{week_id}', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def update_week(week_id: uuid.UUID, payload: dict, db: Session = Depends(get_db)):
    week = db.query(Week).filter(Week.id == week_id).first()
    if not week: raise HTTPException(404, 'Week not found')
    data = _normalize_week_payload({
        'season_id': payload.get('season_id', week.season_id),
        'week_number': payload.get('week_number', week.week_number),
        'label': payload.get('label', week.label),
        'start_date': payload.get('start_date', week.start_date),
        'end_date': payload.get('end_date', week.end_date),
        'primary_game_date': payload.get('primary_game_date', week.primary_game_date),
        'date_type': payload.get('date_type', _week_date_type(week)),
        'notes': payload.get('notes', week.notes),
        'status': payload.get('status', week.status),
    }, db, week_id)
    old_primary_game_date = week.primary_game_date
    for key, value in data.items():
        setattr(week, key, value)
    if week.primary_game_date and week.primary_game_date != old_primary_game_date:
        availability_ids = [item.id for item in db.query(HostingAvailability.id).filter(HostingAvailability.week_id == week.id).all()]
        if availability_ids:
            db.query(HostingAvailability).filter(HostingAvailability.id.in_(availability_ids)).update(
                {HostingAvailability.available_date: week.primary_game_date, HostingAvailability.primary_game_date: week.primary_game_date},
                synchronize_session=False,
            )
            db.query(FieldInstance).filter(FieldInstance.hosting_availability_id.in_(availability_ids)).update(
                {FieldInstance.instance_date: week.primary_game_date},
                synchronize_session=False,
            )
            field_instance_ids = [item.id for item in db.query(FieldInstance.id).filter(FieldInstance.hosting_availability_id.in_(availability_ids)).all()]
            if field_instance_ids:
                db.query(GameSlot).filter(GameSlot.field_instance_id.in_(field_instance_ids)).update(
                    {GameSlot.slot_date: week.primary_game_date},
                    synchronize_session=False,
                )
    db.commit(); db.refresh(week); return _week_to_dict(week)

def _to_game_read(
    g: Game,
    generated_slot: GameSlot | None = None,
    field_instance_name: str | None = None,
    host_location_name: str | None = None,
    home_team_name: str | None = None,
    away_team_name: str | None = None,
    division_name: str | None = None,
    division_group: str | None = None,
) -> GameRead:
    return GameRead(
        id=g.id,
        created_at=g.created_at,
        updated_at=g.updated_at,
        season_id=g.season_id,
        week_id=g.week_id,
        division_id=g.home_team.division_id,
        home_team_id=g.home_team_id,
        away_team_id=g.away_team_id,
        field_id=g.field_id,
        game_status_id=g.game_status_id,
        game_date=g.game_date,
        kickoff_time=g.kickoff_time,
        status_code=g.status.code,
        division_name=division_name,
        division_group=division_group,
        home_team_name=home_team_name,
        away_team_name=away_team_name,
        generated_slot_id=(generated_slot.id if generated_slot else None),
        field_instance_id=(generated_slot.field_instance_id if generated_slot else g.field_instance_id),
        host_location_id=(generated_slot.host_location_id if generated_slot else g.host_location_id),
        field_instance_name=field_instance_name,
        host_location_name=host_location_name,
    )

@router.get('/games', response_model=PagedResponse[GameRead], dependencies=[Depends(get_current_user)])
def list_games(division_id:uuid.UUID|None=None, week_id:uuid.UUID|None=None, team_id:uuid.UUID|None=None, host_location_id:uuid.UUID|None=None, status_code:str|None=None, page:int=1,page_size:int=50, db:Session=Depends(get_db)):
    home_team = aliased(Team, name='home_team')
    away_team = aliased(Team, name='away_team')
    q = db.query(
        Game,
        GameSlot,
        home_team.name.label('home_team_name'),
        away_team.name.label('away_team_name'),
        Division.name.label('division_name'),
        Division.division_group.label('division_group'),
        FieldInstance.field_name.label('field_instance_name'),
        HostLocation.name.label('host_location_name'),
    ).join(Game.status).join(home_team, Game.home_team_id == home_team.id).join(away_team, Game.away_team_id == away_team.id).join(Division, home_team.division_id == Division.id).outerjoin(Game.field).outerjoin(GameSlot, GameSlot.assigned_game_id == Game.id).outerjoin(FieldInstance, FieldInstance.id == GameSlot.field_instance_id).outerjoin(HostLocation, HostLocation.id == GameSlot.host_location_id)
    if division_id: q=q.filter(home_team.division_id==division_id)
    if week_id: q=q.filter(Game.week_id==week_id)
    if team_id: q=q.filter((Game.home_team_id==team_id)|(Game.away_team_id==team_id))
    if host_location_id: q=q.filter((Field.host_location_id==host_location_id) | (GameSlot.host_location_id==host_location_id))
    if status_code: q=q.filter(GameStatus.code==status_code)
    total=q.count(); rows=q.order_by(Game.game_date, Game.kickoff_time).offset((page-1)*page_size).limit(page_size).all()
    items = [
        _to_game_read(
            game,
            generated_slot=slot,
            field_instance_name=field_instance_name,
            host_location_name=host_location_name,
            home_team_name=home_team_name,
            away_team_name=away_team_name,
            division_name=division_name,
            division_group=division_group,
        )
        for game, slot, home_team_name, away_team_name, division_name, division_group, field_instance_name, host_location_name in rows
    ]
    return PagedResponse(items=items, total=total, page=page, page_size=page_size)



@router.get('/manual-schedule-builder/options', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def manual_schedule_builder_options(db: Session = Depends(get_db)):
    divisions = db.query(Division).filter(Division.is_active.is_(True)).order_by(Division.sort_order, Division.name).all()
    teams = db.query(Team).join(Team.division).filter(Team.is_active.is_(True), Division.is_active.is_(True)).order_by(Team.name).all()
    eligible_host_ids = _eligible_host_location_ids(db)
    host_locations = db.query(HostLocation).filter(HostLocation.id.in_(eligible_host_ids)).order_by(HostLocation.name).all()
    seasons = db.query(Season).filter(Season.is_active.is_(True)).order_by(Season.start_date.desc()).all()
    weeks = db.query(Week).order_by(Week.week_number).all()
    organizations = db.query(Organization).filter(Organization.is_active.is_(True)).order_by(Organization.name).all()
    return {
        'divisions': [{'id': d.id, 'name': d.name, 'division_group': d.division_group, 'sort_order': d.sort_order, 'required_field_layout_type': d.required_field_layout_type, 'required_field_type': 'LARGE' if '53' in (d.required_field_layout_type or '') else 'SMALL'} for d in divisions],
        'teams': [{'id': t.id, 'name': t.name, 'division_id': t.division_id, 'is_active': t.is_active} for t in teams],
        'host_locations': [{'id': h.id, 'name': h.name} for h in host_locations],
        'seasons': [{'id': s.id, 'name': s.name, 'start_date': s.start_date, 'end_date': s.end_date, 'is_active': s.is_active} for s in seasons],
        'weeks': [{'id': w.id, 'season_id': w.season_id, 'week_number': w.week_number, 'label': w.label or f'Week {w.week_number}', 'start_date': w.start_date, 'end_date': w.end_date, 'primary_game_date': w.primary_game_date or w.start_date, 'status': w.status} for w in weeks],
        'organizations': [{'id': o.id, 'name': o.name} for o in organizations],
    }





@router.post('/manual-schedule-builder/recommendations', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def manual_schedule_builder_recommendations(payload: dict, db: Session = Depends(get_db)):
    season_id = payload.get('season_id')
    week_id = payload.get('week_id')
    division_id = payload.get('division_id')
    organization_id = payload.get('organization_id')
    host_location_id = payload.get('host_location_id')
    home_team_id = payload.get('home_team_id')
    away_team_id = payload.get('away_team_id')

    division = db.query(Division).filter(Division.id == division_id).first() if division_id else None
    expected_field_type = _required_field_type_for_division(division)
    division_key = canonical_division_id_from_division(division)

    teams_q = db.query(Team).join(Team.division).filter(Team.is_active.is_(True), Division.is_active.is_(True))
    if division_id:
        teams_q = teams_q.filter(Team.division_id == division_id)
    teams = teams_q.order_by(Team.name).all()
    team_ids = {t.id for t in teams}

    games_q = db.query(Game).join(Game.status).filter(GameStatus.code.notin_(['UNSCHEDULED', 'DELETED']))
    if season_id:
        games_q = games_q.filter(Game.season_id == season_id)
    if week_id:
        games_q = games_q.filter(Game.week_id == week_id)
    if division_id:
        games_q = games_q.join(Game.home_team).filter(Team.division_id == division_id)
    division_games = games_q.all()

    team_game_counts: dict[uuid.UUID, int] = {t.id: 0 for t in teams}
    matchup_counts: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
    for g in division_games:
        if g.home_team_id in team_game_counts:
            team_game_counts[g.home_team_id] += 1
        if g.away_team_id in team_game_counts:
            team_game_counts[g.away_team_id] += 1
        key = tuple(sorted([g.home_team_id, g.away_team_id]))
        matchup_counts[key] = matchup_counts.get(key, 0) + 1

    same_day_team_counts: dict[tuple[uuid.UUID, date], int] = {}
    for g in division_games:
        same_day_team_counts[(g.home_team_id, g.game_date)] = same_day_team_counts.get((g.home_team_id, g.game_date), 0) + 1
        same_day_team_counts[(g.away_team_id, g.game_date)] = same_day_team_counts.get((g.away_team_id, g.game_date), 0) + 1

    suggested_matchups = []
    team_list = list(teams)
    already_scheduled_team_ids: set[uuid.UUID] = set()
    already_scheduled_pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for g in division_games:
        if g.home_team_id in team_ids:
            already_scheduled_team_ids.add(g.home_team_id)
        if g.away_team_id in team_ids:
            already_scheduled_team_ids.add(g.away_team_id)
        already_scheduled_pairs.add(tuple(sorted((g.home_team_id, g.away_team_id))))

    max_games_for_division_week = math.ceil(len(team_list) / 2) if division_id and week_id else None
    all_teams_met_weekly_limit = (
        max_games_for_division_week is not None
        and len(team_list) > 0
        and all(team_game_counts.get(t.id, 0) >= 1 for t in team_list)
    )
    rejected_pairings: dict[str, int] = {
        'team_already_has_weekly_game': 0,
        'pairing_already_scheduled_this_week': 0,
    }

    for i in range(len(team_list)):
        for j in range(i + 1, len(team_list)):
            a = team_list[i]
            b = team_list[j]
            key = tuple(sorted([a.id, b.id]))
            if a.id in already_scheduled_team_ids or b.id in already_scheduled_team_ids:
                rejected_pairings['team_already_has_weekly_game'] += 1
                continue
            if key in already_scheduled_pairs:
                rejected_pairings['pairing_already_scheduled_this_week'] += 1
                continue
            repeats = matchup_counts.get(key, 0)
            score = 70
            reasons = []
            if repeats == 0:
                score += 20; reasons.append('unscheduled matchup')
            else:
                score -= min(25, repeats * 12); reasons.append(f'repeat count: {repeats}')
            total_games = team_game_counts.get(a.id, 0) + team_game_counts.get(b.id, 0)
            score += max(0, 15 - total_games * 2)
            reasons.append('prioritizes teams with fewer games')
            suggested_matchups.append({'home_team_id': a.id, 'home_team_name': a.name, 'away_team_id': b.id, 'away_team_name': b.name, 'score': max(0, min(100, score)), 'reason': ', '.join(reasons), 'repeat_count': repeats})
    suggested_matchups.sort(key=lambda x: x['score'], reverse=True)

    slots_q = db.query(GameSlot).join(GameSlot.field_instance).join(GameSlot.host_location).filter(GameSlot.status == 'OPEN')
    if division:
        slots_q = slots_q.filter(GameSlot.field_type == expected_field_type)
    if host_location_id:
        slots_q = slots_q.filter(GameSlot.host_location_id == host_location_id)
    if organization_id:
        slots_q = slots_q.filter(HostLocation.organization_id == organization_id)
    slot_rows = slots_q.order_by(GameSlot.slot_date, GameSlot.start_time).limit(300).all()

    slot_suggestions = []
    selected_pair = [home_team_id, away_team_id] if home_team_id and away_team_id else []
    for slot in slot_rows:
        score = 65
        reasons = []
        conflicts = []
        if division and slot.field_type == expected_field_type:
            score += 15; reasons.append('correct field type')
        else:
            score -= 35; conflicts.append('invalid field type')

        if selected_pair:
            overlap = db.query(Game).join(GameSlot, GameSlot.assigned_game_id == Game.id).filter(
                Game.game_date == slot.slot_date,
                GameSlot.start_time < slot.end_time,
                GameSlot.end_time > slot.start_time,
                ((Game.home_team_id == selected_pair[0]) | (Game.away_team_id == selected_pair[0]) | (Game.home_team_id == selected_pair[1]) | (Game.away_team_id == selected_pair[1]))
            ).count()
            if overlap:
                score -= 50; conflicts.append('team conflict at this time')
            day_games = 0
            for tid in selected_pair:
                day_games += same_day_team_counts.get((tid, slot.slot_date), 0)
            if day_games == 0:
                score += 10; reasons.append('no same-day game yet')
            elif day_games <= 2:
                reasons.append('possible back-to-back double header')
            else:
                score -= 20; conflicts.append('excess same-day games')

        hour = slot.start_time.hour if hasattr(slot.start_time, 'hour') else int(str(slot.start_time).split(':')[0])
        if 11 <= hour <= 16:
            score += 8; reasons.append('balanced time-of-day')

        rating = 'Excellent' if score >= 85 else ('Good' if score >= 65 else 'Warning')
        color = 'green' if rating == 'Excellent' else ('yellow' if rating == 'Good' else 'red')
        slot_suggestions.append({
            'slot_id': slot.id,
            'slot_date': slot.slot_date,
            'start_time': slot.start_time,
            'end_time': slot.end_time,
            'host_location_name': slot.host_location.name,
            'field_instance_name': slot.field_instance.field_name,
            'field_type': slot.field_type,
            'score': max(0, min(100, score)),
            'reason': ', '.join(reasons + conflicts) if (reasons or conflicts) else 'open slot',
            'rating': rating,
            'indicator': color,
            'conflicts': conflicts,
        })
    slot_suggestions.sort(key=lambda x: x['score'], reverse=True)
    all_available_weekly_matchups_scheduled = (
        len(suggested_matchups) == 0
        and (all_teams_met_weekly_limit or (len(team_list) > 0 and sum(rejected_pairings.values()) > 0))
    )
    no_eligible_matchups = len(suggested_matchups) == 0 and len(slot_suggestions) > 0 and len(team_list) > 1
    logger.info(
        'manual_schedule_builder_recommendations division_id=%s division_key=%s active_teams=%s eligible_pairings=%s rejected_pairings=%s compatible_slots=%s',
        division_id,
        division_key,
        len(team_list),
        len(suggested_matchups),
        rejected_pairings,
        len(slot_suggestions),
    )
    return {
        'suggested_matchups': suggested_matchups[:25],
        'suggested_slots': slot_suggestions[:40],
        'all_available_weekly_matchups_scheduled': all_available_weekly_matchups_scheduled,
        'no_eligible_team_matchups': no_eligible_matchups,
    }
@router.post('/manual-schedule-builder/assign', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def assign_generated_slot(payload: dict, db: Session = Depends(get_db)):
    season_id = payload.get('season_id')
    week_id = payload.get('week_id')
    division_id = payload.get('division_id')
    home_team_id = payload.get('home_team_id')
    away_team_id = payload.get('away_team_id')
    generated_slot_id = payload.get('generated_slot_id')
    if not season_id or not week_id:
        raise HTTPException(400, 'Please select a season and week before assigning a game.')
    if not home_team_id or not away_team_id:
        raise HTTPException(400, 'Home Team and Away Team are required')
    if home_team_id == away_team_id:
        raise HTTPException(400, 'Home Team and Away Team cannot be the same')
    home_team = db.query(Team).filter(Team.id == home_team_id).first()
    away_team = db.query(Team).filter(Team.id == away_team_id).first()
    if not home_team or not away_team:
        raise HTTPException(404, 'Team not found')
    if not home_team.is_active or not away_team.is_active:
        raise HTTPException(400, 'Cannot assign inactive teams')
    slot = db.query(GameSlot).join(GameSlot.field_instance).filter(GameSlot.id == generated_slot_id).first()
    if not slot or slot.status != 'OPEN':
        raise HTTPException(400, 'Selected slot must be OPEN')
    division = db.query(Division).filter(Division.id == division_id).first()
    if not division:
        raise HTTPException(404, 'Division not found')
    expected_field_type = _required_field_type_for_division(division)
    if slot.field_type != expected_field_type:
        raise HTTPException(400, 'Selected slot field type must match division requirement')
    overlap = db.query(Game).join(GameSlot, GameSlot.assigned_game_id == Game.id).filter(
        Game.game_date == slot.slot_date,
        GameSlot.start_time < slot.end_time,
        GameSlot.end_time > slot.start_time,
        ((Game.home_team_id == home_team.id) | (Game.away_team_id == home_team.id) | (Game.home_team_id == away_team.id) | (Game.away_team_id == away_team.id))
    ).count()
    if overlap:
        raise HTTPException(400, 'A team cannot be scheduled in overlapping slots')
    duplicate = db.query(Game).filter(
        Game.home_team_id == home_team.id,
        Game.away_team_id == away_team.id,
        Game.game_date == slot.slot_date,
        Game.kickoff_time == slot.start_time,
    ).count()
    if duplicate:
        raise HTTPException(400, 'Exact duplicate matchup already exists for this date/time')
    season = db.query(Season).filter(Season.id == season_id).first()
    week = db.query(Week).filter(Week.id == week_id, Week.season_id == season_id).first()
    if not season or not week:
        raise HTTPException(400, 'Please select a season and week before assigning a game.')
    status = db.query(GameStatus).filter(GameStatus.code == 'SCHEDULED').first()
    teams = db.query(Team).filter(Team.division_id == division_id, Team.is_active.is_(True)).all()
    team_ids = {t.id for t in teams}
    max_games_for_division_week = math.ceil(len(teams) / 2)
    existing_division_games = db.query(Game).join(Game.home_team).filter(
        Game.season_id == season_id,
        Game.week_id == week_id,
        Team.division_id == division_id,
    ).all()
    used_team_ids: set[uuid.UUID] = set()
    for g in existing_division_games:
        if g.home_team_id in team_ids:
            used_team_ids.add(g.home_team_id)
        if g.away_team_id in team_ids:
            used_team_ids.add(g.away_team_id)
    if not status:
        logger.error('Manual assignment blocked: missing required SCHEDULED game status.')
        raise HTTPException(400, 'Game status setup is incomplete. Please contact an administrator.')
    host_location = db.query(HostLocation).filter(HostLocation.id == slot.host_location_id).first() if slot.host_location_id else None
    if not host_location or host_location.id not in _eligible_host_location_ids(db):
        raise HTTPException(400, 'Selected slot host location is unavailable because it has no active field setup.')
    home_team, away_team, adjustment_reason = _enforce_host_owner_home_team(home_team, away_team, host_location)
    if adjustment_reason:
        logger.info(adjustment_reason)
    game = Game(
        season_id=season.id,
        week_id=week.id,
        home_team_id=home_team.id,
        away_team_id=away_team.id,
        field_id=None,
        host_location_id=slot.host_location_id,
        field_instance_id=slot.field_instance_id,
        game_status_id=status.id,
        game_date=slot.slot_date,
        kickoff_time=slot.start_time,
    )
    db.add(game); db.flush()
    slot.status = 'ASSIGNED'; slot.assigned_game_id = game.id
    db.commit(); db.refresh(game)
    return {'game': _to_game_read(game), 'generated_slot_id': slot.id, 'status': 'SCHEDULED', 'adjustment_reason': adjustment_reason}


@router.delete('/manual-schedule-builder/scheduled-games', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def clear_manual_schedule_builder_scheduled_games(
    season_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    season = db.query(Season).filter(Season.id == season_id).first()
    if not season:
        raise HTTPException(404, 'Season not found')

    game_ids_to_delete = [
        row[0]
        for row in db.query(Game.id).join(Game.status).filter(
            Game.season_id == season_id,
            GameStatus.code != 'UNSCHEDULED',
        ).all()
    ]

    if not game_ids_to_delete:
        logger.info(
            'manual_schedule_builder_clear season_id=%s deleted_games=0 actor_user_id=%s actor_email=%s',
            season_id,
            current_user.id,
            current_user.email,
        )
        return {'deleted_count': 0}

    db.query(GameSlot).filter(GameSlot.assigned_game_id.in_(game_ids_to_delete)).update(
        {'assigned_game_id': None, 'status': 'OPEN'},
        synchronize_session=False,
    )
    deleted_count = db.query(Game).filter(Game.id.in_(game_ids_to_delete)).delete(synchronize_session=False)
    db.commit()
    logger.info(
        'manual_schedule_builder_clear season_id=%s deleted_games=%s actor_user_id=%s actor_email=%s',
        season_id,
        deleted_count,
        current_user.id,
        current_user.email,
    )
    return {'deleted_count': deleted_count}


def extract_selected_host_ids(proposals):
    ids = set()

    for proposal in proposals or []:
        host_id = (
            proposal.get('host_location_id')
            or proposal.get('hostLocationId')
            or (
                proposal.get('slot', {}) or {}
            ).get('host_location_id')
        )

        if host_id:
            ids.add(str(host_id))

    return sorted(ids)


@router.post('/manual-schedule-builder/auto-fill-preview', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def auto_fill_preview(payload: dict, db: Session = Depends(get_db)):
    regular_season_host_limit = 2
    sorted_slots: list[GameSlot] = []
    same_community_home_host_conflicts: list[dict[str, object]] = []
    repeat_matchup_warnings: list[dict[str, object]] = []
    third_meeting_warnings: list[dict[str, object]] = []
    preferred_home_site_failures: list[dict[str, object]] = []
    overflow_host_ids: set[uuid.UUID] = set()
    two_location_rule_relaxed = False
    admin_override_third_host = bool(payload.get('admin_override_third_host_locations', False))
    scoring_weights = payload.get('scoring_weights') or {}

    def _weight(name: str, default: int) -> int:
        try:
            return int(scoring_weights.get(name, default))
        except (TypeError, ValueError):
            return default

    balance_weight = _weight('field_utilization_balance', 90)
    completion_weight = _weight('projected_completion_time', 110)
    parallel_weight = _weight('parallel_scheduling_efficiency', 100)
    consolidation_weight = _weight('host_location_consolidation', 45)
    balancing_config = payload.get('field_balancing') or {}

    def _int_cfg(name: str, default: int, minimum: int = 0) -> int:
        try:
            return max(minimum, int(balancing_config.get(name, default)))
        except (TypeError, ValueError):
            return default

    def _float_cfg(name: str, default: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
        try:
            value = float(balancing_config.get(name, default))
        except (TypeError, ValueError):
            return default
        return max(minimum, min(maximum, value))

    min_concurrent_games_for_balancing = _int_cfg('min_concurrent_games_before_balancing', 2, 1)
    max_consecutive_games_same_field = _int_cfg('max_consecutive_games_same_field', 3, 1)
    preferred_utilization_spread = _float_cfg('preferred_utilization_spread', 0.35, 0.0, 1.0)
    centralization_requested = bool(payload.get('centralized_scheduling_requested', False))
    staffing_limited = bool(payload.get('staffing_limited', False))
    no_simultaneous_games_same_host = bool(payload.get('no_simultaneous_games_same_host', False))
    try:
        single_site_game_limit = max(0, int(payload.get('single_site_game_limit', 4)))
    except (TypeError, ValueError):
        single_site_game_limit = 4

    def _log_query_on_error(query, label: str, exc: Exception) -> None:
        try:
            compiled = str(query.statement.compile(compile_kwargs={'literal_binds': True}))
        except Exception:
            compiled = '<query compile unavailable>'
        logger.exception('auto_fill_preview query failure label=%s error=%s sql=%s', label, exc, compiled)

    season_id = payload.get('season_id')
    week_id = payload.get('week_id')
    division_id = payload.get('division_id')
    if not season_id or not week_id or not division_id:
        raise HTTPException(400, 'season_id, week_id, and division_id are required')
    division = db.query(Division).filter(Division.id == division_id).first()
    week = db.query(Week).filter(Week.id == week_id, Week.season_id == season_id).first()
    if not division or not week:
        raise HTTPException(404, 'Selected season/week/division is invalid')
    week_game_date = _week_game_date(week)
    if not week_game_date:
        raise HTTPException(400, 'Selected week is missing a Primary Game Date')
    if not _is_regular_season_week(week):
        return {
            'proposals': [],
            'skipped': [{'reason': f'{_week_date_type(week)} weeks are excluded from regular-season auto-schedule.'}],
            'proposed_game_count': 0,
            'max_allowed_game_count': 0,
            'existing_game_count': 0,
            'unused_team_ids': [],
            'unused_teams': [],
            'selected_division_id': str(division_id),
            'selected_division_key': canonical_division_id_from_division(division),
            'active_teams_found': 0,
            'eligible_pairings_generated': 0,
            'compatible_slots_found': 0,
        }
    season_weeks = (
        db.query(Week)
        .filter(Week.season_id == season_id)
        .order_by(Week.week_number)
        .all()
    )
    week_numbers_by_id = {w.id: int(w.week_number) for w in season_weeks}

    def _date_value(value):
        if isinstance(value, datetime):
            return value.date()
        return value

    def _last_hosted_week_number(host_dates: set[date], target_date: date | None) -> int | None:
        comparable_host_dates = {
            _date_value(host_date)
            for host_date in host_dates
            if host_date and (not target_date or _date_value(host_date) < target_date)
        }
        hosted_week_numbers = [
            week_numbers_by_id.get(season_week.id)
            for season_week in season_weeks
            if _date_value(_week_game_date(season_week)) in comparable_host_dates
        ]
        return max([week_number for week_number in hosted_week_numbers if week_number is not None], default=None)
    division_group_key = (division.division_group or '').strip().upper()
    selected_division_key = canonical_division_id_from_division(division)
    selected_division_normalized = normalized_division_key(division.division_group, division.name)
    full_division_label = f"{division.division_group} {division.name}".strip() if division.division_group else (division.name or '')
    supported_girls_division_keys = {
        'GIRLS_K_2',
        'GIRLS_3_5',
        'GIRLS_6_8',
    }
    required_field_type = _required_field_type_for_division(division)
    teams = db.query(Team).filter(Team.division_id == division_id, Team.is_active.is_(True)).order_by(Team.name).all()
    participation_count = db.query(OrganizationDivisionParticipation).filter(OrganizationDivisionParticipation.division_id == division_id).count()
    if division_group_key == 'GIRLS' and selected_division_key not in supported_girls_division_keys:
        logger.warning(
            'auto_fill_preview selected unexpected girls division key division_id=%s division_key=%s',
            division_id,
            selected_division_key,
        )
    if not teams:
        logger.info(
            'auto_fill_preview division_id=%s division_key=%s active_teams=%s eligible_pairings=%s compatible_slots=%s',
            division_id,
            selected_division_key,
            0,
            0,
            0,
        )
        return {
            'proposals': [],
            'skipped': [{'reason': 'No active teams found for this division.'}],
            'proposed_game_count': 0,
            'max_allowed_game_count': 0,
            'existing_game_count': 0,
            'unused_team_ids': [],
            'unused_teams': [],
            'selected_division_id': str(division_id),
            'selected_division_key': selected_division_key,
            'active_teams_found': 0,
            'eligible_pairings_generated': 0,
            'compatible_slots_found': 0,
        }
    teams_by_id = {t.id: t for t in teams}
    league_active_teams = db.query(Team).join(Division, Team.division_id == Division.id).filter(Team.is_active.is_(True)).all()
    league_total_active_teams = len(league_active_teams)
    league_teams_by_division: dict[str, int] = {}
    league_small_field_teams = 0
    league_large_field_teams = 0
    league_games_required_by_division_week: dict[str, int] = {}
    for league_team in league_active_teams:
        div = league_team.division
        div_key = canonical_division_id_from_division(div) if div else 'UNKNOWN'
        league_teams_by_division[div_key] = league_teams_by_division.get(div_key, 0) + 1
    for div_key, div_team_count in league_teams_by_division.items():
        league_games_required_by_division_week[div_key] = div_team_count // 2
    for league_team in league_active_teams:
        req = _required_field_type_for_division(league_team.division) if league_team.division else None
        if str(req) == 'FieldType.SMALL' or getattr(req, 'value', req) == 'SMALL':
            league_small_field_teams += 1
        elif str(req) == 'FieldType.LARGE' or getattr(req, 'value', req) == 'LARGE':
            league_large_field_teams += 1
    no_byes = bool(payload.get('no_byes', True))
    team_count = len(teams)
    is_odd_division = team_count % 2 == 1
    required_games_for_division_week = (team_count + 1) // 2
    existing_division_games_query = db.query(Game).select_from(Game).join(Team, Game.home_team_id == Team.id).join(Game.status).filter(
        Game.season_id == season_id,
        Game.week_id == week_id,
        Team.division_id == division_id,
        Team.is_active.is_(True),
        GameStatus.code == 'SCHEDULED',
        GameStatus.is_active.is_(True),
    )
    try:
        existing_division_games = existing_division_games_query.all()
    except Exception as exc:
        _log_query_on_error(existing_division_games_query, 'existing_division_games', exc)
        logger.exception('Auto-fill preview query failure')
        raise
    used_team_ids: set[uuid.UUID] = set()
    week_team_game_counts: dict[uuid.UUID, int] = {tid: 0 for tid in teams_by_id}
    used_pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for g in existing_division_games:
        if g.home_team_id in teams_by_id:
            used_team_ids.add(g.home_team_id)
            week_team_game_counts[g.home_team_id] = week_team_game_counts.get(g.home_team_id, 0) + 1
        if g.away_team_id in teams_by_id:
            used_team_ids.add(g.away_team_id)
            week_team_game_counts[g.away_team_id] = week_team_game_counts.get(g.away_team_id, 0) + 1
        used_pairs.add(tuple(sorted((g.home_team_id, g.away_team_id))))
    open_slots = db.query(GameSlot).join(GameSlot.field_instance).filter(
        GameSlot.status == 'OPEN',
        GameSlot.season_id == season_id,
        GameSlot.week_id == week_id,
        GameSlot.slot_date == week_game_date,
        GameSlot.field_type == required_field_type,
        GameSlot.assigned_game_id.is_(None),
    ).order_by(GameSlot.slot_date, GameSlot.start_time).all()
    host_plan_allowed_ids = _host_plan_allowed_host_ids_for_week(db, season_id, week_id, week_game_date)
    if host_plan_allowed_ids is not None:
        open_slots = [slot for slot in open_slots if slot.host_location_id in host_plan_allowed_ids]
    compatible_slots_found = len(open_slots)
    logger.info(
        'division_lookup requested_division=%s normalized_division=%s matched_teams=%s matched_generated_slots=%s participation_rows=%s',
        full_division_label,
        selected_division_normalized,
        len(teams),
        compatible_slots_found,
        participation_count,
    )
    if teams and compatible_slots_found == 0:
        _msg = 'Division has teams but no compatible generated slots.'
        logger.warning('%s division=%s normalized_division=%s', _msg, full_division_label, selected_division_normalized)
        max_new_games_without_slots = max(0, required_games_for_division_week - len(existing_division_games))
        return {
            'proposals': [],
            'scheduled_games': [],
            'warnings': [
                f'Division has teams but no compatible generated slots: {getattr(division, "display_name", full_division_label)}'
            ],
            'week_open_slot_dates': [],
            'week_open_slot_count': 0,
            'compatible_slot_count': 0,
            'skipped': [{'reason': _msg}],
            'proposed_game_count': 0,
            'generated_required_game_groups': max_new_games_without_slots,
            'max_allowed_game_count': required_games_for_division_week,
            'existing_game_count': len(existing_division_games),
            'unused_team_ids': [str(tid) for tid in teams_by_id],
            'unused_teams': [teams_by_id[tid].name for tid in teams_by_id],
            'selected_division_id': str(division_id),
            'selected_division_key': selected_division_key,
            'active_teams_found': len(teams),
            'eligible_pairings_generated': 0,
            'compatible_slots_found': 0,
            'final_validation': {
                'active_team_count': team_count,
                'required_game_count': required_games_for_division_week,
                'created_game_count': len(existing_division_games),
                'odd_even_status_source': 'division_active_team_count',
                'unscheduled_teams': [teams_by_id[tid].name for tid in teams_by_id if week_team_game_counts.get(tid, 0) == 0],
                'double_header_team': None,
                'weekly_completion_status': 'incomplete' if max_new_games_without_slots else 'complete',
            },
            'diagnostics': {
                'missing_division_week': {
                    'week': week.week_number,
                    'date': str(week_game_date) if week_game_date else None,
                    'division': full_division_label,
                    'active_teams': team_count,
                    'active_team_names': [teams_by_id[tid].name for tid in teams_by_id],
                    'expected_games': required_games_for_division_week,
                    'generated_game_groups': max_new_games_without_slots,
                    'required_matchups_generated': [],
                    'placement_attempts': 0,
                    'valid_assignments_found': 0,
                    'scheduled_games': len(existing_division_games),
                    'missing_games': max(0, required_games_for_division_week - len(existing_division_games)),
                    'required_field_size': required_field_type,
                    'compatible_slots_found': 0,
                    'compatible_large_slots_available': 0 if _normalize_field_size(required_field_type) == FIELD_SIZE_LARGE else None,
                    'placement_attempt_details': [],
                    'skipped_placement_reasons': [_msg],
                    'doubleheader_team_selected': None,
                    'doubleheader_placement_failed': bool(is_odd_division and no_byes and max_new_games_without_slots),
                }
            },
        }
    assigned_game_slots = db.query(Game, GameSlot).join(GameSlot, GameSlot.assigned_game_id == Game.id).filter(
        Game.game_date == week_game_date
    ).all()
    community_assigned_hosts: dict[uuid.UUID, set[uuid.UUID]] = {}
    for game, game_slot in assigned_game_slots:
        if not game_slot.host_location_id:
            continue
        for team in (game.home_team, game.away_team):
            if team and team.organization_id:
                community_assigned_hosts.setdefault(team.organization_id, set()).add(game_slot.host_location_id)
    existing_non_unscheduled_games_query = db.query(
        Game.home_team_id,
        Game.away_team_id,
        Game.game_date,
        Game.kickoff_time,
        GameSlot.host_location_id,
        GameSlot.field_instance_id,
        Division.name,
    ).select_from(Game).join(Game.status).join(Team, Game.home_team_id == Team.id).join(Division, Team.division_id == Division.id).outerjoin(
        GameSlot, GameSlot.assigned_game_id == Game.id
    ).filter(
        Game.game_date == week_game_date,
        GameStatus.code != 'UNSCHEDULED',
        GameStatus.is_active.is_(True),
    )
    try:
        existing_non_unscheduled_games = existing_non_unscheduled_games_query.all()
    except Exception as exc:
        _log_query_on_error(existing_non_unscheduled_games_query, 'existing_non_unscheduled_games', exc)
        logger.exception('Auto-fill preview query failure')
        raise
    team_time_occupied = {
        (str(team_id), game_date, kickoff_time)
        for row in existing_non_unscheduled_games
        for team_id, game_date, kickoff_time in (
            (row.home_team_id, row.game_date, row.kickoff_time),
            (row.away_team_id, row.game_date, row.kickoff_time),
        )
        if team_id and game_date and kickoff_time
    }
    field_time_occupied = {
        (str(row.host_location_id), str(row.field_instance_id), row.game_date, row.kickoff_time): row.name
        for row in existing_non_unscheduled_games
        if row.field_instance_id and row.game_date and row.kickoff_time
    }
    host_time_occupied = {
        (str(row.host_location_id), row.game_date, row.kickoff_time): row.name
        for row in existing_non_unscheduled_games
        if row.host_location_id and row.game_date and row.kickoff_time
    }

    def _has_compatible_open_field_at_time(host_location_id: uuid.UUID | None, slot_date, slot_time) -> bool:
        if not host_location_id:
            return False
        compatible_open_slots = db.query(GameSlot).join(GameSlot.field_instance).filter(
            GameSlot.host_location_id == host_location_id,
            GameSlot.slot_date == slot_date,
            GameSlot.start_time == slot_time,
            GameSlot.status == 'OPEN',
            GameSlot.assigned_game_id.is_(None),
            GameSlot.field_type == required_field_type,
        ).all()
        for open_slot in compatible_open_slots:
            open_field_key = (str(open_slot.host_location_id), str(open_slot.field_instance_id), open_slot.slot_date, open_slot.start_time)
            if open_field_key not in field_time_occupied:
                return True
        return False
    postseason_week = bool(
        payload.get('is_postseason')
        or payload.get('is_playoff_week')
        or payload.get('is_tournament_week')
        or payload.get('is_championship_week')
    )
    season_division_games = db.query(Game).select_from(Game).join(Team, Game.home_team_id == Team.id).join(Game.status).filter(
        Game.season_id == season_id,
        Team.division_id == division_id,
        Team.is_active.is_(True),
        GameStatus.code == 'SCHEDULED',
        GameStatus.is_active.is_(True),
    ).all()
    double_header_counts: dict[uuid.UUID, int] = {tid: 0 for tid in teams_by_id}
    for game in season_division_games:
        if game.week_id == week_id:
            continue
        double_header_counts[game.home_team_id] = double_header_counts.get(game.home_team_id, 0)
        double_header_counts[game.away_team_id] = double_header_counts.get(game.away_team_id, 0)
    team_week_counts: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
    double_header_weeks_by_team: dict[uuid.UUID, set[int]] = {tid: set() for tid in teams_by_id}
    for game in season_division_games:
        key_home = (game.home_team_id, game.week_id)
        key_away = (game.away_team_id, game.week_id)
        team_week_counts[key_home] = team_week_counts.get(key_home, 0) + 1
        team_week_counts[key_away] = team_week_counts.get(key_away, 0) + 1
    for (team_id, _wk_id), count in team_week_counts.items():
        if count > 1:
            double_header_counts[team_id] = double_header_counts.get(team_id, 0) + 1
            wk_no = week_numbers_by_id.get(_wk_id)
            if wk_no is not None:
                double_header_weeks_by_team.setdefault(team_id, set()).add(int(wk_no))

    matchup_counts: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
    community_matchup_counts: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
    for game in season_division_games:
        key = tuple(sorted((game.home_team_id, game.away_team_id)))
        matchup_counts[key] = matchup_counts.get(key, 0) + 1
        home_org_id = game.home_team.organization_id if game.home_team else None
        away_org_id = game.away_team.organization_id if game.away_team else None
        if home_org_id and away_org_id:
            community_key = tuple(sorted((home_org_id, away_org_id)))
            community_matchup_counts[community_key] = community_matchup_counts.get(community_key, 0) + 1

    prior_week = db.query(Week).filter(
        Week.season_id == season_id,
        or_(
            Week.week_number < week.week_number,
            and_(Week.week_number == week.week_number, Week.primary_game_date < week_game_date),
        ),
    ).order_by(Week.week_number.desc(), Week.primary_game_date.desc()).first()

    prior_week_team_pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    prior_week_community_pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    if prior_week:
        prior_week_games = [
            g for g in season_division_games
            if g.week_id == prior_week.id
        ]
        for game in prior_week_games:
            prior_week_team_pairs.add(tuple(sorted((game.home_team_id, game.away_team_id))))
            home_org_id = game.home_team.organization_id if game.home_team else None
            away_org_id = game.away_team.organization_id if game.away_team else None
            if home_org_id and away_org_id:
                prior_week_community_pairs.add(tuple(sorted((home_org_id, away_org_id))))
    regular_season_host_occurrences_by_community: dict[uuid.UUID, set[date]] = {}
    regular_season_host_occurrences_by_location: dict[uuid.UUID, set[date]] = {}
    if not postseason_week:
        season_scheduled_rows_query = db.query(
            Week.week_number,
            GameSlot.slot_date,
            GameSlot.host_location_id,
            HostLocation.organization_id,
        ).select_from(Game).join(GameSlot, GameSlot.assigned_game_id == Game.id).join(Week, Week.id == Game.week_id).join(
            HostLocation, HostLocation.id == GameSlot.host_location_id
        ).join(Game.status).filter(
            Game.season_id == season_id,
            GameStatus.code == 'SCHEDULED',
            GameStatus.is_active.is_(True),
        )
        try:
            season_scheduled_rows = season_scheduled_rows_query.all()
        except Exception as exc:
            _log_query_on_error(season_scheduled_rows_query, 'season_scheduled_rows', exc)
            logger.exception('Auto-fill preview query failure')
            raise
        for week_number, slot_date, host_location_id, host_org_id in season_scheduled_rows:
            if week_number > 99:
                continue
            if not host_location_id or not slot_date:
                continue
            regular_season_host_occurrences_by_location.setdefault(host_location_id, set()).add(slot_date)
            if host_org_id:
                regular_season_host_occurrences_by_community.setdefault(host_org_id, set()).add(slot_date)
    plans = []
    skipped: list[dict[str, str]] = []
    skipped_seen: set[str] = set()

    def _add_skipped(reason: str, slot_id: str | None = None) -> None:
        if reason in skipped_seen:
            return
        skipped_seen.add(reason)
        payload = {'reason': reason}
        if slot_id:
            payload['slot_id'] = slot_id
        skipped.append(payload)
    existing_games_count = len(existing_division_games)
    max_new_games = max(0, required_games_for_division_week - existing_games_count)
    if max_new_games == 0:
        counted_game_ids = [str(g.id) for g in existing_division_games]
        return {
            'proposals': plans,
            'skipped': [{
                'slot_id': '',
                'reason': 'Weekly game limit reached for selected division/week',
                'selected_division_id': str(division_id),
                'selected_week_id': str(week_id),
                'active_games_counted': existing_games_count,
                'max_games_allowed': required_games_for_division_week,
                'counted_game_ids': counted_game_ids,
            }],
            'proposed_game_count': 0,
            'max_allowed_game_count': required_games_for_division_week,
            'existing_game_count': existing_games_count,
            'active_games_counted': existing_games_count,
            'counted_game_ids': counted_game_ids,
            'unused_team_ids': [str(tid) for tid in teams_by_id if tid not in used_team_ids],
            'unused_teams': [teams_by_id[tid].name for tid in teams_by_id if tid not in used_team_ids],
        }
    total_unique_pairs_in_division = max(0, (team_count * (team_count - 1)) // 2)
    unique_opponents_per_team = max(0, team_count - 1)
    team_org_ids: dict[uuid.UUID, uuid.UUID | None] = {tid: team.organization_id for tid, team in teams_by_id.items()}
    cross_community_opponents_by_team: dict[uuid.UUID, set[uuid.UUID]] = {}
    for team_id, team in teams_by_id.items():
        cross_community_opponents_by_team[team_id] = {
            other_id for other_id, other_team in teams_by_id.items()
            if other_id != team_id and team.organization_id and other_team.organization_id and team.organization_id != other_team.organization_id
        }
    cross_community_opponents_per_team = min((len(v) for v in cross_community_opponents_by_team.values()), default=0)
    required_games_per_team = min(unique_opponents_per_team, required_games_for_division_week)
    repeats_mathematically_unavoidable = required_games_per_team > unique_opponents_per_team
    same_community_mathematically_necessary = any(
        team.organization_id and len(cross_community_opponents_by_team.get(team_id, set())) == 0
        for team_id, team in teams_by_id.items()
    )
    same_community_operationally_reasonable = (
        cross_community_opponents_per_team < required_games_per_team
        or team_count <= 4
        or repeats_mathematically_unavoidable
        or same_community_mathematically_necessary
    )

    remaining_slots = list(open_slots)
    slots_by_host: dict[uuid.UUID, list[GameSlot]] = {}
    for slot in open_slots:
        if slot.host_location_id:
            slots_by_host.setdefault(slot.host_location_id, []).append(slot)
    games_required = max_new_games
    all_open_slots_for_week = db.query(GameSlot).join(GameSlot.field_instance).filter(
        GameSlot.status == 'OPEN',
        GameSlot.season_id == season_id,
        GameSlot.week_id == week_id,
        GameSlot.slot_date == week_game_date,
        GameSlot.assigned_game_id.is_(None),
    ).all()
    if host_plan_allowed_ids is not None:
        all_open_slots_for_week = [slot for slot in all_open_slots_for_week if slot.host_location_id in host_plan_allowed_ids]
    # Weekly host planning is intentionally based on all available weekly slots, not only
    # the field size for the division currently being placed. This lets the scheduler
    # select the minimum set of host communities for the whole week and then ignore
    # non-selected availability without deleting those availability records.
    weekly_slots_by_host: dict[uuid.UUID, list[GameSlot]] = {}
    for slot in all_open_slots_for_week:
        if slot.host_location_id:
            weekly_slots_by_host.setdefault(slot.host_location_id, []).append(slot)
    weekly_host_capacity_report: dict[uuid.UUID, dict[str, object]] = {}
    for slot in all_open_slots_for_week:
        if not slot.host_location_id:
            continue
        row = weekly_host_capacity_report.setdefault(slot.host_location_id, {
            'host_location_id': str(slot.host_location_id),
            'host_location_name': slot.host_location.name if slot.host_location else '',
            'owning_community_id': str(slot.host_location.organization_id) if slot.host_location and slot.host_location.organization_id else None,
            'small_field_capacity': 0,
            'medium_field_capacity': 0,
            'large_field_capacity': 0,
            'total_game_capacity': 0,
            'remaining_unused_capacity': 0,
            'small_fields': set(),
            'medium_fields': set(),
            'large_fields': set(),
            'current_season_host_count_location': len(regular_season_host_occurrences_by_location.get(slot.host_location_id, set())),
            'current_season_host_count_community': len(regular_season_host_occurrences_by_community.get(slot.host_location.organization_id, set())) if slot.host_location and slot.host_location.organization_id else 0,
        })
        row['total_game_capacity'] += 1
        row['remaining_unused_capacity'] += 1
        if slot.field_type == 'SMALL':
            row['small_field_capacity'] += 1
            row['small_fields'].add(str(slot.field_instance_id))
        elif slot.field_type == 'MEDIUM':
            row['medium_field_capacity'] += 1
            row['medium_fields'].add(str(slot.field_instance_id))
        elif slot.field_type == 'LARGE':
            row['large_field_capacity'] += 1
            row['large_fields'].add(str(slot.field_instance_id))
    host_capacity = []
    for host_id, host_slots in weekly_slots_by_host.items():
        host_capacity.append({
            'host_id': host_id,
            'slot_count': len(host_slots),
            'field_count': len({s.field_instance_id for s in host_slots}),
            'continuity': len({(s.slot_date, s.start_time) for s in host_slots}),
        })
    host_capacity_by_id: dict[uuid.UUID, int] = {row['host_id']: int(row['slot_count']) for row in host_capacity}
    host_ids_by_org: dict[uuid.UUID, set[uuid.UUID]] = {}
    primary_host_by_org: dict[uuid.UUID, uuid.UUID] = {}
    for host_id in weekly_slots_by_host.keys():
        host_row = db.query(HostLocation.id, HostLocation.organization_id).filter(HostLocation.id == host_id).first()
        if host_row and host_row.organization_id:
            host_ids_by_org.setdefault(host_row.organization_id, set()).add(host_row.id)
    host_org_by_id: dict[uuid.UUID, uuid.UUID] = {}
    host_name_by_id: dict[uuid.UUID, str] = {}
    for host in host_capacity:
        host_row = db.query(HostLocation.id, HostLocation.organization_id, HostLocation.name).filter(HostLocation.id == host['host_id']).first()
        if host_row and host_row.organization_id:
            host_org_by_id[host_row.id] = host_row.organization_id
            host_name_by_id[host_row.id] = host_row.name or ''
    for org_id, community_host_ids in host_ids_by_org.items():
        ordered_community_hosts = sorted(
            community_host_ids,
            key=lambda host_id: (
                -host_capacity_by_id.get(host_id, 0),
                host_name_by_id.get(host_id, ''),
            ),
        )
        if ordered_community_hosts:
            primary_host_by_org[org_id] = ordered_community_hosts[0]
    available_host_community_ids = set(host_ids_by_org.keys())
    org_names_by_id = {
        org.id: org.name or str(org.id)
        for org in db.query(Organization).filter(Organization.id.in_(list(available_host_community_ids))).all()
    } if available_host_community_ids else {}
    community_games_hosted_to_date = _scheduled_game_counts_by_host_community(db, season_id, week_game_date)
    community_team_count_by_org: dict[uuid.UUID, int] = {org_id: 0 for org_id in available_host_community_ids}
    active_team_count_rows = (
        db.query(Team.organization_id, func.count(Team.id))
        .join(Division, Division.id == Team.division_id)
        .filter(Team.is_active.is_(True), Division.is_active.is_(True), Team.organization_id.isnot(None))
        .group_by(Team.organization_id)
        .all()
    )
    for org_id, count in active_team_count_rows:
        if org_id in available_host_community_ids:
            community_team_count_by_org[org_id] = int(count or 0)

    def _hosted_games_per_team(org_id: uuid.UUID) -> float:
        return community_games_hosted_to_date.get(org_id, 0) / max(community_team_count_by_org.get(org_id, 0), 1)

    total_games_hosted_to_date = sum(community_games_hosted_to_date.values())
    total_hosting_team_count = sum(max(community_team_count_by_org.get(org_id, 0), 1) for org_id in available_host_community_ids)
    expected_host_share_per_team = (total_games_hosted_to_date / max(total_hosting_team_count, 1)) if available_host_community_ids else 0.0
    hosting_delta_by_org = {org_id: _hosted_games_per_team(org_id) - expected_host_share_per_team for org_id in available_host_community_ids}
    capacity_score_by_org = {
        org_id: sum(host_capacity_by_id.get(host_id, 0) for host_id in host_ids)
        for org_id, host_ids in host_ids_by_org.items()
    }
    community_rotation_ranking = sorted(available_host_community_ids, key=lambda org_id: (
        len(regular_season_host_occurrences_by_community.get(org_id, set())),
        -_days_since_last_hosted(regular_season_host_occurrences_by_community.get(org_id, set()), week_game_date),
        _consecutive_host_count_before_date(regular_season_host_occurrences_by_community.get(org_id, set()), week_game_date),
        community_games_hosted_to_date.get(org_id, 0),
        hosting_delta_by_org.get(org_id, 0.0),
        -capacity_score_by_org.get(org_id, 0),
    ))
    community_rotation_rank_by_org = {org_id: index for index, org_id in enumerate(community_rotation_ranking)}
    host_capacity.sort(key=lambda x: (
        community_rotation_rank_by_org.get(host_org_by_id.get(x['host_id']), 999),
        hosting_delta_by_org.get(host_org_by_id.get(x['host_id']), 0),
        -(x['slot_count'] >= games_required),
        -(x['slot_count']),
        -(x['field_count']),
        host_name_by_id.get(x['host_id'], ''),
    ))
    existing_week_host_counts: dict[uuid.UUID, int] = {}
    existing_week_host_divisions: dict[uuid.UUID, set[str]] = {}
    for row in existing_non_unscheduled_games:
        if not row.host_location_id:
            continue
        existing_week_host_counts[row.host_location_id] = existing_week_host_counts.get(row.host_location_id, 0) + 1
        if row.name:
            existing_week_host_divisions.setdefault(row.host_location_id, set()).add(row.name)
    prior_active_hosts = sorted(
        existing_week_host_counts.keys(),
        key=lambda hid: (
            existing_week_host_counts.get(hid, 0),
            host_capacity_by_id.get(hid, 0),
        ),
        reverse=True,
    )
    def _hosts_for_rotation_community(org_id: uuid.UUID | None) -> set[uuid.UUID]:
        if not org_id:
            return set()
        return set(host_ids_by_org.get(org_id, set()))

    def _selected_capacity(host_ids: set[uuid.UUID]) -> int:
        return sum(len(weekly_slots_by_host.get(host_id, [])) for host_id in host_ids)

    def _selected_capacity_by_size(host_ids: set[uuid.UUID]) -> dict[str, int]:
        return {
            size: sum(1 for host_id in host_ids for slot in weekly_slots_by_host.get(host_id, []) if _normalize_field_size(slot.field_type) == size)
            for size in ('SMALL', 'MEDIUM', 'LARGE')
        }

    primary_rotation_org_id: uuid.UUID | None = community_rotation_ranking[0] if community_rotation_ranking else None
    primary_host_id: uuid.UUID | None = primary_host_by_org.get(primary_rotation_org_id) if primary_rotation_org_id else None
    primary_community_host_ids = _hosts_for_rotation_community(primary_rotation_org_id)
    weekly_demand_by_size = {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0}
    weekly_division_rows = (
        db.query(Division.id, Division.required_field_layout_type, func.count(Team.id))
        .join(Team, Team.division_id == Division.id)
        .filter(Team.is_active.is_(True), Division.is_active.is_(True))
        .group_by(Division.id, Division.required_field_layout_type)
        .all()
    )
    scheduled_counts_by_division = {
        div_id: int(count or 0)
        for div_id, count in db.query(Team.division_id, func.count(Game.id)).select_from(Game).join(
            Game.status
        ).join(
            Team, Game.home_team_id == Team.id
        ).filter(
            Game.season_id == season_id,
            Game.week_id == week_id,
            GameStatus.code == 'SCHEDULED',
            GameStatus.is_active.is_(True),
            Team.is_active.is_(True),
        ).group_by(Team.division_id).all()
    }
    total_weekly_games_required = 0
    for div_id, required_layout, active_team_count in weekly_division_rows:
        size = _normalize_field_size(required_layout) or FIELD_SIZE_SMALL
        required_for_division = (int(active_team_count or 0) + 1) // 2
        remaining_for_division = max(0, required_for_division - scheduled_counts_by_division.get(div_id, 0))
        weekly_demand_by_size[size] += remaining_for_division
        total_weekly_games_required += remaining_for_division
    if total_weekly_games_required == 0 and games_required > 0:
        normalized_required_field_type = _normalize_field_size(required_field_type) or FIELD_SIZE_SMALL
        weekly_demand_by_size[normalized_required_field_type] = games_required
        total_weekly_games_required = games_required

    def _capacity_sufficiency(host_ids: set[uuid.UUID], demand_by_size: dict[str, int]) -> tuple[bool, list[str]]:
        capacity_by_size = _selected_capacity_by_size(host_ids)
        reasons: list[str] = []
        total_capacity = sum(capacity_by_size.values())
        total_demand = sum(int(value or 0) for value in demand_by_size.values())
        if total_capacity < total_demand:
            reasons.append(f'total slot capacity {total_capacity} is below weekly demand {total_demand}')
        for size, demand in demand_by_size.items():
            if int(capacity_by_size.get(size, 0) or 0) < int(demand or 0):
                reasons.append(f'{size.lower()} capacity {capacity_by_size.get(size, 0)} is below demand {demand}')
        return not reasons, reasons

    primary_community_capacity = _selected_capacity(primary_community_host_ids)
    primary_community_can_host_all_games, primary_community_capacity_reasons = _capacity_sufficiency(primary_community_host_ids, weekly_demand_by_size)
    primary_community_can_host_all_games = bool(primary_rotation_org_id and primary_community_can_host_all_games)
    single_site_possible = bool(primary_host_id and len(weekly_slots_by_host.get(primary_host_id, [])) >= total_weekly_games_required)
    prefer_two_sites = total_weekly_games_required > single_site_game_limit and len(host_capacity) >= 2
    selected_host_ids: set[uuid.UUID] = set()
    overflow_host_ids: set[uuid.UUID] = set()
    selected_rotation_orgs: list[uuid.UUID] = []
    skipped_rotation_orgs: list[dict[str, str]] = []
    locked_host_mode = 'none'
    host_lock_reason = 'No compatible host locations found.'
    if host_capacity and community_rotation_ranking and host_plan_allowed_ids is not None:
        selected_host_ids = {row['host_id'] for row in host_capacity if row['host_id'] in host_plan_allowed_ids}
        selected_rotation_orgs = [
            org_id for org_id in community_rotation_ranking
            if host_ids_by_org.get(org_id, set()) & selected_host_ids
        ]
        selected_capacity = _selected_capacity(selected_host_ids)
        selected_can_host_week, selected_capacity_reasons = _capacity_sufficiency(selected_host_ids, weekly_demand_by_size)
        locked_host_mode = 'selected_host_plan'
        if selected_can_host_week:
            host_lock_reason = (
                'saved host plan selected all hosting communities for this date; allocation will balance games by community first, '
                'then split each community share across its selected locations'
            )
        else:
            host_lock_reason = (
                f'saved host plan selected all hosting communities for this date but provides only {selected_capacity} valid slot(s); '
                f'capacity fallback may be needed: {"; ".join(selected_capacity_reasons) if selected_capacity_reasons else "unknown capacity constraint"}'
            )
    elif host_capacity and community_rotation_ranking:
        for org_id in community_rotation_ranking:
            community_host_ids = _hosts_for_rotation_community(org_id)
            if not community_host_ids:
                skipped_rotation_orgs.append({
                    'community_id': str(org_id),
                    'community': org_names_by_id.get(org_id, str(org_id)),
                    'reason': 'skipped: no compatible generated slots for required field size',
                })
                continue
            selected_host_ids.update(community_host_ids)
            selected_rotation_orgs.append(org_id)
            selected_can_host_week, _selected_capacity_reasons = _capacity_sufficiency(selected_host_ids, weekly_demand_by_size)
            if selected_can_host_week or len(selected_rotation_orgs) >= 3:
                break
        for org_id in community_rotation_ranking:
            if org_id not in selected_rotation_orgs and all(row.get('community_id') != str(org_id) for row in skipped_rotation_orgs):
                skipped_rotation_orgs.append({
                    'community_id': str(org_id),
                    'community': org_names_by_id.get(org_id, str(org_id)),
                    'reason': 'unused_this_week: selected weekly host plan has enough compatible capacity',
                })
        if selected_host_ids:
            locked_host_mode = 'rotation_primary' if len(selected_rotation_orgs) == 1 else 'rotation_capacity_extension'
            selected_capacity = _selected_capacity(selected_host_ids)
            primary_name = org_names_by_id.get(primary_rotation_org_id, str(primary_rotation_org_id)) if primary_rotation_org_id else 'unknown community'
            selected_can_host_week, selected_capacity_reasons = _capacity_sufficiency(selected_host_ids, weekly_demand_by_size)
            if selected_can_host_week:
                if primary_community_can_host_all_games:
                    host_lock_reason = (
                        f'community rotation selected {primary_name}; all available host locations in that community were aggregated '
                        f'and can host all {games_required} required game(s) without adding another community'
                    )
                else:
                    host_lock_reason = (
                        f'community rotation selected {primary_name} first; that community provided {primary_community_capacity} valid slot(s), '
                        f'so additional communities were added in rotation order until {games_required} required game(s) could be hosted'
                    )
            else:
                host_lock_reason = (
                    f'community rotation capacity could provide only {selected_capacity} valid slot(s) for '
                    f'{games_required} required game(s); capacity fallback may be needed: '
                    f'{'; '.join(selected_capacity_reasons) if selected_capacity_reasons else 'unknown capacity constraint'}'
                )
        if selected_host_ids and not _capacity_sufficiency(selected_host_ids, weekly_demand_by_size)[0]:
            for host in host_capacity:
                host_id = host['host_id']
                if host_id in selected_host_ids:
                    continue
                selected_host_ids.add(host_id)
                overflow_host_ids.add(host_id)
                if _capacity_sufficiency(selected_host_ids, weekly_demand_by_size)[0]:
                    locked_host_mode = 'rotation_capacity_fallback'
                    host_lock_reason = 'rotation communities kept; extra capacity host locations added to avoid unscheduled games'
                    break
    two_location_rule_relaxed = False
    if is_odd_division and no_byes and selected_host_ids:
        def _host_ids_with_adjacent_doubleheader_capacity(host_ids: set[uuid.UUID]) -> set[uuid.UUID]:
            adjacent_host_ids: set[uuid.UUID] = set()
            slots_by_site_day: dict[tuple[uuid.UUID, object], list[GameSlot]] = {}
            for slot in open_slots:
                if not slot.host_location_id or slot.host_location_id not in host_ids:
                    continue
                slots_by_site_day.setdefault((slot.host_location_id, slot.slot_date), []).append(slot)
            for (host_id, _slot_date), host_slots in slots_by_site_day.items():
                slot_minutes = sorted(
                    minute
                    for minute in (_minutes_from_time(slot.start_time) for slot in host_slots)
                    if minute is not None
                )
                if any((minute + 60) in slot_minutes for minute in slot_minutes):
                    adjacent_host_ids.add(host_id)
            return adjacent_host_ids

        if not _host_ids_with_adjacent_doubleheader_capacity(selected_host_ids):
            adjacent_overflow_hosts = _host_ids_with_adjacent_doubleheader_capacity({row['host_id'] for row in host_capacity})
            for host in host_capacity:
                host_id = host['host_id']
                if host_id in selected_host_ids or host_id not in adjacent_overflow_hosts:
                    continue
                selected_host_ids.add(host_id)
                overflow_host_ids.add(host_id)
                locked_host_mode = 'doubleheader_adjacent_capacity_fallback'
                host_lock_reason = 'additional compatible host location added to provide same-location back-to-back doubleheader capacity'
                _add_skipped('Selected host communities lacked adjacent same-location doubleheader slots; overflow compatible host added.')
                break
    if not selected_host_ids and games_required > 0:
        fallback_hosts = [row['host_id'] for row in host_capacity[:3]]
        if fallback_hosts:
            selected_host_ids = set(fallback_hosts)
            two_location_rule_relaxed = len(selected_host_ids) > 2
            if two_location_rule_relaxed:
                _add_skipped('Two-location host preference relaxed: overflow host location enabled to complete required games.')
            locked_host_mode = 'overflow_relaxed' if two_location_rule_relaxed else 'capacity_fallback'
            host_lock_reason = 'fallback host selection used to avoid missing required games'
        else:
            _add_skipped('Unable to schedule required games due to hard scheduling constraints.')
    if selected_host_ids and not admin_override_third_host:
        remaining_slots = [slot for slot in remaining_slots if slot.host_location_id in selected_host_ids]
        open_slots = [slot for slot in open_slots if slot.host_location_id in selected_host_ids]
        slots_by_host = {host_id: host_slots for host_id, host_slots in slots_by_host.items() if host_id in selected_host_ids}
    split_host_week = len(selected_host_ids) > 1
    selected_week_org_ids: set[uuid.UUID] = set(selected_rotation_orgs) or {
        org_id for host_id, org_id in host_org_by_id.items() if host_id in selected_host_ids
    }
    selected_week_host_ids_by_org: dict[uuid.UUID, set[uuid.UUID]] = {
        org_id: set(host_ids_by_org.get(org_id, set())) & set(selected_host_ids)
        for org_id in selected_week_org_ids
    }
    selected_week_target_base = (games_required / max(len(selected_week_org_ids), 1)) if selected_week_org_ids else 0.0
    # Defensive defaults: hosting equity should influence placement, but a missing or
    # failed equity calculation must never prevent game-group generation.  This is
    # intentionally community-first; location-level shares are derived only after
    # the selected hosting communities for this week/date are known.
    expected_host_share: dict[uuid.UUID, float] = {}
    expected_host_share_by_location: dict[uuid.UUID, float] = {}

    def _fallback_equal_community_host_share(total_games: int, org_ids: set[uuid.UUID]) -> dict[uuid.UUID, float]:
        if not org_ids:
            return {}
        equal_share = total_games / max(len(org_ids), 1)
        return {org_id: equal_share for org_id in org_ids}

    def _integer_targets_from_share(expected_share_by_org: dict[uuid.UUID, float]) -> dict[uuid.UUID, int]:
        if not expected_share_by_org:
            return {}
        targets = {org_id: max(0, int(math.floor(share))) for org_id, share in expected_share_by_org.items()}
        remaining_games = max(0, games_required - sum(targets.values()))
        ordered_org_ids = sorted(expected_share_by_org, key=lambda org_id: (
            -(expected_share_by_org.get(org_id, 0.0) - math.floor(expected_share_by_org.get(org_id, 0.0))),
            _hosted_games_per_team(org_id),
            community_games_hosted_to_date.get(org_id, 0),
            -capacity_score_by_org.get(org_id, 0),
            org_names_by_id.get(org_id, str(org_id)),
        ))
        for org_id in ordered_org_ids[:remaining_games]:
            targets[org_id] = targets.get(org_id, 0) + 1
        return targets

    def _even_community_game_targets(total_games: int, org_ids: set[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not org_ids:
            return {}
        base_target = total_games // len(org_ids)
        extra_games = total_games % len(org_ids)
        ordered_org_ids = sorted(org_ids, key=lambda org_id: (
            _hosted_games_per_team(org_id),
            community_games_hosted_to_date.get(org_id, 0),
            -capacity_score_by_org.get(org_id, 0),
            org_names_by_id.get(org_id, str(org_id)),
        ))
        targets = {org_id: base_target for org_id in org_ids}
        for org_id in ordered_org_ids[:extra_games]:
            targets[org_id] += 1
        return targets

    try:
        expected_host_share = _fallback_equal_community_host_share(games_required, selected_week_org_ids)
        selected_week_target_by_org: dict[uuid.UUID, int] = _integer_targets_from_share(expected_host_share)
        if not selected_week_target_by_org and selected_week_org_ids:
            selected_week_target_by_org = _even_community_game_targets(games_required, selected_week_org_ids)
    except Exception as exc:
        logger.warning(
            'Weekly community hosting equity calculation failed for season_id=%s week_id=%s date=%s; falling back to equal community allocation: %s',
            season_id,
            week_id,
            week_game_date,
            exc,
            exc_info=True,
        )
        expected_host_share = _fallback_equal_community_host_share(games_required, selected_week_org_ids)
        selected_week_target_by_org = _even_community_game_targets(games_required, selected_week_org_ids)

    try:
        for org_id, selected_org_host_ids in selected_week_host_ids_by_org.items():
            org_share = expected_host_share.get(org_id, selected_week_target_base)
            if not selected_org_host_ids:
                continue
            org_capacity = sum(max(0, host_capacity_by_id.get(host_id, 0)) for host_id in selected_org_host_ids)
            if org_capacity > 0:
                for host_id in selected_org_host_ids:
                    expected_host_share_by_location[host_id] = org_share * (max(0, host_capacity_by_id.get(host_id, 0)) / org_capacity)
            else:
                equal_location_share = org_share / max(len(selected_org_host_ids), 1)
                for host_id in selected_org_host_ids:
                    expected_host_share_by_location[host_id] = equal_location_share
    except Exception as exc:
        logger.warning(
            'Weekly location hosting equity split failed for season_id=%s week_id=%s date=%s; falling back to equal location allocation: %s',
            season_id,
            week_id,
            week_game_date,
            exc,
            exc_info=True,
        )
        expected_host_share_by_location = {}
        for org_id, selected_org_host_ids in selected_week_host_ids_by_org.items():
            org_share = expected_host_share.get(org_id, selected_week_target_base)
            equal_location_share = org_share / max(len(selected_org_host_ids), 1) if selected_org_host_ids else 0.0
            for host_id in selected_org_host_ids:
                expected_host_share_by_location[host_id] = equal_location_share
    selected_week_target_floor_by_org = {
        org_id: target
        for org_id, target in selected_week_target_by_org.items()
    }
    selected_week_target_ceiling_by_org = {
        org_id: target
        for org_id, target in selected_week_target_by_org.items()
    }
    selected_week_assignment_events: list[dict[str, object]] = []
    projected_games_by_host: dict[uuid.UUID, int] = {}
    projected_games_by_community: dict[uuid.UUID, int] = {}
    preferred_host_id: uuid.UUID | None = primary_host_id
    used_host_ids: set[uuid.UUID] = set()
    selected_double_header_team_id: uuid.UUID | None = None
    reserved_double_header_slot_ids: set[str] = set()
    reserved_double_header_context: dict[str, object] = {}
    double_header_reservation_failure_reasons: list[str] = []
    odd_double_header_candidate_ids: list[uuid.UUID] = []
    generated_matchups_before_filter: list[dict[str, object]] = []
    matchups_removed_by_filter: list[dict[str, object]] = []
    required_matchup_pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    compatible_adjacent_slot_pairs_by_host: dict[str, list[dict[str, object]]] = {}
    doubleheader_placement_attempts: list[dict[str, object]] = []
    fallback_doubleheader_team_ids_attempted: list[uuid.UUID] = []
    placement_attempt_details: list[dict[str, object]] = []
    placement_attempt_counter = 0
    target_detailed_division_week = int(week.week_number or 0) == 8 and selected_division_key == 'COED_6_7'

    def _team_name_for_attempt(team_id: uuid.UUID | None) -> str | None:
        return teams_by_id.get(team_id).name if team_id in teams_by_id else (str(team_id) if team_id else None)

    def _record_placement_attempt(
        slot: GameSlot | None,
        home_team_id: uuid.UUID | None,
        away_team_id: uuid.UUID | None,
        status: str,
        reason: str,
        selected_field_slot: GameSlot | None = None,
    ) -> None:
        nonlocal placement_attempt_counter
        placement_attempt_counter += 1
        if not target_detailed_division_week and len(placement_attempt_details) >= 100:
            return
        slot_for_output = selected_field_slot or slot
        placement_attempt_details.append({
            'attempt_number': placement_attempt_counter,
            'status': status,
            'reason': reason,
            'home_team_id': str(home_team_id) if home_team_id else None,
            'home_team_name': _team_name_for_attempt(home_team_id),
            'away_team_id': str(away_team_id) if away_team_id else None,
            'away_team_name': _team_name_for_attempt(away_team_id),
            'matchup': f'{_team_name_for_attempt(home_team_id) or "unknown"} vs {_team_name_for_attempt(away_team_id) or "unknown"}' if home_team_id or away_team_id else None,
            'slot_id': str(slot_for_output.id) if slot_for_output else None,
            'slot_date': str(slot_for_output.slot_date) if slot_for_output and slot_for_output.slot_date else None,
            'start_time': str(slot_for_output.start_time) if slot_for_output and slot_for_output.start_time else None,
            'host_location_id': str(slot_for_output.host_location_id) if slot_for_output and slot_for_output.host_location_id else None,
            'host_location': slot_for_output.host_location.name if slot_for_output and slot_for_output.host_location else None,
            'field_instance_id': str(slot_for_output.field_instance_id) if slot_for_output and slot_for_output.field_instance_id else None,
            'field': slot_for_output.field_instance.field_name if slot_for_output and slot_for_output.field_instance else None,
            'field_type': _normalize_field_size(slot_for_output.field_type) if slot_for_output else None,
        })

    compatible_fields_by_host: dict[uuid.UUID, set[uuid.UUID]] = {}
    for slot in open_slots:
        if slot.host_location_id and slot.field_instance_id:
            compatible_fields_by_host.setdefault(slot.host_location_id, set()).add(slot.field_instance_id)
    layout_key = required_field_type.value if hasattr(required_field_type, 'value') else str(required_field_type)

    existing_field_usage_by_host_date_division_layout: dict[tuple[str, str, str, str], int] = {}
    existing_usage_rows = db.query(
        GameSlot.host_location_id,
        GameSlot.slot_date,
        GameSlot.field_instance_id,
        func.count(GameSlot.id),
    ).join(Game, Game.id == GameSlot.assigned_game_id).join(Team, Game.home_team_id == Team.id).filter(
        Team.division_id == division_id,
        Team.is_active.is_(True),
        GameSlot.field_type == required_field_type,
        GameSlot.assigned_game_id.isnot(None),
    ).group_by(
        GameSlot.host_location_id,
        GameSlot.slot_date,
        GameSlot.field_instance_id,
    ).all()
    for host_id, slot_date, field_id, usage_count in existing_usage_rows:
        existing_field_usage_by_host_date_division_layout[(str(host_id), str(slot_date), str(field_id), layout_key)] = int(usage_count or 0)

    proposed_field_usage_by_host_date_division_layout: dict[tuple[str, str, str, str], int] = {}

    def _first_compatible_open_slot_by_field_order(host_location_id: uuid.UUID | None, slot_date, slot_time) -> GameSlot | None:
        if not host_location_id:
            return None
        candidate_slots = db.query(GameSlot).join(GameSlot.field_instance).filter(
            GameSlot.host_location_id == host_location_id,
            GameSlot.slot_date == slot_date,
            GameSlot.start_time == slot_time,
            GameSlot.status == 'OPEN',
            GameSlot.assigned_game_id.is_(None),
            GameSlot.field_type == required_field_type,
        ).all()
        open_compatible_candidates: list[GameSlot] = []
        for candidate in candidate_slots:
            field_time_key = (str(candidate.host_location_id), str(candidate.field_instance_id), candidate.slot_date, candidate.start_time)
            if field_time_key not in field_time_occupied:
                open_compatible_candidates.append(candidate)
        if not open_compatible_candidates:
            return None
        return min(
            open_compatible_candidates,
            key=lambda c: (
                existing_field_usage_by_host_date_division_layout.get((str(c.host_location_id), str(c.slot_date), str(c.field_instance_id), layout_key), 0)
                + proposed_field_usage_by_host_date_division_layout.get((str(c.host_location_id), str(c.slot_date), str(c.field_instance_id), layout_key), 0),
                c.field_instance.field_name if c.field_instance and c.field_instance.field_name else '',
                str(c.id),
            ),
        )
    def _selected_org_has_compatible_remaining_capacity(org_id: uuid.UUID) -> bool:
        return any(
            s.host_location_id in selected_week_host_ids_by_org.get(org_id, set())
            and _normalize_field_size(s.field_type) == _normalize_field_size(required_field_type)
            for s in remaining_slots
        )
    def _weekly_selected_host_capacity_limitation(org_id: uuid.UUID) -> str | None:
        compatible_capacity = sum(
            1 for s in remaining_slots
            if s.host_location_id in selected_week_host_ids_by_org.get(org_id, set())
            and _normalize_field_size(s.field_type) == _normalize_field_size(required_field_type)
        )
        if compatible_capacity <= 0:
            return 'No compatible remaining capacity for required field size.'
        return None

    def _matchup_label(a: uuid.UUID, b: uuid.UUID) -> str:
        return f'{teams_by_id[a].name} vs {teams_by_id[b].name}'

    def _odd_week_matchups_for_doubleheader_team(doubleheader_team_id: uuid.UUID) -> list[tuple[uuid.UUID, uuid.UUID]]:
        remaining_team_ids = [tid for tid in teams_by_id if tid != doubleheader_team_id and week_team_game_counts.get(tid, 0) < 1]
        remaining_team_ids.sort(key=lambda tid: (
            matchup_counts.get(tuple(sorted((doubleheader_team_id, tid))), 0),
            1 if tuple(sorted((doubleheader_team_id, tid))) in prior_week_team_pairs else 0,
            teams_by_id[tid].name,
        ))
        pairs: list[tuple[uuid.UUID, uuid.UUID]] = []
        for opponent_id in remaining_team_ids[:2]:
            pairs.append(tuple(sorted((doubleheader_team_id, opponent_id))))
        rest = remaining_team_ids[2:]
        rest.sort(key=lambda tid: teams_by_id[tid].name)
        while len(rest) >= 2:
            pairs.append(tuple(sorted((rest.pop(0), rest.pop(0)))))
        return pairs[:max_new_games]

    def _adjacent_doubleheader_slot_pairs(slots: list[GameSlot]) -> list[tuple[GameSlot, GameSlot]]:
        site_day_slots: dict[tuple[uuid.UUID, object], list[GameSlot]] = {}
        for candidate_slot in sorted(slots, key=lambda x: (x.slot_date, x.start_time, str(x.host_location_id), str(x.id))):
            if not candidate_slot.host_location_id:
                continue
            site_day_slots.setdefault((candidate_slot.host_location_id, candidate_slot.slot_date), []).append(candidate_slot)
        adjacent_pairs: list[tuple[GameSlot, GameSlot]] = []
        for (host_id, _slot_date), host_slots in site_day_slots.items():
            for i in range(len(host_slots)):
                for j in range(i + 1, len(host_slots)):
                    a_slot = host_slots[i]
                    b_slot = host_slots[j]
                    a_minutes = _minutes_from_time(a_slot.start_time)
                    b_minutes = _minutes_from_time(b_slot.start_time)
                    if a_minutes is None or b_minutes is None:
                        continue
                    if abs(a_minutes - b_minutes) == 60:
                        first, second = (a_slot, b_slot) if a_minutes < b_minutes else (b_slot, a_slot)
                        adjacent_pairs.append((first, second))
                        host_key = str(host_id)
                        compatible_adjacent_slot_pairs_by_host.setdefault(host_key, []).append({
                            'host_location_id': host_key,
                            'host_location': first.host_location.name if first.host_location else None,
                            'slot_date': str(first.slot_date) if first.slot_date else None,
                            'slot_ids': [str(first.id), str(second.id)],
                            'start_times': [str(first.start_time), str(second.start_time)],
                        })
        return adjacent_pairs

    if is_odd_division and no_byes:
        min_dh = min(double_header_counts.values() or [0])
        min_count_candidates = [tid for tid, count in double_header_counts.items() if count == min_dh]
        prior_week_number = prior_week.week_number if prior_week else None
        non_consecutive_candidates = [
            tid for tid in min_count_candidates
            if prior_week_number is None or prior_week_number not in double_header_weeks_by_team.get(tid, set())
        ]
        candidates = non_consecutive_candidates or min_count_candidates
        def _dh_candidate_priority(tid: uuid.UUID) -> tuple[int, int, str]:
            team = teams_by_id.get(tid)
            home_host_ids = host_ids_by_org.get(team.organization_id, set()) if team and team.organization_id else set()
            has_home_host_slot = any(s.host_location_id in home_host_ids for s in remaining_slots) if home_host_ids else False
            has_selected_home_host_slot = any(
                s.host_location_id in home_host_ids and s.host_location_id in selected_host_ids
                for s in remaining_slots
            ) if home_host_ids else False
            return (
                0 if has_selected_home_host_slot else 1,
                0 if has_home_host_slot else 1,
                teams_by_id[tid].name,
            )
        candidates.sort(key=_dh_candidate_priority)
        odd_double_header_candidate_ids = list(candidates)
        adjacent_slot_pairs = _adjacent_doubleheader_slot_pairs(remaining_slots)
        if not adjacent_slot_pairs:
            double_header_reservation_failure_reasons.append('Unable to place required double-header because no same-location adjacent slots exist.')
        for candidate_team_id in candidates:
            candidate_pairs = _odd_week_matchups_for_doubleheader_team(candidate_team_id)
            doubleheader_placement_attempts.append({
                'team_id': str(candidate_team_id),
                'team_name': teams_by_id[candidate_team_id].name,
                'generated_matchups': [_matchup_label(a, b) for a, b in candidate_pairs],
                'adjacent_slot_pairs_available': len(adjacent_slot_pairs),
            })
            if len(candidate_pairs) < max_new_games:
                matchups_removed_by_filter.append({
                    'team_id': str(candidate_team_id),
                    'team_name': teams_by_id[candidate_team_id].name,
                    'reason': 'not enough active opponents remained to build required odd-team weekly matchups',
                })
                fallback_doubleheader_team_ids_attempted.append(candidate_team_id)
                continue
            if not adjacent_slot_pairs:
                fallback_doubleheader_team_ids_attempted.append(candidate_team_id)
                continue
            selected_double_header_team_id = candidate_team_id
            required_matchup_pairs = set(candidate_pairs)
            generated_matchups_before_filter = [
                {
                    'home_team_id': str(a),
                    'away_team_id': str(b),
                    'matchup': _matchup_label(a, b),
                    'includes_selected_doubleheader_team': selected_double_header_team_id in {a, b},
                }
                for a, b in candidate_pairs
            ]
            r1, r2 = adjacent_slot_pairs[0]
            reserved_double_header_slot_ids = {str(r1.id), str(r2.id)}
            reserved_double_header_context = {
                'team_id': str(selected_double_header_team_id),
                'team_name': teams_by_id[selected_double_header_team_id].name if selected_double_header_team_id in teams_by_id else None,
                'slot_ids': sorted(list(reserved_double_header_slot_ids)),
                'reservation_mode': 'adjacent same-location slots',
                'reservation_relaxed': False,
                'candidate_doubleheader_teams': [teams_by_id[tid].name for tid in candidates],
            }
            break
    while remaining_slots and len(plans) < max_new_games:
        if is_odd_division and no_byes and selected_double_header_team_id:
            available_team_ids = [tid for tid in teams_by_id if week_team_game_counts.get(tid, 0) < 1]
            if week_team_game_counts.get(selected_double_header_team_id, 0) < 2 and selected_double_header_team_id not in available_team_ids:
                available_team_ids.append(selected_double_header_team_id)
        else:
            available_team_ids = [tid for tid in teams_by_id if tid not in used_team_ids]
        if len(available_team_ids) < 2:
            break
        sorted_slots = sorted(remaining_slots, key=lambda s: (s.slot_date, s.start_time, str(s.host_location_id), str(s.id)))
        dh_team_needs_reservation = (
            is_odd_division
            and no_byes
            and selected_double_header_team_id is not None
            and week_team_game_counts.get(selected_double_header_team_id, 0) < 2
        )
        if dh_team_needs_reservation and reserved_double_header_slot_ids:
            sorted_slots = [slot for slot in sorted_slots if str(slot.id) in reserved_double_header_slot_ids]
        time_windows: list[tuple[object, object]] = []
        seen_time_windows: set[tuple[object, object]] = set()
        for slot in sorted_slots:
            window_key = (slot.slot_date, slot.start_time)
            if window_key in seen_time_windows:
                continue
            seen_time_windows.add(window_key)
            time_windows.append(window_key)

        valid_candidates = []
        for target_time in time_windows:
            all_candidates = []
            seen_field_time_keys: set[tuple[str, object, object]] = set()
            for slot in sorted_slots:
                if (slot.slot_date, slot.start_time) != target_time:
                    continue
                if not slot.host_location_id:
                    _record_placement_attempt(slot, None, None, 'rejected', 'Slot has no host location.')
                    continue
                field_time_key = (str(slot.host_location_id), str(slot.field_instance_id), slot.slot_date, slot.start_time)
                if field_time_key in seen_field_time_keys:
                    continue
                seen_field_time_keys.add(field_time_key)
                selected_field_slot = slot if _normalize_field_size(slot.field_type) == _normalize_field_size(required_field_type) else _first_compatible_open_slot_by_field_order(slot.host_location_id, slot.slot_date, slot.start_time)
                if not selected_field_slot:
                    _record_placement_attempt(slot, None, None, 'rejected', 'No compatible open field remains at this host/date/time for required field size.')
                    continue
                for i in range(len(available_team_ids)):
                    for j in range(i + 1, len(available_team_ids)):
                        a = available_team_ids[i]
                        b = available_team_ids[j]
                        pair = tuple(sorted((a, b)))
                        if required_matchup_pairs and pair not in required_matchup_pairs:
                            matchups_removed_by_filter.append({
                                'matchup': _matchup_label(a, b),
                                'home_team_id': str(a),
                                'away_team_id': str(b),
                                'reason': 'not part of generated odd-team required matchup set for selected doubleheader team',
                            })
                            continue
                        if pair in used_pairs:
                            _record_placement_attempt(selected_field_slot, a, b, 'rejected', 'Matchup already used in this division/week.')
                            continue
                        if (str(a), slot.slot_date, slot.start_time) in team_time_occupied or (str(b), slot.slot_date, slot.start_time) in team_time_occupied:
                            _record_placement_attempt(selected_field_slot, a, b, 'rejected', 'Team already scheduled at this date/time.')
                            continue
                        if no_simultaneous_games_same_host:
                            host_time_key = (str(slot.host_location_id), slot.slot_date, slot.start_time)
                            if host_time_key in host_time_occupied:
                                _record_placement_attempt(selected_field_slot, a, b, 'rejected', 'Host already has a simultaneous game and no-simultaneous-games-same-host is enabled.')
                                continue
                        team_a = teams_by_id[a]
                        team_b = teams_by_id[b]
                        candidate_host_id = slot.host_location_id
                        host_org_id = slot.host_location.organization_id if slot.host_location else None
                        same_community = bool(team_a.organization_id and team_a.organization_id == team_b.organization_id)
                        preferred_home_host_id = primary_host_by_org.get(team_a.organization_id) if same_community and team_a.organization_id else None
                        hosted_by_own_community = bool(same_community and team_a.organization_id and candidate_host_id in host_ids_by_org.get(team_a.organization_id, set()))
                        host_pref = bool(host_org_id and host_org_id in {team_a.organization_id, team_b.organization_id})
                        repeat_count = matchup_counts.get(pair, 0)
                        community_pair = tuple(sorted((team_a.organization_id, team_b.organization_id))) if team_a.organization_id and team_b.organization_id else None
                        prior_week_team_repeat = pair in prior_week_team_pairs
                        prior_week_community_repeat = bool(community_pair and community_pair in prior_week_community_pairs)
                        community_repeat_count = community_matchup_counts.get(community_pair, 0) if community_pair else 0
    
                        score = 1000
                        reason_bits = ['scheduled game (+1000)']
                        warning_bits = []
                        if _normalize_field_size(selected_field_slot.field_type) == _normalize_field_size(required_field_type):
                            score += 500
                            reason_bits.append('exact field-size capacity fit (+500)')
                        else:
                            score -= 10000
                            warning_bits.append('field-size mismatch (-10000)')
                            if not bool(payload.get('admin_override_incompatible_field_size', False)):
                                _record_placement_attempt(selected_field_slot, a, b, 'rejected', 'Field size is not compatible with division layout requirements.')
                                continue
                        if selected_field_slot.turf_wave_id:
                            turf_time_slots = db.query(GameSlot).filter(
                                GameSlot.host_location_id == selected_field_slot.host_location_id,
                                GameSlot.slot_date == selected_field_slot.slot_date,
                                GameSlot.start_time == selected_field_slot.start_time,
                            ).all()
                            turf_counts = _turf_slot_counts_from_slots(turf_time_slots)
                            if _is_approved_turf_slot_counts(turf_counts):
                                score += 200
                                reason_bits.append('approved turf slot-level configuration (+200)')
                            assigned_turf_counts = _turf_slot_counts_from_slots(turf_time_slots, assigned_only=True)
                            unused_turf_capacity = _turf_unused_compatible_capacity(turf_counts, assigned_turf_counts)
                            if unused_turf_capacity.get(required_field_type, 0) > 0:
                                score += 500
                                reason_bits.append('fills compatible unused turf wave capacity (+500)')
                        if is_odd_division and no_byes and selected_double_header_team_id and selected_double_header_team_id in {a, b}:
                            prior_double_header_slots = [
                                p for p in plans
                                if p.get('home_team_id') == str(selected_double_header_team_id)
                                or p.get('away_team_id') == str(selected_double_header_team_id)
                            ]
                            if prior_double_header_slots:
                                previous = prior_double_header_slots[0]
                                if previous.get('host_location_id') != str(candidate_host_id) or str(previous.get('proposed_date')) != str(slot.slot_date):
                                    continue
                                try:
                                    prev_hour = int(str(previous.get('proposed_start_time')).split(':')[0])
                                    cur_hour = int(str(slot.start_time).split(':')[0])
                                except Exception:
                                    prev_hour = cur_hour = -999
                                if abs(cur_hour - prev_hour) != 1:
                                    continue

                        active_host_has_compatible_capacity = bool(
                            selected_host_ids
                            and any(s.host_location_id in selected_host_ids for s in remaining_slots)
                        )
                        if (
                            selected_host_ids
                            and candidate_host_id
                            and candidate_host_id not in selected_host_ids
                            and not admin_override_third_host
                        ):
                            continue
                        if candidate_host_id and selected_host_ids and candidate_host_id not in selected_host_ids and active_host_has_compatible_capacity:
                            score -= 400
                            warning_bits.append('new host introduced while active host sites still have compatible capacity (-400)')
                        candidate_host = None
                        if candidate_host_id:
                            candidate_host = (
                                db.query(HostLocation)
                                .filter(HostLocation.id == candidate_host_id)
                                .first()
                            )
                        if candidate_host_id and not candidate_host:
                            logger.warning(f"HostLocation not found for id {candidate_host_id}")
                        candidate_host_org_id_for_week = candidate_host.organization_id if candidate_host else host_org_id
                        selected_team_orgs_in_game = {
                            org_id for org_id in (team_a.organization_id, team_b.organization_id)
                            if org_id in selected_week_org_ids
                        }
                        selected_home_org_match = bool(candidate_host_org_id_for_week in selected_team_orgs_in_game)
                        selected_neutral_game = bool(selected_week_org_ids and not selected_team_orgs_in_game)
                        if selected_week_org_ids and candidate_host_org_id_for_week:
                            candidate_week_count = projected_games_by_community.get(candidate_host_org_id_for_week, 0)
                            candidate_week_projected = candidate_week_count + 1
                            candidate_week_target = selected_week_target_by_org.get(candidate_host_org_id_for_week, selected_week_target_base)
                            candidate_week_floor = selected_week_target_floor_by_org.get(candidate_host_org_id_for_week, max(0, int(math.floor(selected_week_target_base - 2))))
                            candidate_week_ceiling = selected_week_target_ceiling_by_org.get(candidate_host_org_id_for_week, int(math.ceil(selected_week_target_base + 2)))
                            current_week_counts = {org_id: projected_games_by_community.get(org_id, 0) for org_id in selected_week_org_ids}
                            projected_week_counts = dict(current_week_counts)
                            projected_week_counts[candidate_host_org_id_for_week] = candidate_week_projected
                            projected_week_gap = max(projected_week_counts.values(), default=0) - min(projected_week_counts.values(), default=0)
                            below_target_available_orgs = [
                                org_id for org_id in selected_week_org_ids
                                if org_id != candidate_host_org_id_for_week
                                and current_week_counts.get(org_id, 0) < selected_week_target_floor_by_org.get(org_id, 0)
                                and _selected_org_has_compatible_remaining_capacity(org_id)
                            ]
                            candidate_over_target = candidate_week_count >= candidate_week_ceiling
                            below_target_names = [org_names_by_id.get(org_id, str(org_id)) for org_id in below_target_available_orgs]
                            lowest_week_count = min(current_week_counts.values(), default=0)
                            if candidate_host_org_id_for_week in selected_week_org_ids:
                                if selected_home_org_match:
                                    score += 30000
                                    reason_bits.append('home team plays at selected home community and counts against community share (+30000)')
                                if candidate_week_count < candidate_week_target:
                                    score += 30000
                                    reason_bits.append('selected host community below target weekly share (+30000)')
                                if candidate_week_floor <= candidate_week_projected <= candidate_week_ceiling:
                                    score += 20000
                                    reason_bits.append('keeps selected communities within exact weekly community target (+20000)')
                                if selected_neutral_game and candidate_week_count == lowest_week_count:
                                    score += 7500
                                    reason_bits.append('neutral game assigned to lowest assigned selected community (+7500)')
                                if candidate_over_target and below_target_available_orgs:
                                    if not selected_home_org_match:
                                        _record_placement_attempt(selected_field_slot, a, b, 'rejected', 'Community target hierarchy: another selected community is below target with compatible capacity.')
                                        continue
                                    score -= 60000
                                    warning_bits.append(f'home-community placement exceeds target because below-target selected communities still have capacity: {", ".join(below_target_names)} (-60000)')
                                elif candidate_over_target:
                                    score -= 7500
                                    warning_bits.append('selected community target already filled; using internal/overflow capacity only because no below-target selected community is feasible (-7500)')
                                if projected_week_gap > 1 and below_target_available_orgs:
                                    score -= 30000
                                    warning_bits.append('avoidable weekly selected-host community imbalance greater than one game (-30000)')
                            else:
                                selected_capacity_exists = any(
                                    _selected_org_has_compatible_remaining_capacity(org_id)
                                    for org_id in selected_week_org_ids
                                )
                                if selected_capacity_exists:
                                    score -= 10000
                                    warning_bits.append('non-selected community used while selected communities have compatible capacity (-10000)')
                        if (
                            selected_team_orgs_in_game
                            and candidate_host_org_id_for_week not in selected_team_orgs_in_game
                            and any(_selected_org_has_compatible_remaining_capacity(org_id) for org_id in selected_team_orgs_in_game)
                        ):
                            score -= 25000
                            warning_bits.append('selected host community home team sent away while compatible home capacity exists (-25000)')
                        if _normalize_field_size(selected_field_slot.field_type) == _normalize_field_size(required_field_type):
                            score += 2000
                            reason_bits.append('preserves field-size compatibility (+2000)')
                        teams_with_unused_unique_opponents = []
                        for team_id in (a, b):
                            if any(
                                matchup_counts.get(tuple(sorted((team_id, opponent_id))), 0) == 0
                                for opponent_id in teams_by_id
                                if opponent_id != team_id
                            ):
                                teams_with_unused_unique_opponents.append(team_id)
                        unique_opponents_exhausted_for_pair = len(teams_with_unused_unique_opponents) == 0
                        required_odd_matchup = bool(required_matchup_pairs and pair in required_matchup_pairs)
                        if repeat_count > 0 and not unique_opponents_exhausted_for_pair and not required_odd_matchup:
                            matchups_removed_by_filter.append({
                                'matchup': _matchup_label(a, b),
                                'home_team_id': str(a),
                                'away_team_id': str(b),
                                'reason': 'repeat matchup filtered while unique opponents remain',
                            })
                            continue
                        if repeat_count >= 2 and not same_community_operationally_reasonable and not required_odd_matchup:
                            # Avoid third meetings unless the division's opponent graph makes repeats unavoidable.
                            matchups_removed_by_filter.append({
                                'matchup': _matchup_label(a, b),
                                'home_team_id': str(a),
                                'away_team_id': str(b),
                                'reason': 'third-or-more meeting filtered while repeats are avoidable',
                            })
                            continue

                        if repeat_count == 0:
                            score += 180
                            reason_bits.append('new opponent pairing (+120)')
                        elif repeat_count == 1:
                            repeat_penalty = 420
                            score -= repeat_penalty
                            warning_bits.append(f'second meeting pairing penalty (-{repeat_penalty})')
                            if same_community:
                                score -= 50
                                warning_bits.append('repeat same-community opponent (-50)')
                        else:
                            # Third-or-more meetings are strongly discouraged and should only survive when unique options are exhausted.
                            repeat_penalty = 50000 + (repeat_count * 4000)
                            score -= repeat_penalty
                            warning_bits.append(f'third-or-more meeting heavily penalized (-{repeat_penalty})')
                            if same_community:
                                score -= 100
                                warning_bits.append('third-or-more same-community repeat (-100)')
    
                        if not same_community:
                            score += 40
                            reason_bits.append('cross-community opponent (+40)')
                        else:
                            cross_options_for_a = cross_community_opponents_by_team.get(a, set())
                            cross_options_for_b = cross_community_opponents_by_team.get(b, set())
                            unused_cross_for_a = any(matchup_counts.get(tuple(sorted((a, opponent))), 0) == 0 for opponent in cross_options_for_a)
                            unused_cross_for_b = any(matchup_counts.get(tuple(sorted((b, opponent))), 0) == 0 for opponent in cross_options_for_b)
                            same_community_penalty_allowed = unused_cross_for_a or unused_cross_for_b
                            if repeat_count == 0 and same_community_penalty_allowed and not same_community_operationally_reasonable:
                                score -= 25
                                warning_bits.append('first-time same-community opponent while unused cross-community options exist (-25)')
                            elif repeat_count == 0:
                                reason_bits.append('Same-community matchup allowed because cross-community options are insufficient')
    
                        if repeat_count > 0 and not same_community:
                            warning_bits.append('repeat matchup selected because unique options were exhausted')
                        if same_community_operationally_reasonable:
                            reason_bits.append('Opponent diversity prioritized because division has limited unique opponents')
                        same_community_home_unavailable_reason = None
                        if same_community and not hosted_by_own_community:
                            # Near-hard preference: same-community games should stay at the community's own host site whenever legal.
                            score -= 500
                            warning_bits.append('same-community game away from primary home host (-500)')
                            home_host_ids = {preferred_home_host_id} if preferred_home_host_id else set()
                            same_community_home_slot_available = any(
                                s.host_location_id in home_host_ids
                                and _first_compatible_open_slot_by_field_order(
                                    s.host_location_id, s.slot_date, s.start_time
                                ) is not None
                                for s in sorted_slots
                            )
                            if same_community_home_slot_available:
                                same_community_home_host_conflicts.append({
                                    'home_team_id': str(team_a.id),
                                    'away_team_id': str(team_b.id),
                                    'home_team_name': team_a.name,
                                    'away_team_name': team_b.name,
                                    'required_community_id': str(team_a.organization_id) if team_a.organization_id else None,
                                    'candidate_host_location_id': str(candidate_host_id) if candidate_host_id else None,
                                    'slot_date': str(slot.slot_date) if slot.slot_date else None,
                                    'slot_time': str(slot.start_time) if slot.start_time else None,
                                    'reason': 'same-community game rejected at non-primary-home host because compatible primary-home slot exists at this date/time',
                                })
                                continue
                            # collect reason for diagnostics when preferred home host cannot be used
                            if not home_host_ids:
                                same_community_home_unavailable_reason = 'community has no registered host locations'
                            else:
                                home_slots_same_time = [
                                    s for s in sorted_slots
                                    if s.host_location_id in home_host_ids
                                    and s.slot_date == slot.slot_date
                                    and s.start_time == slot.start_time
                                ]
                                if not home_slots_same_time:
                                    same_community_home_unavailable_reason = 'no compatible home-host slot exists for this kickoff window'
                                else:
                                    blocked_reasons = []
                                    for hs in home_slots_same_time:
                                        if (str(hs.host_location_id), str(hs.field_instance_id), hs.slot_date, hs.start_time) in field_time_occupied:
                                            blocked_reasons.append('home-host field already occupied at this time')
                                        elif (str(a), hs.slot_date, hs.start_time) in team_time_occupied or (str(b), hs.slot_date, hs.start_time) in team_time_occupied:
                                            blocked_reasons.append('team overlap at home-host time')
                                        elif no_simultaneous_games_same_host and (str(hs.host_location_id), hs.slot_date, hs.start_time) in host_time_occupied:
                                            blocked_reasons.append('host overlap rule blocks home-host slot')
                                    same_community_home_unavailable_reason = blocked_reasons[0] if blocked_reasons else 'home-host slot unavailable due to active constraints'
                                if same_community_home_unavailable_reason:
                                    warning_bits.append(f'home-site unavailable: {same_community_home_unavailable_reason}')
                        if hosted_by_own_community:
                            score += 500
                            reason_bits.append('same-community at primary home host field (+500)')
                        if host_pref:
                            score += 40
                            reason_bits.append('reduced travel via host alignment (+40)')
                        candidate_host_org_id = (
                            candidate_host.organization_id
                            if candidate_host else None
                        )
                        logger.debug(
                            f"candidate_host_id={candidate_host_id}, "
                            f"candidate_host_org_id={candidate_host_org_id}"
                        )
                        if candidate_host_id and candidate_host_org_id and not postseason_week:
                            selected_org_ids = set(selected_rotation_orgs) or set(available_host_community_ids)
                            candidate_current_games = (community_games_hosted_to_date.get(candidate_host_org_id, 0) + projected_games_by_community.get(candidate_host_org_id, 0)) / max(community_team_count_by_org.get(candidate_host_org_id, 0), 1)
                            candidate_projected_games = (community_games_hosted_to_date.get(candidate_host_org_id, 0) + projected_games_by_community.get(candidate_host_org_id, 0) + 1) / max(community_team_count_by_org.get(candidate_host_org_id, 0), 1)
                            current_games_by_selected_org = {
                                org_id: (community_games_hosted_to_date.get(org_id, 0) + projected_games_by_community.get(org_id, 0)) / max(community_team_count_by_org.get(org_id, 0), 1)
                                for org_id in selected_org_ids
                            }
                            min_selected_games = min(current_games_by_selected_org.values(), default=candidate_current_games)
                            max_selected_games_before = max(current_games_by_selected_org.values(), default=candidate_current_games)
                            min_selected_games_before = min(current_games_by_selected_org.values(), default=candidate_current_games)
                            current_gap = max_selected_games_before - min_selected_games_before
                            projected_games_by_selected_org = dict(current_games_by_selected_org)
                            projected_games_by_selected_org[candidate_host_org_id] = candidate_projected_games
                            projected_gap = max(projected_games_by_selected_org.values(), default=candidate_projected_games) - min(projected_games_by_selected_org.values(), default=candidate_projected_games)
                            projected_average = (sum(community_games_hosted_to_date.get(org_id, 0) for org_id in available_host_community_ids) + sum(projected_games_by_community.values()) + 1) / max(len(available_host_community_ids), 1)

                            def _selected_org_has_compatible_capacity(org_id: uuid.UUID) -> bool:
                                return any(
                                    s.host_location_id in host_ids_by_org.get(org_id, set())
                                    and _normalize_field_size(s.field_type) == _normalize_field_size(required_field_type)
                                    for s in remaining_slots
                                )

                            lower_selected_community_available = any(
                                org_id != candidate_host_org_id
                                and current_games_by_selected_org.get(org_id, 0) < candidate_current_games
                                and _selected_org_has_compatible_capacity(org_id)
                                for org_id in selected_org_ids
                            )
                            if candidate_current_games == min_selected_games:
                                score += 5000
                                reason_bits.append('selected community has the lowest hosted-games-per-team value (+5000)')
                            if projected_gap < current_gap:
                                score += 3000
                                reason_bits.append('reduces community hosted-games-per-team imbalance (+3000)')
                            elif projected_gap > current_gap:
                                score -= 3000
                                warning_bits.append('increases community game-count imbalance (-3000)')
                            if projected_gap <= 10:
                                score += 2000
                                reason_bits.append('keeps selected community hosted-games-per-team totals within target range (+2000)')
                            if candidate_current_games < projected_average:
                                score += 1000
                                reason_bits.append('uses compatible capacity of an underused community (+1000)')
                            if candidate_current_games > projected_average and lower_selected_community_available:
                                score -= 5000
                                warning_bits.append('extra game assigned to higher hosted-games-per-team community while lower selected community has compatible capacity (-5000)')
                            if lower_selected_community_available:
                                score -= 1000
                                warning_bits.append('leaves compatible capacity unused at an underused selected community (-1000)')
                            candidate_delta = candidate_current_games - projected_average
                            min_delta = min((count - projected_average for count in current_games_by_selected_org.values()), default=0.0)
                            if candidate_delta < 0:
                                score += 3000
                                reason_bits.append('host week assigned to community below expected share (+3000)')
                            if candidate_delta <= min_delta:
                                score += 3000
                                reason_bits.append('improves season-to-date hosting balance (+3000)')

                        if candidate_host_id and candidate_host_org_id and not postseason_week:
                            location_host_count = len(regular_season_host_occurrences_by_location.get(candidate_host_id, set()))
                            community_host_count = len(regular_season_host_occurrences_by_community.get(candidate_host_org_id, set())) if candidate_host_org_id else 0
                            min_community_host_count = min((len(regular_season_host_occurrences_by_community.get(org_id, set())) for org_id in available_host_community_ids), default=0)
                            if community_host_count == min_community_host_count:
                                score += 10000
                                reason_bits.append('fewest host weeks community (+10000)')
                            elif community_host_count > min_community_host_count:
                                feasible_lower_community_exists = any(
                                    other_org_id != candidate_host_org_id
                                    and len(regular_season_host_occurrences_by_community.get(other_org_id, set())) < community_host_count
                                    and any(s.host_location_id in host_ids_by_org.get(other_org_id, set()) for s in remaining_slots)
                                    for other_org_id in available_host_community_ids
                                )
                                if feasible_lower_community_exists:
                                    score -= 10000
                                    warning_bits.append('higher-host-week community selected while lower-host-week community is feasible (-10000)')
                            projected_location_count = location_host_count + (0 if slot.slot_date in regular_season_host_occurrences_by_location.get(candidate_host_id, set()) else 1)
                            projected_community_count = community_host_count + (0 if (candidate_host_org_id and slot.slot_date in regular_season_host_occurrences_by_community.get(candidate_host_org_id, set())) else 1)
                            all_projected_community_counts = [len(v) for v in regular_season_host_occurrences_by_community.values()]
                            all_projected_community_counts.append(projected_community_count)
                            if all_projected_community_counts:
                                comm_spread = max(all_projected_community_counts) - min(all_projected_community_counts)
                                if comm_spread <= 1:
                                    score += 3000
                                    reason_bits.append('reduces community host-week imbalance (+3000)')
                                elif projected_community_count > max(all_projected_community_counts) - 1:
                                    score -= 3000
                                    warning_bits.append('worsens community hosting imbalance (-3000)')
                            if candidate_host_id in selected_host_ids:
                                selected_capacity_total = max(1, _selected_capacity(selected_host_ids))
                                projected_selected_games = sum(projected_games_by_host.values()) + 1
                                utilization_ratio = projected_selected_games / selected_capacity_total
                                score += int(1000 * min(1.0, utilization_ratio))
                                reason_bits.append('uses selected community combined capacity efficiently (+1000)')
                            consecutive_count = _consecutive_host_count_before_date(regular_season_host_occurrences_by_community.get(candidate_host_org_id, set()), slot.slot_date)
                            if consecutive_count > 0:
                                alternative_non_consecutive_exists = any(
                                    alt_org_id != candidate_host_org_id
                                    and _consecutive_host_count_before_date(regular_season_host_occurrences_by_community.get(alt_org_id, set()), slot.slot_date) == 0
                                    and any(s.host_location_id in host_ids_by_org.get(alt_org_id, set()) for s in remaining_slots)
                                    for alt_org_id in available_host_community_ids
                                )
                                if alternative_non_consecutive_exists:
                                    score -= 7500
                                    warning_bits.append('consecutive host week when alternatives exist (-7500)')
                                else:
                                    reason_bits.append('consecutive hosting allowed: no valid non-consecutive alternative')
                            if _days_since_last_hosted(regular_season_host_occurrences_by_community.get(candidate_host_org_id, set()), slot.slot_date) >= 14:
                                score += 5000
                                reason_bits.append('community has not hosted recently (+5000)')
                            if projected_location_count > regular_season_host_limit or projected_community_count > regular_season_host_limit:
                                alternative_under_limit_exists = False
                                for alternative_slot in remaining_slots:
                                    alt_host_id = alternative_slot.host_location_id
                                    if not alt_host_id or alt_host_id == candidate_host_id:
                                        continue
                                    alt_host = alternative_slot.host_location
                                    alt_org_id = alt_host.organization_id if alt_host else None
                                    alt_loc_count = len(regular_season_host_occurrences_by_location.get(alt_host_id, set()))
                                    alt_comm_count = len(regular_season_host_occurrences_by_community.get(alt_org_id, set())) if alt_org_id else 0
                                    alt_projected_loc = alt_loc_count + (0 if alternative_slot.slot_date in regular_season_host_occurrences_by_location.get(alt_host_id, set()) else 1)
                                    alt_projected_comm = alt_comm_count + (0 if (alt_org_id and alternative_slot.slot_date in regular_season_host_occurrences_by_community.get(alt_org_id, set())) else 1)
                                    if alt_projected_loc <= regular_season_host_limit and alt_projected_comm <= regular_season_host_limit:
                                        alternative_under_limit_exists = True
                                        break
                                if alternative_under_limit_exists:
                                    score -= 5000
                                    warning_bits.append('skipping least-used available community without hard constraint (-5000)')
                                else:
                                    reason_bits.append('host rotation limit relaxed: no valid under-limit alternative for this slot')
                        if split_host_week and candidate_host_id:
                            candidate_host_capacity = max(1, host_capacity_by_id.get(candidate_host_id, 0))
                            current_host_projection = projected_games_by_host.get(candidate_host_id, 0)
                            host_load_ratio = current_host_projection / candidate_host_capacity
                            # Encourage balancing game allocation across selected locations after community selection.
                            location_balance_bonus = 500 + int(balance_weight * (1.0 - min(1.0, host_load_ratio)))
                            score += location_balance_bonus
                            reason_bits.append(f'balances games across selected community locations (+{location_balance_bonus})')
                            candidate_location_target = expected_host_share_by_location.get(candidate_host_id, 0.0)
                            if candidate_location_target > 0:
                                candidate_location_projected = current_host_projection + 1
                                if current_host_projection < candidate_location_target:
                                    score += 1500
                                    reason_bits.append('selected location below internal community share (+1500)')
                                sibling_below_location_target = any(
                                    other_host_id != candidate_host_id
                                    and other_host_id in selected_host_ids
                                    and host_org_by_id.get(other_host_id) == candidate_host_org_id
                                    and projected_games_by_host.get(other_host_id, 0) < expected_host_share_by_location.get(other_host_id, 0.0)
                                    and any(s.host_location_id == other_host_id for s in remaining_slots)
                                    for other_host_id in host_ids_by_org.get(candidate_host_org_id, set())
                                )
                                if candidate_location_projected > math.ceil(candidate_location_target) and sibling_below_location_target:
                                    score -= 1500
                                    warning_bits.append('selected location exceeds internal community share while sibling location is below target (-1500)')
                            overloaded_same_community = any(
                                other_host_id != candidate_host_id
                                and other_host_id in selected_host_ids
                                and host_org_by_id.get(other_host_id) == candidate_host_org_id
                                and projected_games_by_host.get(other_host_id, 0) < current_host_projection
                                and any(s.host_location_id == other_host_id for s in remaining_slots)
                                for other_host_id in host_ids_by_org.get(candidate_host_org_id, set())
                            )
                            if overloaded_same_community:
                                score -= 1000
                                warning_bits.append('overloading one selected community location while another is available (-1000)')

                            teams_at_host_home = int(team_a.organization_id == host_org_id) + int(team_b.organization_id == host_org_id)
                            if teams_at_host_home > 0:
                                affinity_bonus = 35 if teams_at_host_home == 1 else 75
                                score += affinity_bonus
                                reason_bits.append(f'host-site affinity (+{affinity_bonus})')
                            else:
                                away_penalty = 30
                                compatible_home_for_a = any(
                                    _has_compatible_open_field_at_time(home_host_id, slot.slot_date, slot.start_time)
                                    for home_host_id in host_ids_by_org.get(team_a.organization_id, set())
                                ) if team_a.organization_id else False
                                compatible_home_for_b = any(
                                    _has_compatible_open_field_at_time(home_host_id, slot.slot_date, slot.start_time)
                                    for home_host_id in host_ids_by_org.get(team_b.organization_id, set())
                                ) if team_b.organization_id else False
                                if compatible_home_for_a or compatible_home_for_b:
                                    away_penalty += 40
                                    warning_bits.append('host-community team scheduled away while home-compatible slot remains (-40)')
                                score -= away_penalty
                                warning_bits.append(f'away-host assignment in split-host week (-{away_penalty})')
                            same_site_bonus = 200
                            split_site_penalty = 300
                            for team_org_id in (team_a.organization_id, team_b.organization_id):
                                if not team_org_id:
                                    continue
                                assigned_hosts = community_assigned_hosts.get(team_org_id, set())
                                if not assigned_hosts:
                                    continue
                                if candidate_host_id in assigned_hosts:
                                    score += same_site_bonus
                                    reason_bits.append(f'community remains at assigned split-host site (+{same_site_bonus})')
                                    continue
                                compatible_existing_site = any(
                                    _has_compatible_open_field_at_time(assigned_host_id, slot.slot_date, slot.start_time)
                                    for assigned_host_id in assigned_hosts
                                )
                                if compatible_existing_site:
                                    score -= split_site_penalty
                                    warning_bits.append(f'avoidable community split across active host sites (-{split_site_penalty})')
                                else:
                                    warning_bits.append('community split allowed: no compatible capacity at already-used host site')
                        serialization_required = centralization_requested or staffing_limited
                        if preferred_host_id and candidate_host_id == preferred_host_id:
                            consolidation_bonus = consolidation_weight if serialization_required else max(1, consolidation_weight // 2)
                            score += consolidation_bonus
                            reason_bits.append(f'host-location consolidation (+{consolidation_bonus})')
                        elif preferred_host_id and candidate_host_id != preferred_host_id and preferred_host_id in slots_by_host:
                            preferred_open_slots = [s for s in remaining_slots if s.host_location_id == preferred_host_id]
                            if preferred_open_slots and serialization_required:
                                score -= consolidation_weight
                                warning_bits.append(f'second host used while primary host still has compatible slots (-{consolidation_weight})')
                        if single_site_possible and primary_host_id and candidate_host_id == primary_host_id and serialization_required:
                            score += max(completion_weight, 300)
                            reason_bits.append(f'single-site completion path (+{max(completion_weight, 300)})')
                        if single_site_possible and primary_host_id and candidate_host_id != primary_host_id and serialization_required:
                            score -= completion_weight
                            warning_bits.append(f'avoidable multi-site fragmentation (-{completion_weight})')
                        if locked_host_mode in {'dual', 'week_active_reuse'} and candidate_host_id in selected_host_ids:
                            score += 150
                            reason_bits.append('two-host locked scheduling (+150)')
                        if candidate_host_id and candidate_host_id in selected_host_ids and len(selected_host_ids) > 0:
                            score += 400
                            reason_bits.append('continues previously selected active host sites (+400)')
                        if candidate_host_id and candidate_host_id in selected_host_ids and len(existing_week_host_counts) > 0:
                            score += 150
                            reason_bits.append('host-site continuity preserved across divisions (+150)')
                        if prefer_two_sites and len(selected_host_ids) == 2 and candidate_host_id in selected_host_ids:
                            score += 250
                            reason_bits.append('large division/week prefers two selected host locations (+250)')
                        if candidate_host_id and any(p.get('host_location_id') == str(candidate_host_id) for p in plans):
                            score += 25
                            reason_bits.append('adjacent time-slot grouping at same location (+25)')
                        if candidate_host_id and any(
                            p.get('host_location_id') == str(candidate_host_id)
                            and p.get('field') == (selected_field_slot.field_instance.field_name if selected_field_slot.field_instance else '')
                            for p in plans
                        ):
                            score += 10
                            reason_bits.append('light adjacent-field grouping preference (+10)')
                        if is_odd_division and no_byes and selected_double_header_team_id:
                            includes_dh = selected_double_header_team_id in {a, b}
                            if reserved_double_header_slot_ids and week_team_game_counts.get(selected_double_header_team_id, 0) < 2:
                                if str(selected_field_slot.id) in reserved_double_header_slot_ids:
                                    if includes_dh:
                                        score += 550
                                        reason_bits.append('protected double-header reservation capacity (+550)')
                                    else:
                                        score -= 1200
                                        warning_bits.append('reserved double-header capacity protected (-1200)')
                                elif includes_dh:
                                    score -= 350
                                    warning_bits.append('double-header team steered to reserved adjacent capacity (-350)')
                            if week_team_game_counts.get(selected_double_header_team_id, 0) == 0 and not includes_dh:
                                score -= 200
                            if includes_dh:
                                if double_header_counts.get(selected_double_header_team_id, 0) == 0:
                                    score += 75
                                    reason_bits.append('first double-header for selected team (+75)')
                                else:
                                    score -= 200
                                    warning_bits.append('second double-header before full rotation (-200)')
                        if prior_week_team_repeat:
                            score -= 75
                            warning_bits.append('Warning: same matchup occurred last week')
                        else:
                            reason_bits.append('Avoids prior-week team repeat')
                        if prior_week_community_repeat:
                            score -= 35
                            warning_bits.append('Warning: same community pairing occurred last week')
                        else:
                            reason_bits.append('Avoids prior-week community repeat')
                        if community_repeat_count > 0:
                            score -= 20
                        if (
                            len(selected_host_ids) == 2
                            and candidate_host_id in selected_host_ids
                            and host_org_id
                        ):
                            team_a_home_host = candidate_host_id in host_ids_by_org.get(team_a.organization_id, set()) if team_a.organization_id else False
                            team_b_home_host = candidate_host_id in host_ids_by_org.get(team_b.organization_id, set()) if team_b.organization_id else False
                            if team_a_home_host or team_b_home_host:
                                score += 200
                                reason_bits.append('team scheduled at own selected host location (+200)')
    
                        double_header_back_to_back = False
                        if is_odd_division and no_byes and selected_double_header_team_id and selected_double_header_team_id in {a, b}:
                            prior_slots = [p for p in plans if p.get('home_team_id') == str(selected_double_header_team_id) or p.get('away_team_id') == str(selected_double_header_team_id)]
                            if prior_slots:
                                prev_start = prior_slots[0].get('proposed_start_time')
                                if prev_start and str(prev_start) != str(slot.start_time):
                                    try:
                                        prev_hour = int(str(prev_start).split(':')[0])
                                        cur_hour = int(str(slot.start_time).split(':')[0])
                                        if abs(cur_hour - prev_hour) == 1:
                                            score += 3000
                                            reason_bits.append('preserving same-location/back-to-back doubleheader rule (+3000)')
                                            double_header_back_to_back = True
                                        else:
                                            score -= 10000
                                            warning_bits.append('breaking back-to-back doubleheader rule (-10000)')
                                    except Exception:
                                        pass
    
                        if (
                            dh_team_needs_reservation
                            and selected_double_header_team_id
                            and selected_double_header_team_id not in {a, b}
                        ):
                            _record_placement_attempt(selected_field_slot, a, b, 'rejected', 'Reserved double-header slot must be used by selected doubleheader team.')
                            continue
                        all_candidates.append({
                            'slot': slot,
                            'selected_field_slot': selected_field_slot,
                            'home_team_id': a,
                            'away_team_id': b,
                            'pair': pair,
                            'score': score,
                            'same_community': same_community,
                            'hosted_by_own_community': hosted_by_own_community,
                            'reason_bits': reason_bits,
                            'warning_bits': warning_bits,
                            'prior_week_team_repeat': prior_week_team_repeat,
                            'double_header_back_to_back': double_header_back_to_back,
                            'same_community_home_unavailable_reason': same_community_home_unavailable_reason,
                            'compatible_home_slots_at_scheduling_time': (
                                sum(
                                    1
                                    for s in sorted_slots
                                    if same_community
                                    and team_a.organization_id
                                    and s.host_location_id in host_ids_by_org.get(team_a.organization_id, set())
                                    and _first_compatible_open_slot_by_field_order(s.host_location_id, s.slot_date, s.start_time) is not None
                                )
                                if same_community else 0
                            ),
                        })

            home_same_community_pairs = {c['pair'] for c in all_candidates if c['same_community'] and c['hosted_by_own_community']}
            filtered_candidates = [
                c for c in all_candidates
                if not (c['same_community'] and not c['hosted_by_own_community'] and c['pair'] in home_same_community_pairs)
            ]
            cross_candidates = [c for c in filtered_candidates if not c['same_community']]
            candidate_pool = cross_candidates if cross_candidates else filtered_candidates

            if candidate_pool:
                for candidate in candidate_pool:
                    candidate['is_cross_candidate'] = candidate in cross_candidates
                valid_candidates = candidate_pool
                break

        if not valid_candidates:
            break

        best = max(valid_candidates, key=lambda c: c['score'])
        selected_field_slot = best['selected_field_slot']
        if best.get('is_cross_candidate'):
            same_community_rejected = any(c['same_community'] for c in filtered_candidates)
            if same_community_rejected:
                best['reason_bits'].append('Same-community matchup avoided because cross-community option exists')
        if best['prior_week_team_repeat']:
            best['reason_bits'].append('Selected because no better alternative remained')
        home_team = teams_by_id[best['home_team_id']]
        away_team = teams_by_id[best['away_team_id']]
        host_location = selected_field_slot.host_location if selected_field_slot else None
        home_team, away_team, adjustment_reason = _enforce_host_owner_home_team(home_team, away_team, host_location)
        baseline_reason = 'single game per team per selected week'
        if is_odd_division and no_byes:
            baseline_reason = 'maximize one game per team first; allow one required double header for odd team count'
        reason_bits = [baseline_reason, *best['reason_bits'], *best['warning_bits']]
        if is_odd_division and no_byes and selected_double_header_team_id and selected_double_header_team_id in {best['home_team_id'], best['away_team_id']}:
            reason_bits.insert(0, 'Accepted as required double header due to odd team count')
        if adjustment_reason:
            reason_bits.append(adjustment_reason)
        _record_placement_attempt(selected_field_slot, home_team.id, away_team.id, 'accepted', 'Selected highest-scoring valid assignment for this placement pass.', selected_field_slot)
        plans.append({
            'slot_id': str(selected_field_slot.id),
            'proposed_matchup': f'{home_team.name} vs {away_team.name}',
            'home_team_id': str(home_team.id),
            'away_team_id': str(away_team.id),
            'proposed_date': str(selected_field_slot.slot_date),
            'proposed_start_time': str(selected_field_slot.start_time),
            'host_location': selected_field_slot.host_location.name if selected_field_slot.host_location else '',
            'host_location_id': str(selected_field_slot.host_location_id) if selected_field_slot.host_location_id else None,
            'field': selected_field_slot.field_instance.field_name if selected_field_slot.field_instance else '',
            'field_instance_id': str(selected_field_slot.field_instance_id) if selected_field_slot.field_instance_id else None,
            'field_type': selected_field_slot.field_type,
            'score': int(best['score']),
            'reason': '; '.join(reason_bits + ['deterministic field assignment: earliest available time then first compatible open field by host order']),
            'warnings': best['warning_bits'],
            'rules_relaxed': [],
            'week': week.week_number,
            'division': full_division_label,
            'same_community_home_unavailable_reason': best.get('same_community_home_unavailable_reason'),
            'compatible_home_slots_at_scheduling_time': int(best.get('compatible_home_slots_at_scheduling_time') or 0),
        })
        if (
            selected_host_ids
            and len(selected_host_ids) >= 2
            and selected_field_slot.host_location_id in selected_host_ids
            and not admin_override_third_host
        ):
            plans[-1]['warnings'] = list(plans[-1]['warnings']) + [f'Division/week scheduled across {len(selected_host_ids)} host locations for community balance.']
        selected_host_org_id = selected_field_slot.host_location.organization_id if selected_field_slot.host_location else None
        if selected_host_org_id and home_team.organization_id == selected_host_org_id:
            plans[-1]['score'] = int(plans[-1]['score']) + 150
            plans[-1]['reason'] = f"{plans[-1]['reason']}; home team aligned to own selected host location (+150)"
        if admin_override_third_host and selected_field_slot.host_location_id and selected_host_ids and selected_field_slot.host_location_id not in selected_host_ids:
            plans[-1]['warnings'] = list(plans[-1]['warnings']) + ['Admin override: third host location required.']
        usage_key = (str(selected_field_slot.host_location_id), str(selected_field_slot.slot_date), str(selected_field_slot.field_instance_id), layout_key)
        proposed_field_usage_by_host_date_division_layout[usage_key] = proposed_field_usage_by_host_date_division_layout.get(usage_key, 0) + 1
        used_pairs.add(tuple(sorted((best['home_team_id'], best['away_team_id']))))
        week_team_game_counts[best['home_team_id']] = week_team_game_counts.get(best['home_team_id'], 0) + 1
        week_team_game_counts[best['away_team_id']] = week_team_game_counts.get(best['away_team_id'], 0) + 1
        used_team_ids.add(best['home_team_id'])
        used_team_ids.add(best['away_team_id'])
        if selected_field_slot.host_location_id:
            selected_assignment_host_org_id = host_org_by_id.get(selected_field_slot.host_location_id)
            selected_home_orgs = [
                org_id for org_id in (home_team.organization_id, away_team.organization_id)
                if org_id in selected_week_org_ids
            ]
            home_team_forced_away = bool(
                home_team.organization_id in selected_week_org_ids
                and selected_assignment_host_org_id != home_team.organization_id
            )
            selected_week_assignment_events.append({
                'plan_index': len(plans),
                'host_location_id': str(selected_field_slot.host_location_id),
                'host_community_id': str(selected_assignment_host_org_id) if selected_assignment_host_org_id else None,
                'home_team_id': str(home_team.id) if home_team else None,
                'home_team_community_id': str(home_team.organization_id) if home_team and home_team.organization_id else None,
                'home_team_hosted_at_home': bool(home_team and selected_assignment_host_org_id == home_team.organization_id and home_team.organization_id in selected_week_org_ids),
                'home_team_forced_away': home_team_forced_away,
                'selected_team_community_ids': [str(org_id) for org_id in selected_home_orgs],
                'home_capacity_limitation': _weekly_selected_host_capacity_limitation(home_team.organization_id) if home_team and home_team.organization_id in selected_week_org_ids and home_team_forced_away else None,
            })
            used_host_ids.add(selected_field_slot.host_location_id)
            if selected_host_ids and selected_field_slot.host_location_id not in selected_host_ids:
                overflow_host_ids.add(selected_field_slot.host_location_id)
            projected_games_by_host[selected_field_slot.host_location_id] = projected_games_by_host.get(selected_field_slot.host_location_id, 0) + 1
            selected_host_org_id = host_org_by_id.get(selected_field_slot.host_location_id)
            if selected_host_org_id:
                projected_games_by_community[selected_host_org_id] = projected_games_by_community.get(selected_host_org_id, 0) + 1
            if not postseason_week and selected_field_slot.slot_date:
                regular_season_host_occurrences_by_location.setdefault(selected_field_slot.host_location_id, set()).add(selected_field_slot.slot_date)
                selected_host_org_id = selected_field_slot.host_location.organization_id if selected_field_slot.host_location else None
                if selected_host_org_id:
                    regular_season_host_occurrences_by_community.setdefault(selected_host_org_id, set()).add(selected_field_slot.slot_date)
            if not preferred_host_id:
                preferred_host_id = selected_field_slot.host_location_id
            for team_id in (best['home_team_id'], best['away_team_id']):
                team = teams_by_id.get(team_id)
                if team and team.organization_id:
                    community_assigned_hosts.setdefault(team.organization_id, set()).add(selected_field_slot.host_location_id)
        proposed_usage_key = (
            str(selected_field_slot.host_location_id),
            str(selected_field_slot.slot_date),
            str(selected_field_slot.field_instance_id),
            layout_key,
        )
        proposed_field_usage_by_host_date_division_layout[proposed_usage_key] = proposed_field_usage_by_host_date_division_layout.get(proposed_usage_key, 0) + 1
        field_time_occupied[(str(selected_field_slot.host_location_id), str(selected_field_slot.field_instance_id), selected_field_slot.slot_date, selected_field_slot.start_time)] = division.name
        team_time_occupied.add((str(best['home_team_id']), selected_field_slot.slot_date, selected_field_slot.start_time))
        team_time_occupied.add((str(best['away_team_id']), selected_field_slot.slot_date, selected_field_slot.start_time))
        remaining_slots = [
            s for s in remaining_slots
            if not (
                s.field_instance_id == selected_field_slot.field_instance_id
                and s.slot_date == selected_field_slot.slot_date
                and s.start_time == selected_field_slot.start_time
            )
        ]
    unused_team_ids = [str(tid) for tid in teams_by_id if tid not in used_team_ids]
    projected_counts = dict(week_team_game_counts)
    for plan in plans:
        projected_counts[uuid.UUID(plan['home_team_id'])] = projected_counts.get(uuid.UUID(plan['home_team_id']), 0) + 0
        projected_counts[uuid.UUID(plan['away_team_id'])] = projected_counts.get(uuid.UUID(plan['away_team_id']), 0) + 0
    per_team_games = [{
        'team_id': str(tid),
        'team_name': teams_by_id[tid].name,
        'games_in_week': projected_counts.get(tid, 0),
    } for tid in teams_by_id]
    duplicate_matchups = [p['proposed_matchup'] for p in plans if matchup_counts.get(tuple(sorted((uuid.UUID(p['home_team_id']), uuid.UUID(p['away_team_id'])))), 0) > 0]
    double_header_teams = [row['team_name'] for row in per_team_games if row['games_in_week'] > 1]
    if len(plans) == 0 and len(teams) > 1 and not generated_matchups_before_filter:
        _add_skipped('No eligible matchups available for this division/week.')
    total_created_games = existing_games_count + len(plans)
    if total_created_games < required_games_for_division_week:
        if is_odd_division and no_byes:
            if double_header_reservation_failure_reasons:
                for reason in double_header_reservation_failure_reasons:
                    _add_skipped(reason)
            else:
                _add_skipped('Unable to place required double-header because no same-location adjacent slots exist.')
        else:
            _add_skipped('Unable to schedule required games due to hard scheduling constraints.')
    rejected_games = len(skipped)
    logger.info(
        'division_week_diagnostics division=%s normalized_division=%s week=%s required_games=%s compatible_slots=%s teams_found=%s generated_candidate_games=%s scheduled_games_created=%s rejected_games=%s rejection_reasons=%s',
        full_division_label,
        selected_division_normalized,
        week.week_number,
        required_games_for_division_week,
        compatible_slots_found,
        len(teams),
        len(plans),
        total_created_games,
        rejected_games,
        [row.get('reason') for row in skipped],
    )
    unscheduled_team_ids = [str(tid) for tid, count in week_team_game_counts.items() if count == 0]
    teams_with_one_game = [str(tid) for tid, count in week_team_game_counts.items() if count == 1]
    double_header_team_ids = [str(tid) for tid, count in week_team_game_counts.items() if count == 2]
    overbooked_team_ids = [str(tid) for tid, count in week_team_game_counts.items() if count > 2]
    weekly_completion_ok = (
        len(unscheduled_team_ids) == 0
        and len(overbooked_team_ids) == 0
        and (
            (not (is_odd_division and no_byes) and len(double_header_team_ids) == 0)
            or ((is_odd_division and no_byes) and len(double_header_team_ids) == 1)
        )
        and total_created_games >= required_games_for_division_week
    )
    weekly_participation_status = 'complete' if weekly_completion_ok else 'incomplete'

    if (division_group_key == 'GIRLS' and len(teams) > 0 and total_created_games == 0):
        logger.error('Girls division scheduling failed due to category mismatch. division=%s normalized_division=%s week=%s', full_division_label, selected_division_normalized, week.week_number)

    logger.info(
        'auto_fill_preview division_id=%s division_key=%s active_teams=%s eligible_pairings=%s compatible_slots=%s',
        division_id,
        selected_division_key,
        len(teams),
        len(plans),
        compatible_slots_found,
    )
    host_limit_relaxation_reasons = [
        plan.get('reason', '')
        for plan in plans
        if 'host rotation limit relaxed' in str(plan.get('reason', '')).lower()
    ]
    week_host_site_usage = []
    for host_id in selected_host_ids:
        week_host_site_usage.append({
            'host_location_id': str(host_id),
            'remaining_compatible_slots': len([s for s in remaining_slots if s.host_location_id == host_id]),
            'divisions_scheduled': sorted(existing_week_host_divisions.get(host_id, set()) | {division.name}),
        })
    locked_rotation_host_ids = set(selected_host_ids)
    selected_host_ids = extract_selected_host_ids(plans)
    selected_host_id_set: set[uuid.UUID] = {uuid.UUID(str(host_id)) for host_id in (selected_host_ids or []) if host_id}
    locked_rotation_host_id_set: set[uuid.UUID] = set(locked_rotation_host_ids) or set(selected_host_id_set)

    def _host_weekly_capacity_by_size(host_id: uuid.UUID) -> dict[str, int]:
        return {
            size: sum(1 for slot in weekly_slots_by_host.get(host_id, []) if _normalize_field_size(slot.field_type) == size)
            for size in (FIELD_SIZE_SMALL, FIELD_SIZE_MEDIUM, FIELD_SIZE_LARGE)
        }

    def _weekly_plan_location_status(host_id: uuid.UUID) -> tuple[str, str]:
        capacity_by_size = _host_weekly_capacity_by_size(host_id)
        if host_id in locked_rotation_host_id_set:
            if host_id in overflow_host_ids:
                return 'selected_for_schedule', 'selected: additional host added because selected weekly host plan lacked compatible capacity or doubleheader adjacency'
            return 'selected_for_schedule', 'selected: part of weekly host plan capacity pool'
        if sum(capacity_by_size.values()) <= 0:
            return 'blocked_by_capacity', 'blocked_by_capacity: no open generated slots remain for this week'
        if all(capacity_by_size.get(size, 0) < demand for size, demand in weekly_demand_by_size.items() if demand):
            return 'blocked_by_field_size', 'blocked_by_field_size: available capacity does not match weekly field-size demand'
        return 'unused_this_week', 'unused_this_week: available in database but not needed by selected weekly host plan'

    weekly_host_plan_locations = []
    for host_id in sorted(weekly_slots_by_host.keys(), key=lambda hid: host_name_by_id.get(hid, str(hid))):
        org_id = host_org_by_id.get(host_id)
        status, reason = _weekly_plan_location_status(host_id)
        capacity_by_size = _host_weekly_capacity_by_size(host_id)
        weekly_host_plan_locations.append({
            'host_location_id': str(host_id),
            'host_location': host_name_by_id.get(host_id, str(host_id)),
            'community_id': str(org_id) if org_id else None,
            'community': org_names_by_id.get(org_id, str(org_id)) if org_id else None,
            'availability_status': 'available',
            'status': status,
            'reason_selected_or_unused': reason,
            'capacity_by_field_size': capacity_by_size,
            'total_capacity': sum(capacity_by_size.values()),
            'expected_games_hosted': round(expected_host_share_by_location.get(host_id, 0.0), 2),
            'actual_games': projected_games_by_host.get(host_id, 0),
            'unused_compatible_capacity': max(0, sum(capacity_by_size.values()) - projected_games_by_host.get(host_id, 0)),
        })

    def _host_surface_type(host_id: uuid.UUID) -> str:
        host = db.query(HostLocation).filter(HostLocation.id == host_id).first()
        return (host.surface_type if host else None) or 'GRASS_FIELD'

    def _field_configuration_summary(host_ids: set[uuid.UUID]) -> list[dict[str, object]]:
        summaries: list[dict[str, object]] = []
        for host_id in sorted(host_ids, key=lambda hid: host_name_by_id.get(hid, str(hid))):
            host_slots = slots_by_host.get(host_id, [])
            used_games = [plan for plan in plans if plan.get('host_location_id') == str(host_id)]
            capacity_by_size = {
                size: sum(1 for slot in host_slots if _normalize_field_size(slot.field_type) == size)
                for size in (FIELD_SIZE_SMALL, FIELD_SIZE_MEDIUM, FIELD_SIZE_LARGE)
            }
            used_by_size = {
                size: sum(1 for plan in used_games if _normalize_field_size(plan.get('field_type') or required_field_type) == size)
                for size in (FIELD_SIZE_SMALL, FIELD_SIZE_MEDIUM, FIELD_SIZE_LARGE)
            }
            surface_type = _host_surface_type(host_id)
            layout_counts = [f'{count}_{size.lower()}' for size, count in capacity_by_size.items() if count]
            summaries.append({
                'host_location_id': str(host_id),
                'host_location': host_name_by_id.get(host_id, str(host_id)),
                'surface_type': surface_type,
                'selected_turf_layout': 'dynamic_auto_layout' if surface_type == 'TURF_STADIUM' else None,
                'active_grass_fields_used': surface_type != 'TURF_STADIUM' and bool(host_slots),
                'small_fields_available': capacity_by_size.get(FIELD_SIZE_SMALL, 0),
                'medium_fields_available': capacity_by_size.get(FIELD_SIZE_MEDIUM, 0),
                'large_fields_available': capacity_by_size.get(FIELD_SIZE_LARGE, 0),
                'games_assigned': len(used_games),
                'games_assigned_by_size': used_by_size,
                'unused_capacity': max(0, len(host_slots) - len(used_games)),
                'layout_changes_required': 0,
                'field_size_capacity_signature': ', '.join(layout_counts) or 'no capacity',
            })
        return summaries
    host_sites_used_per_date: dict[str, list[str]] = {}
    for plan in plans:
        plan_date = str(plan.get('proposed_date') or '')
        host_id = str(plan.get('host_location_id') or '')
        if not plan_date or not host_id:
            continue
        host_sites_used_per_date.setdefault(plan_date, [])
        if host_id not in host_sites_used_per_date[plan_date]:
            host_sites_used_per_date[plan_date].append(host_id)
    uneven_game_count_teams = [row for row in per_team_games if row['games_in_week'] != required_games_per_team and not (is_odd_division and no_byes and row['games_in_week'] in {required_games_per_team, required_games_per_team - 1})]

    pair_counts_with_proposals = dict(matchup_counts)
    for plan in plans:
        pair = tuple(sorted((uuid.UUID(plan['home_team_id']), uuid.UUID(plan['away_team_id']))))
        pair_counts_with_proposals[pair] = pair_counts_with_proposals.get(pair, 0) + 1
    repeat_matchup_pairs = [
        {
            'home_team_id': str(pair[0]),
            'away_team_id': str(pair[1]),
            'home_team_name': teams_by_id[pair[0]].name if pair[0] in teams_by_id else str(pair[0]),
            'away_team_name': teams_by_id[pair[1]].name if pair[1] in teams_by_id else str(pair[1]),
            'count': count,
            'scheduled_dates': sorted([
                str(plan.get('proposed_date')) for plan in plans
                if tuple(sorted((uuid.UUID(plan['home_team_id']), uuid.UUID(plan['away_team_id'])))) == pair
            ]),
        }
        for pair, count in pair_counts_with_proposals.items() if count > 1
    ]

    plan_by_team: dict[uuid.UUID, list[dict]] = {}
    for plan in plans:
        for key in ('home_team_id', 'away_team_id'):
            team_id = uuid.UUID(plan[key])
            plan_by_team.setdefault(team_id, []).append(plan)
    double_header_spacing_issues = []
    for team_id, team_plans in plan_by_team.items():
        if len(team_plans) < 2:
            continue
        sorted_plans = sorted(team_plans, key=lambda p: (p.get('proposed_date', ''), p.get('proposed_start_time', '')))
        for idx in range(len(sorted_plans)-1):
            cur = sorted_plans[idx]
            nxt = sorted_plans[idx+1]
            same_loc = cur.get('host_location_id') == nxt.get('host_location_id')
            try:
                cur_hour = int(str(cur.get('proposed_start_time')).split(':')[0])
                nxt_hour = int(str(nxt.get('proposed_start_time')).split(':')[0])
                back_to_back = (nxt_hour - cur_hour) == 1
            except Exception:
                back_to_back = False
            if not (same_loc and back_to_back):
                double_header_spacing_issues.append({'team_id': str(team_id), 'team_name': teams_by_id[team_id].name, 'first_slot_id': cur.get('slot_id'), 'second_slot_id': nxt.get('slot_id')})

    same_community_not_home_site = []
    third_meeting_count = 0
    repeat_matchup_details = []
    for plan in plans:
        home_team = teams_by_id.get(uuid.UUID(plan['home_team_id']))
        away_team = teams_by_id.get(uuid.UUID(plan['away_team_id']))
        host_id = plan.get('host_location_id')
        if not home_team or not away_team or not home_team.organization_id or home_team.organization_id != away_team.organization_id:
            continue
        org_host_ids = {str(hid) for hid in host_ids_by_org.get(home_team.organization_id, set())}
        if host_id and org_host_ids and host_id not in org_host_ids:
            same_community_not_home_site.append({
                **plan,
                'preferred_home_site_unavailable_reason': plan.get('same_community_home_unavailable_reason') or 'no compatible home-host slot existed under active constraints',
                'compatible_home_slots_at_scheduling_time': int(plan.get('compatible_home_slots_at_scheduling_time') or 0),
            })
        pair = tuple(sorted((uuid.UUID(plan['home_team_id']), uuid.UUID(plan['away_team_id']))))
        if pair_counts_with_proposals.get(pair, 0) > 1:
            repeat_matchup_details.append({
                'home_team': home_team.name,
                'away_team': away_team.name,
                'games': pair_counts_with_proposals.get(pair, 0),
                'date': plan.get('proposed_date'),
            })
        if pair_counts_with_proposals.get(pair, 0) >= 3:
            third_meeting_count += 1

    division_labels_used = sorted({str(p.get('division') or '') for p in plans if p.get('division')})
    compliance_flags = {
        'host_site_limit_violations': [d for d, hosts in host_sites_used_per_date.items() if len(hosts) > regular_season_host_limit and not admin_override_third_host],
        'division_label_mixing_detected': any('/' in label and ('COED' not in label.upper() and 'GIRLS' not in label.upper()) for label in division_labels_used),
        'double_header_spacing_location_issues': len(double_header_spacing_issues),
        'repeat_matchups_before_exhaustion': len(repeat_matchup_pairs),
        'third_meetings': third_meeting_count,
        'uneven_game_counts': len(uneven_game_count_teams),
        'same_community_not_at_home_site': len(same_community_not_home_site),
    }
    projected_total_games_by_community = {
        org_id: community_games_hosted_to_date.get(org_id, 0) + projected_games_by_community.get(org_id, 0)
        for org_id in community_rotation_ranking
    }
    season_target_games = (sum(projected_total_games_by_community.values()) / max(len(projected_total_games_by_community), 1)) if projected_total_games_by_community else 0.0
    community_game_gap = (max(projected_total_games_by_community.values()) - min(projected_total_games_by_community.values())) if projected_total_games_by_community else 0
    compatible_unused_capacity_by_org = {
        org_id: sum(
            1 for slot in remaining_slots
            if slot.host_location_id in host_ids_by_org.get(org_id, set())
            and _normalize_field_size(slot.field_type) == _normalize_field_size(required_field_type)
        )
        for org_id in community_rotation_ranking
    }

    def _community_game_equity_reason(org_id: uuid.UUID) -> str | None:
        games_hosted = projected_total_games_by_community.get(org_id, 0)
        diff = games_hosted - season_target_games
        unused_capacity = compatible_unused_capacity_by_org.get(org_id, 0)
        if community_game_gap > 10:
            if diff > 0:
                return 'Over target; host-week rotation and compatible field-size capacity limited assignment to lower-hosted selected communities.'
            if diff < 0 and unused_capacity <= 0:
                return 'Under target; no compatible unused capacity remained in this community for the required field size.'
            if diff < 0:
                return 'Under target; compatible capacity existed but matchup, doubleheader, or time-conflict rules constrained placement.'
            return 'Within target, but league-wide highest-to-lowest game gap exceeds 10 due to capacity and compatibility constraints.'
        if diff > 0:
            return 'Slightly over season target but within the 10-game target range.'
        if diff < 0:
            return 'Slightly under season target but within the 10-game target range.'
        return 'On season target.'

    selected_week_actual_games_by_org = {
        org_id: projected_games_by_community.get(org_id, 0)
        for org_id in selected_week_org_ids
    }
    selected_week_capacity_limitations = {
        str(org_id): _weekly_selected_host_capacity_limitation(org_id)
        for org_id in selected_week_org_ids
        if _weekly_selected_host_capacity_limitation(org_id)
    }
    selected_week_validation_flags: list[dict[str, object]] = []
    for org_id in sorted(selected_week_org_ids, key=lambda oid: org_names_by_id.get(oid, str(oid))):
        actual_games = selected_week_actual_games_by_org.get(org_id, 0)
        target_games = selected_week_target_by_org.get(org_id, selected_week_target_base)
        deviation = actual_games - target_games
        capacity_reason = selected_week_capacity_limitations.get(str(org_id))
        if deviation != 0 and not capacity_reason:
            selected_week_validation_flags.append({
                'type': 'selected_host_weekly_target_deviation',
                'community_id': str(org_id),
                'community': org_names_by_id.get(org_id, str(org_id)),
                'target_games': round(target_games, 2),
                'actual_games': actual_games,
                'deviation': round(deviation, 2),
                'message': 'Selected host community differs from its exact weekly community allocation target without a capacity reason.',
            })
    forced_away_events_without_capacity_reason = [
        event for event in selected_week_assignment_events
        if event.get('home_team_forced_away') and not event.get('home_capacity_limitation')
    ]
    if forced_away_events_without_capacity_reason:
        selected_week_validation_flags.append({
            'type': 'selected_home_team_forced_away_without_capacity_reason',
            'count': len(forced_away_events_without_capacity_reason),
            'message': 'A selected host community home team was assigned away while no selected-home capacity limitation was recorded.',
        })

    def _selected_week_imbalance_reason(org_id: uuid.UUID) -> str | None:
        actual_games = selected_week_actual_games_by_org.get(org_id, 0)
        target_games = selected_week_target_by_org.get(org_id, int(round(selected_week_target_base)))
        capacity_reason = selected_week_capacity_limitations.get(str(org_id))
        if actual_games == target_games:
            return 'On target.'
        if capacity_reason and actual_games < target_games:
            return f'Under target: {capacity_reason}'
        if actual_games > target_games:
            home_overage_count = sum(
                1 for event in selected_week_assignment_events
                if event.get('host_community_id') == str(org_id) and event.get('home_team_hosted_at_home')
            )
            if home_overage_count:
                return 'Over target because required home-community placement was prioritized and counted against this community share.'
            return 'Over target because lower-target communities lacked compatible capacity, matchup, or time-window feasibility.'
        return 'Under target because matchup, home-community priority, doubleheader, time-window, or field-size constraints consumed feasible capacity elsewhere.'

    selected_week_actual_games_by_location = {
        host_name_by_id.get(host_id, str(host_id)): projected_games_by_host.get(host_id, 0)
        for host_id in sorted(locked_rotation_host_id_set | selected_host_id_set, key=lambda hid: host_name_by_id.get(hid, str(hid)))
    }
    host_allocation_summary_by_date = {
        'diagnostic_label': 'Host Allocation Summary by Date',
        'game_date': str(week_game_date),
        'week': f'Week {week.week_number}',
        'selected_host_communities': [
            {
                'community_id': str(org_id),
                'community': org_names_by_id.get(org_id, str(org_id)),
                'host_locations': [
                    {
                        'host_location_id': str(host_id),
                        'host_location': host_name_by_id.get(host_id, str(host_id)),
                    }
                    for host_id in sorted(selected_week_host_ids_by_org.get(org_id, set()), key=lambda hid: host_name_by_id.get(hid, ''))
                ],
            }
            for org_id in sorted(selected_week_org_ids, key=lambda oid: org_names_by_id.get(oid, str(oid)))
        ],
        'total_games': len(plans),
        'selected_host_community_count': len(selected_week_org_ids),
        'target_games_per_host_community': round(selected_week_target_base, 2) if selected_week_org_ids else 0,
        'adjusted_target_games_by_host_community': {
            org_names_by_id.get(org_id, str(org_id)): round(selected_week_target_by_org.get(org_id, selected_week_target_base), 2)
            for org_id in sorted(selected_week_org_ids, key=lambda oid: org_names_by_id.get(oid, str(oid)))
        },
        'actual_games_per_host_community': {
            org_names_by_id.get(org_id, str(org_id)): selected_week_actual_games_by_org.get(org_id, 0)
            for org_id in sorted(selected_week_org_ids, key=lambda oid: org_names_by_id.get(oid, str(oid)))
        },
        'actual_games_per_host_location': selected_week_actual_games_by_location,
        'reason_for_community_overage': {
            org_names_by_id.get(org_id, str(org_id)): _selected_week_imbalance_reason(org_id)
            for org_id in sorted(selected_week_org_ids, key=lambda oid: org_names_by_id.get(oid, str(oid)))
            if selected_week_actual_games_by_org.get(org_id, 0) > selected_week_target_by_org.get(org_id, int(round(selected_week_target_base)))
        },
        'reason_for_community_underage': {
            org_names_by_id.get(org_id, str(org_id)): _selected_week_imbalance_reason(org_id)
            for org_id in sorted(selected_week_org_ids, key=lambda oid: org_names_by_id.get(oid, str(oid)))
            if selected_week_actual_games_by_org.get(org_id, 0) < selected_week_target_by_org.get(org_id, int(round(selected_week_target_base)))
        },
        'home_team_games_hosted_at_home': sum(1 for event in selected_week_assignment_events if event.get('home_team_hosted_at_home')),
        'home_team_games_forced_away': sum(1 for event in selected_week_assignment_events if event.get('home_team_forced_away')),
        'capacity_limitations': selected_week_capacity_limitations,
        'reason_for_imbalance': {
            org_names_by_id.get(org_id, str(org_id)): _selected_week_imbalance_reason(org_id)
            for org_id in sorted(selected_week_org_ids, key=lambda oid: org_names_by_id.get(oid, str(oid)))
        },
        'validation_flags': selected_week_validation_flags,
        'assignment_events': selected_week_assignment_events,
    }
    weekly_multi_host_assignment_summary = host_allocation_summary_by_date

    logger.info(
        f'Selected host sites for scheduling: {selected_host_ids}'
    )
    return {
        'proposals': plans,
        'skipped': skipped,
        'proposed_game_count': len(plans),
        'generated_required_game_groups': max_new_games,
        'max_allowed_game_count': required_games_for_division_week,
        'existing_game_count': existing_games_count,
        'unused_team_ids': unused_team_ids,
        'unused_teams': [teams_by_id[uuid.UUID(tid)].name for tid in unused_team_ids],
        'double_header_team_id': str(selected_double_header_team_id) if selected_double_header_team_id else None,
        'final_validation': {
            'active_team_count': team_count,
            'required_game_count': required_games_for_division_week,
            'created_game_count': total_created_games,
            'odd_even_status_source': 'division_active_team_count',
            'unscheduled_teams': [teams_by_id[uuid.UUID(tid)].name for tid in unscheduled_team_ids],
            'double_header_team': teams_by_id[selected_double_header_team_id].name if selected_double_header_team_id else None,
            'weekly_completion_status': weekly_participation_status,
        },
        'diagnostics': {
            'weekly_participation': {
                'division': full_division_label,
                'week': week.week_number,
                'active_teams': team_count,
                'teams_with_zero_games': [teams_by_id[uuid.UUID(tid)].name for tid in unscheduled_team_ids],
                'teams_with_one_game': [teams_by_id[uuid.UUID(tid)].name for tid in teams_with_one_game],
                'double_header_team': teams_by_id[uuid.UUID(double_header_team_ids[0])].name if len(double_header_team_ids) == 1 else None,
                'required_games': required_games_for_division_week,
                'scheduled_games': total_created_games,
                'status': weekly_participation_status,
            },
            'double_header_rotation': [
                {
                    'team': teams_by_id[tid].name,
                    'double_header_count': double_header_counts.get(tid, 0),
                    'weeks_assigned': sorted(list(double_header_weeks_by_team.get(tid, set()))),
                }
                for tid in sorted(teams_by_id.keys(), key=lambda item: teams_by_id[item].name)
            ],
            'division_week_placement': {
                'week': week.week_number,
                'week_date': str(week_game_date) if week_game_date else None,
                'division_name': full_division_label,
                'required_field_size': _normalize_field_size(required_field_type) or str(required_field_type),
                'active_team_count': team_count,
                'active_teams': [teams_by_id[tid].name for tid in sorted(teams_by_id.keys(), key=lambda item: teams_by_id[item].name)],
                'expected_games': required_games_for_division_week,
                'generated_game_groups': max_new_games,
                'required_matchups_generated': [row.get('matchup') for row in generated_matchups_before_filter] or [plan.get('proposed_matchup') for plan in plans],
                'generated_matchups_before_filter': generated_matchups_before_filter,
                'matchups_removed_by_filter': matchups_removed_by_filter,
                'candidate_doubleheader_teams': [teams_by_id[tid].name for tid in odd_double_header_candidate_ids],
                'compatible_adjacent_slot_pairs_by_host': compatible_adjacent_slot_pairs_by_host,
                'doubleheader_placement_attempts': doubleheader_placement_attempts,
                'fallback_doubleheader_teams_attempted': [teams_by_id[tid].name for tid in fallback_doubleheader_team_ids_attempted],
                'placement_attempts': placement_attempt_counter,
                'valid_assignments_found': len(plans),
                'scheduled_games': total_created_games,
                'missing_games': max(0, required_games_for_division_week - total_created_games),
                'missing_teams': [teams_by_id[uuid.UUID(tid)].name for tid in unscheduled_team_ids],
                'doubleheader_team_selected': teams_by_id[selected_double_header_team_id].name if selected_double_header_team_id and selected_double_header_team_id in teams_by_id else None,
                'compatible_slot_count': compatible_slots_found,
                'compatible_large_slots_available': compatible_slots_found if _normalize_field_size(required_field_type) == FIELD_SIZE_LARGE else None,
                'skipped_placement_reasons': [row.get('reason') for row in skipped],
                'placement_attempt_details': placement_attempt_details,
            },
            'odd_team_double_header_reservation': {
                'selected_team_id': str(selected_double_header_team_id) if selected_double_header_team_id else None,
                'selected_team_name': teams_by_id[selected_double_header_team_id].name if selected_double_header_team_id and selected_double_header_team_id in teams_by_id else None,
                'reserved_slot_ids': sorted(list(reserved_double_header_slot_ids)),
                'reservation_context': reserved_double_header_context,
                'reservation_failure_reasons': double_header_reservation_failure_reasons,
                'candidate_doubleheader_teams': [teams_by_id[tid].name for tid in odd_double_header_candidate_ids],
                'compatible_adjacent_slot_pairs_by_host': compatible_adjacent_slot_pairs_by_host,
                'doubleheader_placement_attempts': doubleheader_placement_attempts,
                'fallback_doubleheader_teams_attempted': [teams_by_id[tid].name for tid in fallback_doubleheader_team_ids_attempted],
            },
            'weekly_multi_host_assignment_summary': weekly_multi_host_assignment_summary,
            'host_allocation_summary_by_date': host_allocation_summary_by_date,
            'weekly_host_planning_report': {
                'selected_host_sites': selected_host_ids,
                'overflow_sites_used': [str(hid) for hid in sorted(overflow_host_ids, key=str)],
                'two_location_rule_relaxed': two_location_rule_relaxed,
                'required_games': games_required,
                'created_games': len(plans),
                'missing_games': max(0, games_required - len(plans)),
                'host_limit_exceptions': [],
                'league_team_demand': {},
                'host_capacities': [],
            },
            'teams_evaluated': team_count,
            'slots_evaluated': compatible_slots_found,
            'valid_matchups_found': len(plans),
            'valid_slot_combinations_found': len(plans),
            'repeated_matchup_count': len(repeat_matchup_pairs),
            'third_meeting_count': third_meeting_count,
            'same_community_games_not_at_home': len(same_community_not_home_site),
            'rules_relaxed': len(host_limit_relaxation_reasons),
            'conflicts_avoided': len(skipped),
            'final_games_created': len(plans),
            'soft_priority_order': [
                'required_games_completed',
                'no_overlaps',
                'correct_field_type',
                'double_header_sequencing',
                'team_game_balance',
                'unique_opponent_diversity',
                'same_community_home_placement',
                'travel_optimization',
            ],
            'season_week_date_diagnostics': {
                'week_number': week.week_number,
                'week_start_date': str(week_game_date) if week_game_date else None,
                'week_end_date': str(week.end_date) if week.end_date else None,
                'week_open_slot_dates': sorted({str(s.slot_date) for s in sorted_slots if s.slot_date}),
                'is_week_start_date_active': any(s.slot_date == week_game_date for s in sorted_slots),
                'contains_sept_13_slot_date': any(str(s.slot_date).endswith('-09-13') for s in sorted_slots if s.slot_date),
                'week_range_includes_sept_13': bool(
                    week_game_date
                    and week_game_date == date(week_game_date.year, 9, 13)
                ),
                'sept_13_exclusion_reason': (
                    'Primary Game Date is September 13 but no compatible open slots exist on that date.'
                    if (
                        week_game_date
                        and week_game_date == date(week_game_date.year, 9, 13)
                        and not any(str(s.slot_date).endswith('-09-13') for s in sorted_slots if s.slot_date)
                    )
                    else None
                ),
            },
            'same_community_home_host_conflicts': same_community_home_host_conflicts,
            'same_community_not_home_site_details': same_community_not_home_site,
            'repeat_matchups_with_dates': repeat_matchup_details,
            'division_team_count': team_count,
            'required_games': required_games_for_division_week,
            'actual_games_scheduled': total_created_games,
            'odd_even_status_source': 'division_active_team_count',
            'week_host_site_usage': {
                'active_host_sites': week_host_site_usage,
                'overflow_sites': [str(hid) for hid in sorted(overflow_host_ids, key=str)],
            },
        },
        'audit': {
            'total_games_per_team': per_team_games,
            'duplicate_matchups': duplicate_matchups,
            'double_header_teams_by_week': double_header_teams,
            'host_locations_used_count': len(used_host_ids),
            'host_locations_used': [str(hid) for hid in used_host_ids],
            'locked_host_locations': [str(hid) for hid in sorted(locked_rotation_host_id_set, key=str)],
            'locked_host_mode': locked_host_mode,
            'host_selection_reason': host_lock_reason,
            'community_rotation_order': [
                {
                    'community_id': str(org_id),
                    'community': org_names_by_id.get(org_id, str(org_id)),
                }
                for org_id in community_rotation_ranking
            ],
            'community_hosting_equity_summary': [
                {
                    'diagnostic_label': 'Community Hosting Equity Summary',
                    'community_id': str(org_id),
                    'community': org_names_by_id.get(org_id, str(org_id)),
                    'host_locations': [
                        {'host_location_id': str(host_id), 'host_location': host_name_by_id.get(host_id, str(host_id))}
                        for host_id in sorted(host_ids_by_org.get(org_id, set()), key=lambda hid: host_name_by_id.get(hid, ''))
                    ],
                    'host_weeks': len(regular_season_host_occurrences_by_community.get(org_id, set())) + (1 if projected_games_by_community.get(org_id, 0) and week_game_date not in regular_season_host_occurrences_by_community.get(org_id, set()) else 0),
                    'host_weeks_used': len(regular_season_host_occurrences_by_community.get(org_id, set())) + (1 if projected_games_by_community.get(org_id, 0) and week_game_date not in regular_season_host_occurrences_by_community.get(org_id, set()) else 0),
                    'games_hosted': projected_total_games_by_community.get(org_id, community_games_hosted_to_date.get(org_id, 0)),
                    'games_hosted_to_date': community_games_hosted_to_date.get(org_id, 0),
                    'projected_games_added_this_preview': projected_games_by_community.get(org_id, 0),
                    'average_games_per_host_week': round(projected_total_games_by_community.get(org_id, 0) / max(len(regular_season_host_occurrences_by_community.get(org_id, set())) + (1 if projected_games_by_community.get(org_id, 0) and week_game_date not in regular_season_host_occurrences_by_community.get(org_id, set()) else 0), 1), 2) if (regular_season_host_occurrences_by_community.get(org_id, set()) or projected_games_by_community.get(org_id, 0)) else 0.0,
                    'season_target_games': round(season_target_games, 2),
                    'difference_from_target': round(projected_total_games_by_community.get(org_id, 0) - season_target_games, 2),
                    'compatible_unused_capacity': compatible_unused_capacity_by_org.get(org_id, 0),
                    'reason_if_overused_or_underused': _community_game_equity_reason(org_id),
                    'last_hosted_week': _last_hosted_week_number(regular_season_host_occurrences_by_community.get(org_id, set()), week_game_date),
                    'available_weeks': [f'Week {week.week_number}'],
                    'selected_weeks': [f'Week {week.week_number}'] if org_id in selected_rotation_orgs else [],
                    'hosting_delta': round(projected_total_games_by_community.get(org_id, 0) - season_target_games, 2),
                    'rotation_rank': community_rotation_rank_by_org.get(org_id, 999) + 1,
                }
                for org_id in community_rotation_ranking
            ],
            'weekly_community_host_plan': {
                'diagnostic_label': 'Weekly Host Plan Summary',
                'week': f'Week {week.week_number}',
                'date': str(week_game_date) if week_game_date else None,
                'total_games_required': total_weekly_games_required,
                'field_size_demand': weekly_demand_by_size,
                'available_communities': [org_names_by_id.get(org_id, str(org_id)) for org_id in community_rotation_ranking],
                'available_locations': [row['host_location'] for row in weekly_host_plan_locations],
                'selected_communities': [org_names_by_id.get(org_id, str(org_id)) for org_id in selected_rotation_orgs],
                'selected_locations': [row['host_location'] for row in weekly_host_plan_locations if row['status'] == 'selected_for_schedule'],
                'unused_locations': [row['host_location'] for row in weekly_host_plan_locations if row['status'] == 'unused_this_week'],
                'location_statuses': weekly_host_plan_locations,
                'selected_community_or_communities': [org_names_by_id.get(org_id, str(org_id)) for org_id in selected_rotation_orgs],
                'reason_selected': host_lock_reason,
                'target_games_per_selected_community': {
                    org_names_by_id.get(org_id, str(org_id)): round(selected_week_target_by_org.get(org_id, selected_week_target_base), 2)
                    for org_id in selected_week_org_ids
                },
                'actual_games_per_selected_community': {
                    org_names_by_id.get(org_id, str(org_id)): projected_games_by_community.get(org_id, 0)
                    for org_id in selected_week_org_ids
                },
                'capacity_by_field_size': {
                    row['host_location']: row['capacity_by_field_size']
                    for row in weekly_host_plan_locations
                },
                'unused_compatible_capacity': {
                    row['host_location']: row['unused_compatible_capacity']
                    for row in weekly_host_plan_locations
                },
                'reason_if_additional_host_was_added': host_lock_reason if overflow_host_ids else None,
                'community_capacity_by_field_size': {
                    org_names_by_id.get(org_id, str(org_id)): _selected_capacity_by_size(_hosts_for_rotation_community(org_id) & locked_rotation_host_id_set)
                    for org_id in selected_rotation_orgs
                },
                'locations_used_under_each_community': [
                    {
                        'community_id': str(org_id),
                        'community': org_names_by_id.get(org_id, str(org_id)),
                        'games_assigned': projected_games_by_community.get(org_id, 0),
                        'locations': [
                            {
                                'host_location_id': str(host_id),
                                'host_location': host_name_by_id.get(host_id, str(host_id)),
                                'games_assigned': projected_games_by_host.get(host_id, 0),
                            }
                            for host_id in sorted(_hosts_for_rotation_community(org_id) & locked_rotation_host_id_set, key=lambda hid: host_name_by_id.get(hid, ''))
                        ],
                    }
                    for org_id in selected_rotation_orgs
                ],
                'games_assigned_per_location': [
                    {
                        'host_location_id': str(host_id),
                        'host_location': host_name_by_id.get(host_id, str(host_id)),
                        'games_assigned': projected_games_by_host.get(host_id, 0),
                    }
                    for host_id in sorted(locked_rotation_host_id_set, key=lambda hid: host_name_by_id.get(hid, ''))
                ],
                'reason_additional_community_was_needed': (
                    'Primary selected community lacked enough aggregate weekly capacity, rotation/equity selected a second host, or field-size/doubleheader constraints required expansion.'
                    if len(selected_rotation_orgs) > 1 else None
                ),
                'community_game_count_gap': community_game_gap,
                'community_game_count_target_range': 10,
                'community_game_count_gap_within_target': community_game_gap <= 10,
                'community_game_count_gap_reason': None if community_game_gap <= 10 else 'Gap exceeds 10 because host-week rotation, compatible field sizes, doubleheader/time rules, or selected-community capacity constrained lower-hosted communities.',
                'weekly_multi_host_assignment_summary': weekly_multi_host_assignment_summary,
            },
            'selected_host_locations_by_community': [
                {
                    'community_id': str(org_id),
                    'community': org_names_by_id.get(org_id, str(org_id)),
                    'host_locations': [
                        {
                            'host_location_id': str(host_id),
                            'host_location': host_name_by_id.get(host_id, str(host_id)),
                            'capacity': len(slots_by_host.get(host_id, [])),
                        }
                        for host_id in sorted(_hosts_for_rotation_community(org_id) & locked_rotation_host_id_set, key=lambda hid: host_name_by_id.get(hid, ''))
                    ],
                    'combined_capacity': _selected_capacity(_hosts_for_rotation_community(org_id) & locked_rotation_host_id_set),
                    'combined_capacity_by_size': _selected_capacity_by_size(_hosts_for_rotation_community(org_id) & locked_rotation_host_id_set),
                }
                for org_id in selected_rotation_orgs
            ],
            'combined_selected_community_capacity': _selected_capacity(locked_rotation_host_id_set),
            'combined_selected_community_capacity_by_size': _selected_capacity_by_size(locked_rotation_host_id_set),
            'primary_community_can_host_all_games': primary_community_can_host_all_games,
            'community_capacity_assessment': {
                'week': f'Week {week.week_number}',
                'selected_primary_community_id': str(primary_rotation_org_id) if primary_rotation_org_id else None,
                'selected_primary_community': org_names_by_id.get(primary_rotation_org_id, str(primary_rotation_org_id)) if primary_rotation_org_id else None,
                'available_host_locations': [
                    {'host_location_id': str(host_id), 'host_location': host_name_by_id.get(host_id, str(host_id))}
                    for host_id in sorted(primary_community_host_ids, key=lambda hid: host_name_by_id.get(hid, ''))
                ],
                'small_capacity': _selected_capacity_by_size(primary_community_host_ids).get(FIELD_SIZE_SMALL, 0),
                'medium_capacity': _selected_capacity_by_size(primary_community_host_ids).get(FIELD_SIZE_MEDIUM, 0),
                'large_capacity': _selected_capacity_by_size(primary_community_host_ids).get(FIELD_SIZE_LARGE, 0),
                'total_slot_capacity': primary_community_capacity,
                'weekly_demand': weekly_demand_by_size,
                'can_host_entire_week': primary_community_can_host_all_games,
                'reason_if_no': '; '.join(primary_community_capacity_reasons) if primary_community_capacity_reasons else None,
                'additional_communities_added': [
                    {'community_id': str(org_id), 'community': org_names_by_id.get(org_id, str(org_id))}
                    for org_id in selected_rotation_orgs[1:]
                ],
            },
            'field_configuration_summary': _field_configuration_summary(locked_rotation_host_id_set),
            'additional_communities_needed': len(selected_rotation_orgs) > 1,
            'single_site_game_limit': single_site_game_limit,
            'admin_override_third_host_locations': admin_override_third_host,
            'split_host_week': split_host_week,
            'multi_host_assignment_validation_flags': selected_week_validation_flags,
            'single_site_possible': single_site_possible,
            'centralization_requested': centralization_requested,
            'staffing_limited': staffing_limited,
            'selected_division_id': str(division_id),
            'selected_division_key': selected_division_key,
            'selected_division_normalized': selected_division_normalized,
            'active_teams_found': len(teams),
            'eligible_pairings_generated': len(plans),
            'compatible_slots_found': compatible_slots_found,
            'postseason_host_limit_exempt': postseason_week,
            'available_host_communities': [
                {
                    'community_id': str(org_id),
                    'community': org_names_by_id.get(org_id, str(org_id)),
                }
                for org_id in community_rotation_ranking
            ],
            'selected_host_communities': [
                {
                    'community_id': str(org_id),
                    'community': org_names_by_id.get(org_id, str(org_id)),
                    'selection_reason': 'primary rotation host' if index == 0 else 'added after rotation because earlier communities lacked enough valid capacity',
                }
                for index, org_id in enumerate(selected_rotation_orgs)
            ],
            'skipped_host_communities': skipped_rotation_orgs + [
                {
                    'community_id': str(org_id),
                    'community': org_names_by_id.get(org_id, str(org_id)),
                    'reason': 'unused_this_week: selected weekly host plan has enough compatible capacity',
                }
                for org_id in community_rotation_ranking
                if org_id not in selected_rotation_orgs and all(row.get('community_id') != str(org_id) for row in skipped_rotation_orgs)
            ],
            'host_rotation_ranking': [
                {
                    'community_id': str(org_id),
                    'community': org_names_by_id.get(org_id, str(org_id)),
                    'host_weeks_used': len(regular_season_host_occurrences_by_community.get(org_id, set())),
                    'last_hosted_week_number': _last_hosted_week_number(regular_season_host_occurrences_by_community.get(org_id, set()), week_game_date),
                    'weeks_since_last_hosted': None if _days_since_last_hosted(regular_season_host_occurrences_by_community.get(org_id, set()), week_game_date) >= 999_999 else round(_days_since_last_hosted(regular_season_host_occurrences_by_community.get(org_id, set()), week_game_date) / 7, 2),
                    'days_since_last_hosted': _days_since_last_hosted(regular_season_host_occurrences_by_community.get(org_id, set()), week_game_date),
                    'consecutive_host_weeks': _consecutive_host_count_before_date(regular_season_host_occurrences_by_community.get(org_id, set()), week_game_date),
                    'rotation_rank': community_rotation_rank_by_org.get(org_id, 999) + 1,
                    'selected_as_host': org_id in selected_rotation_orgs,
                    'reason_selected_or_skipped': (
                        'selected as primary rotation host' if selected_rotation_orgs and org_id == selected_rotation_orgs[0]
                        else 'added in rotation order because previous selected community capacity was insufficient' if org_id in selected_rotation_orgs
                        else 'skipped: selected rotation community capacity was sufficient' if capacity_score_by_org.get(org_id, 0) > 0
                        else 'skipped: no compatible generated slots for required field size'
                    ),
                    'games_hosted_season_to_date': community_games_hosted_to_date.get(org_id, 0),
                    'expected_games_hosted': round(expected_host_share.get(org_id, selected_week_target_base), 2),
                    'hosting_delta': round(hosting_delta_by_org.get(org_id, 0.0), 2),
                    'available_field_capacity_by_size': {
                        size: sum(1 for host_id in host_ids_by_org.get(org_id, set()) for slot in slots_by_host.get(host_id, []) if slot.field_type == size)
                        for size in ('SMALL', 'MEDIUM', 'LARGE')
                    },
                    'capacity_score': capacity_score_by_org.get(org_id, 0),
                    'capacity_fit_result': 'selected/valid capacity' if org_id in selected_rotation_orgs else ('valid but not needed' if capacity_score_by_org.get(org_id, 0) > 0 else 'no valid slots'),
                }
                for org_id in community_rotation_ranking
            ],
            'total_host_occurrences_by_community': [
                {'community_id': str(org_id), 'host_occurrences': len(occurrences)}
                for org_id, occurrences in regular_season_host_occurrences_by_community.items()
            ],
            'total_host_occurrences_by_location': [
                {'host_location_id': str(host_id), 'host_occurrences': len(occurrences)}
                for host_id, occurrences in regular_season_host_occurrences_by_location.items()
            ],
            'communities_exceeding_recommended_hosting_limits': [
                str(org_id)
                for org_id, occurrences in regular_season_host_occurrences_by_community.items()
                if len(occurrences) > regular_season_host_limit
            ],
            'host_locations_exceeding_recommended_hosting_limits': [
                str(host_id)
                for host_id, occurrences in regular_season_host_occurrences_by_location.items()
                if len(occurrences) > regular_season_host_limit
            ],
            'balanced_hosting_achieved': (
                not regular_season_host_occurrences_by_community
                or (
                    max(len(v) for v in regular_season_host_occurrences_by_community.values())
                    - min(len(v) for v in regular_season_host_occurrences_by_community.values())
                ) <= 1
            ),
        'field_balancing': {
            'min_concurrent_games_before_balancing': min_concurrent_games_for_balancing,
            'max_consecutive_games_same_field': max_consecutive_games_same_field,
            'preferred_utilization_spread': preferred_utilization_spread,
        },
            'consolidation_achieved': len(used_host_ids) <= 1 if plans else True,
            'fragmentation_necessary': (not single_site_possible and len(used_host_ids) > 1),
            'fragmentation_avoidable': (single_site_possible and len(used_host_ids) > 1),
            'primary_host_location_id': str(primary_host_id) if primary_host_id else None,
            'games_outside_primary_host': len([p for p in plans if p.get('host_location_id') and primary_host_id and p.get('host_location_id') != str(primary_host_id)]),
            'rules_relaxed': [],
            'host_limit_relaxation_reasons': host_limit_relaxation_reasons,
            'unresolved_conflicts': [],
            'compliance_report': {
                'host_sites_used_per_date': host_sites_used_per_date,
                'teams_with_uneven_game_counts': uneven_game_count_teams,
                'repeat_matchups': repeat_matchup_pairs,
                'double_header_spacing_location_issues': double_header_spacing_issues,
                'same_community_games_not_at_home_site': [
                    {
                        'slot_id': p.get('slot_id'),
                        'matchup': p.get('proposed_matchup'),
                        'host_location_id': p.get('host_location_id'),
                    }
                    for p in same_community_not_home_site
                ],
                'division_labels_used': division_labels_used,
            },
            'compliance_flags': compliance_flags,
        },
    }


@router.post('/manual-schedule-builder/auto-fill-apply', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def auto_fill_apply(payload: dict, db: Session = Depends(get_db)):
    season_id = payload.get('season_id')
    week_id = payload.get('week_id')
    division_id = payload.get('division_id')
    proposals = payload.get('proposals') or []
    two_location_rule_relaxed = False
    for proposal in proposals or []:
        reason = (proposal.get('reason') or '').lower()
        if (
            proposal.get('two_location_rule_relaxed')
            or proposal.get('is_overflow')
            or proposal.get('overflow')
            or 'two-location' in reason
            or 'overflow' in reason
        ):
            two_location_rule_relaxed = True
            break
    no_simultaneous_games_same_host = bool(payload.get('no_simultaneous_games_same_host', False))
    if not season_id or not week_id or not division_id:
        raise HTTPException(400, 'season_id, week_id, and division_id are required')
    if not proposals:
        return {
            'proposed_count': 0,
            'created_count': 0,
            'skipped_count': 0,
            'max_games': 0,
            'created_games': 0,
            'assigned_slots': 0,
            'skipped': [],
        }
    season = db.query(Season).filter(Season.id == season_id).first()
    if not season:
        raise HTTPException(404, 'Selected season is invalid')
    week = db.query(Week).filter(Week.id == week_id, Week.season_id == season_id).first()
    if not week:
        raise HTTPException(404, 'Selected week is invalid for this season')
    week_game_date = _week_game_date(week)
    if not week_game_date:
        raise HTTPException(400, 'Selected week is missing a Primary Game Date')
    if not _is_regular_season_week(week):
        raise HTTPException(400, f'{_week_date_type(week)} weeks are excluded from regular-season auto-schedule')
    teams = db.query(Team).filter(Team.division_id == division_id, Team.is_active.is_(True)).all()
    division = db.query(Division).filter(Division.id == division_id).first()
    if not division:
        raise HTTPException(404, 'Selected division is invalid')
    if not teams:
        raise HTTPException(400, 'Division/week produced zero valid schedule candidates.')
    required_field_type = _required_field_type_for_division(division)
    open_slots_count = db.query(GameSlot).filter(
        GameSlot.season_id == season_id,
        GameSlot.week_id == week_id,
        GameSlot.slot_date == week_game_date,
        GameSlot.status == 'OPEN',
        GameSlot.assigned_game_id.is_(None),
        GameSlot.field_type == required_field_type,
        GameSlot.host_location_id.in_(_eligible_host_location_ids(db)),
    ).count()
    if open_slots_count <= 0:
        raise HTTPException(400, 'No valid slot combinations available.')
    host_locations_count = db.query(GameSlot.host_location_id).filter(
        GameSlot.season_id == season_id,
        GameSlot.week_id == week_id,
        GameSlot.slot_date == week_game_date,
        GameSlot.status == 'OPEN',
        GameSlot.assigned_game_id.is_(None),
        GameSlot.field_type == required_field_type,
        GameSlot.host_location_id.is_not(None),
        GameSlot.host_location_id.in_(_eligible_host_location_ids(db)),
    ).distinct().count()
    if host_locations_count <= 0:
        raise HTTPException(400, 'No compatible host locations found.')
    open_slots = db.query(GameSlot).join(GameSlot.field_instance).filter(
        GameSlot.season_id == season_id,
        GameSlot.week_id == week_id,
        GameSlot.slot_date == week_game_date,
        GameSlot.status == 'OPEN',
        GameSlot.assigned_game_id.is_(None),
        GameSlot.field_type == required_field_type,
        GameSlot.host_location_id.in_(_eligible_host_location_ids(db)),
    ).all()
    host_plan_allowed_ids = _host_plan_allowed_host_ids_for_week(db, season_id, week_id, week_game_date)
    if host_plan_allowed_ids is not None:
        open_slots = [slot for slot in open_slots if slot.host_location_id in host_plan_allowed_ids]
    sorted_slots = sorted(
        open_slots or [],
        key=lambda s: (
            getattr(s, 'slot_date', None),
            getattr(s, 'start_time', None),
            str(getattr(s, 'host_location_id', '')),
            str(getattr(s, 'field_instance_id', '')),
        ),
    )
    logger.info(
        'auto_fill_apply_start season_id=%s week_id=%s division_id=%s active_team_count=%s open_slot_count=%s host_location_count=%s valid_matchup_count=%s',
        season_id, week_id, division_id, len(teams), open_slots_count, host_locations_count, len(proposals),
    )
    try:
        primary_host_by_org = _primary_host_by_org(db)
    except Exception:
        logger.warning(
            'auto_fill_apply_primary_host_map_unavailable season_id=%s week_id=%s division_id=%s; continuing without same-community host preference',
            season_id,
            week_id,
            division_id,
            exc_info=True,
        )
        primary_host_by_org = {}
    if primary_host_by_org is None:
        primary_host_by_org = {}
    team_ids = {t.id for t in teams}
    no_byes = bool(payload.get('no_byes', True))
    is_odd_division = len(teams) % 2 == 1
    required_games_for_division_week = (len(teams) + 1) // 2
    existing_division_games = db.query(Game).select_from(Game).join(Team, Game.home_team_id == Team.id).join(Game.status).filter(
        Game.season_id == season_id,
        Game.week_id == week_id,
        Team.division_id == division_id,
        Team.is_active.is_(True),
        GameStatus.code == 'SCHEDULED',
        GameStatus.is_active.is_(True),
    ).all()
    used_team_ids: set[uuid.UUID] = set()
    week_team_game_counts: dict[uuid.UUID, int] = {t.id: 0 for t in teams}
    for g in existing_division_games:
        if g.home_team_id in team_ids:
            used_team_ids.add(g.home_team_id)
            week_team_game_counts[g.home_team_id] = week_team_game_counts.get(g.home_team_id, 0) + 1
        if g.away_team_id in team_ids:
            used_team_ids.add(g.away_team_id)
            week_team_game_counts[g.away_team_id] = week_team_game_counts.get(g.away_team_id, 0) + 1
    status = db.query(GameStatus).filter(GameStatus.code == 'SCHEDULED').first()
    if not status:
        raise HTTPException(400, 'Game status setup is incomplete: missing SCHEDULED status')
    created_games = 0
    assigned_slots = 0
    skipped: list[dict[str, str]] = []
    skipped_seen: set[str] = set()

    def _add_skipped(reason: str) -> None:
        if reason in skipped_seen:
            return
        skipped_seen.add(reason)
        skipped.append({'reason': reason})
    existing_games_count = len(existing_division_games)
    teams_by_id = {str(team.id): team for team in teams}
    existing_non_unscheduled_games = db.query(
        Game.id,
        Game.home_team_id,
        Game.away_team_id,
        Game.game_date,
        Game.kickoff_time,
        GameSlot.host_location_id,
        GameSlot.field_instance_id,
        Division.name,
    ).select_from(Game).join(Game.status).join(Team, Game.home_team_id == Team.id).join(Division, Team.division_id == Division.id).outerjoin(
        GameSlot, GameSlot.assigned_game_id == Game.id
    ).filter(
        Game.game_date == db.query(Week.primary_game_date).filter(Week.id == week_id).scalar_subquery(),
        GameStatus.code != 'UNSCHEDULED',
        GameStatus.is_active.is_(True),
    ).all()
    team_time_occupied = {
        (str(team_id), game_date, kickoff_time)
        for row in existing_non_unscheduled_games
        for team_id, game_date, kickoff_time in (
            (row.home_team_id, row.game_date, row.kickoff_time),
            (row.away_team_id, row.game_date, row.kickoff_time),
        )
        if team_id and game_date and kickoff_time
    }
    field_time_occupied = {
        (str(row.host_location_id), str(row.field_instance_id), row.game_date, row.kickoff_time): row.name
        for row in existing_non_unscheduled_games
        if row.field_instance_id and row.game_date and row.kickoff_time
    }
    host_time_occupied = {
        (str(row.host_location_id), row.game_date, row.kickoff_time): row.name
        for row in existing_non_unscheduled_games
        if row.host_location_id and row.game_date and row.kickoff_time
    }

    def _has_compatible_open_field_at_time(host_location_id: uuid.UUID | None, slot_date, slot_time) -> bool:
        if not host_location_id:
            return False
        compatible_open_slots = db.query(GameSlot).join(GameSlot.field_instance).filter(
            GameSlot.host_location_id == host_location_id,
            GameSlot.slot_date == slot_date,
            GameSlot.start_time == slot_time,
            GameSlot.status == 'OPEN',
            GameSlot.assigned_game_id.is_(None),
            GameSlot.field_type == required_field_type,
        ).all()
        for open_slot in compatible_open_slots:
            open_field_key = (str(open_slot.host_location_id), str(open_slot.field_instance_id), open_slot.slot_date, open_slot.start_time)
            if open_field_key not in field_time_occupied:
                return True
        return False

    def _team_name(team_id: str | None) -> str:
        if not team_id:
            return 'Unknown Team'
        team = teams_by_id.get(str(team_id))
        return team.name if team else 'Unknown Team'

    def _minutes_from_time(value: time | None) -> int:
        if not value:
            return 0
        return (value.hour * 60) + value.minute

    host_locations = db.query(HostLocation).filter(HostLocation.is_active.is_(True)).all()
    host_org_by_location_id: dict[str, str] = {
        str(host.id): str(host.organization_id)
        for host in host_locations
        if host.id and host.organization_id
    }
    host_ids_by_org: dict[str, set[str]] = {}
    for location_id, org_id in host_org_by_location_id.items():
        host_ids_by_org.setdefault(org_id, set()).add(location_id)

    def _slot_host_rank(
        requested_slot: GameSlot | None,
        candidate_slot: GameSlot,
    ) -> int:
        if not candidate_slot.host_location_id:
            return 4
        if requested_slot and requested_slot.field_instance_id and candidate_slot.field_instance_id and requested_slot.field_instance_id == candidate_slot.field_instance_id:
            return 0
        if requested_slot and requested_slot.host_location_id and candidate_slot.host_location_id == requested_slot.host_location_id:
            return 1
        requested_org_id = host_org_by_location_id.get(str(requested_slot.host_location_id)) if requested_slot and requested_slot.host_location_id else None
        candidate_org_id = host_org_by_location_id.get(str(candidate_slot.host_location_id))
        if requested_org_id and candidate_org_id and requested_org_id == candidate_org_id:
            return 2
        return 3

    def _find_adjacent_double_header_slot(
        requested_slot: GameSlot,
        home_team_id: str,
        away_team_id: str,
    ) -> GameSlot | None:
        team_ids = {str(home_team_id), str(away_team_id)}
        occupied_times_by_team: dict[str, set[time]] = {team_id: set() for team_id in team_ids}
        for team_id, game_date, kickoff_time in team_time_occupied:
            if team_id in team_ids and game_date == requested_slot.slot_date and kickoff_time:
                occupied_times_by_team.setdefault(team_id, set()).add(kickoff_time)
        target_team_id = next((team_id for team_id, times in occupied_times_by_team.items() if requested_slot.start_time in times), None)
        if not target_team_id:
            return None
        target_time_minutes = _minutes_from_time(requested_slot.start_time)
        target_team_times = occupied_times_by_team.get(target_team_id, set())
        open_slots = db.query(GameSlot).join(GameSlot.field_instance).filter(
            GameSlot.slot_date == requested_slot.slot_date,
            GameSlot.status == 'OPEN',
            GameSlot.assigned_game_id.is_(None),
            GameSlot.field_type == required_field_type,
            GameSlot.id != requested_slot.id,
        ).all()
        ranked: list[tuple[int, int, int, GameSlot]] = []
        for candidate_slot in open_slots:
            if not candidate_slot.start_time or not candidate_slot.field_instance_id:
                continue
            if (str(home_team_id), candidate_slot.slot_date, candidate_slot.start_time) in team_time_occupied:
                continue
            if (str(away_team_id), candidate_slot.slot_date, candidate_slot.start_time) in team_time_occupied:
                continue
            candidate_field_time_key = (str(candidate_slot.host_location_id), str(candidate_slot.field_instance_id), candidate_slot.slot_date, candidate_slot.start_time)
            if candidate_field_time_key in field_time_occupied:
                continue
            if no_simultaneous_games_same_host and candidate_slot.host_location_id is not None:
                candidate_host_time_key = (str(candidate_slot.host_location_id), candidate_slot.slot_date, candidate_slot.start_time)
                if candidate_host_time_key in host_time_occupied:
                    continue
            if candidate_slot.host_location_id is None:
                continue
            if not _has_compatible_open_field_at_time(candidate_slot.host_location_id, candidate_slot.slot_date, candidate_slot.start_time):
                continue
            distance = abs(_minutes_from_time(candidate_slot.start_time) - target_time_minutes)
            back_to_back_priority = 0 if candidate_slot.start_time in {
                time((requested_slot.start_time.hour - 1) % 24, requested_slot.start_time.minute),
                time((requested_slot.start_time.hour + 1) % 24, requested_slot.start_time.minute),
            } else 1
            if candidate_slot.start_time in target_team_times:
                continue
            host_rank = _slot_host_rank(requested_slot, candidate_slot)
            ranked.append((back_to_back_priority, host_rank, distance, candidate_slot))
        ranked.sort(key=lambda item: (item[0], item[1], item[2], _minutes_from_time(item[3].start_time)))
        return ranked[0][3] if ranked else None

    def _find_best_compatible_slot(
        requested_slot: GameSlot,
        home_team_id: str,
        away_team_id: str,
    ) -> tuple[GameSlot | None, bool]:
        open_slots = db.query(GameSlot).join(GameSlot.field_instance).filter(
            GameSlot.slot_date == requested_slot.slot_date,
            GameSlot.status == 'OPEN',
            GameSlot.assigned_game_id.is_(None),
            GameSlot.field_type == required_field_type,
        ).all()
        requested_minutes = _minutes_from_time(requested_slot.start_time)
        ranked: list[tuple[int, int, int, int, GameSlot]] = []
        for candidate_slot in open_slots:
            if not candidate_slot.start_time or not candidate_slot.field_instance_id:
                continue
            if (str(home_team_id), candidate_slot.slot_date, candidate_slot.start_time) in team_time_occupied:
                continue
            if (str(away_team_id), candidate_slot.slot_date, candidate_slot.start_time) in team_time_occupied:
                continue
            candidate_field_time_key = (str(candidate_slot.host_location_id), str(candidate_slot.field_instance_id), candidate_slot.slot_date, candidate_slot.start_time)
            if candidate_field_time_key in field_time_occupied:
                continue
            if no_simultaneous_games_same_host and candidate_slot.host_location_id is not None:
                candidate_host_time_key = (str(candidate_slot.host_location_id), candidate_slot.slot_date, candidate_slot.start_time)
                if candidate_host_time_key in host_time_occupied:
                    continue
            if candidate_slot.host_location_id is None:
                continue
            if not _has_compatible_open_field_at_time(candidate_slot.host_location_id, candidate_slot.slot_date, candidate_slot.start_time):
                continue
            distance = abs(_minutes_from_time(candidate_slot.start_time) - requested_minutes)
            adjacency_priority = 0 if distance == 60 else 1
            is_later = 0 if _minutes_from_time(candidate_slot.start_time) >= requested_minutes else 1
            host_rank = _slot_host_rank(requested_slot, candidate_slot)
            ranked.append((adjacency_priority, host_rank, is_later, distance, candidate_slot))
        ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3], _minutes_from_time(item[4].start_time)))
        if not ranked:
            return None, False
        selected = ranked[0][4]
        selected_is_non_adjacent = ranked[0][0] == 1
        return selected, selected_is_non_adjacent

    def _fmt_duplicate_skip(home_team_id: str, away_team_id: str, slot: GameSlot | None) -> str:
        home_name = _team_name(home_team_id)
        away_name = _team_name(away_team_id)
        week_label = db.query(Week.week_number).filter(Week.id == week_id).scalar()
        if week_label is None:
            week_text = 'this selected week'
        else:
            week_text = f'Week {week_label}'
        details = []
        if slot and slot.slot_date:
            details.append(f'Date: {slot.slot_date}')
        if slot and slot.start_time:
            details.append(f'Time: {slot.start_time}')
        detail_suffix = f" ({', '.join(details)})" if details else ''
        return f'Skipped {home_name} vs {away_name} because that matchup is already scheduled in {week_text}.{detail_suffix}'

    preview_field_time_duplicates: dict[tuple[str, str, str], int] = {}
    for proposal in proposals:
        slot_id = proposal.get('slot_id')
        if not slot_id:
            continue
        slot = db.query(GameSlot).filter(GameSlot.id == slot_id).first()
        if not slot or not slot.field_instance_id or not slot.slot_date or not slot.start_time:
            continue
        duplicate_key = (str(slot.field_instance_id), str(slot.slot_date), str(slot.start_time))
        preview_field_time_duplicates[duplicate_key] = preview_field_time_duplicates.get(duplicate_key, 0) + 1
    conflicting_preview_keys = [k for k, count in preview_field_time_duplicates.items() if count > 1]
    if conflicting_preview_keys:
        detail = '; '.join([f"field_instance_id={field_id}, date={slot_date}, time={slot_time}" for field_id, slot_date, slot_time in conflicting_preview_keys])
        raise HTTPException(status_code=400, detail=f"Invalid preview batch: duplicate date/time/field assignments detected ({detail}).")

    def _slot_gap_minutes(slot_a: GameSlot | None, slot_b: GameSlot | None) -> int:
        if not slot_a or not slot_b or not slot_a.start_time or not slot_b.start_time:
            return 9999
        return abs(_minutes_from_time(slot_a.start_time) - _minutes_from_time(slot_b.start_time))

    def _is_same_site_day(slot_a: GameSlot | None, slot_b: GameSlot | None) -> bool:
        if not slot_a or not slot_b:
            return False
        return slot_a.host_location_id == slot_b.host_location_id and slot_a.slot_date == slot_b.slot_date

    def _proposal_team_ids(row: dict) -> set[str]:
        return {str(row.get('home_team_id')), str(row.get('away_team_id'))}

    def _proposal_has_time_conflict(row: dict, slot_obj: GameSlot) -> bool:
        home_id = str(row.get('home_team_id'))
        away_id = str(row.get('away_team_id'))
        if (home_id, slot_obj.slot_date, slot_obj.start_time) in team_time_occupied:
            return True
        if (away_id, slot_obj.slot_date, slot_obj.start_time) in team_time_occupied:
            return True
        return False

    proposal_slots: dict[int, GameSlot] = {}
    for idx, proposal in enumerate(proposals):
        slot_id = proposal.get('slot_id')
        if not slot_id:
            continue
        slot_obj = db.query(GameSlot).join(GameSlot.field_instance).filter(GameSlot.id == slot_id).first()
        if slot_obj:
            proposal_slots[idx] = slot_obj

    # Local reshuffle pass: allow in-day/site swaps to improve required double-header adjacency.
    team_to_indices: dict[str, list[int]] = {}
    for idx, proposal in enumerate(proposals):
        for tid in _proposal_team_ids(proposal):
            if tid and tid != 'None':
                team_to_indices.setdefault(tid, []).append(idx)
    double_header_teams = [tid for tid, idxs in team_to_indices.items() if len(idxs) == 2]
    for team_id in double_header_teams:
        idx_a, idx_b = team_to_indices[team_id]
        slot_a = proposal_slots.get(idx_a)
        slot_b = proposal_slots.get(idx_b)
        if not _is_same_site_day(slot_a, slot_b):
            continue
        if _slot_gap_minutes(slot_a, slot_b) <= 60:
            continue
        improved = False
        for candidate_idx, candidate in enumerate(proposals):
            if candidate_idx in {idx_a, idx_b}:
                continue
            candidate_slot = proposal_slots.get(candidate_idx)
            if not _is_same_site_day(slot_a, candidate_slot):
                continue
            if candidate_slot is None or candidate_slot.field_type != required_field_type:
                continue
            if slot_b is None or slot_b.field_type != required_field_type:
                continue
            # Prefer moving non-double-header games instead of splitting a double-header.
            candidate_team_ids = _proposal_team_ids(candidate)
            if any(len(team_to_indices.get(tid, [])) == 2 for tid in candidate_team_ids if tid and tid != 'None'):
                continue
            if _proposal_has_time_conflict(proposals[idx_b], candidate_slot):
                continue
            if _proposal_has_time_conflict(candidate, slot_b):
                continue
            before_gap = _slot_gap_minutes(slot_a, slot_b)
            after_gap = _slot_gap_minutes(slot_a, candidate_slot)
            if after_gap >= before_gap:
                continue
            proposals[idx_b]['slot_id'], proposals[candidate_idx]['slot_id'] = proposals[candidate_idx]['slot_id'], proposals[idx_b]['slot_id']
            proposal_slots[idx_b], proposal_slots[candidate_idx] = candidate_slot, slot_b
            improved = True
            if after_gap <= 60:
                break
        if improved:
            continue

    def _can_place_matchup(home_team_id: str, away_team_id: str, slot: GameSlot) -> tuple[bool, str]:
        if slot.field_type != required_field_type:
            return False, 'incompatible field type'
        if not slot.field_instance_id or not slot.host_location_id:
            return False, 'missing field or host'
        if slot.status != 'OPEN' or slot.assigned_game_id is not None:
            return False, 'slot not open'
        field_time_key = (str(slot.host_location_id), str(slot.field_instance_id), slot.slot_date, slot.start_time)
        if field_time_key in field_time_occupied:
            return False, 'field overlap'
        if (str(home_team_id), slot.slot_date, slot.start_time) in team_time_occupied or (str(away_team_id), slot.slot_date, slot.start_time) in team_time_occupied:
            return False, 'team overlap'
        if no_simultaneous_games_same_host:
            host_time_key = (str(slot.host_location_id), slot.slot_date, slot.start_time)
            if host_time_key in host_time_occupied:
                return False, 'host overlap'
        duplicate = db.query(Game).join(Game.home_team).join(Game.status).filter(
            Game.season_id == season_id,
            Game.week_id == week_id,
            Team.division_id == division_id,
            GameStatus.code == 'SCHEDULED',
            GameStatus.is_active.is_(True),
            or_(
                and_(Game.home_team_id == home_team_id, Game.away_team_id == away_team_id),
                and_(Game.home_team_id == away_team_id, Game.away_team_id == home_team_id),
            ),
        ).count()
        if duplicate:
            return False, 'duplicate opponent'
        return True, ''

    for proposal in proposals:
        if existing_games_count + created_games >= required_games_for_division_week:
            _add_skipped('weekly game limit reached for selected division/week')
            break
        home_team_id = proposal.get('home_team_id')
        away_team_id = proposal.get('away_team_id')
        if not home_team_id or not away_team_id or home_team_id == away_team_id:
            _add_skipped('no valid opponent available (invalid matchup payload)')
            continue
        slot = db.query(GameSlot).join(GameSlot.field_instance).filter(GameSlot.id == proposal.get('slot_id')).first()
        if not slot:
            _add_skipped('No compatible large field available for this division.' if required_field_type == 'LARGE' else 'not enough open matching slots')
            continue
        selected_slot_unavailable = slot.status != 'OPEN' or slot.assigned_game_id is not None
        if selected_slot_unavailable:
            if is_odd_division and no_byes:
                fallback_slot, non_adjacent = _find_best_compatible_slot(slot, str(home_team_id), str(away_team_id))
                if fallback_slot is None:
                    _add_skipped('No compatible large field available for this division.' if required_field_type == 'LARGE' else 'not enough open matching slots')
                    continue
                slot = fallback_slot
                if non_adjacent:
                    _add_skipped('Double header scheduled non-back-to-back because no adjacent compatible slot was available.')
            else:
                _add_skipped('No compatible large field available for this division.' if required_field_type == 'LARGE' else 'not enough open matching slots')
                continue
        field_time_key = (str(slot.host_location_id), str(slot.field_instance_id), slot.slot_date, slot.start_time)
        if field_time_key in field_time_occupied:
            _add_skipped(f"Rejected: time slot already occupied by existing {field_time_occupied[field_time_key]} game.")
            continue
        if slot.field_type != required_field_type:
            _add_skipped('Rejected: selected slot is not compatible with division layout requirements.')
            continue
        if (str(home_team_id), slot.slot_date, slot.start_time) in team_time_occupied or (str(away_team_id), slot.slot_date, slot.start_time) in team_time_occupied:
            if is_odd_division and no_byes:
                fallback_slot, non_adjacent = _find_best_compatible_slot(slot, str(home_team_id), str(away_team_id))
                if fallback_slot is None:
                    _add_skipped('Rejected: team already scheduled at the same exact time.')
                    continue
                slot = fallback_slot
                field_time_key = (str(slot.host_location_id), str(slot.field_instance_id), slot.slot_date, slot.start_time)
                if non_adjacent:
                    _add_skipped('Double header scheduled non-back-to-back because no adjacent compatible slot was available.')
            else:
                _add_skipped('Rejected: team already scheduled at the same exact time.')
                continue
        if slot.host_location_id is None or slot.field_instance_id is None:
            _add_skipped('Rejected: host location does not have an available compatible field at this date/time.')
            continue
        if not _has_compatible_open_field_at_time(slot.host_location_id, slot.slot_date, slot.start_time):
            _add_skipped('Rejected: host location does not have an available compatible field at this date/time.')
            continue
        if no_simultaneous_games_same_host:
            host_time_key = (str(slot.host_location_id), slot.slot_date, slot.start_time)
            if host_time_key in host_time_occupied:
                _add_skipped(f"Rejected: time slot already occupied by existing {host_time_occupied[host_time_key]} game.")
                continue
        duplicate = db.query(Game).join(Game.home_team).join(Game.status).filter(
            Game.season_id == season_id,
            Game.week_id == week_id,
            Team.division_id == division_id,
            GameStatus.code == 'SCHEDULED',
            GameStatus.is_active.is_(True),
            or_(
                and_(Game.home_team_id == home_team_id, Game.away_team_id == away_team_id),
                and_(Game.home_team_id == away_team_id, Game.away_team_id == home_team_id),
            ),
        ).count()
        if duplicate:
            _add_skipped(_fmt_duplicate_skip(str(home_team_id), str(away_team_id), slot))
            continue
        home_uuid = uuid.UUID(str(home_team_id))
        away_uuid = uuid.UUID(str(away_team_id))
        home_limit = 2 if (is_odd_division and no_byes) else 1
        away_limit = 2 if (is_odd_division and no_byes) else 1
        if week_team_game_counts.get(home_uuid, 0) >= home_limit or week_team_game_counts.get(away_uuid, 0) >= away_limit:
            _add_skipped(
                f"Skipped {_team_name(str(home_team_id))} vs {_team_name(str(away_team_id))} "
                'because one team already has a game this week.'
            )
            continue
        home_team_row = teams_by_id.get(str(home_team_id))
        away_team_row = teams_by_id.get(str(away_team_id))
        host_location = slot.host_location
        adj_home, adj_away, adjustment_reason = _enforce_host_owner_home_team(home_team_row, away_team_row, host_location)
        if adj_home and adj_away:
            home_team_id = str(adj_home.id)
            away_team_id = str(adj_away.id)
            if adjustment_reason:
                logger.info(adjustment_reason)
        game = Game(
            season_id=season_id,
            week_id=week_id,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            field_id=None,
            host_location_id=slot.host_location_id,
            field_instance_id=slot.field_instance_id,
            game_status_id=status.id,
            game_date=slot.slot_date,
            kickoff_time=slot.start_time,
        )
        db.add(game)
        db.flush()
        slot.status = 'ASSIGNED'
        slot.assigned_game_id = game.id
        team_time_occupied.add((str(home_team_id), slot.slot_date, slot.start_time))
        team_time_occupied.add((str(away_team_id), slot.slot_date, slot.start_time))
        field_time_occupied[(str(slot.host_location_id), str(slot.field_instance_id), slot.slot_date, slot.start_time)] = teams_by_id.get(str(home_team_id)).division.name if teams_by_id.get(str(home_team_id)) and teams_by_id.get(str(home_team_id)).division else 'another division'
        if slot.host_location_id:
            host_time_occupied[(str(slot.host_location_id), slot.slot_date, slot.start_time)] = teams_by_id.get(str(home_team_id)).division.name if teams_by_id.get(str(home_team_id)) and teams_by_id.get(str(home_team_id)).division else 'another division'
        used_team_ids.add(home_uuid)
        used_team_ids.add(away_uuid)
        week_team_game_counts[home_uuid] = week_team_game_counts.get(home_uuid, 0) + 1
        week_team_game_counts[away_uuid] = week_team_game_counts.get(away_uuid, 0) + 1
        created_games += 1
        assigned_slots += 1
    total_created_for_week = existing_games_count + created_games

    def _division_week_scheduled_games() -> list[Game]:
        return db.query(Game).join(Game.home_team).join(Game.status).filter(
            Game.season_id == season_id,
            Game.week_id == week_id,
            Team.division_id == division_id,
            GameStatus.code == 'SCHEDULED',
            GameStatus.is_active.is_(True),
        ).all()

    def _slot_by_game_id() -> dict[str, GameSlot]:
        rows = db.query(GameSlot).filter(
            GameSlot.assigned_game_id.isnot(None),
            GameSlot.slot_date == db.query(Week.primary_game_date).filter(Week.id == week_id).scalar_subquery(),
        ).all()
        return {str(row.assigned_game_id): row for row in rows if row.assigned_game_id}

    def _double_header_warning_team_ids(games: list[Game], slots_by_game_id: dict[str, GameSlot]) -> list[str]:
        team_slots: dict[str, list[GameSlot]] = {}
        for game in games:
            slot = slots_by_game_id.get(str(game.id))
            if not slot or not slot.start_time:
                continue
            team_slots.setdefault(str(game.home_team_id), []).append(slot)
            team_slots.setdefault(str(game.away_team_id), []).append(slot)
        warning_team_ids: list[str] = []
        for tid, assigned_slots_for_team in team_slots.items():
            if len(assigned_slots_for_team) != 2:
                continue
            first, second = assigned_slots_for_team[0], assigned_slots_for_team[1]
            same_site_day = first.host_location_id == second.host_location_id and first.slot_date == second.slot_date
            adjacent = _slot_gap_minutes(first, second) <= 60
            if not (same_site_day and adjacent):
                warning_team_ids.append(tid)
        return warning_team_ids

    def _can_swap_games(game_a: Game, slot_a: GameSlot, game_b: Game, slot_b: GameSlot) -> bool:
        if not slot_a.start_time or not slot_b.start_time or not slot_a.host_location_id or not slot_b.host_location_id:
            return False
        ok_a, _ = _can_place_matchup(str(game_a.home_team_id), str(game_a.away_team_id), slot_b)
        ok_b, _ = _can_place_matchup(str(game_b.home_team_id), str(game_b.away_team_id), slot_a)
        return ok_a and ok_b

    def _same_community_unresolved_note(game: Game, slot: GameSlot | None, preferred_home_host_id: uuid.UUID | None, reason: str) -> dict[str, object]:
        home_team = teams_by_id.get(game.home_team_id)
        away_team = teams_by_id.get(game.away_team_id)
        return {
            'game_id': str(game.id),
            'date': str(slot.slot_date) if slot and slot.slot_date else None,
            'division': home_team.division.name if home_team and home_team.division else None,
            'teams': f"{home_team.name if home_team else game.home_team_id} vs {away_team.name if away_team else game.away_team_id}",
            'current_location': str(slot.host_location_id) if slot and slot.host_location_id else None,
            'preferred_home_location': str(preferred_home_host_id) if preferred_home_host_id else None,
            'reason': reason,
        }

    optimization_swaps_attempted = 0
    warnings_resolved = 0
    warnings_remaining = 0
    if is_odd_division and no_byes:
        games_for_optimization = _division_week_scheduled_games()
        slots_for_optimization = _slot_by_game_id()
        baseline_warning_team_ids = _double_header_warning_team_ids(games_for_optimization, slots_for_optimization)
        baseline_warning_count = len(baseline_warning_team_ids)
        current_warning_count = baseline_warning_count
        max_attempts = 120
        for problem_tid in list(baseline_warning_team_ids):
            if optimization_swaps_attempted >= max_attempts:
                break
            team_games = [
                g for g in games_for_optimization
                if str(g.home_team_id) == problem_tid or str(g.away_team_id) == problem_tid
            ]
            if len(team_games) != 2:
                continue
            target_game = team_games[1]
            target_slot = slots_for_optimization.get(str(target_game.id))
            anchor_slot = slots_for_optimization.get(str(team_games[0].id))
            if not target_slot or not anchor_slot:
                continue
            swap_candidates = []
            for candidate_game in games_for_optimization:
                if candidate_game.id in {team_games[0].id, team_games[1].id}:
                    continue
                candidate_slot = slots_for_optimization.get(str(candidate_game.id))
                if not candidate_slot:
                    continue
                same_division_week = True
                if not same_division_week:
                    continue
                distance_after = _slot_gap_minutes(anchor_slot, candidate_slot)
                if candidate_slot.host_location_id != anchor_slot.host_location_id or candidate_slot.slot_date != anchor_slot.slot_date:
                    distance_after += 500
                swap_candidates.append((distance_after, candidate_game, candidate_slot))
            swap_candidates.sort(key=lambda item: item[0])
            for _, candidate_game, candidate_slot in swap_candidates:
                if optimization_swaps_attempted >= max_attempts:
                    break
                optimization_swaps_attempted += 1
                if not _can_swap_games(target_game, target_slot, candidate_game, candidate_slot):
                    continue
                original_target_time, original_target_date = target_game.kickoff_time, target_game.game_date
                original_candidate_time, original_candidate_date = candidate_game.kickoff_time, candidate_game.game_date
                target_slot.assigned_game_id = candidate_game.id
                candidate_slot.assigned_game_id = target_game.id
                target_game.kickoff_time, target_game.game_date = candidate_slot.start_time, candidate_slot.slot_date
                candidate_game.kickoff_time, candidate_game.game_date = target_slot.start_time, target_slot.slot_date
                db.flush()
                refreshed_slots = _slot_by_game_id()
                new_warning_count = len(_double_header_warning_team_ids(games_for_optimization, refreshed_slots))
                if new_warning_count < current_warning_count:
                    slots_for_optimization = refreshed_slots
                    current_warning_count = new_warning_count
                    break
                target_slot.assigned_game_id = target_game.id
                candidate_slot.assigned_game_id = candidate_game.id
                target_game.kickoff_time, target_game.game_date = original_target_time, original_target_date
                candidate_game.kickoff_time, candidate_game.game_date = original_candidate_time, original_candidate_date
                db.flush()
        warnings_resolved = max(0, baseline_warning_count - current_warning_count)
        warnings_remaining = current_warning_count
        skipped.append(f'Double-header optimization swaps attempted: {optimization_swaps_attempted}')
        skipped.append(f'Warnings resolved: {warnings_resolved}')
        skipped.append(f'Warnings remaining: {warnings_remaining}')

    selected_host_ids = extract_selected_host_ids(proposals)
    if not selected_host_ids:
        selected_host_ids = sorted({
            str(slot.host_location_id)
            for slot in proposal_slots.values()
            if slot and slot.host_location_id
        })
    selected_org_ids = {
        host_org_by_location_id.get(str(host_id))
        for host_id in selected_host_ids
        if host_org_by_location_id.get(str(host_id))
    }
    selected_org_host_ids = {
        host_id
        for org_id in selected_org_ids
        for host_id in host_ids_by_org.get(str(org_id), set())
    }

    locked_host_ids: set[str] = {str(host_id) for host_id in (selected_host_ids or []) if host_id}
    overflow_host_ids: set[str] = set()
    for idx, proposal in enumerate(proposals or []):
        host_id = proposal.get('host_location_id')
        if not host_id:
            slot_id = proposal.get('slot_id')
            slot_obj = proposal_slots.get(idx)
            if not slot_obj and slot_id:
                slot_obj = db.query(GameSlot).filter(GameSlot.id == slot_id).first()
            if slot_obj and slot_obj.host_location_id:
                host_id = str(slot_obj.host_location_id)
        if not host_id:
            continue
        host_id = str(host_id)
        reason = (proposal.get('reason') or '').lower()
        is_overflow = bool(
            proposal.get('is_overflow')
            or proposal.get('overflow')
            or 'overflow' in reason
            or (locked_host_ids and host_id not in locked_host_ids)
        )
        if is_overflow:
            overflow_host_ids.add(host_id)

    logger.info(
        f'Selected host sites for scheduling: {selected_host_ids}'
    )

    recovery_diagnostics: list[dict[str, object]] = []
    recovery_overflow_used = False
    if total_created_for_week < required_games_for_division_week:
        remaining_needed = required_games_for_division_week - total_created_for_week
        division_team_ids = [str(team.id) for team in teams]
        season_team_counts_rows = db.query(
            Team.id,
            func.count(Game.id),
        ).outerjoin(
            Game,
            and_(
                or_(Game.home_team_id == Team.id, Game.away_team_id == Team.id),
                Game.season_id == season_id,
            ),
        ).outerjoin(GameStatus, Game.game_status_id == GameStatus.id).filter(
            Team.division_id == division_id,
            Team.is_active.is_(True),
        ).filter(
            or_(Game.id.is_(None), GameStatus.code != 'UNSCHEDULED')
        ).group_by(Team.id).all()
        season_team_counts = {str(team_id): int(count or 0) for team_id, count in season_team_counts_rows}
        open_slots = db.query(GameSlot).join(GameSlot.field_instance).filter(
            GameSlot.slot_date == db.query(Week.primary_game_date).filter(Week.id == week_id).scalar_subquery(),
            GameSlot.status == 'OPEN',
            GameSlot.assigned_game_id.is_(None),
            GameSlot.field_type == required_field_type,
        ).order_by(GameSlot.start_time.asc()).all()
        host_plan_allowed_ids = _host_plan_allowed_host_ids_for_week(db, season_id, week_id, db.query(Week.primary_game_date).filter(Week.id == week_id).scalar())
        if host_plan_allowed_ids is not None:
            open_slots = [slot for slot in open_slots if slot.host_location_id in host_plan_allowed_ids]
        while remaining_needed > 0:
            placed = False
            candidate_teams = sorted(
                division_team_ids,
                key=lambda tid: (season_team_counts.get(tid, 0), week_team_game_counts.get(uuid.UUID(tid), 0)),
            )
            for home_tid in candidate_teams:
                for away_tid in candidate_teams:
                    if home_tid == away_tid:
                        continue
                    home_count = week_team_game_counts.get(uuid.UUID(home_tid), 0)
                    away_count = week_team_game_counts.get(uuid.UUID(away_tid), 0)
                    if home_count >= 2 or away_count >= 2:
                        continue
                    preferred_slots = sorted(
                        open_slots,
                        key=lambda slot: (
                            0 if str(slot.host_location_id) in selected_host_ids else (
                                1 if str(slot.host_location_id) in selected_org_host_ids else 2
                            ),
                            _minutes_from_time(slot.start_time),
                        ),
                    )
                    for slot in preferred_slots:
                        ok, reason = _can_place_matchup(home_tid, away_tid, slot)
                        if not ok:
                            recovery_diagnostics.append({'slot': f"{slot.start_time} {slot.field_type}", 'home': _team_name(home_tid), 'away': _team_name(away_tid), 'reason': reason})
                            continue
                        if str(slot.host_location_id) not in selected_host_ids:
                            recovery_overflow_used = True
                            two_location_rule_relaxed = True
                            overflow_host_ids.add(str(slot.host_location_id))
                        game = Game(season_id=season_id, week_id=week_id, home_team_id=home_tid, away_team_id=away_tid, field_id=None, host_location_id=slot.host_location_id, field_instance_id=slot.field_instance_id, game_status_id=status.id, game_date=slot.slot_date, kickoff_time=slot.start_time)
                        db.add(game); db.flush()
                        slot.status = 'ASSIGNED'; slot.assigned_game_id = game.id
                        team_time_occupied.add((home_tid, slot.slot_date, slot.start_time)); team_time_occupied.add((away_tid, slot.slot_date, slot.start_time))
                        field_time_occupied[(str(slot.host_location_id), str(slot.field_instance_id), slot.slot_date, slot.start_time)] = division.name if division else 'another division'
                        host_time_occupied[(str(slot.host_location_id), slot.slot_date, slot.start_time)] = division.name if division else 'another division'
                        week_team_game_counts[uuid.UUID(home_tid)] = home_count + 1
                        week_team_game_counts[uuid.UUID(away_tid)] = away_count + 1
                        season_team_counts[home_tid] = season_team_counts.get(home_tid, 0) + 1
                        season_team_counts[away_tid] = season_team_counts.get(away_tid, 0) + 1
                        created_games += 1; assigned_slots += 1; remaining_needed -= 1; placed = True
                        open_slots = [s for s in open_slots if s.id != slot.id]
                        break
                    if placed:
                        break
                if placed:
                    break
            if not placed:
                break
        total_created_for_week = existing_games_count + created_games
        if total_created_for_week < required_games_for_division_week:
            unscheduled_ids = [tid for tid in division_team_ids if week_team_game_counts.get(uuid.UUID(tid), 0) == 0]
            _add_skipped(f"RECOVERY PASS FAILED Division: {division.name if division else 'Unknown'} Week: {db.query(Week.week_number).filter(Week.id == week_id).scalar()} Unscheduled Teams: {', '.join([_team_name(tid) for tid in unscheduled_ids]) or 'None'}")

    if total_created_for_week >= required_games_for_division_week:
        skipped = []
    elif is_odd_division and no_byes:
        _add_skipped('Unable to place required double-header because no same-location adjacent slots exist.')
    else:
        _add_skipped('Unable to schedule required games due to hard scheduling constraints.')
    unscheduled_teams = [
        t.name for t in teams
        if week_team_game_counts.get(t.id, 0) == 0
    ]
    double_header_team_id = next((str(team_id) for team_id, count in week_team_game_counts.items() if count > 1), None)
    same_community_home_swaps = 0
    same_community_games_reviewed = 0
    same_community_repairs_attempted = 0
    same_community_swaps_attempted = 0
    same_community_swaps_committed = 0
    same_community_home_swap_notes: list[dict[str, object]] = []
    same_community_home_unresolved_notes: list[dict[str, object]] = []
    triple_repeat_swaps = 0
    triple_repeat_swap_notes: list[dict[str, object]] = []
    scheduled_games_for_swap = _division_week_scheduled_games()
    slots_for_swap = _slot_by_game_id()
    # Post-schedule optimization: reduce third-repeat pairings via legal slot swaps and home/away flips.
    def _pair_counts(games):
        counts = {}
        for g in games:
            k = tuple(sorted((str(g.home_team_id), str(g.away_team_id))))
            counts[k] = counts.get(k, 0) + 1
        return counts

    pair_counts_for_swap = _pair_counts(scheduled_games_for_swap)
    for game in list(scheduled_games_for_swap):
        key = tuple(sorted((str(game.home_team_id), str(game.away_team_id))))
        if pair_counts_for_swap.get(key, 0) < 3:
            continue
        slot = slots_for_swap.get(str(game.id))
        if not slot:
            continue
        improved = False
        for other in scheduled_games_for_swap:
            if other.id == game.id:
                continue
            other_key = tuple(sorted((str(other.home_team_id), str(other.away_team_id))))
            if other_key == key:
                continue
            other_slot = slots_for_swap.get(str(other.id))
            if not other_slot:
                continue
            if _can_swap_games(game, slot, other, other_slot):
                game.kickoff_time, other.kickoff_time = other_slot.start_time, slot.start_time
                game.game_date, other.game_date = other_slot.slot_date, slot.slot_date
                slot.assigned_game_id, other_slot.assigned_game_id = other.id, game.id
                db.flush()
                triple_repeat_swaps += 1
                triple_repeat_swap_notes.append({'game_id': str(game.id), 'swapped_with_game_id': str(other.id), 'action': 'slot_swap'})
                slots_for_swap = _slot_by_game_id()
                improved = True
                break
        if not improved:
            # try home/away flip at same slot as lower-risk rebalance
            game.home_team_id, game.away_team_id = game.away_team_id, game.home_team_id
            db.flush()
            triple_repeat_swap_notes.append({'game_id': str(game.id), 'action': 'home_away_flip_attempted'})

    scheduled_games_for_swap = _division_week_scheduled_games()
    slots_for_swap = _slot_by_game_id()

    for game in scheduled_games_for_swap:
        slot = slots_for_swap.get(str(game.id))
        if not slot or not slot.host_location_id:
            continue
        home_team = teams_by_id.get(game.home_team_id)
        away_team = teams_by_id.get(game.away_team_id)
        if not home_team or not away_team:
            continue
        if not home_team.organization_id or home_team.organization_id != away_team.organization_id:
            continue
        same_community_games_reviewed += 1
        preferred_home_hosts = {
            str(host_id)
            for host_id in host_ids_by_org.get(str(home_team.organization_id), set())
        }
        if not preferred_home_hosts:
            same_community_home_unresolved_notes.append(_same_community_unresolved_note(game, slot, None, 'community has no identified host locations'))
            continue
        if str(slot.host_location_id) in preferred_home_hosts:
            continue
        same_community_repairs_attempted += 1
        open_home_slot = next((
            s for s in sorted_slots
            if s.slot_date == slot.slot_date and s.host_location_id and str(s.host_location_id) in preferred_home_hosts and _can_place_matchup(str(game.home_team_id), str(game.away_team_id), s)[0]
        ), None)
        if open_home_slot:
            existing_assigned = db.query(Game).join(GameSlot, GameSlot.assigned_game_id == Game.id).filter(GameSlot.id == open_home_slot.id).first()
            if existing_assigned:
                same_community_home_unresolved_notes.append(_same_community_unresolved_note(game, slot, primary_host_by_org.get(home_team.organization_id), 'organization home slot unexpectedly already assigned'))
            else:
                slot.assigned_game_id = None
                slot.status = 'OPEN'
                open_home_slot.assigned_game_id = game.id
                open_home_slot.status = 'BOOKED'
                game.game_date = open_home_slot.slot_date
                game.kickoff_time = open_home_slot.start_time
                db.flush()
                same_community_home_swaps += 1
                same_community_swaps_committed += 1
                same_community_home_swap_notes.append({'game_id': str(game.id), 'action': 'moved_to_open_home_slot', 'new_host_location_id': str(open_home_slot.host_location_id)})
                slots_for_swap = _slot_by_game_id()
                continue
        candidate_swaps = []
        for other in scheduled_games_for_swap:
            if other.id == game.id:
                continue
            other_slot = slots_for_swap.get(str(other.id))
            if not other_slot or str(other_slot.host_location_id) not in preferred_home_hosts:
                continue
            other_home = teams_by_id.get(other.home_team_id)
            other_away = teams_by_id.get(other.away_team_id)
            if not other_home or not other_away:
                continue
            other_same_community = bool(other_home.organization_id and other_home.organization_id == other_away.organization_id)
            if other_same_community:
                continue
            if slot.slot_date != other_slot.slot_date:
                continue
            same_division = other_home.division_id == home_team.division_id
            same_field_size = bool(slot.field_type and other_slot.field_type and slot.field_type == other_slot.field_type)
            two_location_before = len({str(slots_for_swap.get(str(g.id)).host_location_id) for g in scheduled_games_for_swap if slots_for_swap.get(str(g.id)) and slots_for_swap.get(str(g.id)).slot_date == slot.slot_date})
            projected_hosts = {
                str((other_slot if g.id == game.id else slot if g.id == other.id else slots_for_swap.get(str(g.id))).host_location_id)
                for g in scheduled_games_for_swap
                if (other_slot if g.id == game.id else slot if g.id == other.id else slots_for_swap.get(str(g.id)))
                and (other_slot if g.id == game.id else slot if g.id == other.id else slots_for_swap.get(str(g.id))).slot_date == slot.slot_date
            }
            if len(projected_hosts) > max(two_location_before, regular_season_host_limit):
                continue
            same_community_swaps_attempted += 1
            if _can_swap_games(game, slot, other, other_slot):
                priority = 0 if same_division else (1 if same_field_size else 2)
                candidate_swaps.append((priority, other, other_slot))
        if not candidate_swaps:
            same_community_home_unresolved_notes.append(_same_community_unresolved_note(game, slot, primary_host_by_org.get(home_team.organization_id), 'no compatible same-date organization-home slot or legal swap candidate found'))
            continue
        candidate_swaps.sort(key=lambda x: x[0])
        _, other, other_slot = candidate_swaps[0]
        game.kickoff_time, other.kickoff_time = other_slot.start_time, slot.start_time
        game.game_date, other.game_date = other_slot.slot_date, slot.slot_date
        slot.assigned_game_id, other_slot.assigned_game_id = other.id, game.id
        db.flush()
        same_community_home_swaps += 1
        same_community_swaps_committed += 1
        same_community_home_swap_notes.append({'game_id': str(game.id), 'swapped_with_game_id': str(other.id), 'new_host_location_id': str(other_slot.host_location_id)})
        slots_for_swap = _slot_by_game_id()
    same_community_total = 0
    same_community_at_home = 0
    same_community_not_at_home = 0
    organization_home_placements = 0
    organization_home_misses = 0
    for game in _division_week_scheduled_games():
        slot = _slot_by_game_id().get(str(game.id))
        if not slot or not slot.host_location_id:
            continue
        home_team = teams_by_id.get(game.home_team_id)
        away_team = teams_by_id.get(game.away_team_id)
        if not home_team or not away_team or not home_team.organization_id or home_team.organization_id != away_team.organization_id:
            continue
        same_community_total += 1
        org_host_ids = host_ids_by_org.get(str(home_team.organization_id), set())
        if slot.host_location_id and str(slot.host_location_id) in org_host_ids:
            same_community_at_home += 1
            organization_home_placements += 1
        else:
            same_community_not_at_home += 1
            organization_home_misses += 1

    cross_site_double_headers = 0
    team_week_slots: dict[str, list[GameSlot]] = {}
    scheduled_games_post = _division_week_scheduled_games()
    scheduled_slots_post = _slot_by_game_id()
    for g in scheduled_games_post:
        s = scheduled_slots_post.get(str(g.id))
        if not s:
            continue
        team_week_slots.setdefault(str(g.home_team_id), []).append(s)
        team_week_slots.setdefault(str(g.away_team_id), []).append(s)
    for team_id, assigned_slots_for_team in team_week_slots.items():
        if len(assigned_slots_for_team) != 2:
            continue
        team = teams_by_id.get(team_id)
        if not team or not team.organization_id:
            continue
        org_hosts = host_ids_by_org.get(str(team.organization_id), set())
        first, second = assigned_slots_for_team[0], assigned_slots_for_team[1]
        if not first.host_location_id or not second.host_location_id:
            continue
        if str(first.host_location_id) != str(second.host_location_id) and str(first.host_location_id) in org_hosts and str(second.host_location_id) in org_hosts:
            cross_site_double_headers += 1

    unused_compatible_fields_within_org = db.query(GameSlot).filter(
        GameSlot.slot_date == db.query(Week.primary_game_date).filter(Week.id == week_id).scalar_subquery(),
        GameSlot.status == 'OPEN',
        GameSlot.assigned_game_id.is_(None),
        GameSlot.field_type == required_field_type,
        GameSlot.host_location_id.in_([uuid.UUID(host_id) for host_id in selected_org_host_ids]) if selected_org_host_ids else False,
    ).count() if selected_org_host_ids else 0
    if created_games == 0:
        db.rollback()
        raise HTTPException(400, 'No valid scheduling combinations were found for the selected division/week.')
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            'auto_fill_apply_failed season_id=%s week_id=%s division_id=%s created_games=%s assigned_slots=%s skipped_candidates=%s',
            season_id, week_id, division_id, created_games, assigned_slots, len(skipped),
        )
        raise HTTPException(400, 'No valid slot combinations available.')
    logger.info(
        'auto_fill_apply_complete season_id=%s week_id=%s division_id=%s final_games_created=%s skipped_candidates=%s transaction_status=committed',
        season_id, week_id, division_id, created_games, len(skipped),
    )
    games_required = required_games_for_division_week
    applied_games_created = created_games

    return {
        'proposed_count': len(proposals),
        'created_count': created_games,
        'skipped_count': len(skipped),
        'max_games': required_games_for_division_week,
        'created_games': created_games,
        'assigned_slots': assigned_slots,
        'skipped': skipped,
        'final_validation': {
            'active_team_count': len(teams),
            'required_game_count': required_games_for_division_week,
            'created_game_count': total_created_for_week,
            'odd_even_status_source': 'division_active_team_count',
            'unscheduled_teams': unscheduled_teams,
            'double_header_team': teams_by_id[double_header_team_id].name if double_header_team_id and double_header_team_id in teams_by_id else None,
            'recovery_diagnostics': recovery_diagnostics[-25:],
        },
        'diagnostics': {
            'weekly_host_planning_report': {
                'selected_host_sites': selected_host_ids,
                'overflow_sites_used': [str(hid) for hid in sorted(overflow_host_ids, key=str)],
                'two_location_rule_relaxed': two_location_rule_relaxed,
                'required_games': games_required,
                'created_games': applied_games_created,
                'missing_games': max(0, games_required - applied_games_created),
                'host_limit_exceptions': [],
                'league_team_demand': {},
                'host_capacities': [],
            },
            'teams_evaluated': len(teams),
            'slots_evaluated': open_slots_count,
            'valid_matchups_found': len(proposals),
            'division_team_count': len(teams),
            'required_games': required_games_for_division_week,
            'actual_games_scheduled': total_created_for_week,
            'odd_even_status_source': 'division_active_team_count',
            'valid_slot_combinations_found': len(proposals),
            'rules_relaxed': len([s for s in skipped if 'non-back-to-back' in str(s.get('reason', '')).lower()]),
            'conflicts_avoided': len(skipped),
            'final_games_created': created_games,
            'same_community_home_swaps': same_community_home_swaps,
            'same_community_games_reviewed': same_community_games_reviewed,
            'same_community_repairs_attempted': same_community_repairs_attempted,
            'same_community_repairs_completed': same_community_home_swaps,
            'same_community_repairs_unresolved': same_community_not_at_home,
            'same_community_swaps_attempted': same_community_swaps_attempted,
            'same_community_swaps_committed': same_community_swaps_committed,
            'same_community_home_swap_notes': same_community_home_swap_notes,
            'same_community_home_unresolved_notes': same_community_home_unresolved_notes,
            'same_community_games_total': same_community_total,
            'same_community_games_at_home': same_community_at_home,
            'same_community_games_not_at_home': same_community_not_at_home,
            'organization_home_placements': organization_home_placements,
            'organization_home_misses': organization_home_misses,
            'cross_site_double_headers': cross_site_double_headers,
            'unused_compatible_fields_within_hosting_organizations': unused_compatible_fields_within_org,
            'triple_repeat_swaps': triple_repeat_swaps,
            'triple_repeat_swap_notes': triple_repeat_swap_notes,
        },
    }



def _auto_schedule_division_order(db: Session | None = None) -> list[tuple[str, str]]:
    return [
        ('COED', 'K-1'),
        ('COED', '2-3'),
        ('COED', '4-5'),
        ('COED', '6-7'),
        ('COED', '8'),
        ('GIRLS', 'K-2'),
        ('GIRLS', '3-5'),
        ('GIRLS', '6-8'),
    ]

@router.post('/manual-schedule-builder/auto-schedule-season')
def auto_schedule_entire_season(payload: dict, current_user: User = Depends(require_roles(ROLE_LEAGUE_ADMIN)), db: Session = Depends(get_db)):
    if bool(payload.get('use_host_plan_selections', False)):
        _enforce_host_plan_selection_admin(current_user)
    season_id = payload.get('season_id')
    clear_existing = bool(payload.get('clear_existing', False))
    dry_run = bool(payload.get('dry_run', False))
    if not season_id:
        raise HTTPException(400, 'season_id is required')
    season = db.query(Season).filter(Season.id == season_id).first()
    if not season:
        raise HTTPException(404, 'Season not found')

    if clear_existing:
        game_ids_to_delete = [row[0] for row in db.query(Game.id).join(Game.status).filter(Game.season_id == season_id, GameStatus.code != 'UNSCHEDULED').all()]
        if game_ids_to_delete:
            db.query(GameSlot).filter(GameSlot.assigned_game_id.in_(game_ids_to_delete)).update({'assigned_game_id': None, 'status': 'OPEN'}, synchronize_session=False)
            db.query(Game).filter(Game.id.in_(game_ids_to_delete)).delete(synchronize_session=False)
            if dry_run:
                db.flush()
            else:
                db.commit()

    division_order = _auto_schedule_division_order(db)
    all_divisions = db.query(Division).all()
    divisions_by_key = {canonical_division_id_from_division(d): d for d in all_divisions}
    divisions_by_normalized_name = {
        normalize_division_name(f'{d.division_group or ""} {d.name or ""}'): d
        for d in all_divisions
    }
    weeks = db.query(Week).filter(Week.season_id == season_id).order_by(Week.week_number.asc(), Week.primary_game_date.asc()).all()

    total_games_created = 0
    preview_games_count = 0
    attempted_game_groups = 0
    valid_assignments_found = 0
    preview_assignments_count = 0
    committed_assignments_count = 0
    failed_validation_count = 0
    failed_validation_reasons: dict[str, int] = {}
    database_commit_failed_count = 0
    warnings: list[str] = []
    validation_errors: list[str] = []
    divisions_completed: list[str] = []
    divisions_with_unresolved_games: list[str] = []
    required_games_missing: list[dict[str, object]] = []
    skipped_attempts_by_reason: dict[str, int] = {}
    skipped_attempts_summary: dict[str, int] = {
        'Already scheduled': 0,
        'No compatible field': 0,
        'No available slot': 0,
        'No host capacity': 0,
        'Missing generated game group': 0,
    }
    post_run_validation: list[dict[str, object]] = []
    validation_warnings: list[dict[str, object]] = []
    weekly_diagnostics_by_week_id: dict[uuid.UUID, dict[str, object]] = {}
    division_week_diagnostics: list[dict[str, object]] = []

    def _regular_season_weeks() -> list[Week]:
        return [week for week in weeks if _is_regular_season_week(week)]

    def _active_divisions_for_auto_schedule() -> list[Division]:
        active_divisions: list[Division] = []
        seen_division_ids: set[uuid.UUID] = set()
        for group, name in division_order:
            division = divisions_by_key.get(canonical_division_id(group, name)) or divisions_by_normalized_name.get(normalize_division_name(f'{group} {name}'))
            if division and division.is_active and division.id not in seen_division_ids:
                active_divisions.append(division)
                seen_division_ids.add(division.id)
        return active_divisions

    def _division_label(division: Division) -> str:
        return f'{division.division_group or ""} {division.name or ""}'.strip() or str(division.id)

    def _division_required_games(active_team_count: int) -> int:
        return (int(active_team_count or 0) + 1) // 2

    def _skip_reason_code(reason: str | None) -> str:
        text = (reason or '').strip().lower()
        if not text:
            return 'unknown'
        if 'weekly game limit reached' in text or 'already scheduled' in text or 'duplicate matchup' in text or 'that matchup is already scheduled' in text:
            return 'filtered_out_before_placement'
        if 'no active teams' in text or 'missing generated game group' in text:
            return 'no_game_group_generated'
        if 'no compatible host locations' in text or 'no compatible host location' in text:
            return 'no_compatible_host_location'
        if 'no compatible large field' in text or 'incompatible field' in text or 'not compatible with division layout requirements' in text:
            return 'no_compatible_field_size'
        if 'no compatible generated slots' in text or 'no compatible slot' in text or 'not enough open matching slots' in text:
            return 'no_available_slot'
        if 'unable to schedule required games' in text or 'host capacity' in text or 'capacity fallback' in text:
            return 'no_available_host_community'
        if 'turf' in text and 'capacity' in text:
            return 'turf_wave_capacity_missing'
        if 'grass' in text and 'capacity' in text:
            return 'grass_forecast_capacity_missing'
        if 'double' in text and 'blocked' in text:
            return 'doubleheader_rule_blocked'
        if 'team already scheduled' in text or 'team conflict' in text:
            return 'team_conflict'
        if 'field already occupied' in text or 'field conflict' in text or 'time slot already occupied' in text:
            return 'field_conflict'
        return 'unknown'

    def _skip_summary_bucket(reason: str | None) -> str:
        code = _skip_reason_code(reason)
        if code in {'filtered_out_before_placement', 'team_conflict'}:
            return 'Already scheduled'
        if code in {'no_compatible_field_size', 'no_compatible_host_location'}:
            return 'No compatible field'
        if code in {'no_available_slot', 'no_generated_slot'}:
            return 'No available slot'
        if code in {'no_available_host_community', 'turf_wave_capacity_missing', 'grass_forecast_capacity_missing'}:
            return 'No host capacity'
        if code == 'no_game_group_generated':
            return 'Missing generated game group'
        return 'No available slot'

    def _normalize_skip_reason(reason: str) -> str:
        text = (reason or '').strip().lower()
        if 'team already scheduled at the same exact time' in text:
            return 'team already scheduled at same time'
        if 'occupied by existing' in text or 'time slot already occupied' in text or 'field already occupied' in text:
            return 'field already occupied'
        if 'not compatible with division layout requirements' in text or 'no compatible large field' in text:
            return 'incompatible field size'
        if 'that matchup is already scheduled' in text or 'duplicate matchup' in text:
            return 'duplicate matchup'
        if 'no compatible adjacent slot' in text:
            return 'no compatible adjacent slot'
        if 'host location does not have an available compatible field' in text:
            return 'host-site restriction'
        if 'split-host' in text:
            return 'split-host conflict'
        if 'repeat restriction' in text:
            return 'matchup repeat restriction'
        if 'no compatible slot was available after evaluating all options' in text or 'not enough open matching slots' in text:
            return 'no compatible slot remaining'
        return reason

    def _record_skipped(skipped_rows: list[dict[str, object]] | None) -> None:
        for row in skipped_rows or []:
            reason = str((row or {}).get('reason') or 'unknown')
            key = _normalize_skip_reason(reason)
            skipped_attempts_by_reason[key] = skipped_attempts_by_reason.get(key, 0) + 1
            failed_validation_reasons[key] = failed_validation_reasons.get(key, 0) + 1
            bucket = _skip_summary_bucket(reason)
            skipped_attempts_summary[bucket] = skipped_attempts_summary.get(bucket, 0) + 1

    def _actual_created_game_count_for_week(division_id: uuid.UUID, week_id: uuid.UUID) -> int:
        return db.query(Game.id).join(Game.status).join(Team, Game.home_team_id == Team.id).filter(
            Team.division_id == division_id,
            Team.is_active.is_(True),
            Game.week_id == week_id,
            GameStatus.code != 'UNSCHEDULED',
        ).count()

    def _host_count_for_week(division_id: uuid.UUID, week_id: uuid.UUID) -> int:
        rows = db.query(GameSlot.host_location_id).join(Game, Game.id == GameSlot.assigned_game_id).join(Game.status).join(
            Team, Game.home_team_id == Team.id
        ).filter(
            Team.division_id == division_id,
            Team.is_active.is_(True),
            Game.week_id == week_id,
            GameStatus.code != 'UNSCHEDULED',
            GameSlot.host_location_id.isnot(None),
        ).distinct().all()
        return len(rows)

    def _scheduled_games_for_week(week_id: uuid.UUID) -> list[Game]:
        return db.query(Game).join(Game.status).filter(
            Game.season_id == season_id,
            Game.week_id == week_id,
            GameStatus.code != 'UNSCHEDULED',
            GameStatus.is_active.is_(True),
        ).all()

    def _week_field_size_counts(week_id: uuid.UUID) -> dict[str, int]:
        counts = {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0}
        rows = db.query(GameSlot.field_type, func.count(Game.id)).select_from(Game).join(Game.status).join(
            GameSlot, GameSlot.assigned_game_id == Game.id
        ).filter(
            Game.season_id == season_id,
            Game.week_id == week_id,
            GameStatus.code != 'UNSCHEDULED',
            GameStatus.is_active.is_(True),
        ).group_by(GameSlot.field_type).all()
        for field_type, count in rows:
            size = _normalize_field_size(field_type) or str(field_type or '').upper()
            if size in counts:
                counts[size] = int(count or 0)
        return counts

    def _active_team_count(division_id: uuid.UUID) -> int:
        return db.query(Team.id).filter(Team.division_id == division_id, Team.is_active.is_(True)).count()

    def _expected_regular_season_week_total() -> int:
        total = 0
        for group, name in division_order:
            division = divisions_by_key.get(canonical_division_id(group, name)) or divisions_by_normalized_name.get(normalize_division_name(f'{group} {name}'))
            if not division or not division.is_active:
                continue
            total += _division_required_games(_active_team_count(division.id))
        return total

    def _host_availability_count_for_week(week: Week) -> int:
        game_date = _week_game_date(week)
        if not week.id or not game_date:
            return 0
        return db.query(func.count(func.distinct(HostingAvailability.host_location_id))).outerjoin(
            HostingAvailability.physical_field_area
        ).filter(
            HostingAvailability.season_id == week.season_id,
            HostingAvailability.week_id == week.id,
            HostingAvailability.primary_game_date == game_date,
            HostingAvailability.is_available.is_(True),
        ).scalar() or 0

    def _generated_slot_counts_for_week(week: Week) -> dict[str, int]:
        counts = {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0}
        game_date = _week_game_date(week)
        if not game_date:
            return counts
        for field_type, count in db.query(GameSlot.field_type, func.count(GameSlot.id)).filter(
            GameSlot.season_id == week.season_id,
            GameSlot.week_id == week.id,
            GameSlot.slot_date == game_date,
        ).group_by(GameSlot.field_type).all():
            size = _normalize_field_size(field_type)
            if size in counts:
                counts[size] += int(count or 0)
        return counts

    def _build_root_cause_categories(diagnostics: dict[str, object]) -> list[str]:
        categories: set[str] = set()
        expected_games = int(diagnostics.get('expected_games_total') or 0)
        existing_scheduled = int(diagnostics.get('existing_scheduled_games_total') or 0)
        generated_game_groups = int(diagnostics.get('generated_game_groups_total') or 0)
        no_active_teams = int(diagnostics.get('active_teams_total') or 0) == 0
        no_active_divisions = int(diagnostics.get('divisions_evaluated') or 0) == 0
        no_regular_weeks = int(diagnostics.get('regular_season_weeks_found') or diagnostics.get('weeks_evaluated') or 0) == 0
        every_game_already_scheduled = expected_games > 0 and existing_scheduled >= expected_games
        if no_active_teams:
            categories.add('no_active_teams')
        if no_active_divisions:
            categories.add('no_active_divisions')
        if no_regular_weeks:
            categories.add('no_weeks_found')
        if every_game_already_scheduled:
            categories.add('all_games_already_scheduled')
        if (no_active_teams or no_active_divisions or no_regular_weeks) and generated_game_groups == 0 and not every_game_already_scheduled:
            categories.add('no_required_game_groups')
        if int(diagnostics.get('host_availability_total') or 0) == 0:
            categories.add('no_host_availability')
        placement_attempts = int(diagnostics.get('placement_attempts') or 0)
        preview_count = int(diagnostics.get('preview_assignments_count') or 0)
        committed_count = int(diagnostics.get('committed_assignments_count') or diagnostics.get('scheduled_games_count') or 0)
        validation_failures = int(diagnostics.get('failed_validation_count') or 0)
        database_failures = int(diagnostics.get('database_commit_failed_count') or 0)
        dry_run_result = bool(diagnostics.get('dry_run'))
        missing_slot_sizes = diagnostics.get('missing_generated_slot_field_sizes') or []
        if missing_slot_sizes:
            categories.add('no_generated_slots')
        scheduled_count = int(diagnostics.get('scheduled_games_count') or 0)
        compatible_slot_count = int(diagnostics.get('compatible_generated_slots_total') or 0)
        skipped_count = int(diagnostics.get('skipped_count') or 0)
        if expected_games > 0 and scheduled_count == 0 and existing_scheduled >= expected_games:
            categories.add('all_games_already_scheduled')
        if expected_games > 0 and compatible_slot_count == 0 and not missing_slot_sizes:
            categories.add('no_compatible_slots')
        if expected_games > 0 and scheduled_count == 0 and skipped_count > 0:
            categories.add('placement_blocked_by_constraints')
        if placement_attempts > 0 and committed_count == 0:
            categories.discard('unknown')
            if dry_run_result and preview_count > 0:
                categories.add('dry_run_prevented_commit')
            if database_failures > 0:
                categories.add('database_commit_failed')
            if validation_failures > 0:
                categories.add('placement_candidates_failed_validation')
            if preview_count == 0 and validation_failures == 0 and database_failures == 0:
                categories.add('no_valid_assignments')
        if not categories:
            categories.add('unknown')
        category_order = [
            'all_games_already_scheduled',
            'no_active_teams',
            'no_active_divisions',
            'no_weeks_found',
            'no_required_game_groups',
            'no_host_availability',
            'no_generated_slots',
            'no_compatible_slots',
            'placement_blocked_by_constraints',
            'dry_run_prevented_commit',
            'placement_candidates_failed_validation',
            'database_commit_failed',
            'no_valid_assignments',
            'unknown',
        ]
        return [category for category in category_order if category in categories]

    def _build_auto_schedule_diagnostics() -> dict[str, object]:
        active_divisions = _active_divisions_for_auto_schedule()
        missing_division_weeks: list[dict[str, object]] = []
        expected_games_by_week: dict[str, int] = {}
        expected_games_by_division_week: list[dict[str, object]] = []
        generated_game_groups_by_week: dict[str, int] = {}
        generated_game_groups_by_division_week: list[dict[str, object]] = []
        skipped_game_groups: list[dict[str, object]] = []
        available_host_locations_by_week: dict[str, int] = {}
        generated_slots_by_field_size: dict[str, int] = {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0}
        generated_slots_by_week: dict[str, dict[str, int]] = {}
        generated_slots_by_week_host_field_size: dict[str, list[dict[str, object]]] = {}
        required_games_by_size = _active_division_week_demand_by_size(db, division_order)
        compatible_generated_slots_total = 0
        existing_scheduled_games_total = 0
        active_teams_by_division: list[dict[str, object]] = []
        active_team_count_by_division: dict[uuid.UUID, int] = {}
        active_teams_total = 0
        required_game_groups_total = 0
        host_availability_total = 0
        regular_weeks = _regular_season_weeks()
        generated_rows_by_division_week = {
            (str(row.get('division_id') or ''), int(row.get('week') or 0)): row
            for row in division_week_diagnostics
        }
        for division in active_divisions:
            team_rows = db.query(Team.id, Team.name).filter(Team.division_id == division.id, Team.is_active.is_(True)).order_by(Team.name).all()
            team_count = len(team_rows)
            active_team_count_by_division[division.id] = team_count
            active_teams_total += team_count
            active_teams_by_division.append({
                'division_id': str(division.id),
                'division_name': _division_label(division),
                'active_team_count': team_count,
                'active_teams': [name for _, name in team_rows],
            })
        for week in regular_weeks:
            week_key = str(week.week_number)
            available_hosts = _host_availability_count_for_week(week)
            available_host_locations_by_week[week_key] = available_hosts
            host_availability_total += available_hosts
            slot_counts = _generated_slot_counts_for_week(week)
            generated_slots_by_week[week_key] = slot_counts
            host_slot_rows: list[dict[str, object]] = []
            game_date = _week_game_date(week)
            if game_date:
                for host_id, host_name, field_type, count in db.query(GameSlot.host_location_id, HostLocation.name, GameSlot.field_type, func.count(GameSlot.id)).join(HostLocation, HostLocation.id == GameSlot.host_location_id).filter(
                    GameSlot.season_id == season_id,
                    GameSlot.week_id == week.id,
                    GameSlot.slot_date == game_date,
                ).group_by(GameSlot.host_location_id, HostLocation.name, GameSlot.field_type).order_by(HostLocation.name, GameSlot.field_type).all():
                    host_slot_rows.append({
                        'week': week.week_number,
                        'slot_date': str(game_date),
                        'host_location_id': str(host_id),
                        'host_location_name': host_name,
                        'field_size': _normalize_field_size(field_type) or str(field_type or '').upper(),
                        'generated_slots': int(count or 0),
                    })
            generated_slots_by_week_host_field_size[week_key] = host_slot_rows
            selected_host_ids_for_week = _host_plan_allowed_host_ids_for_week(db, season_id, week.id, game_date)
            for size, count in slot_counts.items():
                generated_slots_by_field_size[size] = generated_slots_by_field_size.get(size, 0) + int(count or 0)
                if int(required_games_by_size.get(size, 0) or 0) > 0:
                    compatible_generated_slots_total += int(count or 0)
            for division in active_divisions:
                division_label = _division_label(division)
                required_games = _division_required_games(active_team_count_by_division.get(division.id, 0))
                expected_games_by_week[week_key] = expected_games_by_week.get(week_key, 0) + required_games
                required_game_groups_total += required_games
                existing = _actual_created_game_count_for_week(division.id, week.id)
                existing_scheduled_games_total += existing
                generated_row = generated_rows_by_division_week.get((str(division.id), int(week.week_number or 0)))
                generated_groups = int((generated_row or {}).get('generated_game_groups') or max(0, required_games - existing))
                generated_game_groups_by_week[week_key] = generated_game_groups_by_week.get(week_key, 0) + generated_groups
                expected_games_by_division_week.append({
                    'division_id': str(division.id),
                    'division_name': division_label,
                    'week': week.week_number,
                    'week_id': str(week.id),
                    'expected_games': required_games,
                    'existing_scheduled_games': existing,
                })
                generated_game_groups_by_division_week.append({
                    'division_id': str(division.id),
                    'division_name': division_label,
                    'week': week.week_number,
                    'week_id': str(week.id),
                    'expected_games': required_games,
                    'existing_scheduled_games': existing,
                    'generated_game_groups': generated_groups,
                })
                if required_games == 0:
                    skipped_game_groups.append({
                        'division_id': str(division.id),
                        'division_name': division_label,
                        'week': week.week_number,
                        'reason': 'No active teams in division.',
                    })
                elif existing >= required_games:
                    skipped_game_groups.append({
                        'division_id': str(division.id),
                        'division_name': division_label,
                        'week': week.week_number,
                        'reason': 'Every required game is already scheduled.',
                    })
                required_size = _required_field_type_for_division(division)
                compatible_slot_count = db.query(GameSlot.id).filter(
                    GameSlot.season_id == season_id,
                    GameSlot.week_id == week.id,
                    GameSlot.slot_date == game_date,
                    GameSlot.field_type == required_size,
                    GameSlot.status == 'OPEN',
                    GameSlot.assigned_game_id.is_(None),
                    GameSlot.host_location_id.in_(selected_host_ids_for_week) if selected_host_ids_for_week is not None else True,
                ).count() if game_date else 0
                if required_games > 0 and existing < required_games and int(compatible_slot_count or 0) <= 0:
                    missing_division_weeks.append({
                        'week': week.week_number,
                        'division_name': division_label,
                        'required_games': required_games,
                        'existing_scheduled_games': existing,
                        'required_field_size': required_size,
                        'week_start_date': str(game_date) if game_date else None,
                        'slot_count_for_week_and_field_size': int(compatible_slot_count or 0),
                        'compatible_slot_count': int(compatible_slot_count or 0),
                        'host_slot_counts_for_week': [row for row in generated_slots_by_week_host_field_size.get(week_key, []) if row.get('field_size') == required_size],
                        'reason': 'Required division/week has no generated slots for its week/date and field size.',
                    })
        missing_generated_slot_field_sizes = [
            size for size in FIELD_SIZE_ORDER
            if int(required_games_by_size.get(size, 0) or 0) > 0 and int(generated_slots_by_field_size.get(size, 0) or 0) == 0
        ]
        diagnostics = {
            'season_id': str(season_id),
            'season_name': season.name,
            'weeks_found': len(weeks),
            'regular_season_weeks_found': len(regular_weeks),
            'weeks_evaluated': len(regular_weeks),
            'division_order_evaluated': [f'{group} {name}' for group, name in division_order],
            'active_divisions_found': len(active_divisions),
            'divisions_evaluated': len(active_divisions),
            'active_teams_total': active_teams_total,
            'active_teams_by_division': active_teams_by_division,
            'expected_games_by_week': expected_games_by_week,
            'expected_games_by_division_week': expected_games_by_division_week,
            'expected_games_total': sum(expected_games_by_week.values()),
            'required_game_groups_total': required_game_groups_total,
            'missing_division_week_generation': missing_division_weeks,
            'generated_game_groups_by_week': generated_game_groups_by_week,
            'generated_game_groups_by_division_week': generated_game_groups_by_division_week,
            'division_week_placement_diagnostics': division_week_diagnostics,
            'generated_game_groups_total': sum(generated_game_groups_by_week.values()),
            'skipped_game_groups': skipped_game_groups,
            'available_host_locations_by_week': available_host_locations_by_week,
            'host_availability_total': host_availability_total,
            'generated_slots_by_field_size': generated_slots_by_field_size,
            'generated_slots_by_week': generated_slots_by_week,
            'generated_slots_by_week_host_field_size': generated_slots_by_week_host_field_size,
            'missing_generated_slot_field_sizes': missing_generated_slot_field_sizes,
            'compatible_generated_slots_total': compatible_generated_slots_total,
            'placement_attempts': attempted_game_groups or (sum(generated_game_groups_by_week.values()) + sum(skipped_attempts_by_reason.values())),
            'attempted_game_groups': attempted_game_groups,
            'valid_assignments_found': valid_assignments_found,
            'preview_assignments_count': preview_assignments_count,
            'preview_games_count': preview_games_count,
            'committed_assignments_count': committed_assignments_count,
            'committed_games_count': committed_assignments_count,
            'failed_validation_count': max(failed_validation_count, sum(failed_validation_reasons.values())),
            'failed_validation_reasons': dict(failed_validation_reasons),
            'database_commit_failed_count': database_commit_failed_count,
            'dry_run': dry_run,
            'scheduled_games_count': total_games_created,
            'existing_scheduled_games_total': existing_scheduled_games_total,
            'skipped_count': sum(skipped_attempts_by_reason.values()),
            'skipped_reasons': dict(skipped_attempts_by_reason),
        }
        diagnostics['root_cause_categories'] = _build_root_cause_categories(diagnostics)
        return diagnostics

    def _log_auto_schedule_result(diagnostics: dict[str, object], level: int = logging.INFO) -> None:
        logger.log(
            level,
            'auto_schedule_result season_id=%s weeks_evaluated=%s divisions_evaluated=%s expected_games_by_week=%s generated_game_groups_by_week=%s available_host_locations_by_week=%s generated_slots_by_field_size=%s placement_attempts=%s scheduled_games_count=%s skipped_count=%s skipped_reasons=%s root_cause_categories=%s missing_generated_slot_field_sizes=%s missing_division_week_generation=%s',
            diagnostics.get('season_id'),
            diagnostics.get('weeks_evaluated'),
            diagnostics.get('divisions_evaluated'),
            diagnostics.get('expected_games_by_week'),
            diagnostics.get('generated_game_groups_by_week'),
            diagnostics.get('available_host_locations_by_week'),
            diagnostics.get('generated_slots_by_field_size'),
            diagnostics.get('placement_attempts'),
            diagnostics.get('scheduled_games_count'),
            diagnostics.get('skipped_count'),
            diagnostics.get('skipped_reasons'),
            diagnostics.get('root_cause_categories'),
            diagnostics.get('missing_generated_slot_field_sizes'),
            diagnostics.get('missing_division_week_generation'),
        )

    preplacement_diagnostics = _build_auto_schedule_diagnostics()
    preplacement_root_causes = list(preplacement_diagnostics.get('root_cause_categories') or [])
    preplacement_generated_groups = int(preplacement_diagnostics.get('generated_game_groups_total') or 0)
    preplacement_expected_games = int(preplacement_diagnostics.get('expected_games_total') or 0)
    if preplacement_generated_groups == 0 and (
        'no_required_game_groups' in preplacement_root_causes
        or 'all_games_already_scheduled' in preplacement_root_causes
        or preplacement_expected_games == 0
    ):
        _log_auto_schedule_result(preplacement_diagnostics, logging.WARNING)
        if 'all_games_already_scheduled' in preplacement_root_causes:
            message = 'Auto-schedule completed but no games were scheduled: all games already scheduled.'
        else:
            message = 'Auto-schedule completed but no games were scheduled: no required game groups were generated.'
        if dry_run:
            db.rollback()
        else:
            db.commit()
        return {
            'status': 'warning',
            'message': message,
            'dry_run': dry_run,
            'preview_games_count': 0,
            'committed_games_count': 0,
            'scheduled_games_count': 0,
            'total_games_created': 0,
            'root_cause_categories': preplacement_root_causes or ['unknown'],
            'auto_schedule_diagnostics': preplacement_diagnostics,
            'slot_capacity_validation': None,
            'games_skipped': 0,
            'skipped_attempts_message': '0 placement attempts skipped; placement was not started because required game groups were not generated.',
            'skipped_attempts_summary': skipped_attempts_summary,
            'skipped_attempts_by_reason': skipped_attempts_by_reason,
            'required_games_still_missing': [],
            'warnings': warnings,
            'validation_errors': validation_errors,
            'validation_warnings': validation_warnings,
            'weekly_schedule_diagnostics': [],
            'division_week_schedule_diagnostics': [],
            'hard_validation': [],
            'post_run_validation': [],
            'divisions_completed': [],
            'divisions_with_unresolved_games': [],
            'post_schedule_repair': {'ran': False, 'note': 'Run manual optimization endpoint to execute repairs.'},
        }

    slot_preflight = _regenerate_and_validate_slots_for_weeks(db, _regular_season_weeks(), division_order)
    slot_preflight_errors = list(slot_preflight.get('validation_errors') or [])
    if slot_preflight_errors:
        validation_errors.extend(slot_preflight_errors)
        warnings.append(
            'Some weeks are missing generated slots for required field sizes; auto-schedule will still preview or commit other valid weeks.'
        )

    for group, name in division_order:
        requested_label = f'{group} {name}'
        requested_normalized = normalize_division_name(requested_label)
        division = divisions_by_key.get(canonical_division_id(group, name)) or divisions_by_normalized_name.get(requested_normalized)
        division_label = f'{group.title()} {name}'
        logger.info(
            'auto_schedule_division_lookup requested_division=%s normalized_division=%s matched_division_id=%s',
            requested_label,
            requested_normalized,
            str(division.id) if division else None,
        )
        if not division:
            warnings.append(f'Division not found: {division_label}')
            continue
        division_created = 0
        division_unresolved = False
        for week in _regular_season_weeks():
            week_game_date = _week_game_date(week)
            if not week_game_date:
                warnings.append(f'Week {week.week_number} skipped: missing Primary Game Date.')
                continue
            proposals = []
            preview = {}
            preview_skipped: list[dict[str, object]] = []
            apply_skipped: list[dict[str, object]] = []
            generated_game_groups = 0
            active_team_count = _active_team_count(division.id)
            required_games = _division_required_games(active_team_count)
            unscheduled_teams: list[str] = []
            unresolved_conflicts: list[dict[str, object]] = []
            host_count = 0
            try:
                preview = auto_fill_preview({'season_id': season_id, 'week_id': week.id, 'division_id': division.id}, db)
                proposals = preview.get('proposals') or []
                generated_game_groups = int(preview.get('generated_required_game_groups') if preview.get('generated_required_game_groups') is not None else len(proposals))
                attempted_game_groups += len(proposals)
                valid_assignments_found += len(proposals)
                preview_assignments_count += len(proposals)
                preview_games_count += len(proposals)
                preview_skipped = list(preview.get('skipped') or [])
                _record_skipped(preview_skipped)
                preview_validation = preview.get('final_validation') or {}
                active_team_count = int(preview_validation.get('active_team_count') or active_team_count)
                required_games = int(preview_validation.get('required_game_count') or required_games)
                unscheduled_teams = list(preview_validation.get('unscheduled_teams') or [])
                unresolved_conflicts = list(preview_skipped)
                if not proposals:
                    actual_created_games = _actual_created_game_count_for_week(division.id, week.id)
                    host_count = _host_count_for_week(division.id, week.id)
                    if required_games > actual_created_games and not preview_skipped:
                        preview_skipped.append({'reason': 'Missing generated game group for required division/week.'})
                        _record_skipped([preview_skipped[-1]])
                else:
                    if dry_run:
                        actual_created_games = _actual_created_game_count_for_week(division.id, week.id)
                        host_count = _host_count_for_week(division.id, week.id)
                    else:
                        try:
                            applied = auto_fill_apply({'season_id': season_id, 'week_id': week.id, 'division_id': division.id, 'proposals': proposals}, db)
                            created_count = int(applied.get('created_count') or 0)
                            skipped_count = int(applied.get('skipped_count') or 0)
                            division_created += created_count
                            total_games_created += created_count
                            committed_assignments_count += created_count
                            apply_skipped = list(applied.get('skipped') or [])
                            failed_validation_count += skipped_count
                            _record_skipped(apply_skipped)
                            host_count = _host_count_for_week(division.id, week.id)
                            actual_created_games = _actual_created_game_count_for_week(division.id, week.id)
                            if skipped_count > 0:
                                division_unresolved = True
                            apply_validation = applied.get('final_validation') or {}
                            if int(apply_validation.get('required_game_count') or 0) != required_games:
                                required_games = int(apply_validation.get('required_game_count') or 0)
                        except Exception as exc:
                            db.rollback()
                            database_commit_failed_count += 1
                            failed_validation_count += len(proposals)
                            division_unresolved = True
                            actual_created_games = _actual_created_game_count_for_week(division.id, week.id)
                            host_count = _host_count_for_week(division.id, week.id)
                            apply_skipped = [{'reason': f'Placement failed but scheduling continued for later divisions: {exc}'}]
                            _record_skipped(apply_skipped)
                            warnings.append(f'{division_label} Week {week.week_number}: placement failed; continuing with later divisions.')
                            logger.exception('auto_schedule_apply_failed_continuing season_id=%s week_id=%s division_id=%s', season_id, week.id, division.id)
            except Exception as exc:
                db.rollback()
                division_unresolved = True
                actual_created_games = _actual_created_game_count_for_week(division.id, week.id)
                host_count = _host_count_for_week(division.id, week.id)
                preview_skipped = [{'reason': f'Game group generation failed but scheduling continued for later divisions: {exc}'}]
                _record_skipped(preview_skipped)
                warnings.append(f'{division_label} Week {week.week_number}: game group generation failed; continuing with later divisions.')
                logger.exception('auto_schedule_preview_failed_continuing season_id=%s week_id=%s division_id=%s', season_id, week.id, division.id)
            generated_game_groups = max(generated_game_groups, min(required_games, actual_created_games))
            all_skips_for_division_week = preview_skipped + apply_skipped
            preview_diagnostics = preview.get('diagnostics') or {}
            preview_dh = preview_diagnostics.get('odd_team_double_header_reservation') or {}
            placement_preview_diagnostic = preview_diagnostics.get('division_week_placement') or {}
            missing_preview_diagnostic = preview_diagnostics.get('missing_division_week') or {}
            placement_attempt_details = list(
                placement_preview_diagnostic.get('placement_attempt_details')
                or missing_preview_diagnostic.get('placement_attempt_details')
                or []
            )
            required_matchups_generated = list(
                placement_preview_diagnostic.get('required_matchups_generated')
                or missing_preview_diagnostic.get('required_matchups_generated')
                or [proposal.get('proposed_matchup') for proposal in proposals if proposal.get('proposed_matchup')]
            )
            active_team_names = list(
                placement_preview_diagnostic.get('active_teams')
                or missing_preview_diagnostic.get('active_team_names')
                or [name for _, name in db.query(Team.id, Team.name).filter(Team.division_id == division.id, Team.is_active.is_(True)).order_by(Team.name).all()]
            )
            missing_team_names = list(
                placement_preview_diagnostic.get('missing_teams')
                or unscheduled_teams
                or []
            )
            skip_reasons = sorted({_skip_reason_code(str((row or {}).get('reason') or 'unknown')) for row in all_skips_for_division_week})
            rejected_attempt_reasons = [
                str(row.get('reason') or 'unknown')
                for row in placement_attempt_details
                if row.get('status') == 'rejected'
            ]
            division_week_diagnostic = {
                'division_id': str(division.id),
                'week': week.week_number,
                'week_start_date': str(week_game_date) if week_game_date else None,
                'division_name': division_label,
                'active_team_count': active_team_count,
                'active_teams': active_team_names,
                'expected_games': required_games,
                'generated_game_groups': generated_game_groups,
                'required_matchups_generated': required_matchups_generated,
                'placement_attempts': int(placement_preview_diagnostic.get('placement_attempts') or missing_preview_diagnostic.get('placement_attempts') or len(proposals)),
                'valid_assignments_found': int(placement_preview_diagnostic.get('valid_assignments_found') or missing_preview_diagnostic.get('valid_assignments_found') or len(proposals)),
                'scheduled_games': actual_created_games,
                'missing_games': max(0, required_games - actual_created_games),
                'missing_teams': missing_team_names,
                'skipped_placements': len(all_skips_for_division_week),
                'skip_reasons': skip_reasons or ([] if actual_created_games >= required_games else ['unknown']),
                'date': str(week_game_date) if week_game_date else None,
                'required_field_size': _normalize_field_size(_required_field_type_for_division(division)) or str(_required_field_type_for_division(division)),
                'compatible_slots_found': int(preview.get('compatible_slots_found') or placement_preview_diagnostic.get('compatible_slot_count') or missing_preview_diagnostic.get('compatible_slots_found') or 0),
                'compatible_slot_count': int(preview.get('compatible_slots_found') or placement_preview_diagnostic.get('compatible_slot_count') or missing_preview_diagnostic.get('compatible_slots_found') or 0),
                'compatible_large_slots_available': placement_preview_diagnostic.get('compatible_large_slots_available') if placement_preview_diagnostic else missing_preview_diagnostic.get('compatible_large_slots_available'),
                'placement_attempt_details': placement_attempt_details,
                'rejected_placement_reasons': rejected_attempt_reasons,
                'skipped_placement_reasons': [str((row or {}).get('reason') or 'unknown') for row in all_skips_for_division_week],
                'doubleheader_team_selected': preview_dh.get('selected_team_name') or placement_preview_diagnostic.get('doubleheader_team_selected') or missing_preview_diagnostic.get('doubleheader_team_selected'),
                'doubleheader_placement_failed': bool(
                    (active_team_count % 2 == 1)
                    and required_games > actual_created_games
                    and (preview_dh.get('reservation_failure_reasons') or missing_preview_diagnostic.get('doubleheader_placement_failed'))
                ),
            }
            division_week_diagnostics.append(division_week_diagnostic)
            log_level = logging.WARNING if int(division_week_diagnostic.get('missing_games') or 0) > 0 else logging.INFO
            logger.log(
                log_level,
                'auto_schedule_division_week_placement_diagnostics week=%s week_date=%s division=%s required_field_size=%s active_team_count=%s active_teams=%s expected_games=%s generated_game_groups=%s required_matchups=%s placement_attempts=%s valid_assignments_found=%s scheduled_games=%s missing_games=%s missing_teams=%s doubleheader_team_selected=%s compatible_slot_count=%s compatible_large_slots_available=%s skipped_placement_reasons=%s rejected_placement_reasons=%s placement_attempt_details=%s',
                division_week_diagnostic.get('week'),
                division_week_diagnostic.get('week_start_date'),
                division_week_diagnostic.get('division_name'),
                division_week_diagnostic.get('required_field_size'),
                division_week_diagnostic.get('active_team_count'),
                division_week_diagnostic.get('active_teams'),
                division_week_diagnostic.get('expected_games'),
                division_week_diagnostic.get('generated_game_groups'),
                division_week_diagnostic.get('required_matchups_generated'),
                division_week_diagnostic.get('placement_attempts'),
                division_week_diagnostic.get('valid_assignments_found'),
                division_week_diagnostic.get('scheduled_games'),
                division_week_diagnostic.get('missing_games'),
                division_week_diagnostic.get('missing_teams'),
                division_week_diagnostic.get('doubleheader_team_selected'),
                division_week_diagnostic.get('compatible_slot_count'),
                division_week_diagnostic.get('compatible_large_slots_available'),
                division_week_diagnostic.get('skipped_placement_reasons'),
                division_week_diagnostic.get('rejected_placement_reasons'),
                division_week_diagnostic.get('placement_attempt_details') if (division_week_diagnostic.get('week') == 8 and str(division_week_diagnostic.get('division_name') or '').upper().startswith('COED 6TH/7TH')) else [],
            )
            week_diagnostic = weekly_diagnostics_by_week_id.setdefault(week.id, {
                'week': week.week_number,
                'week_start_date': str(week_game_date) if week_game_date else None,
                'expected_games_total': 0,
                'generated_game_groups_total': 0,
                'scheduled_games_total': 0,
                'missing_games_total': 0,
                'skipped_placements_total': 0,
                'divisions': [],
            })
            week_diagnostic['expected_games_total'] = int(week_diagnostic['expected_games_total']) + required_games
            week_diagnostic['generated_game_groups_total'] = int(week_diagnostic['generated_game_groups_total']) + generated_game_groups
            week_diagnostic['skipped_placements_total'] = int(week_diagnostic['skipped_placements_total']) + len(all_skips_for_division_week)
            week_diagnostic['divisions'].append(division_week_diagnostic)
            post_run_validation.append({
                'division': division_label,
                'week': week.week_number,
                'active_team_count': active_team_count,
                'required_games': required_games,
                'created_games': actual_created_games,
                'missing_games': max(0, required_games - actual_created_games),
                'unscheduled_teams': unscheduled_teams,
                'unresolved_conflicts': unresolved_conflicts,
                'overflow_used': host_count > 2,
                'two_location_rule_relaxed': host_count > 2,
                'validation_warnings': ['Third host location used.'] if host_count > 2 else [],
            })
            if host_count > 2:
                validation_warnings.append({
                    'division': division_label,
                    'week': week.week_number,
                    'warning': 'Third host location used.',
                })
            if actual_created_games < required_games:
                division_unresolved = True
                missing_games = required_games - actual_created_games
                division_week_team_counts = db.query(
                    Team.name,
                    func.count(Game.id),
                ).outerjoin(
                    Game,
                    and_(
                        or_(Game.home_team_id == Team.id, Game.away_team_id == Team.id),
                        Game.week_id == week.id,
                    ),
                ).outerjoin(GameStatus, Game.game_status_id == GameStatus.id).filter(
                    Team.division_id == division.id,
                    Team.is_active.is_(True),
                ).filter(
                    or_(Game.id.is_(None), GameStatus.code != 'UNSCHEDULED')
                ).group_by(Team.id, Team.name).all()
                missing_team_names = [name for name, count in division_week_team_counts if int(count or 0) == 0]
                warning = (
                    f'Unresolved scheduling warning: {division_label} Week {week.week_number} '
                    f'(Required games: {required_games}, Created games: {actual_created_games}, Missing games: {missing_games})'
                )
                warnings.append(warning)
                required_games_missing.append({
                    'division': division_label,
                    'week': week.week_number,
                    'required_games': required_games,
                    'created_games': actual_created_games,
                    'missing_games': missing_games,
                    'teams_missing_games': missing_team_names,
                    'rejected_placement_reasons': rejected_attempt_reasons or [str((row or {}).get('reason') or 'unknown') for row in all_skips_for_division_week],
                    'placement_attempt_details': placement_attempt_details,
                    'required_matchups_generated': required_matchups_generated,
                    'doubleheader_team_selected': division_week_diagnostic.get('doubleheader_team_selected'),
                    'compatible_slot_count': division_week_diagnostic.get('compatible_slot_count'),
                    'compatible_large_slots_available': division_week_diagnostic.get('compatible_large_slots_available'),
                })
                validation_errors.append(
                    f'{division_label} Week {week.week_number}: required={required_games}, created={actual_created_games}, missing={missing_games}, teams_missing_games={missing_team_names}'
                )
        if division_created > 0 and not division_unresolved:
            divisions_completed.append(division_label)
        else:
            divisions_with_unresolved_games.append(division_label)
        season_team_game_counts = db.query(
            Team.name,
            func.count(Game.id),
        ).outerjoin(
            Game,
            and_(
                or_(Game.home_team_id == Team.id, Game.away_team_id == Team.id),
                Game.season_id == season_id,
            ),
        ).outerjoin(GameStatus, Game.game_status_id == GameStatus.id).filter(
            Team.division_id == division.id,
            Team.is_active.is_(True),
        ).filter(
            or_(Game.id.is_(None), GameStatus.code != 'UNSCHEDULED')
        ).group_by(Team.id, Team.name).all()
        season_counts_only = [int(count or 0) for _, count in season_team_game_counts]
        if season_counts_only:
            min_games = min(season_counts_only)
            max_games = max(season_counts_only)
            odd_team_double_header_allowed = (len(season_counts_only) % 2) == 1
            if (max_games - min_games) > 1 and not odd_team_double_header_allowed:
                under_target_teams = [name for name, count in season_team_game_counts if int(count or 0) == min_games]
                validation_errors.append(
                    f'{division_label}: season team game counts are imbalanced (min={min_games}, max={max_games}); must be within 1 game.'
                )
                warnings.append(
                    f'Balance validation failed for {division_label}: min={min_games}, max={max_games}.'
                )
                warnings.append(f'Balance under-target teams for {division_label}: {under_target_teams}')

    season_weeks = [w for w in weeks if w.start_date]
    september_13_weeks = [w for w in season_weeks if w.start_date.month == 9 and w.start_date.day == 13 and _is_regular_season_week(w)]
    september_13_slots = db.query(GameSlot.id).join(FieldInstance, FieldInstance.id == GameSlot.field_instance_id).join(
        HostLocation, HostLocation.id == FieldInstance.host_location_id
    ).filter(
        GameSlot.slot_date == date(season.start_date.year, 9, 13)
    ).count() if season.start_date else 0

    expected_regular_season_games = _expected_regular_season_week_total()
    hard_validation: list[dict[str, object]] = []
    for week in _regular_season_weeks():
        week_game_date = _week_game_date(week)
        if not week_game_date:
            continue
        scheduled_games = _scheduled_games_for_week(week.id)
        scheduled_games_total = len(scheduled_games)
        unique_team_ids = {
            team_id
            for game in scheduled_games
            for team_id in (game.home_team_id, game.away_team_id)
            if team_id
        }
        unique_teams_playing = len(unique_team_ids)
        field_size_counts = _week_field_size_counts(week.id)
        missing_total = max(0, expected_regular_season_games - scheduled_games_total)
        week_diagnostic = weekly_diagnostics_by_week_id.setdefault(week.id, {
            'week': week.week_number,
            'week_start_date': str(week_game_date) if week_game_date else None,
            'expected_games_total': expected_regular_season_games,
            'generated_game_groups_total': 0,
            'scheduled_games_total': 0,
            'missing_games_total': 0,
            'skipped_placements_total': 0,
            'divisions': [],
        })
        week_diagnostic['expected_games_total'] = expected_regular_season_games
        week_diagnostic['scheduled_games_total'] = scheduled_games_total
        week_diagnostic['missing_games_total'] = missing_total
        week_diagnostic['unique_teams_playing'] = unique_teams_playing
        week_diagnostic['field_size_counts'] = field_size_counts
        missing_divisions = [
            division_row
            for division_row in week_diagnostic.get('divisions', [])
            if int(division_row.get('missing_games') or 0) > 0
        ]
        validation_row = {
            'week': week.week_number,
            'week_start_date': str(week_game_date) if week_game_date else None,
            'expected_games': expected_regular_season_games,
            'scheduled_games': scheduled_games_total,
            'unique_teams_playing': unique_teams_playing,
            'expected_unique_teams_playing': 43,
            'field_size_counts': field_size_counts,
            'missing_games': missing_total,
            'missing_divisions': missing_divisions,
            'skipped_placement_reasons': sorted({
                reason
                for division_row in missing_divisions
                for reason in (division_row.get('skip_reasons') or ['unknown'])
            }),
        }
        if expected_regular_season_games != 22:
            validation_errors.append(
                f'Week {week.week_number}: expected regular-season game count is {expected_regular_season_games}; hard validation expects 22 based on current league setup.'
            )
        if scheduled_games_total != expected_regular_season_games:
            validation_errors.append(
                f'Week {week.week_number}: scheduled_games={scheduled_games_total}, expected_games={expected_regular_season_games}, missing_games={missing_total}.'
            )
        if unique_teams_playing != 43:
            validation_errors.append(
                f'Week {week.week_number}: unique_teams_playing={unique_teams_playing}, expected_unique_teams_playing=43.'
            )
        if missing_total > 0 and not any(row.get('week') == week.week_number for row in required_games_missing):
            required_games_missing.append({
                'division': 'WEEK_TOTAL',
                'week': week.week_number,
                'required_games': expected_regular_season_games,
                'created_games': scheduled_games_total,
                'missing_games': missing_total,
                'missing_divisions': missing_divisions,
                'skipped_placement_reasons': validation_row['skipped_placement_reasons'],
            })
        if week_game_date == date(2026, 9, 13):
            expected_by_size = {FIELD_SIZE_SMALL: 10, FIELD_SIZE_MEDIUM: 5, FIELD_SIZE_LARGE: 7}
            missing_by_size = {
                size: max(0, expected_count - int(field_size_counts.get(size, 0) or 0))
                for size, expected_count in expected_by_size.items()
            }
            validation_row['september_13_validation'] = {
                'expected_small_games': expected_by_size[FIELD_SIZE_SMALL],
                'expected_medium_games': expected_by_size[FIELD_SIZE_MEDIUM],
                'expected_large_games': expected_by_size[FIELD_SIZE_LARGE],
                'actual_small_games': field_size_counts[FIELD_SIZE_SMALL],
                'actual_medium_games': field_size_counts[FIELD_SIZE_MEDIUM],
                'actual_large_games': field_size_counts[FIELD_SIZE_LARGE],
                'missing_small_games': missing_by_size[FIELD_SIZE_SMALL],
                'missing_medium_games': missing_by_size[FIELD_SIZE_MEDIUM],
                'missing_large_games': missing_by_size[FIELD_SIZE_LARGE],
            }
            if any(missing_by_size.values()):
                validation_errors.append(
                    '09/13/2026 field-size validation failed: '
                    f"missing_small_games={missing_by_size[FIELD_SIZE_SMALL]}, "
                    f"missing_medium_games={missing_by_size[FIELD_SIZE_MEDIUM]}, "
                    f"missing_large_games={missing_by_size[FIELD_SIZE_LARGE]}."
                )
        hard_validation.append(validation_row)

    schedule_complete = not validation_errors and not required_games_missing
    skipped_attempts_message = (
        f"{sum(skipped_attempts_by_reason.values())} placement attempts skipped:\n"
        f"- Already scheduled: {skipped_attempts_summary.get('Already scheduled', 0)}\n"
        f"- No compatible field: {skipped_attempts_summary.get('No compatible field', 0)}\n"
        f"- No available slot: {skipped_attempts_summary.get('No available slot', 0)}\n"
        f"- No host capacity: {skipped_attempts_summary.get('No host capacity', 0)}\n"
        f"- Missing generated game group: {skipped_attempts_summary.get('Missing generated game group', 0)}"
    )

    auto_schedule_diagnostics = _build_auto_schedule_diagnostics()
    root_cause_categories = list(auto_schedule_diagnostics.get('root_cause_categories') or ['unknown'])
    if int(auto_schedule_diagnostics.get('expected_games_total') or 0) > 0 and total_games_created == 0 and not dry_run:
        warning_message = 'Auto-schedule completed but no games were scheduled.'
        if 'all_games_already_scheduled' in root_cause_categories:
            warning_message = 'Auto-schedule completed but no games were scheduled: all games already scheduled.'
        elif 'no_generated_slots' in root_cause_categories:
            missing_sizes = ', '.join(auto_schedule_diagnostics.get('missing_generated_slot_field_sizes') or [])
            warning_message = f'Auto-schedule completed but no games were scheduled: no generated slots for required field sizes ({missing_sizes or "unknown"}).'
        elif 'no_required_game_groups' in root_cause_categories:
            warning_message = 'Auto-schedule completed but no games were scheduled: no required game groups were generated.'
        warnings.append(warning_message)
        validation_errors.append('Auto-schedule placed 0 games even though expected_games > 0; review auto_schedule_diagnostics.root_cause_categories.')
        schedule_complete = False
    _log_auto_schedule_result(auto_schedule_diagnostics, logging.WARNING if total_games_created == 0 else logging.INFO)

    # Intentionally do not run post-schedule optimization automatically.
    # Optimization is executed manually via /manual-schedule-builder/optimize-schedule.
    if dry_run:
        db.rollback()
    else:
        db.commit()

    final_status = 'complete' if schedule_complete else 'incomplete'
    final_message = 'Auto-schedule completed.' if schedule_complete else 'Auto-schedule completed with missing required games; review validation_errors and diagnostics.'
    if dry_run:
        final_status = 'complete' if preview_assignments_count > 0 else 'warning'
        if preview_assignments_count > 0:
            final_message = f'Dry run completed. {preview_games_count} games would be scheduled. No games were saved.'
        else:
            reason_message = '; '.join(validation_errors[:3]) or '; '.join(warnings[:3]) or 'review auto_schedule_diagnostics.root_cause_categories.'
            final_message = f'Dry run found no valid assignments. {reason_message}'
    elif total_games_created == 0:
        final_status = 'warning'
        final_message = 'Auto-schedule completed but no games were scheduled.'
        if 'all_games_already_scheduled' in root_cause_categories:
            final_message = 'Auto-schedule completed but no games were scheduled: all games already scheduled.'
        elif 'no_generated_slots' in root_cause_categories:
            missing_sizes_message = ', '.join(auto_schedule_diagnostics.get('missing_generated_slot_field_sizes') or []) or 'unknown'
            final_message = f'Auto-schedule completed but no games were scheduled: no generated slots for required field sizes ({missing_sizes_message}).'
        elif 'no_required_game_groups' in root_cause_categories:
            final_message = 'Auto-schedule completed but no games were scheduled: no required game groups were generated.'

    return {
        'status': final_status,
        'message': final_message,
        'dry_run': dry_run,
        'preview_games_count': preview_games_count,
        'committed_games_count': committed_assignments_count,
        'scheduled_games_count': committed_assignments_count,
        'total_games_created': total_games_created,
        'root_cause_categories': root_cause_categories,
        'auto_schedule_diagnostics': auto_schedule_diagnostics,
        'slot_capacity_validation': slot_preflight,
        'season_date_diagnostics': {
            'target_date_checked': f"{season.start_date.year}-09-13" if season.start_date else None,
            'matching_week_numbers': [w.week_number for w in september_13_weeks],
            'date_in_regular_season_weeks': len(september_13_weeks) > 0,
            'available_slots_on_target_date': september_13_slots,
            'date_excluded_reason': None if len(september_13_weeks) > 0 else 'No season week starts on September 13; date is outside defined weekly schedule windows.',
        },
        'games_skipped': sum(skipped_attempts_by_reason.values()),
        'skipped_attempts_message': skipped_attempts_message,
        'skipped_attempts_summary': skipped_attempts_summary,
        'skipped_attempts_by_reason': skipped_attempts_by_reason,
        'required_games_still_missing': required_games_missing,
        'warnings': warnings,
        'validation_errors': validation_errors,
        'validation_warnings': validation_warnings,
        'weekly_schedule_diagnostics': sorted(weekly_diagnostics_by_week_id.values(), key=lambda row: (int(row.get('week') or 0), str(row.get('week_start_date') or ''))),
        'division_week_schedule_diagnostics': division_week_diagnostics,
        'hard_validation': hard_validation,
        'post_run_validation': post_run_validation,
        'divisions_completed': divisions_completed,
        'divisions_with_unresolved_games': divisions_with_unresolved_games,
        'post_schedule_repair': {'ran': False, 'note': 'Run manual optimization endpoint to execute repairs.'},
    }




@router.post('/manual-schedule-builder/optimize-schedule', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def optimize_schedule(payload: dict, db: Session = Depends(get_db)):
    season_id = payload.get('season_id')
    if not season_id:
        raise HTTPException(400, 'season_id is required')
    season = db.query(Season).filter(Season.id == season_id).first()
    if not season:
        raise HTTPException(404, 'Season not found')

    optimize_same_community_home = bool(payload.get('optimize_same_community_home', True))
    repair_double_headers = bool(payload.get('repair_double_headers', True))
    reduce_repeat_matchups = bool(payload.get('reduce_repeat_matchups', False))
    preserve_two_location_limit = bool(payload.get('preserve_two_location_limit', True))
    dry_run = bool(payload.get('dry_run', True))

    try:
        diagnostics = run_post_schedule_repair_pass(
            db,
            season_id,
            optimize_same_community_home=optimize_same_community_home,
            repair_double_headers=repair_double_headers,
            reduce_repeat_matchups=reduce_repeat_matchups,
            preserve_two_location_limit=preserve_two_location_limit,
        )
    except Exception as exc:
        db.rollback()
        logger.exception('Schedule optimization failed for season_id=%s', season_id)
        return {
            'ran': False,
            'dry_run': dry_run,
            'summary': {'error': str(exc)},
            'proposed_changes': [],
            'rejected_changes': [],
            'remaining_violations': [],
            'warnings': [f'Optimization failed: {exc}'],
        }

    proposed_changes = list((diagnostics.get('proposed_changes') or []))
    rejected_changes = list((diagnostics.get('rejected_changes') or []))

    if dry_run:
        db.rollback()
    else:
        db.commit()

    summary = diagnostics.get('summary') or {}
    return {
        'ran': True,
        'dry_run': dry_run,
        'summary': summary,
        'proposed_changes': proposed_changes,
        'rejected_changes': rejected_changes,
        'remaining_violations': diagnostics.get('remaining_violations') or [],
        'warnings': diagnostics.get('warnings') or [],
    }
@router.post('/manual-schedule-builder/repair/same-community-home-fields', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def run_same_community_home_field_repair(payload: dict, db: Session = Depends(get_db)):
    season_id = payload.get('season_id')
    if not season_id:
        raise HTTPException(400, 'season_id is required')
    season = db.query(Season).filter(Season.id == season_id).first()
    if not season:
        raise HTTPException(404, 'Season not found')
    diagnostics = repair_same_community_home_fields(db, season_id)
    db.commit()
    return {
        'season_id': str(season_id),
        'same_community_repair': diagnostics,
    }

@router.get('/public/games', response_model=PagedResponse[PublicGameRead])
@router.get('/public/schedule', response_model=PagedResponse[PublicGameRead])
def list_public_games(season_id: uuid.UUID | None = None, host_location_id: uuid.UUID | None = None, organization_id: uuid.UUID | None = None, division_id: uuid.UUID | None = None, week_id: uuid.UUID | None = None, field_type: str | None = None, field_id: uuid.UUID | None = None, team_id: uuid.UUID | None = None, status_code: str | None = None, date: date | None = None, page: int = 1, page_size: int = 500, db: Session = Depends(get_db)):
    season = _get_schedule_scope_season(db, season_id)
    filters = _scheduled_games_filters(
        season.id if season else season_id,
        date=date,
        division_id=division_id,
        organization_id=organization_id,
        host_location_id=host_location_id,
        field_type=field_type,
        field_id=field_id,
        team_id=team_id,
        week_id=week_id,
        status_code=status_code,
    )

    if not season or not _season_schedule_is_published(season):
        return PagedResponse(
            items=[],
            total=0,
            page=page,
            page_size=page_size,
            message='No published schedule is currently available.',
        )

    rows = [
        row for row in get_scheduled_games_for_season(db, season.id, filters, organization_filter_any_team=True)
        if row[6] and row[6].is_active
    ]
    total = len(rows)
    start = max(page - 1, 0) * page_size
    items = rows[start:start + page_size]
    return PagedResponse(
        items=[_public_game_read_from_schedule_row(row) for row in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get('/public/schedule/debug')
def public_schedule_debug(season_id: uuid.UUID | None = None, host_location_id: uuid.UUID | None = None, organization_id: uuid.UUID | None = None, division_id: uuid.UUID | None = None, week_id: uuid.UUID | None = None, field_type: str | None = None, field_id: uuid.UUID | None = None, team_id: uuid.UUID | None = None, status_code: str | None = None, date: date | None = None, db: Session = Depends(get_db)):
    season = _get_schedule_scope_season(db, season_id)
    base_filters = _scheduled_games_filters(season.id if season else season_id)
    active_filters = _scheduled_games_filters(
        season.id if season else season_id,
        date=date,
        division_id=division_id,
        organization_id=organization_id,
        host_location_id=host_location_id,
        field_type=field_type,
        field_id=field_id,
        team_id=team_id,
        week_id=week_id,
        status_code=status_code,
    )
    admin_rows = get_scheduled_games_for_season(db, season.id if season else None, base_filters) if season else []
    public_before_filters = admin_rows if season and _season_schedule_is_published(season) else []
    public_after_filters = get_scheduled_games_for_season(db, season.id, active_filters, organization_filter_any_team=True) if season and _season_schedule_is_published(season) else []
    return {
        'season_status': season.schedule_status if season else None,
        'admin_schedule_management_count': len(admin_rows),
        'public_schedule_count_before_filters': len(public_before_filters),
        'public_schedule_count_after_filters': len(public_after_filters),
        'filters': _serialize_schedule_filters(active_filters),
    }


@router.get('/public/schedule/options')
@router.get('/public/schedule-filters')
def list_public_schedule_filters(season_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    season = _get_schedule_scope_season(db, season_id)
    rows = [
        row for row in get_scheduled_games_for_season(db, season.id, _scheduled_games_filters(season.id))
        if row[6] and row[6].is_active
    ] if season and _season_schedule_is_published(season) else []

    if rows:
        host_locations_by_id = {host.id: host for _, _, _, host, _, _, _, _, _ in rows if host}
        organizations_by_id = {org.id: org for _, _, _, _, _, _, _, org, _ in rows if org}
        for _, _, _, _, home, away, _, _, _ in rows:
            if home.organization:
                organizations_by_id[home.organization.id] = home.organization
            if away.organization:
                organizations_by_id[away.organization.id] = away.organization
        divisions_by_id = {div.id: div for _, _, _, _, _, _, div, _, _ in rows if div}
        weeks_by_id = {g.week.id: g.week for g, _, _, _, _, _, _, _, _ in rows if g.week}
        teams_by_id = {}
        fields_by_id = {}
        for _, _, fi, _, home, away, _, _, _ in rows:
            teams_by_id[home.id] = home
            teams_by_id[away.id] = away
            if fi:
                fields_by_id[fi.id] = fi

        host_locations = sorted(host_locations_by_id.values(), key=lambda item: item.name)
        organizations = sorted(organizations_by_id.values(), key=lambda item: item.name)
        divisions = sorted(divisions_by_id.values(), key=lambda item: (item.sort_order or 0, item.name))
        weeks = sorted(weeks_by_id.values(), key=lambda item: (item.start_date, item.week_number))
        teams = sorted(teams_by_id.values(), key=lambda item: item.name)
        fields = sorted(fields_by_id.values(), key=lambda item: item.field_name)
    else:
        host_locations = db.query(HostLocation).join(HostLocation.organization).filter(
            HostLocation.is_active.is_(True),
            Organization.is_active.is_(True),
        ).order_by(HostLocation.name).all()
        organizations = db.query(Organization).filter(Organization.is_active.is_(True)).order_by(Organization.name).all()
        divisions = db.query(Division).filter(Division.is_active.is_(True)).order_by(Division.sort_order, Division.name).all()
        weeks_query = db.query(Week).join(Week.season).filter(Season.is_active.is_(True))
        if season:
            weeks_query = weeks_query.filter(Week.season_id == season.id)
        weeks = weeks_query.order_by(Week.primary_game_date, Week.week_number).all()
        teams = db.query(Team).filter(Team.is_active.is_(True)).order_by(Team.name).all()
        fields = db.query(FieldInstance).filter(FieldInstance.is_active.is_(True)).order_by(FieldInstance.field_name).all()

    return {
        'season': ({'id': str(season.id), 'name': season.name, 'schedule_status': season.schedule_status} if season else None),
        'host_locations': [{'id': item.id, 'name': item.name} for item in host_locations],
        'organizations': [{'id': item.id, 'name': item.name} for item in organizations],
        'divisions': [{'id': item.id, 'name': item.name, 'division_group': item.division_group} for item in divisions],
        'weeks': [{'id': item.id, 'week_number': item.week_number, 'start_date': item.start_date, 'end_date': item.end_date, 'primary_game_date': item.primary_game_date or item.start_date, 'label': item.label or f'Week {item.week_number}', 'date_type': _week_date_type(item)} for item in weeks],
        'teams': [{'id': item.id, 'name': item.name} for item in teams],
        'fields': [{'id': item.id, 'name': item.field_name} for item in fields],
    }


def _required_field_type_for_division(division: Division | None) -> str:
    if not division:
        return FIELD_SIZE_SMALL
    division_label = normalized_division_key(getattr(division, 'division_group', None), getattr(division, 'name', None))
    small_divisions = {'coed_k_1st', 'girls_k_1st', 'coed_k1st', 'girls_k1st', 'coed_k_1', 'girls_k_2', 'coed_2nd_3rd', 'girls_2nd_3rd', 'coed_2_3'}
    medium_divisions = {'coed_4th_5th', 'girls_4th_5th', 'coed_4_5', 'girls_3_5'}
    large_divisions = {'coed_6th_7th', 'girls_6th_7th', 'girls_6th_7th_8th', 'coed_6_7', 'girls_6_8', 'coed_8th', 'girls_8th', 'coed_8'}
    if division_label in small_divisions:
        return FIELD_SIZE_SMALL
    if division_label in medium_divisions:
        return FIELD_SIZE_MEDIUM
    if division_label in large_divisions:
        return FIELD_SIZE_LARGE
    layout_type = (getattr(division, 'required_field_layout_type', None) or '').strip().upper()
    normalized_size = _normalize_field_size(layout_type)
    return normalized_size or FIELD_SIZE_SMALL


LEAGUE_DEMAND_DIVISION_KEYS_BY_SIZE = {
    FIELD_SIZE_SMALL: {'COED_K_1', 'COED_2_3', 'GIRLS_K_2'},
    FIELD_SIZE_MEDIUM: {'COED_4_5', 'GIRLS_3_5'},
    FIELD_SIZE_LARGE: {'COED_6_7', 'COED_8', 'GIRLS_6_8', 'GIRLS_6_7_8'},
}
LEAGUE_DEMAND_DIVISION_KEYS = {
    key
    for keys in LEAGUE_DEMAND_DIVISION_KEYS_BY_SIZE.values()
    for key in keys
}


def _league_week_demand_summary(db: Session, division_order: list[tuple[str, str]]) -> dict[str, object]:
    """Build one league-wide weekly demand model before host/location slot generation.

    Demand intentionally counts all active teams in each active league division and
    does not filter by selected host, host community, or location. The odd-team
    doubleheader case is included by rounding up team pairs into expected games.
    """
    demand = _empty_field_size_counts()
    all_divisions = db.query(Division).all()
    divisions_by_key = {canonical_division_id_from_division(d): d for d in all_divisions}
    divisions_by_normalized_name = {
        normalize_division_name(f'{d.division_group or ""} {d.name or ""}'): d
        for d in all_divisions
    }
    ordered_divisions: list[Division] = []
    seen_division_ids: set[uuid.UUID] = set()

    for group, name in division_order:
        division = divisions_by_key.get(canonical_division_id(group, name)) or divisions_by_normalized_name.get(normalize_division_name(f'{group} {name}'))
        if division and division.id not in seen_division_ids:
            ordered_divisions.append(division)
            seen_division_ids.add(division.id)

    for division in sorted(all_divisions, key=lambda d: (str(d.division_group or ''), str(d.name or ''), str(d.id))):
        if division.id in seen_division_ids:
            continue
        if canonical_division_id_from_division(division) in LEAGUE_DEMAND_DIVISION_KEYS:
            ordered_divisions.append(division)
            seen_division_ids.add(division.id)

    division_rows: list[dict[str, object]] = []
    for division in ordered_divisions:
        division_key = canonical_division_id_from_division(division)
        if not division.is_active or division_key not in LEAGUE_DEMAND_DIVISION_KEYS:
            continue
        active_team_count = db.query(Team.id).filter(Team.division_id == division.id, Team.is_active.is_(True)).count()
        expected_games = _estimated_games_from_team_count(active_team_count)
        required_size = _required_field_type_for_division(division)
        if required_size not in demand:
            continue
        demand[required_size] += expected_games
        division_rows.append({
            'division_id': str(division.id),
            'division_key': division_key,
            'division_name': f'{division.division_group or ""} {division.name or ""}'.strip() or str(division.id),
            'team_count': active_team_count,
            'expected_games': expected_games,
            'field_size': required_size,
            'includes_odd_team_doubleheader': active_team_count % 2 == 1 and active_team_count > 1,
        })

    return {
        'active_divisions_included': division_rows,
        'league_wide_demand_by_size': demand,
    }


def _active_division_week_demand_by_size(db: Session, division_order: list[tuple[str, str]]) -> dict[str, int]:
    return dict(_league_week_demand_summary(db, division_order)['league_wide_demand_by_size'])


def _availability_generation_reason(
    db: Session,
    host: HostLocation,
    availability: HostingAvailability,
    demand_counts_override: dict[str, int] | None = None,
) -> str:
    surface_type = (host.surface_type or 'GRASS_FIELD') if host else 'GRASS_FIELD'
    hours = _hours_between(availability.start_time, availability.end_time, availability.available_date)
    if not availability.is_available:
        return f'{host.name}: availability is marked unavailable.'
    if surface_type == 'TURF_STADIUM':
        active_configs = db.query(HostLocationConfiguration).filter(
            HostLocationConfiguration.host_location_id == host.id,
            HostLocationConfiguration.is_active.is_(True),
        ).all()
        active_names = sorted(_available_turf_configuration_names(active_configs))
        demand = _normalized_demand_counts(demand_counts_override) if demand_counts_override is not None else _turf_demand_counts_for_date(db, host, availability.available_date)
        selected = availability.selected_configuration.configuration_name if availability.selected_configuration else None
        if availability.auto_select_turf_layout and not availability.lock_selected_layout:
            plan = _plan_turf_layout_blocks(demand, hours, set(active_names))
            return (
                f'{host.name}: turf auto layout evaluated approved layouts {active_names or ["none"]}; '
                f'demand small={demand[FIELD_SIZE_SMALL]}, medium={demand[FIELD_SIZE_MEDIUM]}, large={demand[FIELD_SIZE_LARGE]}; '
                f'planned waves={plan or "none"}.'
            )
        return f'{host.name}: turf locked/selected layout={selected or "none"}; active approved layouts={active_names or ["none"]}.'
    forecast = _grass_setup_forecast_for_availability(db, host, availability, demand_counts_override)
    return (
        f'{host.name}: grass forecast demand={forecast["demand"]}, requested_fields={forecast["requested"]}, '
        f'capacity={forecast["capacity"]}, forecast_fields={forecast["forecast"]}, status={forecast["capacity_status"]}; '
        f'warnings={forecast["warnings"] or "none"}.'
    )


def _regenerate_and_validate_slots_for_weeks(
    db: Session,
    weeks: list[Week],
    division_order: list[tuple[str, str]],
) -> dict[str, object]:
    regular_weeks = [week for week in weeks if _is_regular_season_week(week) and _week_game_date(week)]
    week_dates = {_week_game_date(week) for week in regular_weeks if _week_game_date(week)}
    week_by_id = {week.id: week for week in regular_weeks}
    week_by_date = {_week_game_date(week): week for week in regular_weeks if _week_game_date(week)}
    hosts = db.query(HostLocation).join(HostLocation.organization).filter(
        HostLocation.is_active.is_(True),
        Organization.is_active.is_(True),
    ).order_by(HostLocation.name).all()
    hosts_by_id = {host.id: host for host in hosts}
    generation_results: list[dict[str, object]] = []
    evaluated_hosts_by_date: dict[date, list[str]] = {week_date: [] for week_date in week_dates}
    generation_reasons_by_date: dict[date, list[str]] = {week_date: [] for week_date in week_dates}
    selected_host_diagnostics_by_date: dict[date, list[dict[str, object]]] = {week_date: [] for week_date in week_dates}
    selected_host_diagnostic_by_availability_id: dict[uuid.UUID, dict[str, object]] = {}
    league_demand_summary = _league_week_demand_summary(db, division_order)
    required_games_by_size = dict(league_demand_summary['league_wide_demand_by_size'])
    active_division_demand_rows = list(league_demand_summary['active_divisions_included'])
    demand_summary_by_date: dict[date, dict[str, object]] = {
        week_date: {
            'active_divisions_included': active_division_demand_rows,
            'league_wide_demand_by_size': dict(required_games_by_size),
        }
        for week_date in week_dates
    }
    availabilities_by_host_id: dict[uuid.UUID, list[HostingAvailability]] = {}
    available_hosts_by_date: dict[date, list[HostLocation]] = {week_date: [] for week_date in week_dates}

    def _matching_selected_availability(selection: HostPlanSelection, week: Week, host: HostLocation) -> tuple[HostingAvailability | None, dict[str, object], str | None]:
        game_date = _normalize_local_date_only(_week_game_date(week))
        if not week.id or not game_date:
            return None, {'lookup_method': 'missing_week_or_primary_game_date'}, 'Selected host is missing season_week_id or primary_game_date.'
        resolved = _resolve_hosting_availability(db, selection.season_id, week, game_date, host.id, repair=True, host=host)
        availability = resolved.get('availability')
        if availability and _availability_allows_generated_slots(db, availability):
            return availability, resolved, None
        return None, resolved, HOST_PLAN_SKIPPED_MISSING_AVAILABILITY_MESSAGE

    season_ids = {week.season_id for week in regular_weeks if week.season_id}
    selected_query = db.query(HostPlanSelection)
    if season_ids:
        selected_query = selected_query.filter(HostPlanSelection.season_id.in_(season_ids))
    regular_week_ids = {week.id for week in regular_weeks if week.id}
    selected_rows = selected_query.filter(
        or_(
            HostPlanSelection.week_id.in_(regular_week_ids),
            HostPlanSelection.game_date.in_(week_dates),
        ),
    ).order_by(HostPlanSelection.game_date, HostPlanSelection.status, HostPlanSelection.created_at).all() if week_dates and regular_week_ids else []
    for selection in selected_rows:
        selection_status = str(selection.status or '').upper()
        if selection_status not in HOST_PLAN_SCHEDULABLE_STATUSES and not selection.locked:
            continue
        week = week_by_id.get(selection.week_id) if selection.week_id else week_by_date.get(_normalize_local_date_only(selection.game_date))
        if not week or not _is_regular_season_week(week):
            continue
        game_date = _normalize_local_date_only(_week_game_date(week))
        if not game_date or selection.season_id != week.season_id:
            continue
        host = hosts_by_id.get(selection.host_location_id)
        if not host:
            continue
        availability, resolved_availability, lookup_warning = _matching_selected_availability(selection, week, host)
        diagnostic = {
            'host_location_id': str(host.id),
            'host_location_name': host.name,
            'expected_season_week_id': str(week.id) if week.id else None,
            'season_week_id': str(week.id) if week.id else None,
            'expected_primary_game_date': str(game_date),
            'primary_game_date': str(game_date),
            'host_plan_selection_id': str(selection.id),
            'hosting_availability_found': bool(availability),
            'hosting_availability_id': str(availability.id) if availability else None,
            'found_record_id': resolved_availability.get('found_record_id'),
            'found_record_season_week_id': resolved_availability.get('found_record_season_week_id'),
            'found_record_primary_game_date': resolved_availability.get('found_record_primary_game_date'),
            'found_record_available_date': resolved_availability.get('found_record_available_date'),
            'lookup_method_used': resolved_availability.get('lookup_method') or 'not_found',
            'repair_action_taken_or_required': resolved_availability.get('repair_actions') or resolved_availability.get('requires_admin_action'),
            'generated_slots_by_size': _empty_field_size_counts(),
            'zero_slot_reason': None,
        }
        selected_host_diagnostics_by_date.setdefault(game_date, []).append(diagnostic)
        if not availability:
            diagnostic['skipped'] = True
            diagnostic['reason_skipped'] = HOST_PLAN_SKIPPED_MISSING_AVAILABILITY_MESSAGE
            diagnostic['zero_slot_reason'] = lookup_warning or HOST_PLAN_SKIPPED_MISSING_AVAILABILITY_MESSAGE
            generation_reasons_by_date.setdefault(game_date, []).append(
                f'{HOST_PLAN_SKIPPED_MISSING_AVAILABILITY_MESSAGE}: {host.name}, {game_date}'
            )
            continue
        diagnostic['skipped'] = False
        diagnostic['reason_skipped'] = None
        evaluated_hosts_by_date.setdefault(game_date, []).append(host.name)
        availability.primary_game_date = game_date
        availability.week_id = week.id
        availability.season_id = week.season_id
        selected_host_diagnostic_by_availability_id[availability.id] = diagnostic
        availabilities_by_host_id.setdefault(host.id, [])
        if availability.id not in {row.id for row in availabilities_by_host_id[host.id]}:
            availabilities_by_host_id[host.id].append(availability)
            available_hosts_by_date.setdefault(game_date, []).append(host)

    # Backward-compatible fallback: older setups may have saved HostingAvailability
    # without HostPlanSelection rows. Use those rows only when no selected/locked/
    # overflow host exists for that regular-season date.
    for week in regular_weeks:
        game_date = _week_game_date(week)
        if not game_date or available_hosts_by_date.get(game_date):
            continue
        fallback_rows = db.query(HostingAvailability, HostLocation).join(
            HostLocation, HostingAvailability.host_location_id == HostLocation.id
        ).filter(
            HostLocation.is_active.is_(True),
            HostLocation.organization_id.is_not(None),
            HostingAvailability.season_id == week.season_id,
            HostingAvailability.week_id == week.id,
            HostingAvailability.primary_game_date == game_date,
            HostingAvailability.is_available.is_(True),
            HostingAvailability.active.is_(True),
        ).order_by(HostLocation.name, HostingAvailability.start_time).all()
        for availability, host in fallback_rows:
            if not _availability_allows_generated_slots(db, availability):
                continue
            availability.available_date = game_date
            availability.primary_game_date = game_date
            availability.week_id = week.id
            availability.season_id = week.season_id
            availabilities_by_host_id.setdefault(host.id, [])
            if availability.id not in {row.id for row in availabilities_by_host_id[host.id]}:
                availabilities_by_host_id[host.id].append(availability)
                available_hosts_by_date.setdefault(game_date, []).append(host)

    demand_by_availability_id_by_host: dict[uuid.UUID, dict[uuid.UUID, dict[str, int]]] = {}
    for available_date, date_hosts in available_hosts_by_date.items():
        selected_hosts = sorted(date_hosts, key=lambda h: ((h.name or '').lower(), str(h.id)))
        if available_date in demand_summary_by_date:
            demand_summary_by_date[available_date]['selected_hosts'] = [host.name for host in selected_hosts]
        for host in selected_hosts:
            for availability in availabilities_by_host_id.get(host.id, []):
                if (availability.primary_game_date or availability.available_date) == available_date:
                    # Forecast each selected host/location from the full league-wide demand.
                    # Host capacity may cap what is generated, but host/community-local demand
                    # must not erase required field sizes before grass or turf planning runs.
                    demand_by_availability_id_by_host.setdefault(host.id, {})[availability.id] = dict(required_games_by_size)


    for host in hosts:
        availabilities = availabilities_by_host_id.get(host.id, [])
        if not availabilities:
            continue
        demand_by_availability_id = {
            availability.id: demand_by_availability_id_by_host.get(host.id, {}).get(availability.id, _empty_field_size_counts())
            for availability in availabilities
        }
        result = _regenerate_hosting_day(db, availabilities, host, demand_by_availability_id)
        slots_created_by_availability = {
            availability.id: db.query(GameSlot.id).join(GameSlot.field_instance).filter(
                FieldInstance.hosting_availability_id == availability.id,
                GameSlot.season_id == availability.season_id,
                GameSlot.week_id == availability.week_id,
                GameSlot.slot_date == (availability.primary_game_date or availability.available_date),
            ).count()
            for availability in availabilities
        }
        slots_created_by_size_by_availability: dict[uuid.UUID, dict[str, int]] = {availability.id: _empty_field_size_counts() for availability in availabilities}
        for availability_id, field_type, count in db.query(FieldInstance.hosting_availability_id, GameSlot.field_type, func.count(GameSlot.id)).join(
            GameSlot, GameSlot.field_instance_id == FieldInstance.id
        ).filter(
            FieldInstance.hosting_availability_id.in_([availability.id for availability in availabilities]),
        ).group_by(FieldInstance.hosting_availability_id, GameSlot.field_type).all():
            size = _normalize_field_size(field_type)
            if size in FIELD_SIZE_ORDER:
                slots_created_by_size_by_availability.setdefault(availability_id, _empty_field_size_counts())[size] += int(count or 0)
        generation_results.append({
            'host_location_id': str(host.id),
            'host_location_name': host.name,
            'surface_type': host.surface_type or 'GRASS_FIELD',
            'slots_created': result.slots_created,
            'new_slots_created': result.new_slots_created,
            'slots_regenerated': result.slots_regenerated,
            'locked_slots_skipped': result.locked_slots_skipped,
            'errors': result.errors,
        })
        for availability in availabilities:
            availability_game_date = availability.primary_game_date or availability.available_date
            evaluated_hosts_by_date.setdefault(availability_game_date, []).append(host.name)
            generation_reason = _availability_generation_reason(db, host, availability, demand_by_availability_id.get(availability.id))
            generation_reasons_by_date.setdefault(availability_game_date, []).append(generation_reason)
            diagnostic = selected_host_diagnostic_by_availability_id.get(availability.id)
            if diagnostic is not None:
                diagnostic['generated_slots_by_size'] = dict(slots_created_by_size_by_availability.get(availability.id, _empty_field_size_counts()))
            if int(slots_created_by_availability.get(availability.id, 0) or 0) == 0:
                if diagnostic is not None:
                    diagnostic['zero_slot_reason'] = generation_reason
                generation_reasons_by_date.setdefault(availability_game_date, []).append(
                    f'Selected host has availability but generated zero slots: {host.name}, {availability_game_date}, {generation_reason}'
                )
    db.flush()

    validation_errors: list[str] = []
    validation_rows: list[dict[str, object]] = []
    org_names_for_capacity = {org.id: org.name or str(org.id) for org in db.query(Organization).filter(Organization.is_active.is_(True)).all()}
    for week in weeks:
        game_date = _week_game_date(week)
        if not game_date or not _is_regular_season_week(week):
            continue
        slot_counts = {FIELD_SIZE_SMALL: 0, FIELD_SIZE_MEDIUM: 0, FIELD_SIZE_LARGE: 0}
        for field_type, count in db.query(GameSlot.field_type, func.count(GameSlot.id)).filter(
            GameSlot.season_id == week.season_id,
            GameSlot.week_id == week.id,
            GameSlot.slot_date == game_date,
        ).group_by(GameSlot.field_type).all():
            size = _normalize_field_size(field_type)
            if size in slot_counts:
                slot_counts[size] += int(count or 0)
        missing_sizes = [
            size for size in FIELD_SIZE_ORDER
            if int(required_games_by_size.get(size, 0) or 0) > 0 and int(slot_counts.get(size, 0) or 0) == 0
        ]
        community_capacity_by_size: dict[str, dict[str, int]] = {}
        location_capacity_by_community: dict[str, list[dict[str, object]]] = {}
        capacity_rows = db.query(HostLocation.organization_id, HostLocation.name, GameSlot.field_type, func.count(GameSlot.id)).select_from(GameSlot).join(
            HostLocation, HostLocation.id == GameSlot.host_location_id
        ).filter(GameSlot.season_id == week.season_id, GameSlot.week_id == week.id, GameSlot.slot_date == game_date).group_by(HostLocation.organization_id, HostLocation.name, GameSlot.field_type).all()
        for org_id, host_name, field_type, count in capacity_rows:
            community_name = org_names_for_capacity.get(org_id, str(org_id))
            size = _normalize_field_size(field_type) or str(field_type or 'UNKNOWN')
            community_capacity_by_size.setdefault(community_name, _empty_field_size_counts())
            if size in community_capacity_by_size[community_name]:
                community_capacity_by_size[community_name][size] += int(count or 0)
            location_rows = location_capacity_by_community.setdefault(community_name, [])
            location_row = next((row for row in location_rows if row.get('host_location') == host_name), None)
            if not location_row:
                location_row = {'host_location': host_name, 'capacity_by_size': _empty_field_size_counts()}
                location_rows.append(location_row)
            if size in location_row['capacity_by_size']:
                location_row['capacity_by_size'][size] += int(count or 0)
        selected_hosts_for_date = sorted(set(evaluated_hosts_by_date.get(game_date, [])))
        zero_slot_reason = None
        if sum(int(slot_counts.get(size, 0) or 0) for size in FIELD_SIZE_ORDER) == 0:
            zero_slot_reason = 'No selected host availability was evaluated for this regular-season week.'
            if selected_hosts_for_date:
                zero_slot_reason = 'Selected hosts were evaluated but generated zero slots; review generation_reasons for capacity/layout details.'
        demand_summary = dict(demand_summary_by_date.get(game_date, {}))
        demand_summary.setdefault('active_divisions_included', active_division_demand_rows)
        demand_summary.setdefault('league_wide_demand_by_size', dict(required_games_by_size))
        demand_summary['week'] = week.week_number
        demand_summary['date'] = str(game_date)
        demand_summary['status'] = _week_date_type(week)
        selected_host_diagnostics = selected_host_diagnostics_by_date.get(game_date, [])
        selected_host_count = len(selected_host_diagnostics)
        valid_selected_host_count = sum(1 for item in selected_host_diagnostics if item.get('hosting_availability_id'))
        skipped_host_rows = [
            {
                'host_location_id': item.get('host_location_id'),
                'host_location_name': item.get('host_location_name'),
                'reason_skipped': item.get('reason_skipped') or item.get('zero_slot_reason'),
                'hosting_availability_id': item.get('hosting_availability_id'),
            }
            for item in selected_host_diagnostics
            if item.get('skipped') or not item.get('hosting_availability_id')
        ]
        host_plan_data_integrity_summary = {
            'diagnostic_label': 'Host Plan Data Integrity Summary',
            'selected_host_count': selected_host_count,
            'selected_hosts_with_valid_availability': valid_selected_host_count,
            'selected_hosts_missing_availability': selected_host_count - valid_selected_host_count,
            'skipped_hosts': skipped_host_rows,
        }
        demand_summary['selected_hosts'] = selected_hosts_for_date
        demand_summary['generated_slots_by_size'] = dict(slot_counts)
        demand_summary['selected_host_generated_slot_diagnostics'] = selected_host_diagnostics
        demand_summary['host_plan_data_integrity_summary'] = host_plan_data_integrity_summary
        demand_summary['zero_slot_reason'] = zero_slot_reason
        row = {
            'week': week.week_number,
            'week_start_date': str(game_date),
            'date': str(game_date),
            'status': _week_date_type(week),
            'required_games_by_size': dict(required_games_by_size),
            'league_wide_demand_by_size': dict(required_games_by_size),
            'active_divisions_included': active_division_demand_rows,
            'generated_slots_by_size': dict(slot_counts),
            'community_capacity_by_field_size': community_capacity_by_size,
            'host_location_capacity_by_community': location_capacity_by_community,
            'missing_field_sizes': missing_sizes,
            'selected_hosts': selected_hosts_for_date,
            'host_locations_evaluated': selected_hosts_for_date,
            'generation_reasons': generation_reasons_by_date.get(game_date, []),
            'selected_host_generated_slot_diagnostics': selected_host_diagnostics,
            'host_plan_data_integrity_summary': host_plan_data_integrity_summary,
            'zero_slot_reason': zero_slot_reason,
            'generated_slots_demand_summary': demand_summary,
        }
        validation_rows.append(row)
        for size in missing_sizes:
            validation_errors.append(
                f'Week {week.week_number} ({game_date}) requires {required_games_by_size[size]} {size} game(s) but generated 0 {size} slot(s). '
                f'Host locations evaluated: {", ".join(row["host_locations_evaluated"]) or "none"}. '
                f'Reasons: {" | ".join(row["generation_reasons"]) or "No hosting availability was evaluated for this week."}'
            )
    return {
        'generation_results': generation_results,
        'validation_rows': validation_rows,
        'validation_errors': validation_errors,
    }


def _game_required_field_type(game: Game | None) -> str | None:
    """Return required field type for a game based on division settings."""
    if not game:
        return None
    division = getattr(game, 'division', None)
    if not division:
        home_team = getattr(game, 'home_team', None)
        division = getattr(home_team, 'division', None) if home_team else None
    if not division:
        away_team = getattr(game, 'away_team', None)
        division = getattr(away_team, 'division', None) if away_team else None
    if not division:
        return None
    required_type = _required_field_type_for_division(division)
    return required_type.strip().upper() if required_type else None


def _slot_field_type(slot: GameSlot | None) -> str | None:
    """Return actual field type for a slot from best available field references."""
    if not slot:
        return None
    slot_type = getattr(slot, 'field_type', None)
    if slot_type:
        return str(slot_type).strip().upper()
    field_instance = getattr(slot, 'field_instance', None)
    if field_instance:
        instance_type = getattr(field_instance, 'field_type', None)
        if instance_type:
            return str(instance_type).strip().upper()
        area = getattr(field_instance, 'physical_field_area', None)
        if area:
            area_type = getattr(area, 'field_type', None)
            if area_type:
                return str(area_type).strip().upper()
        config = getattr(field_instance, 'field_config_option', None)
        if config:
            config_type = getattr(config, 'field_type', None)
            if config_type:
                return str(config_type).strip().upper()
    return None


def _enforce_host_owner_home_team(
    home_team: Team | None,
    away_team: Team | None,
    host_location: HostLocation | None,
) -> tuple[Team | None, Team | None, str | None]:
    if not home_team or not away_team or not host_location or not host_location.organization_id:
        return home_team, away_team, None
    host_org_id = host_location.organization_id
    home_matches = home_team.organization_id == host_org_id
    away_matches = away_team.organization_id == host_org_id
    if home_matches == away_matches:
        return home_team, away_team, None
    if away_matches and not home_matches:
        reason = f'Home/away adjusted because {away_team.organization.name if away_team.organization else "host community"} owns {host_location.name}.'
        return away_team, home_team, reason
    return home_team, away_team, None


def _primary_host_by_org(db: Session) -> dict[uuid.UUID, uuid.UUID]:
    """Return organization -> primary host-location mapping."""
    active_hosts = db.query(HostLocation).filter(HostLocation.is_active.is_(True)).all()
    if not active_hosts:
        return {}
    host_ids = [host.id for host in active_hosts]
    game_counts_by_host: dict[uuid.UUID, int] = {}
    for host_id, game_count in db.query(Field.host_location_id, func.count(Game.id)).join(
        Game, Game.field_id == Field.id
    ).filter(
        Field.host_location_id.in_(host_ids)
    ).group_by(Field.host_location_id).all():
        if host_id:
            game_counts_by_host[host_id] = int(game_count or 0)
    hosts_by_org: dict[uuid.UUID, list[HostLocation]] = {}
    for host in active_hosts:
        if host.organization_id:
            hosts_by_org.setdefault(host.organization_id, []).append(host)
    primary_by_org: dict[uuid.UUID, uuid.UUID] = {}
    for org_id, org_hosts in hosts_by_org.items():
        ranked_hosts = sorted(
            org_hosts,
            key=lambda host: (
                1 if bool(getattr(host, 'is_primary', False) or getattr(host, 'is_default', False) or getattr(host, 'preferred', False)) else 0,
                game_counts_by_host.get(host.id, 0),
            ),
            reverse=True,
        )
        if ranked_hosts:
            primary_by_org[org_id] = ranked_hosts[0].id
    return primary_by_org


def repair_same_community_home_fields(db: Session, season_id: uuid.UUID) -> dict[str, object]:
    logger.info("[REPAIR] Same-community home-field repair started")
    teams = db.query(Team).filter(Team.is_active.is_(True)).all()
    teams_by_id = {t.id: t for t in teams}
    primary_host_by_org = _primary_host_by_org(db)
    host_locations = db.query(HostLocation).filter(HostLocation.is_active.is_(True)).all()
    host_ids_by_org: dict[str, set[str]] = {}
    for host in host_locations:
        if host.id and host.organization_id:
            host_ids_by_org.setdefault(str(host.organization_id), set()).add(str(host.id))
    if not primary_host_by_org:
        logger.warning("[REPAIR] No primary host mappings found")
        return {
            'ran': True,
            'violations_found': 0,
            'swaps_attempted': 0,
            'swaps_committed': 0,
            'unrepaired': [],
        }
    violations_found = 0
    swaps_attempted = 0
    swaps_committed = 0
    unrepaired: list[dict[str, object]] = []
    season_games = db.query(Game).join(Game.status).filter(Game.season_id == season_id, GameStatus.code != 'UNSCHEDULED').all()
    slots = db.query(GameSlot).filter(GameSlot.assigned_game_id.isnot(None)).all()
    slots_by_game_id = {str(s.assigned_game_id): s for s in slots if s.assigned_game_id}

    def _reason_note(game: Game, reason: str) -> None:
        unrepaired.append({'game_id': str(game.id), 'reason': reason})

    for game in season_games:
        slot = slots_by_game_id.get(str(game.id))
        if not slot or not slot.host_location_id:
            continue
        home_team = teams_by_id.get(game.home_team_id)
        away_team = teams_by_id.get(game.away_team_id)
        if not home_team or not away_team:
            continue
        if not home_team.organization_id or home_team.organization_id != away_team.organization_id:
            continue
        preferred_home_hosts = host_ids_by_org.get(str(home_team.organization_id), set())
        if not preferred_home_hosts:
            violations_found += 1
            _reason_note(game, 'no compatible home slot')
            continue
        if str(slot.host_location_id) in preferred_home_hosts:
            continue
        violations_found += 1
        candidate_home_slots = db.query(GameSlot).filter(
            GameSlot.slot_date == slot.slot_date,
        ).all()
        candidate_home_slots = [s for s in candidate_home_slots if s.host_location_id and str(s.host_location_id) in preferred_home_hosts]
        open_home_slot = next((s for s in candidate_home_slots if s.assigned_game_id is None and s.status == 'OPEN'), None)
        if open_home_slot:
            swaps_attempted += 1
            slot.assigned_game_id = None
            slot.status = 'OPEN'
            open_home_slot.assigned_game_id = game.id
            open_home_slot.status = 'BOOKED'
            game.game_date = open_home_slot.slot_date
            game.kickoff_time = open_home_slot.start_time
            db.flush()
            slots_by_game_id[str(game.id)] = open_home_slot
            swaps_committed += 1
            continue
        swap_candidates = [s for s in candidate_home_slots if s.assigned_game_id and str(s.assigned_game_id) in {str(g.id) for g in season_games}]
        if not swap_candidates:
            _reason_note(game, 'no compatible home slot')
            continue
        committed = False
        for candidate_slot in swap_candidates:
            other_game = next((g for g in season_games if str(g.id) == str(candidate_slot.assigned_game_id)), None)
            if not other_game:
                continue
            swaps_attempted += 1
            other_home = teams_by_id.get(other_game.home_team_id)
            other_away = teams_by_id.get(other_game.away_team_id)
            if not other_home or not other_away:
                _reason_note(game, 'swap would cause team overlap')
                continue
            if slot.field_type and candidate_slot.field_type and slot.field_type != candidate_slot.field_type:
                _reason_note(game, 'swap would violate field type')
                continue
            same_week_games = [g for g in season_games if g.week_id == game.week_id]
            hosts_before = {str(slots_by_game_id.get(str(g.id)).host_location_id) for g in same_week_games if slots_by_game_id.get(str(g.id))}
            hosts_after = set(hosts_before)
            hosts_after.discard(str(slot.host_location_id)); hosts_after.discard(str(candidate_slot.host_location_id))
            hosts_after.add(str(slot.host_location_id)); hosts_after.add(str(candidate_slot.host_location_id))
            if len(hosts_after) > max(len(hosts_before), 2):
                _reason_note(game, 'swap would worsen two-location rule')
                continue
            # conservative placeholder checks for constraints not explicitly modeled in persisted records
            if game.kickoff_time == other_game.kickoff_time and game.week_id == other_game.week_id:
                _reason_note(game, 'swap would cause team overlap')
                continue
            game.kickoff_time, other_game.kickoff_time = candidate_slot.start_time, slot.start_time
            game.game_date, other_game.game_date = candidate_slot.slot_date, slot.slot_date
            slot.assigned_game_id, candidate_slot.assigned_game_id = other_game.id, game.id
            db.flush()
            slots_by_game_id[str(game.id)] = candidate_slot
            slots_by_game_id[str(other_game.id)] = slot
            swaps_committed += 1
            committed = True
            break
        if not committed and not any(u.get('game_id') == str(game.id) for u in unrepaired):
            _reason_note(game, 'no compatible home slot')

    violations_remaining = len(unrepaired)
    logger.info("[REPAIR] violations_found=%s", violations_found)
    logger.info("[REPAIR] swaps_attempted=%s", swaps_attempted)
    logger.info("[REPAIR] swaps_committed=%s", swaps_committed)
    logger.info("[REPAIR] violations_remaining=%s", violations_remaining)
    return {
        'ran': True,
        'violations_found': violations_found,
        'swaps_attempted': swaps_attempted,
        'swaps_committed': swaps_committed,
        'violations_remaining': violations_remaining,
        'unrepaired': unrepaired,
    }


def run_post_schedule_repair_pass(db: Session, season_id: uuid.UUID, *, optimize_same_community_home: bool = True, repair_double_headers: bool = True, reduce_repeat_matchups: bool = False, preserve_two_location_limit: bool = True) -> dict[str, object]:
    """Final repair pass for a fully-built season schedule.

    Order of operations is intentional:
      1) double-header adjacency/location
      2) same-community primary-home host placement
      3) post-repair validation diagnostics
    """
    teams = db.query(Team).filter(Team.is_active.is_(True)).all()
    teams_by_id = {t.id: t for t in teams}
    primary_host_by_org = _primary_host_by_org(db)
    scheduled_games = db.query(Game).join(Game.status).filter(
        Game.season_id == season_id,
        GameStatus.code != 'UNSCHEDULED',
    ).all()
    scheduled_game_ids = {g.id for g in scheduled_games}
    slots = db.query(GameSlot).filter(
        GameSlot.assigned_game_id.isnot(None),
    ).all()
    slots_by_game_id = {s.assigned_game_id: s for s in slots if s.assigned_game_id in scheduled_game_ids}
    pre_repair_snapshot: list[dict[str, object]] = [
        {'game_id': g.id, 'date': g.game_date, 'time': g.kickoff_time, 'slot': slots_by_game_id.get(g.id)}
        for g in scheduled_games
    ]

    base_team_counts: dict[uuid.UUID, int] = {}
    for g in scheduled_games:
        base_team_counts[g.home_team_id] = base_team_counts.get(g.home_team_id, 0) + 1
        base_team_counts[g.away_team_id] = base_team_counts.get(g.away_team_id, 0) + 1

    def _time_minutes(t: time | None) -> int:
        return (t.hour * 60 + t.minute) if t else -1

    def _adjacent(a: time | None, b: time | None) -> bool:
        if not a or not b:
            return False
        return abs(_time_minutes(a) - _time_minutes(b)) == 60

    def validate_schedule_integrity(games: list[Game], *, enforce_double_header_preference: bool = False) -> dict[str, object]:
        errors: list[str] = []
        warnings: list[str] = []
        team_time_slots: dict[tuple[uuid.UUID, date, time], str] = {}
        field_time_slots: dict[tuple[uuid.UUID | None, date, time], str] = {}
        game_ids_seen: set[uuid.UUID] = set()
        slot_keys_seen: set[tuple[date, time, uuid.UUID | None, uuid.UUID | None]] = set()

        for g in games:
            if g.id in game_ids_seen:
                errors.append(f'duplicate game id {g.id}')
            game_ids_seen.add(g.id)
            if not g.home_team_id or not g.away_team_id:
                errors.append(f'game {g.id} has missing teams')
            slot = slots_by_game_id.get(g.id)
            if not slot:
                continue
            if slot.assigned_game_id != g.id:
                errors.append(f'game {g.id} has inconsistent slot assignment')
                continue
            required_type = _game_required_field_type(g)
            actual_type = _slot_field_type(slot)
            if required_type and actual_type and required_type != actual_type:
                errors.append(f'game {g.id} has invalid field type assignment required={required_type} actual={actual_type}')
            elif not required_type or not actual_type:
                warnings.append(f'Unable to determine field type for game/slot game_id={g.id} slot_id={slot.id}')
            if not g.game_date or not g.kickoff_time:
                errors.append(f'game {g.id} missing date/time')
                continue
            for tid in (g.home_team_id, g.away_team_id):
                team_key = (tid, g.game_date, g.kickoff_time)
                if team_key in team_time_slots:
                    errors.append(
                        f'team overlap: team {tid} scheduled at {g.game_date} {g.kickoff_time} in games {team_time_slots[team_key]} and {g.id}'
                    )
                else:
                    team_time_slots[team_key] = str(g.id)
            field_key = (slot.field_instance_id, g.game_date, g.kickoff_time)
            if field_key in field_time_slots:
                errors.append(
                    f'field overlap: field {slot.field_instance_id} scheduled at {g.game_date} {g.kickoff_time} in games {field_time_slots[field_key]} and {g.id}'
                )
            else:
                field_time_slots[field_key] = str(g.id)
            slot_key = (slot.slot_date, slot.start_time, slot.field_instance_id, slot.host_location_id)
            if slot_key in slot_keys_seen:
                errors.append(f'duplicate slot assignment detected for game {g.id}')
            slot_keys_seen.add(slot_key)

        weekly_by_team: dict[tuple[uuid.UUID, uuid.UUID], list[GameSlot]] = {}
        for g in games:
            slot = slots_by_game_id.get(g.id)
            if not slot:
                continue
            for tid in (g.home_team_id, g.away_team_id):
                weekly_by_team.setdefault((tid, g.week_id), []).append(slot)
        for (tid, _), team_slots in weekly_by_team.items():
            if len(team_slots) != 2:
                continue
            a, b = team_slots[0], team_slots[1]
            # Hard rule: never same start time for a double-header team.
            if a.slot_date == b.slot_date and a.start_time and b.start_time and a.start_time == b.start_time:
                errors.append(f'double-header overlap: team {tid} has two games at the same time')
            if enforce_double_header_preference:
                if not _adjacent(a.start_time, b.start_time):
                    errors.append(f'double-header spacing violation: team {tid} not in adjacent slots')
                if a.host_location_id and b.host_location_id and a.host_location_id != b.host_location_id:
                    errors.append(f'double-header location violation: team {tid} spans different host locations')

        return {'valid': not errors, 'errors': errors, 'warnings': warnings}

    def _collect_weekly_pairs() -> list[tuple[uuid.UUID, uuid.UUID, list[Game]]]:
        by_key: dict[tuple[uuid.UUID, uuid.UUID], list[Game]] = {}
        for g in scheduled_games:
            for tid in (g.home_team_id, g.away_team_id):
                by_key.setdefault((tid, g.week_id), []).append(g)
        return [(tid, wk, games) for (tid, wk), games in by_key.items() if len(games) == 2]

    def _snapshot_for_rollback(g1: Game, s1: GameSlot, g2: Game, s2: GameSlot) -> dict[str, object]:
        return {
            'g1_date': g1.game_date, 'g1_time': g1.kickoff_time, 's1_game': s1.assigned_game_id, 's1_status': s1.status,
            'g2_date': g2.game_date, 'g2_time': g2.kickoff_time, 's2_game': s2.assigned_game_id, 's2_status': s2.status,
        }

    def _rollback(snapshot: dict[str, object], g1: Game, s1: GameSlot, g2: Game, s2: GameSlot) -> None:
        g1.game_date = snapshot['g1_date']; g1.kickoff_time = snapshot['g1_time']
        s1.assigned_game_id = snapshot['s1_game']; s1.status = snapshot['s1_status']
        g2.game_date = snapshot['g2_date']; g2.kickoff_time = snapshot['g2_time']
        s2.assigned_game_id = snapshot['s2_game']; s2.status = snapshot['s2_status']
        db.flush()

    dh_found = 0
    dh_attempted = 0
    dh_committed = 0
    dh_remaining: list[dict[str, object]] = []
    dh_unrepaired: list[dict[str, object]] = []
    repair_rejected_reasons: list[str] = []
    for team_id, week_id, games in _collect_weekly_pairs():
        if not repair_double_headers:
            continue
        g1, g2 = games[0], games[1]
        s1 = slots_by_game_id.get(g1.id)
        s2 = slots_by_game_id.get(g2.id)
        if not s1 or not s2:
            continue
        same_loc = s1.host_location_id and s1.host_location_id == s2.host_location_id
        is_adj = _adjacent(s1.start_time, s2.start_time)
        if same_loc and is_adj:
            continue
        dh_found += 1
        committed = False
        if s1.host_location_id and s2.host_location_id and s1.host_location_id != s2.host_location_id:
            dh_unrepaired.append({'team_id': str(team_id), 'week_id': str(week_id), 'reason': 'double-header spans different locations; no safe same-location swap found'})
            continue
        base_slot = s1 if s1.host_location_id else s2
        other_slot = s2 if base_slot.id == s1.id else s1
        host_id = base_slot.host_location_id
        if not host_id:
            dh_unrepaired.append({'team_id': str(team_id), 'week_id': str(week_id), 'reason': 'missing host location data'})
            continue
        open_adjacent = db.query(GameSlot).filter(
            GameSlot.host_location_id == host_id,
            GameSlot.slot_date == base_slot.slot_date,
            GameSlot.field_type == base_slot.field_type,
            GameSlot.assigned_game_id.is_(None),
            GameSlot.status == 'OPEN',
        ).all()
        target = next((s for s in open_adjacent if _adjacent(base_slot.start_time, s.start_time)), None)
        if target:
            dh_attempted += 1
            snapshot = {
                'from_slot_game': other_slot.assigned_game_id,
                'from_slot_status': other_slot.status,
                'to_slot_game': target.assigned_game_id,
                'to_slot_status': target.status,
                'moving_game_date': (g2 if other_slot.id == s2.id else g1).game_date,
                'moving_game_time': (g2 if other_slot.id == s2.id else g1).kickoff_time,
            }
            try:
                target.assigned_game_id = other_slot.assigned_game_id
                target.status = 'BOOKED'
                other_slot.assigned_game_id = None
                other_slot.status = 'OPEN'
                moving_game = g2 if other_slot.id == s2.id else g1
                moving_game.game_date = target.slot_date
                moving_game.kickoff_time = target.start_time
                db.flush()
                slots_by_game_id[moving_game.id] = target
                validation = validate_schedule_integrity(scheduled_games, enforce_double_header_preference=False)
                if validation['valid']:
                    committed = True
                    dh_committed += 1
                else:
                    other_slot.assigned_game_id = snapshot['from_slot_game']
                    other_slot.status = snapshot['from_slot_status']
                    target.assigned_game_id = snapshot['to_slot_game']
                    target.status = snapshot['to_slot_status']
                    moving_game.game_date = snapshot['moving_game_date']
                    moving_game.kickoff_time = snapshot['moving_game_time']
                    slots_by_game_id[moving_game.id] = other_slot
                    db.flush()
                    reasons = validation['errors']
                    repair_rejected_reasons.extend(reasons)
                    dh_unrepaired.append({'team_id': str(team_id), 'week_id': str(week_id), 'reason': 'rollback: integrity validation failed', 'details': reasons[:5]})
            except Exception:
                db.rollback()
                dh_unrepaired.append({'team_id': str(team_id), 'week_id': str(week_id), 'reason': 'rollback: failed committing adjacent-slot move'})
        if not committed:
            dh_remaining.append({'team_id': str(team_id), 'team_name': teams_by_id.get(team_id).name if team_id in teams_by_id else str(team_id), 'week_id': str(week_id)})

    same_found = 0
    same_attempted = 0
    same_committed = 0
    same_remaining: list[dict[str, object]] = []
    same_unrepaired: list[dict[str, object]] = []
    for g in scheduled_games:
        if not optimize_same_community_home:
            continue
        slot = slots_by_game_id.get(g.id)
        if not slot or not slot.host_location_id:
            continue
        ht = teams_by_id.get(g.home_team_id)
        at = teams_by_id.get(g.away_team_id)
        if not ht or not at or not ht.organization_id or ht.organization_id != at.organization_id:
            continue
        preferred = primary_host_by_org.get(ht.organization_id)
        if not preferred or slot.host_location_id == preferred:
            continue
        same_found += 1
        open_home = db.query(GameSlot).filter(
            GameSlot.slot_date == slot.slot_date,
            GameSlot.host_location_id == preferred,
            GameSlot.field_type == slot.field_type,
            GameSlot.assigned_game_id.is_(None),
            GameSlot.status == 'OPEN',
        ).order_by(GameSlot.start_time.asc()).all()
        target = open_home[0] if open_home else None
        if not target:
            same_unrepaired.append({'game_id': str(g.id), 'reason': 'no compatible open preferred-home slot on same date'})
            same_remaining.append({'game_id': str(g.id)})
            continue
        same_attempted += 1
        snapshot = {
            'from_slot_game': slot.assigned_game_id,
            'from_slot_status': slot.status,
            'to_slot_game': target.assigned_game_id,
            'to_slot_status': target.status,
            'game_date': g.game_date,
            'game_time': g.kickoff_time,
        }
        try:
            slot.assigned_game_id = None
            slot.status = 'OPEN'
            target.assigned_game_id = g.id
            target.status = 'BOOKED'
            g.game_date = target.slot_date
            g.kickoff_time = target.start_time
            db.flush()
            slots_by_game_id[g.id] = target
            validation = validate_schedule_integrity(scheduled_games, enforce_double_header_preference=False)
            if validation['valid']:
                same_committed += 1
            else:
                slot.assigned_game_id = snapshot['from_slot_game']
                slot.status = snapshot['from_slot_status']
                target.assigned_game_id = snapshot['to_slot_game']
                target.status = snapshot['to_slot_status']
                g.game_date = snapshot['game_date']
                g.kickoff_time = snapshot['game_time']
                slots_by_game_id[g.id] = slot
                db.flush()
                reasons = validation['errors']
                repair_rejected_reasons.extend(reasons)
                same_unrepaired.append({'game_id': str(g.id), 'reason': 'rollback: repair caused hard validation failure', 'details': reasons[:5]})
                same_remaining.append({'game_id': str(g.id)})
        except Exception:
            db.rollback()
            same_unrepaired.append({'game_id': str(g.id), 'reason': 'rollback: repair caused validation/constraint failure'})
            same_remaining.append({'game_id': str(g.id)})

    db.flush()
    post_team_counts: dict[uuid.UUID, int] = {}
    for g in scheduled_games:
        post_team_counts[g.home_team_id] = post_team_counts.get(g.home_team_id, 0) + 1
        post_team_counts[g.away_team_id] = post_team_counts.get(g.away_team_id, 0) + 1
    count_changed = base_team_counts != post_team_counts
    if count_changed:
        same_unrepaired.append({'reason': 'team game counts changed unexpectedly during repair pass'})
        repair_rejected_reasons.append('team game counts changed unexpectedly during repair pass')

    final_validation = validate_schedule_integrity(scheduled_games, enforce_double_header_preference=False)
    rollback_triggered = count_changed or (not final_validation['valid'])
    if rollback_triggered:
        for snap in pre_repair_snapshot:
            game = next((g for g in scheduled_games if g.id == snap['game_id']), None)
            if not game:
                continue
            game.game_date = snap['date']
            game.kickoff_time = snap['time']
            slot = snap['slot']
            if slot is None:
                continue
            current_slot = slots_by_game_id.get(game.id)
            if current_slot and current_slot.id != slot.id:
                current_slot.assigned_game_id = None
                current_slot.status = 'OPEN'
            slot.assigned_game_id = game.id
            slot.status = 'BOOKED'
            slots_by_game_id[game.id] = slot
        db.flush()
        if not final_validation['valid']:
            repair_rejected_reasons.extend(final_validation['errors'])
        same_unrepaired.append({'reason': 'Repair pass rolled back due to hard validation failure.'})

    summary = {
        'games_reviewed': len(scheduled_games),
        'same_community_violations_found': same_found,
        'same_community_repairs_proposed': same_attempted,
        'same_community_repairs_committed': same_committed,
        'double_header_violations_found': dh_found,
        'double_header_repairs_proposed': dh_attempted,
        'double_header_repairs_committed': dh_committed,
        'repairs_rejected': (dh_attempted + same_attempted) - (dh_committed + same_committed),
    }
    return {
        'ran': True,
        'summary': summary,
        'proposed_changes': [],
        'rejected_changes': [],
        'remaining_violations': (dh_remaining + same_remaining),
        'post_schedule_repair': {
            'repairs_attempted': dh_attempted + same_attempted,
            'repairs_committed': dh_committed + same_committed,
            'repairs_rejected': (dh_attempted + same_attempted) - (dh_committed + same_committed),
            'rollback_triggered': rollback_triggered,
            'rejected_reasons': repair_rejected_reasons,
        },
        'double_header': {
            'violations_found': dh_found,
            'repairs_attempted': dh_attempted,
            'repairs_committed': dh_committed,
            'violations_remaining': dh_remaining,
            'unrepaired_reasons': dh_unrepaired,
        },
        'same_community_home': {
            'violations_found': same_found,
            'repairs_attempted': same_attempted,
            'repairs_committed': same_committed,
            'violations_remaining': same_remaining,
            'unrepaired_reasons': same_unrepaired,
        },
        'warnings': final_validation.get('warnings') or [],
    }


def _season_schedule_is_published(season: Season | None) -> bool:
    return str(getattr(season, 'schedule_status', '') or '').lower() == 'published'


def _get_schedule_scope_season(db: Session, season_id: uuid.UUID | None = None) -> Season | None:
    if season_id:
        return db.query(Season).filter(Season.id == season_id).first()
    return db.query(Season).filter(Season.is_active.is_(True)).order_by(Season.start_date.desc()).first()


def _scheduled_games_filters(season_id: uuid.UUID | None = None, **filters) -> dict:
    shared_filters = {k: v for k, v in filters.items() if v not in (None, '')}
    if season_id:
        shared_filters['season_id'] = season_id
    return shared_filters


def _serialize_schedule_filters(filters: dict) -> dict:
    return {key: (value.isoformat() if hasattr(value, 'isoformat') else str(value)) for key, value in filters.items()}


def _schedule_management_rows(db: Session, filters: dict | None = None, organization_filter_any_team: bool = False):
    filters = filters or {}
    home = aliased(Team)
    away = aliased(Team)
    q = db.query(Game, GameSlot, FieldInstance, HostLocation, home, away, Division, Organization, GameStatus).join(Game.status).join(home, Game.home_team_id == home.id).join(away, Game.away_team_id == away.id).join(Division, home.division_id == Division.id).join(Organization, home.organization_id == Organization.id).outerjoin(GameSlot, GameSlot.assigned_game_id == Game.id).outerjoin(FieldInstance, FieldInstance.id == GameSlot.field_instance_id).outerjoin(HostLocation, HostLocation.id == GameSlot.host_location_id)
    q = q.filter(func.lower(GameStatus.code) != 'unscheduled')
    if filters.get('date'): q = q.filter(Game.game_date == filters['date'])
    if filters.get('division_id'): q = q.filter(Division.id == filters['division_id'])
    if filters.get('organization_id'):
        if organization_filter_any_team:
            q = q.filter(or_(home.organization_id == filters['organization_id'], away.organization_id == filters['organization_id']))
        else:
            q = q.filter(home.organization_id == filters['organization_id'])
    if filters.get('host_location_id'): q = q.filter(HostLocation.id == filters['host_location_id'])
    if filters.get('field_type'): q = q.filter(GameSlot.field_type == filters['field_type'])
    if filters.get('field_id'): q = q.filter(FieldInstance.id == filters['field_id'])
    if filters.get('team_id'): q = q.filter((home.id == filters['team_id']) | (away.id == filters['team_id']))
    if filters.get('week_id'): q = q.filter(Game.week_id == filters['week_id'])
    if filters.get('status_code'): q = q.filter(func.lower(GameStatus.code) == str(filters['status_code']).strip().lower())
    if filters.get('season_id'): q = q.filter(Game.season_id == filters['season_id'])
    return q.order_by(Game.game_date, Game.kickoff_time).all()


def get_scheduled_games_for_season(db: Session, season_id: uuid.UUID | None, filters: dict | None = None, organization_filter_any_team: bool = False):
    shared_filters = dict(filters or {})
    if season_id:
        shared_filters['season_id'] = season_id
    return _schedule_management_rows(db, shared_filters, organization_filter_any_team=organization_filter_any_team)


def _public_game_read_from_schedule_row(row) -> PublicGameRead:
    g, slot, fi, host, home, away, div, org, status = row
    return PublicGameRead(
        id=g.id,
        game_date=g.game_date,
        kickoff_time=g.kickoff_time,
        host_location_id=host.id if host else None,
        host_location_name=host.name if host else '',
        field_id=fi.id if fi else None,
        field_name=fi.field_name if fi else '',
        field_type=slot.field_type if slot else None,
        organization_id=org.id,
        organization_name=org.name,
        division_id=div.id,
        division_name=div.name,
        week_id=g.week_id,
        week_number=(g.week.week_number if g.week else None),
        week_label=_week_label(g.week),
        date_type=_week_date_type(g.week),
        home_team_id=home.id,
        home_team_name=home.name,
        away_team_id=away.id,
        away_team_name=away.name,
        game_status_id=g.game_status_id,
        game_status_code=status.code,
        game_status_label=status.label,
    )


def _quality_status(ok: bool, warning: bool = False) -> str:
    if ok:
        return 'OK'
    if warning:
        return 'Warning'
    return 'Issue'


def _empty_quality_report() -> dict:
    return {
        'games_per_team': [],
        'repeat_matchups': [],
        'home_away_balance': [],
        'time_of_day_balance': [],
        'host_community_priority': [],
        'double_headers': [],
        'unscheduled_teams': [],
        'field_utilization': [],
    }



@router.get('/schedule-management/publish-diagnostics', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def schedule_publish_diagnostics(season_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    if season_id:
        season = db.query(Season).filter(Season.id == season_id).first()
    else:
        season = db.query(Season).filter(Season.is_active.is_(True)).order_by(Season.start_date.desc()).first()
    if not season:
        raise HTTPException(404, 'No season found')

    counts = dict(
        db.query(func.lower(GameStatus.code), func.count(Game.id))
        .join(Game, Game.game_status_id == GameStatus.id)
        .filter(Game.season_id == season.id)
        .group_by(func.lower(GameStatus.code))
        .all()
    )
    total = int(sum(counts.values()))
    schedule_is_published = str(season.schedule_status or '').lower() == 'published'
    published = total if schedule_is_published else int(counts.get('published', 0))
    archived = int(counts.get('archived', 0))
    draft = 0 if schedule_is_published else max(total - published - archived, 0)
    return {
        'season_id': str(season.id),
        'season_name': season.name,
        'schedule_status': season.schedule_status,
        'total_scheduled_games': total,
        'published_games': published,
        'draft_games': draft,
        'archived_games': archived,
    }

@router.get('/schedule-management/quality-report', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def schedule_quality_report(division_id: uuid.UUID | None = None, organization_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    try:
        season = db.query(Season).filter(Season.is_active.is_(True)).order_by(Season.start_date.desc()).first()
        if not season:
            raise HTTPException(404, 'No season found')
        quality = build_schedule_quality_report(db, season.id)
        filters = {'division_id': division_id, 'organization_id': organization_id}
        rows = _schedule_management_rows(db, filters)
        teams_query = db.query(Team, Division, Organization).join(Team.division).join(Team.organization).filter(Team.is_active.is_(True))
        if division_id:
            teams_query = teams_query.filter(Team.division_id == division_id)
        if organization_id:
            teams_query = teams_query.filter(Team.organization_id == organization_id)
        teams = teams_query.order_by(Division.sort_order, Division.name, Team.name).all()

        team_stats: dict[uuid.UUID, dict] = {}
        division_totals: dict[uuid.UUID, list[int]] = {}
        for team, div, org in teams:
            team_stats[team.id] = {
                'team_id': str(team.id),
                'team_name': team.name,
                'division_id': str(div.id),
                'division_name': div.name,
                'organization_id': str(org.id),
                'organization_name': org.name,
                'games_scheduled': 0,
                'home_games': 0,
                'away_games': 0,
                'time_of_day': {'Morning': 0, 'Midday': 0, 'Afternoon': 0},
            }

        matchup_counts: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
        team_games_by_date: dict[tuple[uuid.UUID, date], list[dict]] = {}
        org_host_stats: dict[uuid.UUID, dict] = {}
        utilization: dict[tuple[str, date], dict] = {}

        for g, slot, fi, host, home, away, div, org, status in rows:
            for tid, is_home in ((home.id, True), (away.id, False)):
                if tid not in team_stats:
                    continue
                entry = team_stats[tid]
                entry['games_scheduled'] += 1
                if is_home:
                    entry['home_games'] += 1
                else:
                    entry['away_games'] += 1
                time_val = g.kickoff_time
                if time_val.hour < 11:
                    bucket = 'Morning'
                elif time_val.hour < 14:
                    bucket = 'Midday'
                else:
                    bucket = 'Afternoon'
                entry['time_of_day'][bucket] += 1
                team_games_by_date.setdefault((tid, g.game_date), []).append({'time': g.kickoff_time, 'slot_id': str(slot.id) if slot else None})

            key = tuple(sorted((home.id, away.id), key=lambda x: str(x)))
            matchup_counts[key] = matchup_counts.get(key, 0) + 1

            if host:
                utilization_key = (host.name, g.game_date)
                if utilization_key not in utilization:
                    total_slots = db.query(GameSlot).filter(GameSlot.host_location_id == host.id, GameSlot.slot_date == g.game_date).count()
                    utilization[utilization_key] = {'host_location_name': host.name, 'date': g.game_date.isoformat(), 'assigned_slots': 0, 'open_slots': total_slots, 'utilization_percent': 0.0}
                utilization[utilization_key]['assigned_slots'] += 1

        for team in team_stats.values():
            division_totals.setdefault(uuid.UUID(team['division_id']), []).append(team['games_scheduled'])

        games_per_team = []
        for team in team_stats.values():
            div_games = division_totals.get(uuid.UUID(team['division_id']), [0])
            avg = (sum(div_games) / len(div_games)) if div_games else 0
            delta = team['games_scheduled'] - avg
            row_status = _quality_status(abs(delta) <= 0.5, warning=abs(delta) <= 1.5)
            games_per_team.append({**team, 'division_average': round(avg, 2), 'status': row_status})

        repeat_matchups = []
        for (home_id, away_id), count in matchup_counts.items():
            if count > 1 and home_id in team_stats and away_id in team_stats:
                repeat_matchups.append({'team_a': team_stats[home_id]['team_name'], 'team_b': team_stats[away_id]['team_name'], 'games': count, 'status': _quality_status(False, warning=count == 2)})

        home_away_balance = []
        time_of_day_balance = []
        unscheduled = []
        for team in games_per_team:
            variance = abs(team['home_games'] - team['away_games'])
            home_away_balance.append({'team_name': team['team_name'], 'home_games': team['home_games'], 'away_games': team['away_games'], 'variance': variance, 'status': _quality_status(variance <= 1, warning=variance == 2)})
            total = team['games_scheduled']
            counts = team['time_of_day']
            max_bucket = max(counts.values()) if total else 0
            balance_status = _quality_status(total == 0 or max_bucket <= (total * 0.6), warning=total > 0 and max_bucket <= (total * 0.8))
            time_of_day_balance.append({'team_name': team['team_name'], 'morning': counts['Morning'], 'midday': counts['Midday'], 'afternoon': counts['Afternoon'], 'status': balance_status})
            if total == 0:
                unscheduled.append({'team_name': team['team_name'], 'division_name': team['division_name'], 'organization_name': team['organization_name'], 'status': 'Issue'})

        host_rows = db.query(HostingAvailability, HostLocation, Organization).join(Field, HostingAvailability.field_id == Field.id).join(HostLocation, Field.host_location_id == HostLocation.id).join(Organization, HostLocation.organization_id == Organization.id)
        if organization_id:
            host_rows = host_rows.filter(Organization.id == organization_id)
        host_rows = host_rows.all()
        for availability, host_location, host_org in host_rows:
            item = org_host_stats.setdefault(host_org.id, {'organization_name': host_org.name, 'host_dates': set(), 'games_when_hosting': 0, 'home_team_games': 0, 'total_team_games': 0})
            item['host_dates'].add(availability.available_date)

        for g, slot, fi, host, home, away, div, org, status in rows:
            for stat in org_host_stats.values():
                if g.game_date in stat['host_dates']:
                    stat['games_when_hosting'] += 1
                    if home.organization_id == next((k for k, v in org_host_stats.items() if v is stat), None):
                        stat['home_team_games'] += 1
                    stat['total_team_games'] += 1

        host_priority = []
        for org_id, stat in org_host_stats.items():
            pct = (stat['home_team_games'] / stat['total_team_games'] * 100) if stat['total_team_games'] else 0
            host_priority.append({'organization_name': stat['organization_name'], 'games_when_community_hosts': stat['games_when_hosting'], 'home_percentage_during_host_dates': round(pct, 1), 'status': _quality_status(pct >= 50, warning=pct >= 35)})

        double_headers = []
        for (team_id, game_date), entries in team_games_by_date.items():
            if len(entries) <= 1:
                continue
            entries = sorted(entries, key=lambda e: e['time'])
            back_to_back = True
            for prev, cur in zip(entries, entries[1:]):
                if (datetime.combine(date.today(), cur['time']) - datetime.combine(date.today(), prev['time'])).seconds > 7200:
                    back_to_back = False
            double_headers.append({'team_name': team_stats[team_id]['team_name'], 'date': game_date.isoformat(), 'games': len(entries), 'is_back_to_back': back_to_back, 'status': _quality_status(back_to_back, warning=False)})

        field_utilization = []
        for data in utilization.values():
            data['open_slots'] = max(data['open_slots'] - data['assigned_slots'], 0)
            total = data['assigned_slots'] + data['open_slots']
            data['utilization_percent'] = round((data['assigned_slots'] / total * 100) if total else 0, 1)
            data['status'] = _quality_status(data['utilization_percent'] >= 70, warning=data['utilization_percent'] >= 40)
            field_utilization.append(data)

        return {
            **quality,
            'games_per_team': games_per_team,
            'repeat_matchups': repeat_matchups,
            'home_away_balance': home_away_balance,
            'time_of_day_balance': time_of_day_balance,
            'host_community_priority': host_priority,
            'double_headers': double_headers,
            'unscheduled_teams': unscheduled,
            'field_utilization': field_utilization,
        }
    except Exception as exc:
        logger.exception('Schedule quality report generation failed (division_id=%s organization_id=%s)', division_id, organization_id)
        return {
            **_empty_quality_report(),
            'overall_health': 'Validation Error',
            'hard_errors': ['quality report generation failed'],
            'details': str(exc),
        }

@router.get('/schedule-management/games', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def schedule_management_games(season_id: uuid.UUID | None = None, date: date | None = None, division_id: uuid.UUID | None = None, organization_id: uuid.UUID | None = None, host_location_id: uuid.UUID | None = None, field_type: str | None = None, field_id: uuid.UUID | None = None, week_id: uuid.UUID | None = None, team_id: uuid.UUID | None = None, status_code: str | None = None, db: Session = Depends(get_db)):
    season = _get_schedule_scope_season(db, season_id)
    filters = _scheduled_games_filters(season.id if season else season_id, date=date, division_id=division_id, organization_id=organization_id, host_location_id=host_location_id, field_type=field_type, field_id=field_id, week_id=week_id, team_id=team_id, status_code=status_code)
    rows = get_scheduled_games_for_season(db, season.id if season else season_id, filters)
    return {'items': [{
        'id': str(g.id), 'date': g.game_date.isoformat(), 'time': g.kickoff_time.strftime('%H:%M:%S'), 'division_id': str(div.id), 'division_name': div.name,
        'home_team_id': str(home.id), 'home_team_name': home.name, 'away_team_id': str(away.id), 'away_team_name': away.name,
        'organization_id': str(org.id), 'organization_name': org.name, 'host_location_id': (str(host.id) if host else None), 'host_location_name': (host.name if host else None),
        'field_id': (str(fi.id) if fi else None), 'field': (fi.field_name if fi else None), 'field_type': (slot.field_type if slot else None), 'status': status.code, 'slot_id': (str(slot.id) if slot else None), 'is_slot_active': (fi.is_active if fi else False),
    } for g, slot, fi, host, home, away, div, org, status in rows]}

@router.get('/schedule-management/conflicts', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def schedule_management_conflicts(db: Session = Depends(get_db)):
    rows = _schedule_management_rows(db)
    conflicts=[]
    team_time={}
    field_time={}
    matchup=set()
    for g, slot, fi, host, home, away, div, org, status in rows:
        key=(g.game_date,g.kickoff_time)
        for t in [home,away]:
            tk=(t.id,key)
            if tk in team_time: conflicts.append({'type':'TEAM_OVERLAP','message':f'{t.name} scheduled multiple times at same date/time'})
            team_time[tk]=g.id
        if slot:
            fk=(slot.field_instance_id,key)
            if fk in field_time: conflicts.append({'type':'FIELD_DOUBLE_BOOKED','message':f'{fi.field_name} double-booked at same date/time'})
            field_time[fk]=g.id
            if slot.field_type != _required_field_type_for_division(div): conflicts.append({'type':'WRONG_FIELD_TYPE','message':f'{div.name} assigned wrong field type'})
            if not fi.is_active: conflicts.append({'type':'INACTIVE_SLOT','message':f'Game on inactive slot {fi.field_name}'})
        mk=(home.id,away.id,g.game_date)
        if mk in matchup: conflicts.append({'type':'DUPLICATE_MATCHUP','message':f'Duplicate matchup {home.name} vs {away.name}'})
        matchup.add(mk)
        if not home.is_active or not away.is_active: conflicts.append({'type':'INACTIVE_TEAM','message':f'Game assigned to inactive team'})
    return {'conflicts': conflicts}

@router.patch('/schedule-management/games/{game_id}/move', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def move_game_schedule(game_id: uuid.UUID, payload: dict, db: Session = Depends(get_db)):
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game: raise HTTPException(404, 'Game not found')
    new_slot = db.query(GameSlot).join(GameSlot.field_instance).filter(GameSlot.id == payload.get('generated_slot_id')).first()
    if not new_slot or new_slot.status != 'OPEN': raise HTTPException(400, 'Selected slot must be OPEN')
    division = db.query(Division).join(Team, Team.division_id == Division.id).filter(Team.id == game.home_team_id).first()
    if new_slot.field_type != _required_field_type_for_division(division): raise HTTPException(400, 'Selected slot field type must match division requirement')
    home_team = db.query(Team).filter(Team.id == game.home_team_id).first()
    away_team = db.query(Team).filter(Team.id == game.away_team_id).first()
    host_location = db.query(HostLocation).filter(HostLocation.id == new_slot.host_location_id).first() if new_slot.host_location_id else None
    adj_home, adj_away, adjustment_reason = _enforce_host_owner_home_team(home_team, away_team, host_location)
    if adj_home and adj_away:
        game.home_team_id = adj_home.id
        game.away_team_id = adj_away.id
        if adjustment_reason:
            logger.info(adjustment_reason)
    old_slot = db.query(GameSlot).filter(GameSlot.assigned_game_id == game.id).first()
    if old_slot: old_slot.status = 'OPEN'; old_slot.assigned_game_id = None
    new_slot.status = 'ASSIGNED'; new_slot.assigned_game_id = game.id
    game.host_location_id = new_slot.host_location_id
    game.field_instance_id = new_slot.field_instance_id
    game.game_date = new_slot.slot_date; game.kickoff_time = new_slot.start_time
    db.commit()
    return {'ok': True}

@router.patch('/schedule-management/games/{game_id}/unschedule', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def unschedule_game(game_id: uuid.UUID, db: Session = Depends(get_db)):
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game: raise HTTPException(404, 'Game not found')
    division_id = db.query(Team.division_id).filter(Team.id == game.home_team_id).scalar()
    week_id = game.week_id
    slot = db.query(GameSlot).filter(GameSlot.assigned_game_id == game.id).first()
    if slot: slot.status='OPEN'; slot.assigned_game_id=None
    db.delete(game)
    db.commit()
    active_remaining = 0
    if division_id and week_id:
        active_remaining = db.query(Game).join(Game.home_team).join(Game.status).filter(
            Game.week_id == week_id,
            Team.division_id == division_id,
            Team.is_active.is_(True),
            GameStatus.code == 'SCHEDULED',
            GameStatus.is_active.is_(True),
        ).count()
    logger.info(
        'unschedule_game: deleted game_id=%s reopened_slot_id=%s remaining_active_scheduled_games=%s division_id=%s week_id=%s',
        game_id,
        slot.id if slot else None,
        active_remaining,
        division_id,
        week_id,
    )
    return {'ok': True}


@router.post('/schedule-management/cleanup-unscheduled-games', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def cleanup_unscheduled_games(db: Session = Depends(get_db)):
    unscheduled_status_ids = db.query(GameStatus.id).filter(GameStatus.code == 'UNSCHEDULED').subquery()
    unscheduled_game_ids = [row[0] for row in db.query(Game.id).filter(Game.game_status_id.in_(unscheduled_status_ids)).all()]
    reopened_slots = db.query(GameSlot).filter(GameSlot.assigned_game_id.in_(unscheduled_game_ids)).update(
        {GameSlot.status: 'OPEN', GameSlot.assigned_game_id: None},
        synchronize_session=False,
    ) if unscheduled_game_ids else 0
    deleted_unscheduled_games = db.query(Game).filter(Game.id.in_(unscheduled_game_ids)).delete(synchronize_session=False) if unscheduled_game_ids else 0

    missing_slot_ids = [row[0] for row in db.query(GameSlot.id).filter(
        GameSlot.assigned_game_id.is_not(None),
        ~GameSlot.assigned_game_id.in_(db.query(Game.id)),
    ).all()]
    reopened_missing_links = db.query(GameSlot).filter(GameSlot.id.in_(missing_slot_ids)).update(
        {GameSlot.status: 'OPEN', GameSlot.assigned_game_id: None},
        synchronize_session=False,
    ) if missing_slot_ids else 0
    db.commit()
    return {
        'ok': True,
        'deleted_unscheduled_games': deleted_unscheduled_games,
        'reopened_slots_from_unscheduled_games': reopened_slots,
        'reopened_slots_from_missing_game_links': reopened_missing_links,
    }

@router.get('/schedule-management/export.csv', dependencies=[Depends(get_current_user)])
def export_schedule_management_csv(date: date | None = None, division_id: uuid.UUID | None = None, organization_id: uuid.UUID | None = None, host_location_id: uuid.UUID | None = None, field_type: str | None = None, field_id: uuid.UUID | None = None, team_id: uuid.UUID | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = _schedule_management_rows(db, {'date': date, 'division_id': division_id, 'organization_id': organization_id, 'host_location_id': host_location_id, 'field_type': field_type, 'field_id': field_id, 'team_id': team_id})
    out = io.StringIO(); w=csv.writer(out); w.writerow(['Date','Time','Division Group','Division','Division ID','Display Division Name','Category/Gender','Normalized Division Key','Home Team','Away Team','Host Location','Field','Field Type','Status'])
    export_division_names: set[str] = set()
    exported_dates = {g.game_date for g, *_ in rows if g.game_date}
    for g, slot, fi, host, home, away, div, org, status in rows:
        export_division_names.add(f'{div.division_group} {div.name}'.strip())
        w.writerow([g.game_date.isoformat(), g.kickoff_time.strftime('%H:%M'), div.division_group, div.name, str(div.id), f'{div.division_group} {div.name}'.strip(), div.division_group or '', normalized_division_key(div.division_group, div.name), home.name, away.name, host.name if host else '', fi.field_name if fi else '', slot.field_type if slot else '', status.code])

    validation_week_query = db.query(Week)
    if date:
        validation_week_query = validation_week_query.filter(Week.primary_game_date == date)
    elif exported_dates:
        validation_week_query = validation_week_query.filter(Week.primary_game_date.in_(exported_dates))
    validation_weeks = validation_week_query.order_by(Week.primary_game_date.asc(), Week.week_number.asc()).all()
    validation_division_query = db.query(Division).filter(Division.is_active.is_(True))
    if division_id:
        validation_division_query = validation_division_query.filter(Division.id == division_id)
    validation_divisions = validation_division_query.order_by(Division.division_group.asc(), Division.name.asc()).all()
    export_validation_warnings: list[dict[str, object]] = []
    for validation_week in validation_weeks:
        if int(validation_week.week_number or 0) > 99:
            continue
        for validation_division in validation_divisions:
            active_team_count = db.query(Team.id).filter(Team.division_id == validation_division.id, Team.is_active.is_(True)).count()
            expected_games = (int(active_team_count or 0) + 1) // 2
            if expected_games <= 0:
                continue
            scheduled_games = db.query(Game.id).join(Game.status).join(Team, Game.home_team_id == Team.id).filter(
                Team.division_id == validation_division.id,
                Team.is_active.is_(True),
                Game.week_id == validation_week.id,
                GameStatus.code != 'UNSCHEDULED',
                GameStatus.is_active.is_(True),
            ).count()
            missing_games = max(0, expected_games - int(scheduled_games or 0))
            if missing_games <= 0:
                continue
            division_label = f'{validation_division.division_group} {validation_division.name}'.strip()
            warning_message = f'EXPORT VALIDATION: incomplete division/week schedule; Week {validation_week.week_number} expected {expected_games}, scheduled {scheduled_games}, missing {missing_games}'
            export_validation_warnings.append({
                'week': validation_week.week_number,
                'week_start_date': str(_week_game_date(validation_week)) if _week_game_date(validation_week) else None,
                'division': division_label,
                'expected_games': expected_games,
                'scheduled_games': scheduled_games,
                'missing_games': missing_games,
            })
            w.writerow([
                _week_game_date(validation_week).isoformat() if _week_game_date(validation_week) else '',
                '',
                validation_division.division_group,
                validation_division.name,
                str(validation_division.id),
                division_label,
                validation_division.division_group or '',
                normalized_division_key(validation_division.division_group, validation_division.name),
                warning_message,
                '',
                '',
                '',
                _normalize_field_size(_required_field_type_for_division(validation_division)) or str(_required_field_type_for_division(validation_division)),
                'EXPORT_VALIDATION_INCOMPLETE',
            ])
    if export_validation_warnings:
        logger.warning('export_schedule_management_csv incomplete_division_week_schedules=%s', export_validation_warnings)
    logger.info('export_schedule_management_csv division_entries=%s', sorted(export_division_names))
    return StreamingResponse(iter([out.getvalue()]), media_type='text/csv', headers={'Content-Disposition':'attachment; filename="schedule-export.csv"'})
@router.post('/games', response_model=GameSaveResponse, dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def create_game(payload:GameCreate, db:Session=Depends(get_db)):
    validation=validate_game(db,payload); status=db.query(GameStatus).filter(GameStatus.id==payload.game_status_id).first()
    if not status: raise HTTPException(400,'Invalid game status')
    if status.code=='published' and validation.hard_conflicts: raise HTTPException(status_code=400, detail={'error':'hard_conflicts','validation':validation.model_dump()})
    obj=Game(**payload.model_dump(exclude={'division_id'})); db.add(obj); db.commit(); db.refresh(obj)
    return GameSaveResponse(game=_to_game_read(obj), validation=validation)

@router.put('/games/{game_id}', response_model=GameSaveResponse, dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def update_game(game_id:uuid.UUID,payload:GameCreate, db:Session=Depends(get_db)):
    obj=db.query(Game).filter(Game.id==game_id).first()
    if not obj: raise HTTPException(404,'Game not found')
    validation=validate_game(db,payload,game_id=game_id); status=db.query(GameStatus).filter(GameStatus.id==payload.game_status_id).first()
    if not status: raise HTTPException(400,'Invalid game status')
    if status.code=='published' and validation.hard_conflicts: raise HTTPException(status_code=400, detail={'error':'hard_conflicts','validation':validation.model_dump()})
    for k,v in payload.model_dump(exclude={'division_id'}).items(): setattr(obj,k,v)
    db.commit(); db.refresh(obj)
    return GameSaveResponse(game=_to_game_read(obj), validation=validation)


@router.patch('/games/{game_id}', response_model=GameSaveResponse, dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def patch_game(game_id: uuid.UUID, payload: GameCreate, db: Session = Depends(get_db)):
    return update_game(game_id, payload, db)


@router.delete('/games/{game_id}', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def delete_game(game_id: uuid.UUID, db: Session = Depends(get_db)):
    obj = db.query(Game).filter(Game.id == game_id).first()
    if not obj:
        raise HTTPException(404, 'Game not found')
    slot = db.query(GameSlot).filter(GameSlot.assigned_game_id == game_id).first()
    if slot:
        slot.status = 'OPEN'
        slot.assigned_game_id = None
    db.delete(obj)
    db.commit()
    return {'ok': True}
