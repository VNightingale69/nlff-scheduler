import uuid

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, Time, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TimestampMixin:
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Role(Base, TimestampMixin):
    __tablename__ = 'roles'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Organization(Base, TimestampMixin):
    __tablename__ = 'organizations'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class User(Base, TimestampMixin):
    __tablename__ = 'users'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('roles.id'), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id'))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    role = relationship('Role')
    organization = relationship('Organization')


class Division(Base, TimestampMixin):
    __tablename__ = 'divisions'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    division_group: Mapped[str] = mapped_column(String(20), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    required_field_layout_type: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    __table_args__ = (UniqueConstraint('division_group', 'name', name='uq_division_group_name'),)


class OrganizationDivisionParticipation(Base, TimestampMixin):
    __tablename__ = 'organization_division_participations'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id'), nullable=False)
    division_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('divisions.id'), nullable=False)
    is_participating: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    team_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    organization = relationship('Organization')
    division = relationship('Division')
    __table_args__ = (
        UniqueConstraint('organization_id', 'division_id', name='uq_org_division_participation'),
        Index('ix_org_division_participations_organization_id', 'organization_id'),
        Index('ix_org_division_participations_division_id', 'division_id'),
    )

class HostLocation(Base, TimestampMixin):
    __tablename__ = 'host_locations'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id'), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(String(255))
    address_line1: Mapped[str | None] = mapped_column(String(255))
    address_line2: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(80))
    zip_code: Mapped[str | None] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    organization = relationship('Organization')
    __table_args__ = (UniqueConstraint('organization_id', 'name', name='uq_host_location_org_name'),)

class Field(Base, TimestampMixin):
    __tablename__ = 'fields'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host_location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('host_locations.id'), nullable=False)
    physical_field_area_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('physical_field_areas.id'))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    layout_type: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    host_location = relationship('HostLocation')
    physical_field_area = relationship('PhysicalFieldArea')
    __table_args__ = (UniqueConstraint('host_location_id', 'name', name='uq_field_location_name'),)


class PhysicalFieldArea(Base, TimestampMixin):
    __tablename__ = 'physical_field_areas'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host_location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('host_locations.id'), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    field_space_type: Mapped[str] = mapped_column(String(80), nullable=False)
    supports_dynamic_configuration: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    host_location = relationship('HostLocation')
    __table_args__ = (UniqueConstraint('host_location_id', 'name', name='uq_field_area_location_name'),)


class FieldConfigurationOption(Base, TimestampMixin):
    __tablename__ = 'field_configuration_options'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    physical_field_area_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('physical_field_areas.id', ondelete='CASCADE'), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    thirty_yard_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fifty_three_yard_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    physical_field_area = relationship('PhysicalFieldArea')
    __table_args__ = (UniqueConstraint('physical_field_area_id', 'name', name='uq_field_config_option_area_name'),)

class Team(Base, TimestampMixin):
    __tablename__ = 'teams'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id'), nullable=False)
    division_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('divisions.id'), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    organization = relationship('Organization')
    division = relationship('Division')
    __table_args__ = (UniqueConstraint('organization_id', 'division_id', 'name', name='uq_team_org_div_name'),)

class Season(Base, TimestampMixin):
    __tablename__ = 'seasons'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    start_date: Mapped[Date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Date] = mapped_column(Date, nullable=False)
    schedule_status: Mapped[str] = mapped_column(String(20), nullable=False, default='draft')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class Week(Base, TimestampMixin):
    __tablename__ = 'weeks'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    season_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('seasons.id'), nullable=True)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[Date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Date] = mapped_column(Date, nullable=False)
    season = relationship('Season')
    __table_args__ = (UniqueConstraint('season_id', 'week_number', name='uq_week_season_number'),)

class HostingAvailability(Base, TimestampMixin):
    __tablename__ = 'hosting_availabilities'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    field_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('fields.id'))
    physical_field_area_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('physical_field_areas.id'))
    field_configuration_option_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('field_configuration_options.id'))
    layout_type: Mapped[str | None] = mapped_column(String(100))
    slot_index: Mapped[int | None] = mapped_column(Integer)
    available_date: Mapped[Date] = mapped_column(Date, nullable=False)
    start_time: Mapped[Time] = mapped_column(Time, nullable=False)
    end_time: Mapped[Time] = mapped_column(Time, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    field = relationship('Field')
    physical_field_area = relationship('PhysicalFieldArea')
    field_configuration_option = relationship('FieldConfigurationOption')
    __table_args__ = (UniqueConstraint('field_id', 'physical_field_area_id', 'available_date', 'start_time', 'end_time', 'layout_type', 'slot_index', name='uq_field_availability_slot'),)


class FieldInstance(Base, TimestampMixin):
    __tablename__ = 'field_instances'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host_location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('host_locations.id'), nullable=False)
    hosting_availability_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('hosting_availabilities.id'), nullable=False)
    instance_date: Mapped[Date] = mapped_column(Date, nullable=False)
    field_name: Mapped[str] = mapped_column(String(120), nullable=False)
    field_type: Mapped[str] = mapped_column(String(10), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    host_location = relationship('HostLocation')
    hosting_availability = relationship('HostingAvailability')
    __table_args__ = (UniqueConstraint('hosting_availability_id', 'field_name', name='uq_field_instance_availability_name'),)


class GameSlot(Base, TimestampMixin):
    __tablename__ = 'game_slots'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    field_instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('field_instances.id'), nullable=False)
    host_location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('host_locations.id'), nullable=False)
    slot_date: Mapped[Date] = mapped_column(Date, nullable=False)
    start_time: Mapped[Time] = mapped_column(Time, nullable=False)
    end_time: Mapped[Time] = mapped_column(Time, nullable=False)
    field_type: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='OPEN')
    assigned_game_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('games.id'))
    field_instance = relationship('FieldInstance')
    host_location = relationship('HostLocation')
    assigned_game = relationship('Game')
    __table_args__ = (UniqueConstraint('field_instance_id', 'start_time', 'end_time', name='uq_game_slot_instance_time'),)

class GameStatus(Base, TimestampMixin):
    __tablename__ = 'game_statuses'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class Game(Base, TimestampMixin):
    __tablename__ = 'games'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    season_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('seasons.id'), nullable=True)
    week_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('weeks.id'), nullable=True)
    home_team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('teams.id'), nullable=False)
    away_team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('teams.id'), nullable=False)
    field_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('fields.id'), nullable=True)
    game_status_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('game_statuses.id'), nullable=False)
    game_date: Mapped[Date] = mapped_column(Date, nullable=False)
    kickoff_time: Mapped[Time] = mapped_column(Time, nullable=False)
    season = relationship('Season')
    week = relationship('Week')
    field = relationship('Field')
    status = relationship('GameStatus')
    home_team = relationship('Team', foreign_keys=[home_team_id])
    away_team = relationship('Team', foreign_keys=[away_team_id])
