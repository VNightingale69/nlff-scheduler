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
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    is_active: bool = True

class HostLocationRead(BaseSchema, HostLocationCreate):
    pass

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
    thirty_yard_capacity: int
    fifty_three_yard_capacity: int
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
    start_date: date
    end_date: date

class WeekRead(BaseSchema, WeekCreate):
    pass

class HostingAvailabilityCreate(BaseModel):
    field_id: uuid.UUID | None = None
    physical_field_area_id: uuid.UUID | None = None
    field_configuration_option_id: uuid.UUID | None = None
    layout_type: str | None = None
    slot_index: int | None = None
    available_date: date
    start_time: time
    end_time: time
    is_available: bool = True

class HostingAvailabilityRead(BaseSchema, HostingAvailabilityCreate):
    pass


class HostingAvailabilityBulkSlot(BaseModel):
    field_id: uuid.UUID | None = None
    physical_field_area_id: uuid.UUID | None = None
    field_configuration_option_id: uuid.UUID | None = None
    layout_type: str | None = None
    slot_index: int | None = None
    available_date: date
    start_time: time
    end_time: time
    is_available: bool = True


class HostingAvailabilityBulkUpsertRequest(BaseModel):
    slots: list[HostingAvailabilityBulkSlot]


class HostingAvailabilityBulkUpsertResponse(BaseModel):
    created: int
    updated: int




class SavedAvailabilityRange(BaseModel):
    start_time: time
    end_time: time


class SavedAvailabilityEntry(BaseModel):
    available_date: date
    host_location_name: str
    site_type: str
    available_layout: str
    small_field_capacity: int
    large_field_capacity: int
    time_ranges: list[SavedAvailabilityRange]


class SavedAvailabilityResponse(BaseModel):
    items: list[SavedAvailabilityEntry]

class GameStatusCreate(BaseModel):
    code: str
    label: str
    is_active: bool = True

class GameStatusRead(BaseSchema, GameStatusCreate):
    pass

class GameCreate(BaseModel):
    season_id: uuid.UUID
    week_id: uuid.UUID
    division_id: uuid.UUID
    home_team_id: uuid.UUID
    away_team_id: uuid.UUID
    field_id: uuid.UUID
    game_status_id: uuid.UUID
    game_date: date
    kickoff_time: time

class GameUpdate(GameCreate):
    pass

class GameRead(BaseSchema, GameCreate):
    status_code: str


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
    host_location_id: uuid.UUID
    host_location_name: str
    field_id: uuid.UUID
    field_name: str
    organization_id: uuid.UUID
    organization_name: str
    division_id: uuid.UUID
    division_name: str
    week_id: uuid.UUID
    week_number: int
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
