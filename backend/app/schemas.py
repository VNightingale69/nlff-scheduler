import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, EmailStr


class BaseSchema(BaseModel):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RoleCreate(BaseModel):
    name: str
    description: str | None = None
    is_active: bool = True


class RoleRead(BaseSchema, RoleCreate):
    pass


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    role_name: str
    organization_id: uuid.UUID | None = None
    is_active: bool = True


class UserRead(BaseSchema):
    email: EmailStr
    full_name: str
    role_name: str
    organization_id: uuid.UUID | None
    is_active: bool


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = 'bearer'


class OrganizationCreate(BaseModel):
    name: str
    is_active: bool = True

class OrganizationRead(BaseSchema, OrganizationCreate):
    pass

class DivisionCreate(BaseModel):
    name: str
    division_group: str
    sort_order: int = 0
    required_field_layout_type: str
    is_active: bool = True

class DivisionRead(BaseSchema, DivisionCreate):
    pass


class OrganizationDivisionParticipationCreate(BaseModel):
    organization_id: uuid.UUID
    division_id: uuid.UUID
    is_participating: bool
    team_count: int = 0
    is_active: bool = True


class OrganizationDivisionParticipationRead(BaseSchema, OrganizationDivisionParticipationCreate):
    pass


class OrganizationDivisionParticipationUpsertItem(BaseModel):
    division_id: uuid.UUID
    is_participating: bool
    team_count: int


class OrganizationDivisionParticipationBulkUpsertRequest(BaseModel):
    organization_id: uuid.UUID
    items: list[OrganizationDivisionParticipationUpsertItem]

class HostLocationCreate(BaseModel):
    organization_id: uuid.UUID
    name: str
    address: str | None = None
    surface_type: str = 'GRASS_FIELD'
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    notes: str | None = None
    is_active: bool = True

class HostLocationRead(BaseSchema, HostLocationCreate):
    has_active_field_setup: bool = False
    effective_is_active: bool = False
    status_label: str = 'Inactive/Unavailable'
    status_warning: str | None = None


class HostLocationConfigurationCreate(BaseModel):
    host_location_id: uuid.UUID
    configuration_name: str
    is_active: bool = True

class HostLocationConfigurationRead(BaseSchema, HostLocationConfigurationCreate):
    surface_type: str = 'TURF_STADIUM'
    space_used_yards: int = 0
    remaining_yards: int = 0
    large_field_count: int = 0
    medium_field_count: int = 0
    small_field_count: int = 0
    field_instances: list[str] = []

class PhysicalFieldAreaCreate(BaseModel):
    host_location_id: uuid.UUID
    name: str
    field_space_type: str
    supports_dynamic_configuration: bool = False
    notes: str | None = None
    is_active: bool = True

class PhysicalFieldAreaRead(BaseSchema, PhysicalFieldAreaCreate):
    pass

class FieldConfigurationOptionCreate(BaseModel):
    physical_field_area_id: uuid.UUID
    name: str
    thirty_yard_capacity: int = 0
    fifty_three_yard_capacity: int = 0
    configuration_name: str | None = None
    surface_type: str = 'GRASS_FIELD'
    space_used_yards: int = 0
    remaining_yards: int = 0
    large_field_count: int = 0
    medium_field_count: int = 0
    small_field_count: int = 0
    is_active: bool = True

class FieldConfigurationOptionRead(BaseSchema, FieldConfigurationOptionCreate):
    pass

class FieldCreate(BaseModel):
    host_location_id: uuid.UUID
    physical_field_area_id: uuid.UUID | None = None
    name: str
    layout_type: str
    is_active: bool = True
    notes: str | None = None

class FieldRead(BaseSchema, FieldCreate):
    pass

class TeamCreate(BaseModel):
    organization_id: uuid.UUID
    division_id: uuid.UUID
    name: str
    is_active: bool = True

class TeamRead(BaseSchema, TeamCreate):
    pass


class TeamUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None

class SeasonCreate(BaseModel):
    name: str
    start_date: date
    end_date: date
    is_active: bool = True

class SeasonRead(BaseSchema, SeasonCreate):
    pass

class WeekCreate(BaseModel):
    season_id: uuid.UUID
    week_number: int
    label: str | None = None
    start_date: date
    end_date: date
    primary_game_date: date | None = None
    notes: str | None = None
    status: str = 'draft'

class WeekRead(BaseSchema, WeekCreate):
    pass

