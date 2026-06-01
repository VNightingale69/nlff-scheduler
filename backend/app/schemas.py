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


class TokenUser(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    role_name: str
    organization_id: uuid.UUID | None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = 'bearer'
    user: TokenUser | None = None




class RulebookRead(BaseSchema):
    original_filename: str
    content_type: str
    file_size_bytes: int
    uploaded_by_user_id: uuid.UUID
    uploaded_by_name: str | None = None
    uploaded_by_email: str | None = None
    uploaded_at: datetime
    is_active: bool
    view_url: str = '/api/public/rulebook/view'
    download_url: str = '/api/public/rulebook/download'


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
    max_small_fields: int = 0
    max_medium_fields: int = 0
    max_large_fields: int = 0
    max_total_fields: int = 0
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
    date_type: str = 'REGULAR_SEASON'
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


HOST_PLAN_SELECTION_STATUSES = {
    'AVAILABLE',
    'NOT_AVAILABLE',
    'SELECTED',
    'EXCLUDED',
    'LOCKED',
    'BLOCKED_CAPACITY',
    'BLOCKED_ROTATION',
    'BLOCKED_FIELD_SIZE',
    'OVERFLOW',
}


class HostPlanSelectionUpdate(BaseModel):
    season_id: uuid.UUID
    week_id: uuid.UUID | None = None
    game_date: date
    community_id: uuid.UUID
    host_location_id: uuid.UUID
    availability_id: uuid.UUID | None = None
    status: str
    locked: bool = False
    reason: str | None = None


class HostPlanSelectionRead(BaseSchema, HostPlanSelectionUpdate):
    pass


class HostAvailabilityMatrixSaveRequest(BaseModel):
    season_id: uuid.UUID
    selections: list[HostPlanSelectionUpdate]


class HostAvailabilityMatrixSaveResponse(BaseModel):
    saved: int
    selections: list[HostPlanSelectionRead]


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
    season_id: uuid.UUID | None = None
    season_week_id: uuid.UUID | None = None
    week_id: uuid.UUID | None = None
    game_date: date
    available_date: date
    date_type: str | None = None
    host_location_id: uuid.UUID | None = None
    host_location_name: str
    field_instance_id: uuid.UUID | None = None
    field_instance_name: str
    field_size: str
    field_type: str
    start_time: time
    end_time: time
    status: str
    is_available: bool = True
    is_locked: bool = False


class GeneratedSlotsClearResponse(BaseModel):
    slots_deleted: int = 0
    field_instances_deleted: int = 0
    field_instances_preserved: int = 0
    games_preserved: int = 0
    warning: str | None = None


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



class ScheduleReadinessTurfWaveSlotRow(BaseModel):
    start_time: time
    end_time: time
    slot_level_configuration: str | None = None
    field_instances_generated: list[str] = []
    games_assigned_by_field_size: dict[str, int] = {}
    unused_compatible_capacity: dict[str, int] = {}
    inserted_through_slot_level_optimization: list[str] = []
    rejected_assignments: list[str] = []
    warnings: list[str] = []


class ScheduleReadinessTurfWaveRow(BaseModel):
    host_location_id: uuid.UUID
    host_location_name: str
    host_date: date
    sequence_number: int
    wave_intent: str
    preferred_layout_code: str
    start_time: time
    end_time: time
    transition_before_minutes: int = 0
    transition_after_minutes: int = 0
    generated_field_instances: list[str] = []
    assigned_games: int = 0
    capacity_slots: int = 0
    utilization_percent: float = 0.0
    idle_hours_after_wave: float = 0.0
    notes: str | None = None
    slot_level_configurations: list[ScheduleReadinessTurfWaveSlotRow] = []
    warnings: list[str] = []


class ScheduleReadinessHostSiteRow(BaseModel):
    host_location_id: uuid.UUID
    host_location_name: str
    community_id: uuid.UUID | None = None
    community_name: str | None = None
    surface_type: str
    selected_turf_layout: str | None = None
    grass_field_capacity: int = 0
    small_fields_to_line: int = 0
    medium_fields_to_line: int = 0
    large_fields_to_line: int = 0
    total_fields_to_line: int = 0
    capacity_status: str = 'not_applicable'
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
    turf_wave_plan: list[ScheduleReadinessTurfWaveRow] = []


class ScheduleReadinessHostDateRow(BaseModel):
    host_date: date
    date_type: str | None = None
    label: str | None = None
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
    diagnostic_label: str | None = None
    community_id: uuid.UUID | None = None
    community: str
    host_locations: list[dict] = []
    available_host_dates: int
    available_host_weeks: int = 0
    available_weeks: list[str] = []
    selected_weeks: list[str] = []
    host_weeks_used: int = 0
    games_hosted_this_week: int
    games_hosted_season_to_date: int
    games_hosted: int = 0
    average_games_per_host_week: float = 0
    expected_host_share: float
    expected_games_hosted: float = 0
    hosting_delta: float
    last_hosted_week: str | None = None
    consecutive_host_count: int = 0
    rotation_rank: int | None = None
    status: str


class HostingRotationRow(BaseModel):
    diagnostic_label: str | None = None
    week: str
    host_date: str | None = None
    available_communities: list[str] = []
    selected_host_communities: list[str] = []
    selected_community_or_communities: list[str] = []
    selected_host_locations_by_community: list[dict] = []
    community_capacity_by_field_size: dict[str, dict] = {}
    locations_used_under_each_community: list[dict] = []
    combined_community_capacity: int = 0
    selected_community_could_host_all_games: bool = False
    additional_communities_needed: bool = False
    reason_additional_community_needed: str | None = None
    skipped_communities: list[dict] = []
    rotation_ranking: list[dict] = []
    reason_selected: list[str] = []
    reason_skipped: list[str] = []


class FieldConfigurationEfficiencyRow(BaseModel):
    host_location_id: uuid.UUID | None = None
    host_location: str
    host_date: date
    selected_turf_layout: str | None = None
    small_fields: int = 0
    medium_fields: int = 0
    large_fields: int = 0
    field_size_blocks: list[str] = []
    layout_changes: int
    transition_windows_required: int
    transition_windows: list[str] = []
    unused_capacity: int = 0
    warnings: list[str] = []


class WeeklyFieldDemandRow(BaseModel):
    host_date: date
    small_games_required: int
    medium_games_required: int
    large_games_required: int
    capacity_available: int = 0
    capacity_used: int = 0
    available_capacity_by_community: list[dict] = []


class ScheduleReadinessResponse(BaseModel):
    rows: list[ScheduleReadinessDivisionRow]
    totals: ScheduleReadinessTotals
    warnings: list[str] = []
    host_dates: list[ScheduleReadinessHostDateRow] = []
    hosting_balance: list[HostingBalanceRow] = []
    hosting_rotation: list[HostingRotationRow] = []
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


class ScorePayload(BaseModel):
    home_score: int
    away_score: int
    community_admin_notes: str | None = None
    league_admin_notes: str | None = None


class ScoreApprovePayload(BaseModel):
    league_admin_notes: str | None = None


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
    week_label: str | None = None
    date_type: str | None = None
    home_team_id: uuid.UUID
    home_team_name: str
    away_team_id: uuid.UUID
    away_team_name: str
    game_status_id: uuid.UUID
    game_status_code: str
    game_status_label: str
    public_score_status: str | None = None
    home_score: int | None = None
    away_score: int | None = None


from pydantic.generics import GenericModel
from typing import Generic, TypeVar
T=TypeVar('T')
class PagedResponse(GenericModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    message: str | None = None
