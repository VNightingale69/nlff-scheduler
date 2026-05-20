import uuid

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, Time, UniqueConstraint, func
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
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    required_field_layout_type: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class HostLocation(Base, TimestampMixin):
    __tablename__ = 'host_locations'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id'), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    organization = relationship('Organization')
    __table_args__ = (UniqueConstraint('organization_id', 'name', name='uq_host_location_org_name'),)

class Field(Base, TimestampMixin):
    __tablename__ = 'fields'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host_location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('host_locations.id'), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    layout_type: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    host_location = relationship('HostLocation')
    __table_args__ = (UniqueConstraint('host_location_id', 'name', name='uq_field_location_name'),)

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
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class Week(Base, TimestampMixin):
    __tablename__ = 'weeks'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    season_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('seasons.id'), nullable=False)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[Date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Date] = mapped_column(Date, nullable=False)
    season = relationship('Season')
    __table_args__ = (UniqueConstraint('season_id', 'week_number', name='uq_week_season_number'),)

class HostingAvailability(Base, TimestampMixin):
    __tablename__ = 'hosting_availabilities'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    field_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('fields.id'), nullable=False)
    available_date: Mapped[Date] = mapped_column(Date, nullable=False)
    start_time: Mapped[Time] = mapped_column(Time, nullable=False)
    end_time: Mapped[Time] = mapped_column(Time, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    field = relationship('Field')
    __table_args__ = (UniqueConstraint('field_id', 'available_date', 'start_time', 'end_time', name='uq_field_availability_slot'),)

class GameStatus(Base, TimestampMixin):
    __tablename__ = 'game_statuses'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class Game(Base, TimestampMixin):
    __tablename__ = 'games'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    season_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('seasons.id'), nullable=False)
    week_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('weeks.id'), nullable=False)
    home_team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('teams.id'), nullable=False)
    away_team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('teams.id'), nullable=False)
    field_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('fields.id'), nullable=False)
    game_status_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('game_statuses.id'), nullable=False)
    game_date: Mapped[Date] = mapped_column(Date, nullable=False)
    kickoff_time: Mapped[Time] = mapped_column(Time, nullable=False)
    season = relationship('Season')
    week = relationship('Week')
    field = relationship('Field')
    status = relationship('GameStatus')
    home_team = relationship('Team', foreign_keys=[home_team_id])
    away_team = relationship('Team', foreign_keys=[away_team_id])