class HostingAvailabilityCreate(BaseModel):
    season_id: uuid.UUID | None = None
    week_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    host_location_id: uuid.UUID | None = None
    selected_configuration_id: uuid.UUID | None = None
    auto_select_turf_layout: bool = True
    lock_selected_layout: bool = False
    allow_turf_layout_changes: bool = False
    admin_override_incompatible_field_size: bool = False
    field_id: uuid.UUID | None | None = None
    physical_field_area_id: uuid.UUID | None = None
    field_configuration_option_id: uuid.UUID | None = None
    layout_type: str | None = None
    slot_index: int | None = None
    available_date: date
    primary_game_date: date | None = None
    active: bool = True
    start_time: time
    end_time: time
    is_available: bool = True
    notes: str | None = None

class HostingAvailabilityRead(BaseSchema, HostingAvailabilityCreate):
    pass


class HostingAvailabilityBulkSlot(BaseModel):
    season_id: uuid.UUID | None = None
    week_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    host_location_id: uuid.UUID | None = None
    selected_configuration_id: uuid.UUID | None = None
    auto_select_turf_layout: bool = True
    lock_selected_layout: bool = False
    allow_turf_layout_changes: bool = False
    admin_override_incompatible_field_size: bool = False
    field_id: uuid.UUID | None | None = None
    physical_field_area_id: uuid.UUID | None = None
    field_configuration_option_id: uuid.UUID | None = None
    layout_type: str | None = None
    slot_index: int | None = None
    available_date: date
    primary_game_date: date | None = None
    active: bool = True
    start_time: time
    end_time: time
    is_available: bool = True
    notes: str | None = None


class HostingAvailabilityBulkUpsertRequest(BaseModel):
    slots: list[HostingAvailabilityBulkSlot]


class HostingAvailabilityBulkUpsertResponse(BaseModel):
    created: int
    updated: int
    generated_field_instances: int = 0
    generated_slots: int = 0




class SavedAvailabilityRange(BaseModel):
    start_time: time
    end_time: time


class SavedAvailabilityEntry(BaseModel):
    id: uuid.UUID
    season_id: uuid.UUID | None = None
    week_id: uuid.UUID | None = None
    week_number: int | None = None
    week_label: str | None = None
    week_status: str | None = None
    primary_game_date: date | None = None
    available_date: date
    organization_id: uuid.UUID | None = None
    organization_name: str | None = None
    host_location_name: str
    host_location_id: uuid.UUID | None = None
    site_type: str
    available_layout: str
    small_field_capacity: int
    medium_field_capacity: int = 0
    large_field_capacity: int
    total_fields_found: int = 0
    inactive_field_count: int = 0
    unmatched_field_records: int = 0
    has_field_inventory_mismatch: bool = False
    time_ranges: list[SavedAvailabilityRange]


class SavedAvailabilityResponse(BaseModel):
    items: list[SavedAvailabilityEntry]

class GeneratedSlotRead(BaseModel):
    id: uuid.UUID
    available_date: date
    host_location_name: str
    field_instance_name: str
    field_type: str
    start_time: time
    end_time: time
    status: str
    is_locked: bool = False


class ScheduleReadinessDivisionRow(BaseModel):
    division_id: uuid.UUID
    division_label: str
    field_type_required: str
    number_of_teams: int
    minimum_unique_matchups: int
    target_scheduled_games: int | None = None
    available_matching_slots: int
    status: str


class ScheduleReadinessTotals(BaseModel):
    total_teams: int
    total_minimum_unique_matchups: int
    total_target_scheduled_games: int | None = None
    total_small_field_slots: int
    total_medium_field_slots: int = 0
    total_large_field_slots: int
    total_open_slots: int



class ScheduleReadinessHostSiteRow(BaseModel):
    host_location_id: uuid.UUID
    host_location_name: str
    community_id: uuid.UUID | None = None
    community_name: str | None = None
    surface_type: str
    selected_turf_layout: str | None = None
    grass_field_capacity: int = 0
    active_fields: list[str] = []
    field_counts_by_size: dict[str, int]
    total_field_capacity_by_size: dict[str, int] = {}
    generated_slots: int
    games_assigned: int
    games_assigned_by_location: int = 0
    games_unscheduled: int
    divisions_supported: list[str] = []
    warnings: list[str] = []
    auto_select_turf_layout: bool = True
    lock_selected_layout: bool = False


class ScheduleReadinessHostDateRow(BaseModel):
    host_date: date
    community_id: uuid.UUID | None = None
    community_name: str | None = None
    selected_host_locations: list[str] = []
    host_sites_available: int
    generated_slots: int
    games_assigned: int
    games_unscheduled: int
    field_counts_by_size: dict[str, int]
    host_sites: list[ScheduleReadinessHostSiteRow]
    warnings: list[str] = []




