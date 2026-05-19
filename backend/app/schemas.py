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
    required_field_layout_type: str
    min_age: int | None = None
    max_age: int | None = None
    is_active: bool = True

class DivisionRead(BaseSchema, DivisionCreate):
    pass

class HostLocationCreate(BaseModel):
    organization_id: uuid.UUID
    name: str
    address: str | None = None
    is_active: bool = True

class HostLocationRead(BaseSchema, HostLocationCreate):
    pass

class FieldCreate(BaseModel):
    host_location_id: uuid.UUID
    name: str
    layout_type: str
    is_active: bool = True

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
    field_id: uuid.UUID
    available_date: date
    start_time: time
    end_time: time
    is_available: bool = True

class HostingAvailabilityRead(BaseSchema, HostingAvailabilityCreate):
    pass

class GameStatusCreate(BaseModel):
    code: str
    label: str
    is_active: bool = True

class GameStatusRead(BaseSchema, GameStatusCreate):
    pass

class GameCreate(BaseModel):
    season_id: uuid.UUID
    week_id: uuid.UUID
    home_team_id: uuid.UUID
    away_team_id: uuid.UUID
    field_id: uuid.UUID
    game_status_id: uuid.UUID
    game_date: date
    kickoff_time: time

class GameRead(BaseSchema, GameCreate):
    pass


class ValidationMessage(BaseModel):
    code: str
    message: str


class GameValidationResponse(BaseModel):
    hard_conflicts: list[ValidationMessage]
    soft_warnings: list[ValidationMessage]


from pydantic.generics import GenericModel
from typing import Generic, TypeVar
T=TypeVar('T')
class PagedResponse(GenericModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