class HostingBalanceRow(BaseModel):
    community_id: uuid.UUID | None = None
    community: str
    available_host_dates: int
    games_hosted_this_week: int
    games_hosted_season_to_date: int
    expected_host_share: float
    hosting_delta: float
    status: str


class FieldConfigurationEfficiencyRow(BaseModel):
    host_location_id: uuid.UUID | None = None
    host_location: str
    host_date: date
    selected_turf_layout: str | None = None
    field_size_blocks: list[str] = []
    layout_changes: int
    transition_windows_required: int
    warnings: list[str] = []


class WeeklyFieldDemandRow(BaseModel):
    host_date: date
    small_games_required: int
    medium_games_required: int
    large_games_required: int
    available_capacity_by_community: list[dict] = []


class ScheduleReadinessResponse(BaseModel):
    rows: list[ScheduleReadinessDivisionRow]
    totals: ScheduleReadinessTotals
    warnings: list[str] = []
    host_dates: list[ScheduleReadinessHostDateRow] = []
    hosting_balance: list[HostingBalanceRow] = []
    field_configuration_efficiency: list[FieldConfigurationEfficiencyRow] = []
    weekly_field_demand: list[WeeklyFieldDemandRow] = []


class HostingGenerationLocationResult(BaseModel):
    host_location_id: uuid.UUID
    host_location_name: str
    total_slots_evaluated: int = 0
    slots_regenerated: int = 0
    locked_slots_skipped: int = 0
    new_slots_created: int = 0
    obsolete_unused_slots_removed: int = 0
    hard_failures: int = 0
    field_instances_created: int = 0
    slots_created: int = 0
    skipped_reason: str | None = None
    errors: list[str] = []


class HostingGenerationRunResult(BaseModel):
    message: str
    processed: int = 0
    skipped: int = 0
    errors: int = 0
    total_field_instances_created: int = 0
    total_slots_created: int = 0
    total_slots_evaluated: int = 0
    total_slots_regenerated: int = 0
    total_locked_slots_skipped: int = 0
    total_new_slots_created: int = 0
    total_obsolete_unused_slots_removed: int = 0
    total_hard_failures: int = 0
    last_generated_at: datetime
    results: list[HostingGenerationLocationResult]

class GameStatusCreate(BaseModel):
    code: str
    label: str
    is_active: bool = True

class GameStatusRead(BaseSchema, GameStatusCreate):
    pass

class GameCreate(BaseModel):
    season_id: uuid.UUID | None
    week_id: uuid.UUID | None
    division_id: uuid.UUID
    home_team_id: uuid.UUID
    away_team_id: uuid.UUID
    field_id: uuid.UUID | None
    host_location_id: uuid.UUID | None = None
    field_instance_id: uuid.UUID | None = None
    game_status_id: uuid.UUID
    game_date: date
    kickoff_time: time

class GameUpdate(GameCreate):
    pass

class GameRead(BaseSchema, GameCreate):
    status_code: str
    division_name: str | None = None
    division_group: str | None = None
    home_team_name: str | None = None
    away_team_name: str | None = None
    generated_slot_id: uuid.UUID | None = None
    field_instance_id: uuid.UUID | None = None
    host_location_id: uuid.UUID | None = None
    field_instance_name: str | None = None
    host_location_name: str | None = None


class GameSaveResponse(BaseModel):
    game: GameRead
    validation: "GameValidationResponse"


class ValidationMessage(BaseModel):
    code: str
    message: str


class GameValidationResponse(BaseModel):
    hard_conflicts: list[ValidationMessage]
    soft_warnings: list[ValidationMessage]


class PublicGameRead(BaseModel):
    id: uuid.UUID
    game_date: date
    kickoff_time: time
    host_location_id: uuid.UUID | None
    host_location_name: str
    field_id: uuid.UUID | None
    field_name: str
    field_type: str | None = None
    organization_id: uuid.UUID
    organization_name: str
    division_id: uuid.UUID
    division_name: str
    week_id: uuid.UUID | None
    week_number: int | None
    home_team_id: uuid.UUID
    home_team_name: str
    away_team_id: uuid.UUID
    away_team_name: str
    game_status_id: uuid.UUID
    game_status_code: str
    game_status_label: str


from pydantic.generics import GenericModel
from typing import Generic, TypeVar
T=TypeVar('T')
class PagedResponse(GenericModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    message: str | None = None
