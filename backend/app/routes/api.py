import csv
import os
import io
import math
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
import logging
from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError
from sqlalchemy.orm import Session, aliased

from app.auth import ROLE_COMMUNITY_SCHEDULER, ROLE_LEAGUE_ADMIN, enforce_organization_scope, get_current_user, require_roles
from app.database import get_db
from app.models import Division, Field, FieldConfigurationOption, FieldInstance, Game, GameSlot, GameStatus, HostLocation, HostingAvailability, Organization, OrganizationDivisionParticipation, PhysicalFieldArea, Role, Season, Team, User, Week
from app.schemas import (
    DivisionCreate, DivisionRead, FieldConfigurationOptionCreate, FieldConfigurationOptionRead, FieldCreate, FieldRead, GameCreate, GameRead, GameSaveResponse,
    OrganizationDivisionParticipationBulkUpsertRequest, OrganizationDivisionParticipationRead,
    GeneratedSlotRead, HostLocationCreate, HostLocationRead, HostingAvailabilityCreate, HostingAvailabilityRead, HostingAvailabilityBulkUpsertRequest, HostingAvailabilityBulkUpsertResponse, HostingGenerationRunResult, HostingGenerationLocationResult, PhysicalFieldAreaCreate, PhysicalFieldAreaRead, SavedAvailabilityResponse,
    LoginRequest, OrganizationCreate, OrganizationRead, PagedResponse, PublicGameRead, RefreshRequest,
    TeamCreate, TeamRead, TeamUpdate, TokenResponse, UserCreate, UserRead,
    ScheduleReadinessDivisionRow, ScheduleReadinessResponse, ScheduleReadinessTotals
)
from app.security import create_access_token, create_refresh_token, hash_password, validate_password_strength, verify_password, decode_token
from app.services.game_statuses import REQUIRED_GAME_STATUSES, ensure_required_game_statuses
from app.services.scheduling_validation import validate_game

router = APIRouter(prefix='/api')
logger = logging.getLogger(__name__)
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
        '2ND3RD': '2_3',
        '4TH5TH': '4_5',
        '6TH7TH': '6_7',
        '8TH': '8',
        '6TH7TH8TH': '6_7_8',
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

def _capacity_for_layout(layout_name: str | None, option: FieldConfigurationOption | None) -> tuple[int, int]:
    if option:
        return option.thirty_yard_capacity, option.fifty_three_yard_capacity
    if layout_name == '1x53_plus_2x30':
        return 2, 1
    if layout_name == '2x53':
        return 0, 2
    if layout_name == '3x30':
        return 3, 0
    return 0, 0


def _regenerate_generated_slots(db: Session, availability: HostingAvailability, host_location_id: uuid.UUID):
    assigned_slots = db.query(GameSlot).join(GameSlot.field_instance).filter(
        FieldInstance.hosting_availability_id == availability.id,
        GameSlot.assigned_game_id.isnot(None),
    ).count()
    if assigned_slots > 0:
        raise HTTPException(400, 'Cannot update availability because one or more generated slots are assigned to games.')

    db.query(GameSlot).filter(GameSlot.field_instance_id.in_(db.query(FieldInstance.id).filter(FieldInstance.hosting_availability_id == availability.id))).delete(synchronize_session=False)
    db.query(FieldInstance).filter(FieldInstance.hosting_availability_id == availability.id).delete(synchronize_session=False)

    if not availability.is_available:
        return
    area = availability.physical_field_area
    if not area:
        return
    option = availability.field_configuration_option
    small_count, large_count = _capacity_for_layout(availability.layout_type or (option.name if option else None), option)
    instances: list[FieldInstance] = []
    for i in range(large_count):
        instances.append(FieldInstance(host_location_id=host_location_id, hosting_availability_id=availability.id, instance_date=availability.available_date, field_name=f'Large Field {i + 1}', field_type='LARGE', is_active=True))
    for i in range(small_count):
        instances.append(FieldInstance(host_location_id=host_location_id, hosting_availability_id=availability.id, instance_date=availability.available_date, field_name=f'Small Field {i + 1}', field_type='SMALL', is_active=True))
    for instance in instances:
        db.add(instance)
    db.flush()
    logger.info('Generated %s field instances for availability_id=%s host_location_id=%s', len(instances), availability.id, host_location_id)
    created_slots = 0
    start_dt = datetime.combine(availability.available_date, availability.start_time)
    end_dt = datetime.combine(availability.available_date, availability.end_time)
    while start_dt < end_dt:
        next_dt = start_dt + timedelta(hours=1)
        for instance in instances:
            db.add(GameSlot(field_instance_id=instance.id, host_location_id=host_location_id, slot_date=availability.available_date, start_time=start_dt.time(), end_time=next_dt.time(), field_type=instance.field_type, status='OPEN'))
            created_slots += 1
        start_dt = next_dt
    logger.info('Generated %s game slots for availability_id=%s host_location_id=%s', created_slots, availability.id, host_location_id)


def _regenerate_hosting_day(db: Session, availability_rows: list[HostingAvailability], host: HostLocation) -> HostingGenerationLocationResult:
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
            if not availability.physical_field_area:
                msg = 'Hosting setup missing for this location.'
                result.errors.append(msg)
                logger.error('Host %s (%s) availability %s error: %s', host.name, host.id, availability.id, msg)
                continue

            before_instances = db.query(FieldInstance).filter(FieldInstance.hosting_availability_id == availability.id).count()
            before_slots = db.query(GameSlot).join(GameSlot.field_instance).filter(FieldInstance.hosting_availability_id == availability.id).count()
            _regenerate_generated_slots(db, availability, host.id)
            after_instances = db.query(FieldInstance).filter(FieldInstance.hosting_availability_id == availability.id).count()
            after_slots = db.query(GameSlot).join(GameSlot.field_instance).filter(FieldInstance.hosting_availability_id == availability.id).count()
            result.field_instances_created += max(after_instances, before_instances)
            result.slots_created += max(after_slots, before_slots)
            logger.info('Host %s (%s): availability %s regenerated, field_instances=%s slots=%s', host.name, host.id, availability.id, after_instances, after_slots)
        except HTTPException as exc:
            detail = str(exc.detail)
            result.errors.append(detail)
            logger.error('Host %s (%s): availability %s failed: %s', host.name, host.id, availability.id, detail)
        except Exception as exc:
            detail = str(exc)
            result.errors.append(detail)
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
    today = date.today()
    return [
        ('Fields', db.query(Field).filter(Field.host_location_id == host_location_id).count()),
        ('Physical Field Areas', db.query(PhysicalFieldArea).filter(PhysicalFieldArea.host_location_id == host_location_id).count()),
        ('Hosting Availability', db.query(HostingAvailability).filter((HostingAvailability.field_id.in_(field_ids_subquery)) | (HostingAvailability.physical_field_area_id.in_(area_ids_subquery))).count()),
        ('Field Configuration Options', db.query(FieldConfigurationOption).filter(FieldConfigurationOption.physical_field_area_id.in_(area_ids_subquery)).count()),
        ('Scheduled Games', db.query(Game).join(Game.field).filter(Field.host_location_id == host_location_id, Game.game_date >= today).count()),
        ('Published Games', db.query(Game).join(Game.status).join(Game.field).filter(Field.host_location_id == host_location_id, GameStatus.code == 'published').count()),
    ]


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
        'role_name': user.role.name, 'organization_id': user.organization_id,
    }

@router.post('/auth/login', response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).join(User.role).filter(User.email == payload.email, User.is_active.is_(True), Role.is_active.is_(True)).first()
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
    role = db.query(Role).filter(Role.name == payload.role_name, Role.is_active.is_(True)).first()
    if not role: raise HTTPException(400, 'Invalid role')
    if payload.role_name == ROLE_COMMUNITY_SCHEDULER and not payload.organization_id: raise HTTPException(400, 'Community scheduler requires organization_id')
    validate_password_strength(payload.password)
    obj = User(email=payload.email, full_name=payload.full_name, password_hash=hash_password(payload.password), role_id=role.id, organization_id=payload.organization_id, is_active=payload.is_active)
    db.add(obj); db.commit(); db.refresh(obj)
    return UserRead(id=obj.id, created_at=obj.created_at, updated_at=obj.updated_at, email=obj.email, full_name=obj.full_name, role_name=obj.role.name, organization_id=obj.organization_id, is_active=obj.is_active)

@router.post('/organizations', response_model=OrganizationRead, dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def create_organization(payload: OrganizationCreate, db: Session = Depends(get_db)):
    obj = Organization(**payload.model_dump()); db.add(obj); db.commit(); db.refresh(obj); return obj

@router.get('/organizations', response_model=PagedResponse[OrganizationRead], dependencies=[Depends(get_current_user)])
def list_organizations(search: str | None = None, is_active: bool | None = None, page: int = 1, page_size: int = 20, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Organization)
    if current_user.role.name == ROLE_COMMUNITY_SCHEDULER: q = q.filter(Organization.id == current_user.organization_id)
    if search: q = q.filter(func.lower(Organization.name).like(f"%{search.lower()}%"))
    if is_active is not None: q = q.filter(Organization.is_active == is_active)
    return paginate(q.order_by(Organization.name), page, page_size)

@router.put('/organizations/{org_id}', response_model=OrganizationRead, dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def update_organization(org_id: uuid.UUID, payload: OrganizationCreate, db: Session = Depends(get_db)):
    o = db.query(Organization).filter(Organization.id == org_id).first()
    if not o: raise HTTPException(404, 'Organization not found')
    for k, v in payload.model_dump().items(): setattr(o, k, v)
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
def delete_organization(org_id: uuid.UUID, force: bool = Query(False), db: Session = Depends(get_db)):
    def _log_delete_step(step: str, organization_name: str, rows_affected: int | None = None, table: str | None = None):
        logger.info(
            '[ORG DELETE] organization_id=%s organization_name=%s step=%s table=%s rows_affected=%s',
            org_id,
            organization_name,
            step,
            table or 'n/a',
            rows_affected if rows_affected is not None else 'n/a',
        )

    def _execute_step(step: str, organization_name: str, sql: str, table: str) -> int:
        result = db.execute(text(sql), {'org_id': str(org_id)})
        rowcount = result.rowcount or 0
        _log_delete_step(step, organization_name, rowcount, table)
        return rowcount

    try:
        def _cleanup_team_dependencies_for_org(org_id_value: uuid.UUID) -> tuple[int, int, int]:
            # Mandatory direct-SQL cleanup immediately before any organization delete.
            db.execute(text("""
                DELETE FROM games
                WHERE home_team_id IN (
                    SELECT id FROM teams WHERE organization_id = :org_id
                )
                OR away_team_id IN (
                    SELECT id FROM teams WHERE organization_id = :org_id
                )
            """), {"org_id": str(org_id_value)})

            # Find all FK columns that reference teams.id and clear dependent rows first.
            team_fk_refs = db.execute(text("""
                SELECT
                    tc.table_name AS table_name,
                    kcu.column_name AS column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = 'public'
                  AND ccu.table_name = 'teams'
                  AND ccu.column_name = 'id'
                  AND tc.table_name <> 'teams'
                ORDER BY tc.table_name, kcu.column_name
            """)).mappings().all()

            for ref in team_fk_refs:
                table_name = ref['table_name']
                column_name = ref['column_name']
                db.execute(text(f"""
                    DELETE FROM {table_name}
                    WHERE {column_name} IN (
                        SELECT id
                        FROM teams
                        WHERE organization_id = :org_id
                    )
                """), {"org_id": str(org_id_value)})

            teams_before_delete = db.execute(text("""
                SELECT COUNT(*)
                FROM teams
                WHERE organization_id = :org_id
            """), {'org_id': str(org_id_value)}).scalar() or 0
            logger.info('[ORG DELETE] teams before delete: %s', teams_before_delete)

            team_delete_result = db.execute(text("""
                DELETE FROM teams
                WHERE organization_id = :org_id
            """), {'org_id': str(org_id_value)})
            teams_deleted = team_delete_result.rowcount or 0
            logger.info('[ORG DELETE] teams deleted rowcount: %s', teams_deleted)

            teams_after_delete = db.execute(text("""
                SELECT COUNT(*)
                FROM teams
                WHERE organization_id = :org_id
            """), {'org_id': str(org_id_value)}).scalar() or 0
            logger.info('[ORG DELETE] teams remaining after delete: %s', teams_after_delete)
            return teams_before_delete, teams_deleted, teams_after_delete

        o = db.query(Organization).filter(Organization.id == org_id).first()
        if not o:
            raise HTTPException(404, 'Organization not found')
        org_name = o.name

        if not force:
            deleted_game_slots = db.execute(text("""
                DELETE FROM game_slots
                WHERE field_instance_id IN (
                    SELECT fi.id
                    FROM field_instances fi
                    JOIN hosting_availabilities ha
                        ON fi.hosting_availability_id = ha.id
                    JOIN field_configuration_options fco
                        ON ha.field_configuration_option_id = fco.id
                    JOIN physical_field_areas pfa
                        ON fco.physical_field_area_id = pfa.id
                    JOIN host_locations hl
                        ON pfa.host_location_id = hl.id
                    WHERE hl.organization_id = :org_id
                )
            """), {"org_id": str(org_id)}).rowcount or 0
            logger.info(f"[ORG DELETE] game_slots deleted: {deleted_game_slots}")

            remaining_game_slots = db.execute(text("""
                SELECT COUNT(*)
                FROM game_slots
                WHERE field_instance_id IN (
                    SELECT fi.id
                    FROM field_instances fi
                    JOIN hosting_availabilities ha
                        ON fi.hosting_availability_id = ha.id
                    JOIN field_configuration_options fco
                        ON ha.field_configuration_option_id = fco.id
                    JOIN physical_field_areas pfa
                        ON fco.physical_field_area_id = pfa.id
                    JOIN host_locations hl
                        ON pfa.host_location_id = hl.id
                    WHERE hl.organization_id = :org_id
                )
            """), {"org_id": str(org_id)}).scalar() or 0
            logger.info(f"[ORG DELETE] game_slots remaining after delete: {remaining_game_slots}")
            if remaining_game_slots > 0:
                raise HTTPException(409, "Delete blocked. game_slots still reference field_instances.")

            deleted_field_instances = db.execute(text("""
                DELETE FROM field_instances
                WHERE hosting_availability_id IN (
                    SELECT ha.id
                    FROM hosting_availabilities ha
                    JOIN field_configuration_options fco
                        ON ha.field_configuration_option_id = fco.id
                    JOIN physical_field_areas pfa
                        ON fco.physical_field_area_id = pfa.id
                    JOIN host_locations hl
                        ON pfa.host_location_id = hl.id
                    WHERE hl.organization_id = :org_id
                )
            """), {"org_id": str(org_id)}).rowcount or 0
            logger.info(f"[ORG DELETE] field_instances deleted: {deleted_field_instances}")

            deleted_hosting_availabilities = db.execute(text("""
                DELETE FROM hosting_availabilities
                WHERE field_configuration_option_id IN (
                    SELECT fco.id
                    FROM field_configuration_options fco
                    JOIN physical_field_areas pfa
                        ON fco.physical_field_area_id = pfa.id
                    JOIN host_locations hl
                        ON pfa.host_location_id = hl.id
                    WHERE hl.organization_id = :org_id
                )
            """), {"org_id": str(org_id)}).rowcount or 0
            logger.info(f"[ORG DELETE] hosting_availabilities deleted: {deleted_hosting_availabilities}")

            deleted_field_configuration_options = db.execute(text("""
                DELETE FROM field_configuration_options
                WHERE physical_field_area_id IN (
                    SELECT pfa.id
                    FROM physical_field_areas pfa
                    JOIN host_locations hl
                        ON pfa.host_location_id = hl.id
                    WHERE hl.organization_id = :org_id
                )
            """), {"org_id": str(org_id)}).rowcount or 0
            logger.info(f"[ORG DELETE] field_configuration_options deleted: {deleted_field_configuration_options}")

            deleted_physical_field_areas = db.execute(text("""
                DELETE FROM physical_field_areas
                WHERE host_location_id IN (
                    SELECT id
                    FROM host_locations
                    WHERE organization_id = :org_id
                )
            """), {"org_id": str(org_id)}).rowcount or 0
            logger.info(f"[ORG DELETE] physical_field_areas deleted: {deleted_physical_field_areas}")

            remaining_physical_field_areas = db.execute(text("""
                SELECT COUNT(*)
                FROM physical_field_areas
                WHERE host_location_id IN (
                    SELECT id
                    FROM host_locations
                    WHERE organization_id = :org_id
                )
            """), {"org_id": str(org_id)}).scalar() or 0
            logger.info(f"[ORG DELETE] physical_field_areas remaining after delete: {remaining_physical_field_areas}")

            if remaining_physical_field_areas > 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Delete blocked. {remaining_physical_field_areas} physical_field_areas still reference host_locations for organization {org_id}.",
                )

            host_count = db.execute(text("""
                SELECT COUNT(*)
                FROM host_locations
                WHERE organization_id = :org_id
            """), {"org_id": str(org_id)}).scalar()
            logger.info(f"[ORG DELETE] host_locations before delete: {host_count}")

            result = db.execute(text("""
                DELETE FROM host_locations
                WHERE organization_id = :org_id
            """), {"org_id": str(org_id)})
            logger.info(f"[ORG DELETE] host_locations deleted: {result.rowcount}")

            db.flush()

            remaining = db.execute(text("""
                SELECT COUNT(*)
                FROM host_locations
                WHERE organization_id = :org_id
            """), {"org_id": str(org_id)}).scalar()
            logger.info(f"[ORG DELETE] host_locations remaining after delete: {remaining}")

            if remaining > 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Delete blocked. {remaining} host_locations still reference organization {org_id}.",
                )

            _, _, teams_after_delete = _cleanup_team_dependencies_for_org(org_id)
            if teams_after_delete > 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Delete blocked. {teams_after_delete} teams still reference this organization.",
                )

            logger.info('[ORG DELETE] final organization delete started')
            result = db.execute(text('DELETE FROM organizations WHERE id = :org_id'), {'org_id': str(org_id)})
            db.commit()
            return {'success': True, 'deleted': {'organization': result.rowcount or 0}}

        rowcounts: dict[str, int] = {}

        rowcounts['games_by_team'] = _execute_step('delete_games_by_team', org_name, """
            DELETE FROM games
            WHERE home_team_id IN (
              SELECT id FROM teams WHERE organization_id = :org_id
            )
            OR away_team_id IN (
              SELECT id FROM teams WHERE organization_id = :org_id
            )
        """, 'games')

        rowcounts['games_by_slot'] = _execute_step('delete_games_by_generated_slots', org_name, """
            DELETE FROM games
            WHERE generated_slot_id IN (
              SELECT gs.id
              FROM generated_slots gs
              JOIN host_locations hl ON gs.host_location_id = hl.id
              WHERE hl.organization_id = :org_id
            )
        """, 'games')

        rowcounts['game_slots'] = _execute_step('delete_game_slots_by_field_instances', org_name, """
            DELETE FROM game_slots
            WHERE field_instance_id IN (
                SELECT fi.id
                FROM field_instances fi
                JOIN hosting_availabilities ha
                    ON fi.hosting_availability_id = ha.id
                JOIN field_configuration_options fco
                    ON ha.field_configuration_option_id = fco.id
                JOIN physical_field_areas pfa
                    ON fco.physical_field_area_id = pfa.id
                JOIN host_locations hl
                    ON pfa.host_location_id = hl.id
                WHERE hl.organization_id = :org_id
            )
        """, 'game_slots')

        rowcounts['field_instances'] = _execute_step('delete_field_instances', org_name, """
            DELETE FROM field_instances
            WHERE hosting_availability_id IN (
                SELECT ha.id
                FROM hosting_availabilities ha
                JOIN field_configuration_options fco
                    ON ha.field_configuration_option_id = fco.id
                JOIN physical_field_areas pfa
                    ON fco.physical_field_area_id = pfa.id
                JOIN host_locations hl
                    ON pfa.host_location_id = hl.id
                WHERE hl.organization_id = :org_id
            )
        """, 'field_instances')

        rowcounts['hosting_availabilities'] = _execute_step('delete_hosting_availabilities', org_name, """
            DELETE FROM hosting_availabilities
            WHERE field_configuration_option_id IN (
                SELECT fco.id
                FROM field_configuration_options fco
                JOIN physical_field_areas pfa
                    ON fco.physical_field_area_id = pfa.id
                JOIN host_locations hl
                    ON pfa.host_location_id = hl.id
                WHERE hl.organization_id = :org_id
            )
        """, 'hosting_availabilities')

        rowcounts['field_configuration_options'] = _execute_step('delete_field_configuration_options', org_name, """
            DELETE FROM field_configuration_options
            WHERE physical_field_area_id IN (
                SELECT pfa.id
                FROM physical_field_areas pfa
                JOIN host_locations hl
                    ON pfa.host_location_id = hl.id
                WHERE hl.organization_id = :org_id
            )
        """, 'field_configuration_options')

        rowcounts['physical_field_areas'] = _execute_step('delete_physical_field_areas', org_name, """
            DELETE FROM physical_field_areas
            WHERE host_location_id IN (
              SELECT id
              FROM host_locations
              WHERE organization_id = :org_id
            )
        """, 'physical_field_areas')

        rowcounts['generated_slots'] = _execute_step('delete_generated_slots', org_name, """
            DELETE FROM generated_slots
            WHERE host_location_id IN (
              SELECT id FROM host_locations WHERE organization_id = :org_id
            )
        """, 'generated_slots')

        remaining_physical_field_areas = db.execute(text("""
            SELECT COUNT(*)
            FROM physical_field_areas
            WHERE host_location_id IN (
                SELECT id
                FROM host_locations
                WHERE organization_id = :org_id
            )
        """), {'org_id': str(org_id)}).scalar() or 0
        logger.info(f"[ORG DELETE] physical_field_areas remaining after delete: {remaining_physical_field_areas}")

        if remaining_physical_field_areas > 0:
            raise HTTPException(
                status_code=409,
                detail=f"Delete blocked. {remaining_physical_field_areas} physical_field_areas still reference host_locations for organization {org_id}.",
            )

        host_count = db.execute(text("""
            SELECT COUNT(*)
            FROM host_locations
            WHERE organization_id = :org_id
        """), {"org_id": str(org_id)}).scalar()
        logger.info(f"[ORG DELETE] host_locations before delete: {host_count}")

        result = db.execute(text("""
            DELETE FROM host_locations
            WHERE organization_id = :org_id
        """), {"org_id": str(org_id)})
        logger.info(f"[ORG DELETE] host_locations deleted: {result.rowcount}")
        rowcounts['host_locations'] = result.rowcount or 0

        db.flush()

        remaining = db.execute(text("""
            SELECT COUNT(*)
            FROM host_locations
            WHERE organization_id = :org_id
        """), {'org_id': str(org_id)}).scalar() or 0
        logger.info(f"[ORG DELETE] host_locations remaining after delete: {remaining}")

        if remaining > 0:
            raise HTTPException(
                status_code=409,
                detail=f"Delete blocked. {remaining} host_locations still reference organization {org_id}.",
            )

        rowcounts['community_division_participation'] = _execute_step('delete_community_division_participation', org_name, """
            DELETE FROM community_division_participation
            WHERE organization_id = :org_id
        """, 'community_division_participation')

        teams_before_delete, teams_deleted, teams_after_delete = _cleanup_team_dependencies_for_org(org_id)
        rowcounts['teams_before_delete'] = teams_before_delete
        rowcounts['teams'] = teams_deleted
        rowcounts['teams_remaining_after_delete'] = teams_after_delete

        host_locations_remaining_before_org_delete = db.execute(text("""
            SELECT COUNT(*)
            FROM host_locations
            WHERE organization_id = :org_id
        """), {'org_id': str(org_id)}).scalar() or 0

        if teams_after_delete > 0 or host_locations_remaining_before_org_delete > 0:
            raise HTTPException(
                status_code=409,
                detail=f"Delete blocked. Remaining dependencies: teams={teams_after_delete}, host_locations={host_locations_remaining_before_org_delete}",
            )

        logger.info('[ORG DELETE] final organization delete started')
        rowcounts['organization'] = _execute_step('delete_organization', org_name, """
            DELETE FROM organizations
            WHERE id = :org_id
        """, 'organizations')

        db.commit()

        response = {
            'success': True,
            'message': 'Organization and related records deleted.',
            'host_locations_remaining': remaining,
            'organization_deleted': rowcounts['organization'] > 0,
        }

        import os
        env = (os.getenv('APP_ENV') or os.getenv('ENV') or os.getenv('ENVIRONMENT') or 'development').lower()
        if env in {'dev', 'development', 'local'}:
            response['rowcounts'] = rowcounts

        return response
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception('Organization delete failed for org_id=%s force=%s', org_id, force)
        raise HTTPException(status_code=500, detail={'error': 'organization_delete_failed', 'stage': 'unhandled', 'message': f'Delete failed during unhandled: {str(exc)}', 'raw_error': str(exc)})


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
    {'name': 'K/1st', 'division_group': 'COED', 'sort_order': 1, 'required_field_layout_type': 'THIRTY_YARD_WIDTH', 'is_active': True},
    {'name': '2nd/3rd', 'division_group': 'COED', 'sort_order': 2, 'required_field_layout_type': 'THIRTY_YARD_WIDTH', 'is_active': True},
    {'name': '4th/5th', 'division_group': 'COED', 'sort_order': 3, 'required_field_layout_type': 'THIRTY_YARD_WIDTH', 'is_active': True},
    {'name': '6th/7th', 'division_group': 'COED', 'sort_order': 4, 'required_field_layout_type': 'FIFTY_THREE_YARD_WIDTH', 'is_active': True},
    {'name': '8th', 'division_group': 'COED', 'sort_order': 5, 'required_field_layout_type': 'FIFTY_THREE_YARD_WIDTH', 'is_active': True},
    {'name': 'K/1st', 'division_group': 'GIRLS', 'sort_order': 1, 'required_field_layout_type': 'THIRTY_YARD_WIDTH', 'is_active': True},
    {'name': '2nd/3rd', 'division_group': 'GIRLS', 'sort_order': 2, 'required_field_layout_type': 'THIRTY_YARD_WIDTH', 'is_active': True},
    {'name': '4th/5th', 'division_group': 'GIRLS', 'sort_order': 3, 'required_field_layout_type': 'THIRTY_YARD_WIDTH', 'is_active': True},
    {'name': '6th/7th/8th', 'division_group': 'GIRLS', 'sort_order': 4, 'required_field_layout_type': 'FIFTY_THREE_YARD_WIDTH', 'is_active': True},
]


def ensure_league_defined_divisions(db: Session) -> None:
    changed = False
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



@router.get('/schedule-readiness', response_model=ScheduleReadinessResponse, dependencies=[Depends(get_current_user)])
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
    ).group_by(
        Division.id, Division.division_group, Division.name, Division.sort_order, Division.required_field_layout_type
    ).order_by(Division.division_group, Division.sort_order, Division.name).all()

    open_slot_counts = dict(
        db.query(GameSlot.field_type, func.count(GameSlot.id))
        .filter(GameSlot.status == 'OPEN')
        .group_by(GameSlot.field_type)
        .all()
    )

    small_slots = int(open_slot_counts.get('SMALL', 0) or 0)
    large_slots = int(open_slot_counts.get('LARGE', 0) or 0)

    rows: list[ScheduleReadinessDivisionRow] = []
    total_teams = 0
    total_games_needed = 0

    for row in division_rows:
        teams = int(row.team_count or 0)
        games_needed = (teams * (teams - 1)) // 2
        required_field_type = 'SMALL' if row.required_field_layout_type == 'THIRTY_YARD_WIDTH' else 'LARGE'
        available_matching_slots = small_slots if required_field_type == 'SMALL' else large_slots

        if teams == 0:
            status = 'NO TEAMS'
        elif available_matching_slots >= games_needed:
            status = 'READY'
        else:
            status = 'SHORT'

        rows.append(ScheduleReadinessDivisionRow(
            division_id=row.division_id,
            division_label=f"{row.division_group.title()} {row.division_name}",
            field_type_required=required_field_type,
            number_of_teams=teams,
            estimated_games_needed=games_needed,
            available_matching_slots=available_matching_slots,
            status=status,
        ))
        total_teams += teams
        total_games_needed += games_needed

    return ScheduleReadinessResponse(
        rows=rows,
        totals=ScheduleReadinessTotals(
            total_teams=total_teams,
            total_games_needed=total_games_needed,
            total_small_field_slots=small_slots,
            total_large_field_slots=large_slots,
            total_open_slots=small_slots + large_slots,
        ),
    )
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


@router.put('/organization-division-participation', response_model=list[OrganizationDivisionParticipationRead], dependencies=[Depends(get_current_user)])
def upsert_organization_division_participation(
    payload: OrganizationDivisionParticipationBulkUpsertRequest,
    current_user: User = Depends(get_current_user),
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
    x = HostLocation(**payload.model_dump()); db.add(x); db.commit(); db.refresh(x); return x

@router.get('/host-locations', response_model=PagedResponse[HostLocationRead], dependencies=[Depends(get_current_user)])
def list_host_locations(search: str | None = None, organization_id: uuid.UUID | None = None, is_active: bool | None = None, page: int = 1, page_size: int = 20, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(HostLocation)
    if current_user.role.name == ROLE_COMMUNITY_SCHEDULER: q = q.filter(HostLocation.organization_id == current_user.organization_id)
    elif organization_id: q = q.filter(HostLocation.organization_id == organization_id)
    if search: q = q.filter(func.lower(HostLocation.name).like(f"%{search.lower()}%"))
    if is_active is not None: q = q.filter(HostLocation.is_active == is_active)
    return paginate(q.order_by(HostLocation.name), page, page_size)

@router.put('/host-locations/{item_id}', response_model=HostLocationRead, dependencies=[Depends(get_current_user)])
def upd_host_location(item_id: uuid.UUID, payload: HostLocationCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(HostLocation).filter(HostLocation.id == item_id).first()
    if not x: raise HTTPException(404, 'Host location not found')
    enforce_organization_scope(payload.organization_id, current_user)
    for k, v in payload.model_dump().items(): setattr(x, k, v)
    db.commit(); db.refresh(x); return x

@router.get('/host-locations/{item_id}/delete-check', dependencies=[Depends(get_current_user)])
def get_host_location_delete_check(item_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(HostLocation).filter(HostLocation.id == item_id).first()
    if not x: raise HTTPException(404, 'Host location not found')
    enforce_organization_scope(x.organization_id, current_user)
    dependencies = _host_location_dependency_summary(db, item_id)
    return {
        'host_location_id': str(x.id),
        'host_location_name': x.name,
        'can_delete': all(count == 0 for _, count in dependencies),
        'dependencies': [{'label': label, 'count': count} for label, count in dependencies],
    }


@router.delete('/host-locations/{item_id}', dependencies=[Depends(get_current_user)])
def del_host_location(item_id: uuid.UUID, force: bool = Query(False), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(HostLocation).filter(HostLocation.id == item_id).first()
    if not x: raise HTTPException(404, 'Host location not found')
    enforce_organization_scope(x.organization_id, current_user)
    dependencies = _host_location_dependency_summary(db, item_id)
    dependency_map = {label: count for label, count in dependencies}

    if not force:
        detail = _format_delete_blockers(x.name, dependencies)
        if detail:
            raise HTTPException(400, detail)
        db.delete(x); db.commit(); return {'ok': True, 'deleted': {'host_locations': 1}}

    require_roles(ROLE_LEAGUE_ADMIN)(current_user)
    if dependency_map.get('Published Games', 0) > 0:
        raise HTTPException(400, "Cannot force delete host location with published games.")

    field_ids = [field_id for (field_id,) in db.query(Field.id).filter(Field.host_location_id == item_id).all()]
    area_ids = [area_id for (area_id,) in db.query(PhysicalFieldArea.id).filter(PhysicalFieldArea.host_location_id == item_id).all()]

    deleted_games = db.query(Game).filter(Game.field_id.in_(field_ids)).delete(synchronize_session=False) if field_ids else 0
    deleted_hosting_availability = db.query(HostingAvailability).filter(
        (HostingAvailability.field_id.in_(field_ids)) | (HostingAvailability.physical_field_area_id.in_(area_ids))
    ).delete(synchronize_session=False) if (field_ids or area_ids) else 0
    deleted_field_configuration_options = db.query(FieldConfigurationOption).filter(FieldConfigurationOption.physical_field_area_id.in_(area_ids)).delete(synchronize_session=False) if area_ids else 0
    deleted_fields = db.query(Field).filter(Field.id.in_(field_ids)).delete(synchronize_session=False) if field_ids else 0
    deleted_physical_field_areas = db.query(PhysicalFieldArea).filter(PhysicalFieldArea.id.in_(area_ids)).delete(synchronize_session=False) if area_ids else 0
    db.delete(x)
    db.commit()

    return {
        'ok': True,
        'deleted': {
            'host_locations': 1,
            'fields': deleted_fields,
            'physical_field_areas': deleted_physical_field_areas,
            'hosting_availability': deleted_hosting_availability,
            'field_configuration_options': deleted_field_configuration_options,
            'games': deleted_games,
        }
    }

@router.post('/physical-field-areas', response_model=PhysicalFieldAreaRead, dependencies=[Depends(get_current_user)])
def create_physical_field_area(payload: PhysicalFieldAreaCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    host_location = db.query(HostLocation).filter(HostLocation.id == payload.host_location_id).first()
    if not host_location: raise HTTPException(400, 'Invalid host location')
    enforce_organization_scope(host_location.organization_id, current_user)
    if payload.field_space_type not in ALLOWED_FIELD_SPACE_TYPES:
        raise HTTPException(400, f"Invalid field space type: {payload.field_space_type}")
    x = PhysicalFieldArea(**payload.model_dump()); db.add(x); db.commit(); db.refresh(x); return x

@router.get('/physical-field-areas', response_model=PagedResponse[PhysicalFieldAreaRead], dependencies=[Depends(get_current_user)])
def list_physical_field_areas(host_location_id: uuid.UUID | None = None, page: int = 1, page_size: int = 50, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(PhysicalFieldArea).join(PhysicalFieldArea.host_location)
    if current_user.role.name == ROLE_COMMUNITY_SCHEDULER: q = q.filter(HostLocation.organization_id == current_user.organization_id)
    if host_location_id: q = q.filter(PhysicalFieldArea.host_location_id == host_location_id)
    return paginate(q.order_by(PhysicalFieldArea.name), page, page_size)

@router.put('/physical-field-areas/{item_id}', response_model=PhysicalFieldAreaRead, dependencies=[Depends(get_current_user)])
def upd_physical_field_area(item_id: uuid.UUID, payload: PhysicalFieldAreaCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(PhysicalFieldArea).filter(PhysicalFieldArea.id == item_id).first()
    if not x: raise HTTPException(404, 'Physical field area not found')
    host_location = db.query(HostLocation).filter(HostLocation.id == payload.host_location_id).first()
    if not host_location: raise HTTPException(400, 'Invalid host location')
    enforce_organization_scope(host_location.organization_id, current_user)
    if payload.field_space_type not in ALLOWED_FIELD_SPACE_TYPES:
        raise HTTPException(400, f"Invalid field space type: {payload.field_space_type}")
    for k, v in payload.model_dump().items(): setattr(x, k, v)
    db.commit(); db.refresh(x); return x

@router.post('/field-configuration-options', response_model=FieldConfigurationOptionRead, dependencies=[Depends(get_current_user)])
def create_field_configuration_option(payload: FieldConfigurationOptionCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    area = db.query(PhysicalFieldArea).join(PhysicalFieldArea.host_location).filter(PhysicalFieldArea.id == payload.physical_field_area_id).first()
    if not area: raise HTTPException(400, 'Invalid physical field area')
    enforce_organization_scope(area.host_location.organization_id, current_user)
    if payload.thirty_yard_capacity < 0 or payload.fifty_three_yard_capacity < 0:
        raise HTTPException(400, 'Capacities must be non-negative')
    x = FieldConfigurationOption(**payload.model_dump()); db.add(x); db.commit(); db.refresh(x); return x

@router.get('/field-configuration-options', response_model=PagedResponse[FieldConfigurationOptionRead], dependencies=[Depends(get_current_user)])
def list_field_configuration_options(physical_field_area_id: uuid.UUID | None = None, page: int = 1, page_size: int = 50, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(FieldConfigurationOption).join(FieldConfigurationOption.physical_field_area).join(PhysicalFieldArea.host_location)
    if current_user.role.name == ROLE_COMMUNITY_SCHEDULER: q = q.filter(HostLocation.organization_id == current_user.organization_id)
    if physical_field_area_id: q = q.filter(FieldConfigurationOption.physical_field_area_id == physical_field_area_id)
    return paginate(q.order_by(FieldConfigurationOption.name), page, page_size)

@router.put('/field-configuration-options/{item_id}', response_model=FieldConfigurationOptionRead, dependencies=[Depends(get_current_user)])
def upd_field_configuration_option(item_id: uuid.UUID, payload: FieldConfigurationOptionCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(FieldConfigurationOption).filter(FieldConfigurationOption.id == item_id).first()
    if not x: raise HTTPException(404, 'Field configuration option not found')
    area = db.query(PhysicalFieldArea).join(PhysicalFieldArea.host_location).filter(PhysicalFieldArea.id == payload.physical_field_area_id).first()
    if not area: raise HTTPException(400, 'Invalid physical field area')
    enforce_organization_scope(area.host_location.organization_id, current_user)
    if payload.thirty_yard_capacity < 0 or payload.fifty_three_yard_capacity < 0:
        raise HTTPException(400, 'Capacities must be non-negative')
    for k, v in payload.model_dump().items(): setattr(x, k, v)
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
    if payload.physical_field_area_id:
        area = db.query(PhysicalFieldArea).filter(PhysicalFieldArea.id == payload.physical_field_area_id, PhysicalFieldArea.host_location_id == payload.host_location_id).first()
        if not area: raise HTTPException(400, 'Invalid physical field area for host location')
    x = Field(**payload.model_dump()); db.add(x); db.commit(); db.refresh(x); return x

@router.get('/fields', response_model=PagedResponse[FieldRead], dependencies=[Depends(get_current_user)])
def list_fields(search: str | None = None, host_location_id: uuid.UUID | None = None, page: int = 1, page_size: int = 20, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Field).join(Field.host_location)
    if current_user.role.name == ROLE_COMMUNITY_SCHEDULER: q = q.filter(HostLocation.organization_id == current_user.organization_id)
    if host_location_id: q = q.filter(Field.host_location_id == host_location_id)
    if search: q = q.filter(func.lower(Field.name).like(f"%{search.lower()}%"))
    return paginate(q.order_by(Field.name), page, page_size)

@router.put('/fields/{item_id}', response_model=FieldRead, dependencies=[Depends(get_current_user)])
def upd_field(item_id: uuid.UUID, payload: FieldCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(Field).filter(Field.id == item_id).first()
    if not x: raise HTTPException(404, 'Field not found')
    host_location = db.query(HostLocation).filter(HostLocation.id == payload.host_location_id).first()
    if not host_location: raise HTTPException(400, 'Invalid host location')
    enforce_organization_scope(host_location.organization_id, current_user)
    for k, v in payload.model_dump().items(): setattr(x, k, v)
    db.commit(); db.refresh(x); return x

@router.delete('/fields/{item_id}', dependencies=[Depends(get_current_user)])
def del_field(item_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(Field).filter(Field.id == item_id).first()
    if not x: raise HTTPException(404, 'Field not found')
    enforce_organization_scope(x.host_location.organization_id, current_user)
    db.delete(x); db.commit(); return {'ok': True}

@router.post('/hosting-availabilities', response_model=HostingAvailabilityRead, dependencies=[Depends(get_current_user)])
def create_hosting_availability(payload: HostingAvailabilityCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    field = None
    area = None
    if payload.field_id:
        field = db.query(Field).join(Field.host_location).filter(Field.id == payload.field_id).first()
        if not field: raise HTTPException(400, 'Invalid field')
        enforce_organization_scope(field.host_location.organization_id, current_user)
    elif payload.physical_field_area_id:
        area = db.query(PhysicalFieldArea).join(PhysicalFieldArea.host_location).filter(PhysicalFieldArea.id == payload.physical_field_area_id).first()
        if not area: raise HTTPException(400, 'Invalid physical field area')
        enforce_organization_scope(area.host_location.organization_id, current_user)
    else:
        raise HTTPException(400, 'field_id or physical_field_area_id is required')
    validate_hour_block(payload.start_time, payload.end_time)
    x = HostingAvailability(**payload.model_dump()); db.add(x); db.flush()
    resolved_host_id = area.host_location_id if area else field.host_location_id
    _regenerate_generated_slots(db, x, resolved_host_id)
    db.commit(); db.refresh(x); return x

@router.get('/hosting-availabilities', response_model=PagedResponse[HostingAvailabilityRead], dependencies=[Depends(get_current_user)])
def list_hosting_availabilities(field_id: uuid.UUID | None = None, field_ids: str | None = None, host_location_id: uuid.UUID | None = None, organization_id: uuid.UUID | None = None, available_date: str | None = None, available_dates: str | None = None, page: int = 1, page_size: int = 20, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(HostingAvailability).join(HostingAvailability.field).join(Field.host_location)
    if current_user.role.name == ROLE_COMMUNITY_SCHEDULER: q = q.filter(HostLocation.organization_id == current_user.organization_id)
    elif organization_id: q = q.filter(HostLocation.organization_id == organization_id)
    if host_location_id: q = q.filter(Field.host_location_id == host_location_id)
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
    field = None
    area = None
    if payload.field_id:
        field = db.query(Field).join(Field.host_location).filter(Field.id == payload.field_id).first()
        if not field: raise HTTPException(400, 'Invalid field')
        enforce_organization_scope(field.host_location.organization_id, current_user)
    elif payload.physical_field_area_id:
        area = db.query(PhysicalFieldArea).join(PhysicalFieldArea.host_location).filter(PhysicalFieldArea.id == payload.physical_field_area_id).first()
        if not area: raise HTTPException(400, 'Invalid physical field area')
        enforce_organization_scope(area.host_location.organization_id, current_user)
    validate_hour_block(payload.start_time, payload.end_time)
    for k, v in payload.model_dump().items(): setattr(x, k, v)
    db.flush()
    resolved_host_id = area.host_location_id if area else field.host_location_id
    _regenerate_generated_slots(db, x, resolved_host_id)
    db.commit(); db.refresh(x); return x

@router.delete('/hosting-availabilities/{item_id}', dependencies=[Depends(get_current_user)])
def del_hosting_availability(item_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(HostingAvailability).filter(HostingAvailability.id == item_id).first()
    if not x: raise HTTPException(404, 'Hosting availability not found')
    enforce_organization_scope(x.field.host_location.organization_id, current_user)
    host_location_id = x.physical_field_area.host_location_id if x.physical_field_area_id else x.field.host_location_id
    _delete_availability_with_generated_slots_guard(db, [x.id], host_location_id, x.available_date)
    db.delete(x); db.commit(); return {'ok': True}



@router.post('/hosting-availabilities/bulk-upsert', response_model=HostingAvailabilityBulkUpsertResponse, dependencies=[Depends(get_current_user)])
def bulk_upsert_hosting_availabilities(payload: HostingAvailabilityBulkUpsertRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    created = 0
    updated = 0
    for slot in payload.slots:
        if slot.field_id:
            field = db.query(Field).join(Field.host_location).filter(Field.id == slot.field_id).first()
            if not field: raise HTTPException(400, f'Invalid field: {slot.field_id}')
            enforce_organization_scope(field.host_location.organization_id, current_user)
        elif slot.physical_field_area_id:
            area = db.query(PhysicalFieldArea).join(PhysicalFieldArea.host_location).filter(PhysicalFieldArea.id == slot.physical_field_area_id).first()
            if not area: raise HTTPException(400, f'Invalid physical field area: {slot.physical_field_area_id}')
            enforce_organization_scope(area.host_location.organization_id, current_user)
            if not slot.field_configuration_option_id:
                raise HTTPException(400, 'field_configuration_option_id is required for physical field area slots')
            option = db.query(FieldConfigurationOption).filter(FieldConfigurationOption.id == slot.field_configuration_option_id, FieldConfigurationOption.physical_field_area_id == slot.physical_field_area_id).first()
            if not option: raise HTTPException(400, f'Invalid field configuration option: {slot.field_configuration_option_id}')
        else:
            raise HTTPException(400, 'Each slot must include field_id or physical_field_area_id')
        validate_hour_block(slot.start_time, slot.end_time)
        existing = db.query(HostingAvailability).filter(
            HostingAvailability.field_id == slot.field_id,
            HostingAvailability.physical_field_area_id == slot.physical_field_area_id,
            HostingAvailability.available_date == slot.available_date,
            HostingAvailability.start_time == slot.start_time,
            HostingAvailability.end_time == slot.end_time,
            HostingAvailability.layout_type == slot.layout_type,
            HostingAvailability.slot_index == slot.slot_index,
        ).first()
        if existing:
            existing.is_available = slot.is_available
            updated += 1
            _regenerate_generated_slots(db, existing, area.host_location_id if slot.physical_field_area_id else field.host_location_id)
        else:
            availability = HostingAvailability(**slot.model_dump())
            db.add(availability)
            db.flush()
            _regenerate_generated_slots(db, availability, area.host_location_id if slot.physical_field_area_id else field.host_location_id)
            created += 1
    db.commit()
    generated_field_instances = db.query(FieldInstance).join(FieldInstance.hosting_availability).join(HostingAvailability.physical_field_area).join(PhysicalFieldArea.host_location)
    generated_slots = db.query(GameSlot).join(GameSlot.host_location)
    if current_user.role.name == ROLE_COMMUNITY_SCHEDULER:
        generated_field_instances = generated_field_instances.filter(HostLocation.organization_id == current_user.organization_id)
        generated_slots = generated_slots.filter(HostLocation.organization_id == current_user.organization_id)
    return HostingAvailabilityBulkUpsertResponse(
        created=created,
        updated=updated,
        generated_field_instances=generated_field_instances.count(),
        generated_slots=generated_slots.count(),
    )
@router.get('/hosting-availabilities/saved', response_model=SavedAvailabilityResponse, dependencies=[Depends(get_current_user)])
def list_saved_hosting_availability(organization_id: uuid.UUID | None = None, host_location_id: uuid.UUID | None = None, site_type: str | None = None, layout: str | None = None, available_date: str | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(HostingAvailability).join(HostingAvailability.physical_field_area).join(PhysicalFieldArea.host_location).outerjoin(HostingAvailability.field_configuration_option).filter(HostingAvailability.is_available.is_(True))
    if current_user.role.name == ROLE_COMMUNITY_SCHEDULER:
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
            layout_small = int(option.thirty_yard_capacity) if option and option.is_active else 0
            layout_large = int(option.fifty_three_yard_capacity) if option and option.is_active else 0
            layout_key = (host_id, layout_name)
            layout_counts = field_counts_by_layout.setdefault(
                layout_key,
                {'small': layout_small, 'large': layout_large, 'total': layout_small + layout_large, 'inactive': 0, 'unmatched': 0, 'mismatch': False, 'fields': []},
            )
            layout_counts['small'] = layout_small
            layout_counts['large'] = layout_large
            layout_counts['total'] = layout_small + layout_large
            layout_counts['mismatch'] = layout_small + layout_large == 0
            grouped[key] = {
                'id': row.id,
                'available_date': row.available_date,
                'organization_id': host.organization_id,
                'organization_name': host.organization.name if host.organization else None,
                'host_location_id': host.id,
                'host_location_name': host.name,
                'site_type': area.field_space_type,
                'available_layout': layout_name,
                'small_field_capacity': layout_counts['small'],
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
                        'large_field_count': layout_counts['large'],
                        'is_active': bool(option.is_active) if option else False,
                    }
                ],
                'hours': []
            }
        grouped[key]['hours'].append(row.start_time.hour)

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
            'available_date': data['available_date'],
            'organization_id': data['organization_id'],
            'organization_name': data['organization_name'],
            'host_location_id': data['host_location_id'],
            'host_location_name': data['host_location_name'],
            'site_type': data['site_type'],
            'available_layout': data['available_layout'],
            'small_field_capacity': data['small_field_capacity'],
            'large_field_capacity': data['large_field_capacity'],
            'total_fields_found': data['total_fields_found'],
            'inactive_field_count': data['inactive_field_count'],
            'unmatched_field_records': data['unmatched_field_records'],
            'has_field_inventory_mismatch': data['has_field_inventory_mismatch'],
            'time_ranges': ranges,
            'hostLocationId': data['host_location_id'],
            'hostLocationName': data['host_location_name'],
            'smallFieldCount': data['small_field_capacity'],
            'largeFieldCount': data['large_field_capacity'],
            'fields': data['fields'],
        })
    items.sort(key=lambda x: (x['available_date'], x['host_location_name']))
    return {'items': items}


@router.delete('/hosting-availabilities/saved/{item_id}', dependencies=[Depends(get_current_user)])
def delete_saved_hosting_availability(item_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        availability_id = uuid.UUID(item_id)
    except ValueError as exc:
        raise HTTPException(400, 'Invalid availability id.') from exc

    sample = db.query(HostingAvailability).join(HostingAvailability.physical_field_area).join(PhysicalFieldArea.host_location).filter(HostingAvailability.id == availability_id).first()
    if not sample:
        raise HTTPException(404, 'Saved availability not found')
    if not sample.physical_field_area or not sample.physical_field_area.host_location:
        raise HTTPException(400, 'Saved availability is missing host location data')

    host_location_id = sample.physical_field_area.host_location.id
    date_value = sample.available_date
    enforce_organization_scope(sample.physical_field_area.host_location.organization_id, current_user)
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
    except SQLAlchemyError:
        db.rollback()
        logger.exception(
            'Availability delete failed availability_ids=%s host_location_id=%s date=%s outcome=db_error',
            availability_ids,
            host_location_id,
            date_value,
        )
        raise HTTPException(500, 'A database error occurred while processing the request.')

    logger.info(
        'Availability delete complete availability_ids=%s host_location_id=%s date=%s deleted_availability_count=%s outcome=success',
        availability_ids,
        host_location_id,
        date_value,
        deleted,
    )
    return {'ok': True, 'deleted': deleted}


def _delete_availability_with_generated_slots_guard(db: Session, availability_ids: list[uuid.UUID], host_location_id: uuid.UUID, available_date: date):
    generated_slot_count = db.query(GameSlot).join(GameSlot.field_instance).filter(
        FieldInstance.hosting_availability_id.in_(availability_ids),
    ).count()
    scheduled_game_count = db.query(GameSlot).join(GameSlot.field_instance).filter(
        FieldInstance.hosting_availability_id.in_(availability_ids),
        GameSlot.assigned_game_id.isnot(None),
    ).count()

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

    db.query(GameSlot).filter(
        GameSlot.field_instance_id.in_(
            db.query(FieldInstance.id).filter(FieldInstance.hosting_availability_id.in_(availability_ids))
        )
    ).delete(synchronize_session=False)
    db.query(FieldInstance).filter(FieldInstance.hosting_availability_id.in_(availability_ids)).delete(synchronize_session=False)
    logger.info(
        'Availability dependent slots removed availability_ids=%s host_location_id=%s date=%s generated_slot_count=%s scheduled_game_count=%s outcome=slots_deleted',
        availability_ids,
        host_location_id,
        available_date,
        generated_slot_count,
        scheduled_game_count,
    )


@router.get('/hosting-availabilities/generated-slots', response_model=list[GeneratedSlotRead], dependencies=[Depends(get_current_user)])
def list_generated_slots(host_location_id: uuid.UUID, available_date: str | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    host = db.query(HostLocation).filter(HostLocation.id == host_location_id).first()
    if not host:
        raise HTTPException(404, 'Host location not found')
    enforce_organization_scope(host.organization_id, current_user)
    q = db.query(GameSlot, FieldInstance.field_name, HostLocation.name.label('host_location_name')).join(GameSlot.field_instance).join(GameSlot.host_location).filter(GameSlot.host_location_id == host_location_id)
    if available_date:
        q = q.filter(func.cast(GameSlot.slot_date, str) == available_date)
    rows = q.order_by(GameSlot.slot_date, GameSlot.start_time, FieldInstance.field_name).all()
    return [{'id': row.GameSlot.id, 'available_date': row.GameSlot.slot_date, 'host_location_name': row.host_location_name, 'field_instance_name': row.field_name, 'field_type': row.GameSlot.field_type, 'start_time': row.GameSlot.start_time, 'end_time': row.GameSlot.end_time, 'status': row.GameSlot.status} for row in rows]


@router.get('/field-instances', dependencies=[Depends(get_current_user)])
def list_field_instances(host_location_id: uuid.UUID | None = None, available_date: str | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(FieldInstance, HostLocation.name.label('host_location_name')).join(FieldInstance.host_location)
    if current_user.role.name == ROLE_COMMUNITY_SCHEDULER:
        q = q.filter(HostLocation.organization_id == current_user.organization_id)
    if host_location_id:
        q = q.filter(FieldInstance.host_location_id == host_location_id)
    if available_date:
        q = q.filter(func.cast(FieldInstance.instance_date, str) == available_date)
    rows = q.order_by(FieldInstance.instance_date, HostLocation.name, FieldInstance.field_name).all()
    return [{'id': r.FieldInstance.id, 'date': r.FieldInstance.instance_date, 'host_location_name': r.host_location_name, 'field_instance_name': r.FieldInstance.field_name, 'field_type': r.FieldInstance.field_type, 'hosting_availability_id': r.FieldInstance.hosting_availability_id} for r in rows]


@router.get('/generated-game-slots', response_model=list[GeneratedSlotRead], dependencies=[Depends(get_current_user)])
def list_generated_game_slots(host_location_id: uuid.UUID | None = None, available_date: str | None = None, status: str | None = None, field_type: str | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(GameSlot, FieldInstance.field_name, HostLocation.name.label('host_location_name')).join(GameSlot.field_instance).join(GameSlot.host_location)
    if current_user.role.name == ROLE_COMMUNITY_SCHEDULER:
        q = q.filter(HostLocation.organization_id == current_user.organization_id)
    if host_location_id:
        q = q.filter(GameSlot.host_location_id == host_location_id)
    if available_date:
        q = q.filter(func.cast(GameSlot.slot_date, str) == available_date)
    if status:
        q = q.filter(GameSlot.status == status)
    if field_type:
        q = q.filter(GameSlot.field_type == field_type)
    rows = q.order_by(GameSlot.slot_date, GameSlot.start_time, FieldInstance.field_name).all()
    return [{'id': row.GameSlot.id, 'available_date': row.GameSlot.slot_date, 'host_location_name': row.host_location_name, 'field_instance_name': row.field_name, 'field_type': row.GameSlot.field_type, 'start_time': row.GameSlot.start_time, 'end_time': row.GameSlot.end_time, 'status': row.GameSlot.status} for row in rows]


@router.post('/generated-game-slots/regenerate', response_model=HostingGenerationRunResult, dependencies=[Depends(get_current_user)])
def regenerate_generated_game_slots(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    host_query = db.query(HostLocation).filter(HostLocation.is_active.is_(True))
    if current_user.role.name == ROLE_COMMUNITY_SCHEDULER:
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
    for host in hosts:
        availabilities = db.query(HostingAvailability).join(HostingAvailability.physical_field_area).filter(
            PhysicalFieldArea.host_location_id == host.id,
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

    db.commit()
    return HostingGenerationRunResult(
        message='Slots generated successfully' if processed > 0 else 'No hosting availability records found.',
        processed=processed,
        skipped=skipped,
        errors=errors,
        total_field_instances_created=total_field_instances,
        total_slots_created=total_slots,
        last_generated_at=datetime.utcnow(),
        results=results,
    )


@router.post('/teams', response_model=TeamRead, dependencies=[Depends(get_current_user)])
def create_team(payload: TeamCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enforce_organization_scope(payload.organization_id, current_user)
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
    if payload.is_active and active_count >= participation.team_count and current_user.role.name != ROLE_LEAGUE_ADMIN:
        raise HTTPException(400, 'Cannot exceed participating team count for this division')
    x = Team(**payload.model_dump()); db.add(x); db.commit(); db.refresh(x); return x

@router.get('/teams', response_model=PagedResponse[TeamRead], dependencies=[Depends(get_current_user)])
def list_teams(search: str | None = None, organization_id: uuid.UUID | None = None, division_id: uuid.UUID | None = None, page: int = 1, page_size: int = 20, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Team)
    if current_user.role.name == ROLE_COMMUNITY_SCHEDULER: q = q.filter(Team.organization_id == current_user.organization_id)
    elif organization_id: q = q.filter(Team.organization_id == organization_id)
    if division_id: q = q.filter(Team.division_id == division_id)
    if search: q = q.filter(func.lower(Team.name).like(f"%{search.lower()}%"))
    return paginate(q.order_by(Team.name), page, page_size)

@router.put('/teams/{item_id}', response_model=TeamRead, dependencies=[Depends(get_current_user)])
def upd_team(item_id: uuid.UUID, payload: TeamCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(Team).filter(Team.id == item_id).first()
    if not x: raise HTTPException(404, 'Team not found')
    enforce_organization_scope(payload.organization_id, current_user)
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
    if payload.is_active and active_count >= participation.team_count and current_user.role.name != ROLE_LEAGUE_ADMIN:
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
        if active_count >= participation.team_count and current_user.role.name != ROLE_LEAGUE_ADMIN:
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
    return PagedResponse(items=[{"id":x.id,"name":x.name} for x in q.offset((page-1)*page_size).limit(page_size).all()], total=q.count(), page=page, page_size=page_size)

@router.get('/weeks', response_model=PagedResponse[dict], dependencies=[Depends(get_current_user)])
def list_weeks(season_id:uuid.UUID|None=None, page:int=1,page_size:int=100, db:Session=Depends(get_db)):
    q=db.query(Week)
    if season_id: q=q.filter(Week.season_id==season_id)
    q=q.order_by(Week.week_number)
    return PagedResponse(items=[{"id":x.id,"season_id":x.season_id,"week_number":x.week_number} for x in q.offset((page-1)*page_size).limit(page_size).all()], total=q.count(), page=page, page_size=page_size)

@router.post('/seasons', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def create_season(payload: dict, db: Session = Depends(get_db)):
    season = Season(name=payload['name'], start_date=payload['start_date'], end_date=payload['end_date'], is_active=bool(payload.get('is_active', True)))
    db.add(season); db.commit(); db.refresh(season)
    return {"id": season.id, "name": season.name}

@router.put('/seasons/{season_id}', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def update_season(season_id: uuid.UUID, payload: dict, db: Session = Depends(get_db)):
    season = db.query(Season).filter(Season.id == season_id).first()
    if not season: raise HTTPException(404, 'Season not found')
    season.name = payload.get('name', season.name); season.start_date = payload.get('start_date', season.start_date); season.end_date = payload.get('end_date', season.end_date); season.is_active = bool(payload.get('is_active', season.is_active))
    db.commit(); db.refresh(season); return {"id": season.id, "name": season.name}

@router.post('/weeks', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def create_week(payload: dict, db: Session = Depends(get_db)):
    week = Week(season_id=payload['season_id'], week_number=payload['week_number'], start_date=payload['start_date'], end_date=payload['end_date'])
    db.add(week); db.commit(); db.refresh(week)
    return {"id": week.id, "week_number": week.week_number, "season_id": week.season_id}

@router.put('/weeks/{week_id}', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def update_week(week_id: uuid.UUID, payload: dict, db: Session = Depends(get_db)):
    week = db.query(Week).filter(Week.id == week_id).first()
    if not week: raise HTTPException(404, 'Week not found')
    week.season_id = payload.get('season_id', week.season_id); week.week_number = payload.get('week_number', week.week_number); week.start_date = payload.get('start_date', week.start_date); week.end_date = payload.get('end_date', week.end_date)
    db.commit(); db.refresh(week); return {"id": week.id, "week_number": week.week_number, "season_id": week.season_id}

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
        field_instance_id=(generated_slot.field_instance_id if generated_slot else None),
        host_location_id=(generated_slot.host_location_id if generated_slot else None),
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
    teams = db.query(Team).filter(Team.is_active.is_(True)).order_by(Team.name).all()
    host_locations = db.query(HostLocation).filter(HostLocation.is_active.is_(True)).order_by(HostLocation.name).all()
    seasons = db.query(Season).filter(Season.is_active.is_(True)).order_by(Season.start_date.desc()).all()
    weeks = db.query(Week).order_by(Week.week_number).all()
    organizations = db.query(Organization).filter(Organization.is_active.is_(True)).order_by(Organization.name).all()
    return {
        'divisions': [{'id': d.id, 'name': d.name, 'division_group': d.division_group, 'sort_order': d.sort_order, 'required_field_layout_type': d.required_field_layout_type, 'required_field_type': 'LARGE' if '53' in (d.required_field_layout_type or '') else 'SMALL'} for d in divisions],
        'teams': [{'id': t.id, 'name': t.name, 'division_id': t.division_id, 'is_active': t.is_active} for t in teams],
        'host_locations': [{'id': h.id, 'name': h.name} for h in host_locations],
        'seasons': [{'id': s.id, 'name': s.name, 'start_date': s.start_date, 'end_date': s.end_date, 'is_active': s.is_active} for s in seasons],
        'weeks': [{'id': w.id, 'season_id': w.season_id, 'week_number': w.week_number, 'start_date': w.start_date, 'end_date': w.end_date} for w in weeks],
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

    teams_q = db.query(Team).filter(Team.is_active.is_(True))
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
    home_team, away_team, adjustment_reason = _enforce_host_owner_home_team(home_team, away_team, host_location)
    if adjustment_reason:
        logger.info(adjustment_reason)
    game = Game(
        season_id=season.id,
        week_id=week.id,
        home_team_id=home_team.id,
        away_team_id=away_team.id,
        field_id=None,
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
    division_group_key = (division.division_group or '').strip().upper()
    selected_division_key = canonical_division_id_from_division(division)
    selected_division_normalized = normalized_division_key(division.division_group, division.name)
    full_division_label = f"{division.division_group} {division.name}".strip() if division.division_group else (division.name or '')
    supported_girls_division_keys = {
        'GIRLS_K_1',
        'GIRLS_2_3',
        'GIRLS_4_5',
        'GIRLS_6_7_8',
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
    required_games_for_division_week = (team_count + 1) // 2 if (is_odd_division and no_byes) else team_count // 2
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
        GameSlot.slot_date == week.start_date,
        GameSlot.field_type == required_field_type,
        GameSlot.assigned_game_id.is_(None),
    ).order_by(GameSlot.slot_date, GameSlot.start_time).all()
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
    assigned_game_slots = db.query(Game, GameSlot).join(GameSlot, GameSlot.assigned_game_id == Game.id).filter(
        Game.game_date == week.start_date
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
        Game.game_date == week.start_date,
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
        (str(row.field_instance_id), row.game_date, row.kickoff_time): row.name
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
            open_field_key = (str(open_slot.field_instance_id), open_slot.slot_date, open_slot.start_time)
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
    for game in season_division_games:
        key_home = (game.home_team_id, game.week_id)
        key_away = (game.away_team_id, game.week_id)
        team_week_counts[key_home] = team_week_counts.get(key_home, 0) + 1
        team_week_counts[key_away] = team_week_counts.get(key_away, 0) + 1
    for (team_id, _wk_id), count in team_week_counts.items():
        if count > 1:
            double_header_counts[team_id] = double_header_counts.get(team_id, 0) + 1

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
            and_(Week.week_number == week.week_number, Week.start_date < week.start_date),
        ),
    ).order_by(Week.week_number.desc(), Week.start_date.desc()).first()

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
    regular_season_host_occurrences_by_community: dict[uuid.UUID, set[tuple[uuid.UUID, date]]] = {}
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
                regular_season_host_occurrences_by_community.setdefault(host_org_id, set()).add((host_location_id, slot_date))
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
        GameSlot.slot_date == week.start_date,
        GameSlot.assigned_game_id.is_(None),
    ).all()
    weekly_host_capacity_report: dict[uuid.UUID, dict[str, object]] = {}
    for slot in all_open_slots_for_week:
        if not slot.host_location_id:
            continue
        row = weekly_host_capacity_report.setdefault(slot.host_location_id, {
            'host_location_id': str(slot.host_location_id),
            'host_location_name': slot.host_location.name if slot.host_location else '',
            'owning_community_id': str(slot.host_location.organization_id) if slot.host_location and slot.host_location.organization_id else None,
            'small_field_capacity': 0,
            'large_field_capacity': 0,
            'total_game_capacity': 0,
            'remaining_unused_capacity': 0,
            'small_fields': set(),
            'large_fields': set(),
            'current_season_host_count_location': len(regular_season_host_occurrences_by_location.get(slot.host_location_id, set())),
            'current_season_host_count_community': len(regular_season_host_occurrences_by_community.get(slot.host_location.organization_id, set())) if slot.host_location and slot.host_location.organization_id else 0,
        })
        row['total_game_capacity'] += 1
        row['remaining_unused_capacity'] += 1
        if slot.field_type == 'SMALL':
            row['small_field_capacity'] += 1
            row['small_fields'].add(str(slot.field_instance_id))
        elif slot.field_type == 'LARGE':
            row['large_field_capacity'] += 1
            row['large_fields'].add(str(slot.field_instance_id))
    host_capacity = []
    for host_id, host_slots in slots_by_host.items():
        host_capacity.append({
            'host_id': host_id,
            'slot_count': len(host_slots),
            'field_count': len({s.field_instance_id for s in host_slots}),
            'continuity': len({(s.slot_date, s.start_time) for s in host_slots}),
        })
    host_capacity_by_id: dict[uuid.UUID, int] = {row['host_id']: int(row['slot_count']) for row in host_capacity}
    host_capacity.sort(key=lambda x: (
        x['slot_count'] >= games_required,
        -(weekly_host_capacity_report.get(x['host_id'], {}).get('current_season_host_count_community', 0) or 0),
        -(weekly_host_capacity_report.get(x['host_id'], {}).get('current_season_host_count_location', 0) or 0),
        x['slot_count'],
        x['field_count'],
        x['continuity'],
    ), reverse=True)
    host_ids_by_org: dict[uuid.UUID, set[uuid.UUID]] = {}
    for host_id in slots_by_host.keys():
        host_row = db.query(HostLocation.id, HostLocation.organization_id).filter(HostLocation.id == host_id).first()
        if host_row and host_row.organization_id:
            host_ids_by_org.setdefault(host_row.organization_id, set()).add(host_row.id)
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
    primary_host_id: uuid.UUID | None = host_capacity[0]['host_id'] if host_capacity else None
    single_site_possible = bool(host_capacity and host_capacity[0]['slot_count'] >= games_required)
    prefer_two_sites = games_required > single_site_game_limit and len(host_capacity) >= 2
    selected_host_ids: set[uuid.UUID] = set()
    locked_host_mode = 'none'
    host_lock_reason = 'No compatible host locations found.'
    if host_capacity:
        reusable_prior_hosts = [hid for hid in prior_active_hosts if hid in slots_by_host]
        reusable_prior_capacity = sum(len(slots_by_host.get(hid, [])) for hid in reusable_prior_hosts)
        if reusable_prior_hosts and reusable_prior_capacity > 0:
            selected_host_ids = set(reusable_prior_hosts[:2])
            locked_host_mode = 'week_active_reuse'
            host_lock_reason = 'reusing week/day active host sites from earlier divisions'
        if prefer_two_sites and not selected_host_ids:
            best_two_host_combo: tuple[uuid.UUID, uuid.UUID] | None = None
            best_two_host_score = -1
            for i in range(len(host_capacity)):
                for j in range(i + 1, len(host_capacity)):
                    host_a = host_capacity[i]
                    host_b = host_capacity[j]
                    host_a_id = host_a['host_id']
                    host_b_id = host_b['host_id']
                    combo_capacity = int(host_a['slot_count']) + int(host_b['slot_count'])
                    if combo_capacity < games_required:
                        continue
                    host_a_orgs = {
                        team_id for team_id, team_org in team_org_ids.items()
                        if team_org and host_a_id in host_ids_by_org.get(team_org, set())
                    }
                    host_b_orgs = {
                        team_id for team_id, team_org in team_org_ids.items()
                        if team_org and host_b_id in host_ids_by_org.get(team_org, set())
                    }
                    represented_teams = len(host_a_orgs | host_b_orgs)
                    combo_score = (
                        represented_teams * 10_000
                        + combo_capacity * 100
                        + int(host_a['field_count']) + int(host_b['field_count'])
                    )
                    if combo_score > best_two_host_score:
                        best_two_host_score = combo_score
                        best_two_host_combo = (host_a_id, host_b_id)
            if best_two_host_combo:
                selected_host_ids = {best_two_host_combo[0], best_two_host_combo[1]}
                locked_host_mode = 'dual'
                host_lock_reason = f'required games ({games_required}) exceed single-site game limit ({single_site_game_limit}); selected two hosts'
        if not selected_host_ids and single_site_possible and primary_host_id:
            selected_host_ids = {primary_host_id}
            locked_host_mode = 'single'
            host_lock_reason = 'single host has enough compatible slots for required games'
        elif not selected_host_ids:
            best_two_host_combo: tuple[uuid.UUID, uuid.UUID] | None = None
            best_two_host_capacity = -1
            for i in range(len(host_capacity)):
                for j in range(i + 1, len(host_capacity)):
                    host_a = host_capacity[i]
                    host_b = host_capacity[j]
                    combo_capacity = int(host_a['slot_count']) + int(host_b['slot_count'])
                    if combo_capacity < games_required:
                        continue
                    if combo_capacity > best_two_host_capacity:
                        best_two_host_capacity = combo_capacity
                        best_two_host_combo = (host_a['host_id'], host_b['host_id'])
            if best_two_host_combo:
                selected_host_ids = {best_two_host_combo[0], best_two_host_combo[1]}
                locked_host_mode = 'dual'
                host_lock_reason = 'single host insufficient; selected two hosts to satisfy required games'
    if not selected_host_ids and not admin_override_third_host and games_required > 0:
        _add_skipped('More than 2 host locations required. Admin override needed.')
        _add_skipped('This division/week cannot be scheduled within the two-location limit based on available slots.')
        return {
            'proposals': [],
            'skipped': skipped,
            'proposed_game_count': 0,
            'max_allowed_game_count': required_games_for_division_week,
            'existing_game_count': existing_games_count,
            'unused_team_ids': [str(tid) for tid in teams_by_id if tid not in used_team_ids],
            'unused_teams': [teams_by_id[tid].name for tid in teams_by_id if tid not in used_team_ids],
            'audit': {
                'host_locations_used_count': 0,
                'host_locations_used': [],
                'locked_host_locations': [],
                'locked_host_mode': locked_host_mode,
                'admin_override_third_host_locations': admin_override_third_host,
            },
        }
    if selected_host_ids and not admin_override_third_host:
        remaining_slots = [slot for slot in remaining_slots if slot.host_location_id in selected_host_ids]
        open_slots = [slot for slot in open_slots if slot.host_location_id in selected_host_ids]
        slots_by_host = {host_id: host_slots for host_id, host_slots in slots_by_host.items() if host_id in selected_host_ids}
    split_host_week = len(host_capacity) > 1
    projected_games_by_host: dict[uuid.UUID, int] = {}
    preferred_host_id: uuid.UUID | None = primary_host_id
    used_host_ids: set[uuid.UUID] = set()
    selected_double_header_team_id: uuid.UUID | None = None
    reserved_double_header_slot_ids: set[str] = set()
    reserved_double_header_context: dict[str, object] = {}
    double_header_reservation_failure_reasons: list[str] = []
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
            field_time_key = (str(candidate.field_instance_id), candidate.slot_date, candidate.start_time)
            if field_time_key not in field_time_occupied:
                open_compatible_candidates.append(candidate)
        if not open_compatible_candidates:
            return None
        return min(
            open_compatible_candidates,
            key=lambda c: (
                c.field_instance.field_name if c.field_instance and c.field_instance.field_name else '',
                str(c.id),
            ),
        )
    if is_odd_division and no_byes:
        min_dh = min(double_header_counts.values() or [0])
        candidates = [tid for tid, count in double_header_counts.items() if count == min_dh]
        candidates.sort(key=lambda tid: teams_by_id[tid].name)
        selected_double_header_team_id = candidates[0] if candidates else None
        if selected_double_header_team_id:
            site_day_slots: dict[tuple[uuid.UUID, object], list[GameSlot]] = {}
            for s in sorted(remaining_slots, key=lambda x: (x.slot_date, x.start_time, str(x.host_location_id), str(x.id))):
                if not s.host_location_id:
                    continue
                site_day_slots.setdefault((s.host_location_id, s.slot_date), []).append(s)
            reservation_candidates: list[tuple[int, int, GameSlot, GameSlot, str]] = []
            for _, slots in site_day_slots.items():
                for i in range(len(slots)):
                    for j in range(i + 1, len(slots)):
                        a = slots[i]
                        b = slots[j]
                        a_minutes = _minutes_from_time(a.start_time)
                        b_minutes = _minutes_from_time(b.start_time)
                        if a_minutes is None or b_minutes is None:
                            continue
                        gap = abs(a_minutes - b_minutes)
                        if gap == 60:
                            reservation_candidates.append((0, gap, a, b, 'adjacent same-location slots'))
            if not reservation_candidates:
                double_header_reservation_failure_reasons.append('Unable to place required double-header because no same-location adjacent slots exist.')
            else:
                reservation_candidates.sort(key=lambda row: (row[0], row[1], row[2].slot_date, row[2].start_time, str(row[2].host_location_id)))
                chosen_priority, _, r1, r2, reservation_mode = reservation_candidates[0]
                reserved_double_header_slot_ids = {str(r1.id), str(r2.id)}
                reserved_double_header_context = {
                    'team_id': str(selected_double_header_team_id),
                    'team_name': teams_by_id[selected_double_header_team_id].name if selected_double_header_team_id in teams_by_id else None,
                    'slot_ids': sorted(list(reserved_double_header_slot_ids)),
                    'reservation_mode': reservation_mode,
                    'reservation_relaxed': chosen_priority > 0,
                }
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
            seen_host_time_keys: set[tuple[str, object, object]] = set()
            for slot in sorted_slots:
                if (slot.slot_date, slot.start_time) != target_time:
                    continue
                if not slot.host_location_id:
                    continue
                host_time_key = (str(slot.host_location_id), slot.slot_date, slot.start_time)
                if host_time_key in seen_host_time_keys:
                    continue
                seen_host_time_keys.add(host_time_key)
                selected_field_slot = _first_compatible_open_slot_by_field_order(slot.host_location_id, slot.slot_date, slot.start_time)
                if not selected_field_slot:
                    continue
                for i in range(len(available_team_ids)):
                    for j in range(i + 1, len(available_team_ids)):
                        a = available_team_ids[i]
                        b = available_team_ids[j]
                        pair = tuple(sorted((a, b)))
                        if pair in used_pairs:
                            continue
                        if (str(a), slot.slot_date, slot.start_time) in team_time_occupied or (str(b), slot.slot_date, slot.start_time) in team_time_occupied:
                            continue
                        if no_simultaneous_games_same_host:
                            host_time_key = (str(slot.host_location_id), slot.slot_date, slot.start_time)
                            if host_time_key in host_time_occupied:
                                continue
                        team_a = teams_by_id[a]
                        team_b = teams_by_id[b]
                        host_org_id = slot.host_location.organization_id if slot.host_location else None
                        same_community = bool(team_a.organization_id and team_a.organization_id == team_b.organization_id)
                        hosted_by_own_community = bool(same_community and host_org_id and host_org_id == team_a.organization_id)
                        host_pref = bool(host_org_id and host_org_id in {team_a.organization_id, team_b.organization_id})
                        repeat_count = matchup_counts.get(pair, 0)
                        community_pair = tuple(sorted((team_a.organization_id, team_b.organization_id))) if team_a.organization_id and team_b.organization_id else None
                        prior_week_team_repeat = pair in prior_week_team_pairs
                        prior_week_community_repeat = bool(community_pair and community_pair in prior_week_community_pairs)
                        community_repeat_count = community_matchup_counts.get(community_pair, 0) if community_pair else 0
    
                        score = 0
                        reason_bits = []
                        warning_bits = []
                        candidate_host_id = slot.host_location_id
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
                        if repeat_count == 0:
                            score += 120
                            reason_bits.append('new opponent pairing (+120)')
                        else:
                            repeat_penalty = 150 * repeat_count
                            score -= repeat_penalty
                            warning_bits.append(f'repeat opponent pairing (-{repeat_penalty})')
                            if same_community:
                                score -= 50
                                warning_bits.append('repeat same-community opponent (-50)')
    
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
                            warning_bits.append('Repeat avoided because first-time opponent was available' if any(matchup_counts.get(tuple(sorted((a, oid))),0)==0 for oid in teams_by_id if oid!=a) or any(matchup_counts.get(tuple(sorted((b, oid))),0)==0 for oid in teams_by_id if oid!=b) else 'repeat matchup selected because unique options were exhausted')
                        if same_community_operationally_reasonable:
                            reason_bits.append('Opponent diversity prioritized because division has limited unique opponents')
                        if hosted_by_own_community:
                            score += 60
                            reason_bits.append('same-community at home host field (+60)')
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
                            location_host_count = len(regular_season_host_occurrences_by_location.get(candidate_host_id, set()))
                            community_host_count = len(regular_season_host_occurrences_by_community.get(candidate_host_org_id, set())) if candidate_host_org_id else 0
                            min_location_host_count = min((len(v) for v in regular_season_host_occurrences_by_location.values()), default=0)
                            min_community_host_count = min((len(v) for v in regular_season_host_occurrences_by_community.values()), default=0)
                            if location_host_count == min_location_host_count or community_host_count == min_community_host_count:
                                score += 120
                                reason_bits.append('fewest season host assignments (+120)')
                            projected_location_count = location_host_count + (0 if slot.slot_date in regular_season_host_occurrences_by_location.get(candidate_host_id, set()) else 1)
                            projected_community_count = community_host_count + (0 if (candidate_host_org_id and (candidate_host_id, slot.slot_date) in regular_season_host_occurrences_by_community.get(candidate_host_org_id, set())) else 1)
                            all_projected_location_counts = [len(v) for v in regular_season_host_occurrences_by_location.values()]
                            all_projected_community_counts = [len(v) for v in regular_season_host_occurrences_by_community.values()]
                            all_projected_location_counts.append(projected_location_count)
                            all_projected_community_counts.append(projected_community_count)
                            if all_projected_location_counts and all_projected_community_counts:
                                loc_spread = max(all_projected_location_counts) - min(all_projected_location_counts)
                                comm_spread = max(all_projected_community_counts) - min(all_projected_community_counts)
                                if loc_spread <= 1 and comm_spread <= 1:
                                    score += 80
                                    reason_bits.append('balanced host distribution (+80)')
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
                                    alt_projected_comm = alt_comm_count + (0 if (alt_org_id and (alt_host_id, alternative_slot.slot_date) in regular_season_host_occurrences_by_community.get(alt_org_id, set())) else 1)
                                    if alt_projected_loc <= regular_season_host_limit and alt_projected_comm <= regular_season_host_limit:
                                        alternative_under_limit_exists = True
                                        break
                                if alternative_under_limit_exists:
                                    score -= 150
                                    warning_bits.append('third regular-season host occurrence while alternatives exist (-150)')
                                else:
                                    reason_bits.append('host rotation limit relaxed: no valid under-limit alternative for this slot')
                        if split_host_week and candidate_host_id:
                            candidate_host_capacity = max(1, host_capacity_by_id.get(candidate_host_id, 0))
                            current_host_projection = projected_games_by_host.get(candidate_host_id, 0)
                            host_load_ratio = current_host_projection / candidate_host_capacity
                            # Encourage balancing game allocation across active host pools.
                            score += int(balance_weight * (1.0 - min(1.0, host_load_ratio)))
                            reason_bits.append('split-host balancing across active sites')

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
                                            score += 100
                                            reason_bits.append('double-header back-to-back (+100)')
                                            double_header_back_to_back = True
                                        else:
                                            score -= 150
                                            warning_bits.append('double-header separated by gap (-150)')
                                    except Exception:
                                        pass
    
                        if (
                            dh_team_needs_reservation
                            and selected_double_header_team_id
                            and selected_double_header_team_id not in {a, b}
                        ):
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
            'score': int(best['score']),
            'reason': '; '.join(reason_bits + ['deterministic field assignment: earliest available time then first compatible open field by host order']),
            'warnings': best['warning_bits'],
            'rules_relaxed': [],
            'week': week.week_number,
            'division': full_division_label,
        })
        if (
            selected_host_ids
            and len(selected_host_ids) >= 2
            and selected_field_slot.host_location_id in selected_host_ids
            and not admin_override_third_host
        ):
            plans[-1]['warnings'] = list(plans[-1]['warnings']) + ['Division/week scheduled across 2 host locations.']
        selected_host_org_id = selected_field_slot.host_location.organization_id if selected_field_slot.host_location else None
        if selected_host_org_id and home_team.organization_id == selected_host_org_id:
            plans[-1]['score'] = int(plans[-1]['score']) + 150
            plans[-1]['reason'] = f"{plans[-1]['reason']}; home team aligned to own selected host location (+150)"
        if admin_override_third_host and selected_field_slot.host_location_id and selected_host_ids and selected_field_slot.host_location_id not in selected_host_ids:
            plans[-1]['warnings'] = list(plans[-1]['warnings']) + ['Admin override: third host location required.']
        used_pairs.add(tuple(sorted((best['home_team_id'], best['away_team_id']))))
        week_team_game_counts[best['home_team_id']] = week_team_game_counts.get(best['home_team_id'], 0) + 1
        week_team_game_counts[best['away_team_id']] = week_team_game_counts.get(best['away_team_id'], 0) + 1
        if not (is_odd_division and no_byes):
            used_team_ids.add(best['home_team_id'])
            used_team_ids.add(best['away_team_id'])
        if selected_field_slot.host_location_id:
            used_host_ids.add(selected_field_slot.host_location_id)
            projected_games_by_host[selected_field_slot.host_location_id] = projected_games_by_host.get(selected_field_slot.host_location_id, 0) + 1
            if not postseason_week and selected_field_slot.slot_date:
                regular_season_host_occurrences_by_location.setdefault(selected_field_slot.host_location_id, set()).add(selected_field_slot.slot_date)
                selected_host_org_id = selected_field_slot.host_location.organization_id if selected_field_slot.host_location else None
                if selected_host_org_id:
                    regular_season_host_occurrences_by_community.setdefault(selected_host_org_id, set()).add((selected_field_slot.host_location_id, selected_field_slot.slot_date))
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
        field_time_occupied[(str(selected_field_slot.field_instance_id), selected_field_slot.slot_date, selected_field_slot.start_time)] = division.name
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
    if len(plans) == 0 and len(teams) > 1:
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
    selected_host_ids = extract_selected_host_ids(plans)
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
        {'home_team_id': str(pair[0]), 'away_team_id': str(pair[1]), 'count': count}
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
    for plan in plans:
        home_team = teams_by_id.get(uuid.UUID(plan['home_team_id']))
        away_team = teams_by_id.get(uuid.UUID(plan['away_team_id']))
        host_id = plan.get('host_location_id')
        if not home_team or not away_team or not home_team.organization_id or home_team.organization_id != away_team.organization_id:
            continue
        org_host_ids = {str(hid) for hid in host_ids_by_org.get(home_team.organization_id, set())}
        if host_id and org_host_ids and host_id not in org_host_ids:
            same_community_not_home_site.append(plan)

    division_labels_used = sorted({str(p.get('division') or '') for p in plans if p.get('division')})
    compliance_flags = {
        'host_site_limit_violations': [d for d, hosts in host_sites_used_per_date.items() if len(hosts) > regular_season_host_limit and not admin_override_third_host],
        'division_label_mixing_detected': any('/' in label and ('COED' not in label.upper() and 'GIRLS' not in label.upper()) for label in division_labels_used),
        'double_header_spacing_location_issues': len(double_header_spacing_issues),
        'repeat_matchups_before_exhaustion': len(repeat_matchup_pairs),
        'uneven_game_counts': len(uneven_game_count_teams),
        'same_community_not_at_home_site': len(same_community_not_home_site),
    }
    logger.info(
        f'Selected host sites for scheduling: {selected_host_ids}'
    )
    return {
        'proposals': plans,
        'skipped': skipped,
        'proposed_game_count': len(plans),
        'max_allowed_game_count': required_games_for_division_week,
        'existing_game_count': existing_games_count,
        'unused_team_ids': unused_team_ids,
        'unused_teams': [teams_by_id[uuid.UUID(tid)].name for tid in unused_team_ids],
        'double_header_team_id': str(selected_double_header_team_id) if selected_double_header_team_id else None,
        'final_validation': {
            'active_team_count': team_count,
            'required_game_count': required_games_for_division_week,
            'created_game_count': total_created_games,
            'unscheduled_teams': [teams_by_id[uuid.UUID(tid)].name for tid in unscheduled_team_ids],
            'double_header_team': teams_by_id[selected_double_header_team_id].name if selected_double_header_team_id else None,
        },
        'diagnostics': {
            'odd_team_double_header_reservation': {
                'selected_team_id': str(selected_double_header_team_id) if selected_double_header_team_id else None,
                'selected_team_name': teams_by_id[selected_double_header_team_id].name if selected_double_header_team_id and selected_double_header_team_id in teams_by_id else None,
                'reserved_slot_ids': sorted(list(reserved_double_header_slot_ids)),
                'reservation_context': reserved_double_header_context,
                'reservation_failure_reasons': double_header_reservation_failure_reasons,
            },
            'weekly_host_planning_report': {
                'selected_host_sites': selected_host_ids,
                'overflow_sites_used': [],
                'host_limit_exceptions': [],
                'league_team_demand': {},
                'host_capacities': [],
            },
            'teams_evaluated': team_count,
            'slots_evaluated': compatible_slots_found,
            'valid_matchups_found': len(plans),
            'valid_slot_combinations_found': len(plans),
            'rules_relaxed': len(host_limit_relaxation_reasons),
            'conflicts_avoided': len(skipped),
            'final_games_created': len(plans),
            'week_host_site_usage': {
                'active_host_sites': week_host_site_usage,
                'overflow_sites': [],
            },
        },
        'audit': {
            'total_games_per_team': per_team_games,
            'duplicate_matchups': duplicate_matchups,
            'double_header_teams_by_week': double_header_teams,
            'host_locations_used_count': len(used_host_ids),
            'host_locations_used': [str(hid) for hid in used_host_ids],
            'locked_host_locations': [str(hid) for hid in selected_host_ids],
            'locked_host_mode': locked_host_mode,
            'host_selection_reason': host_lock_reason,
            'single_site_game_limit': single_site_game_limit,
            'admin_override_third_host_locations': admin_override_third_host,
            'split_host_week': split_host_week,
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
                not regular_season_host_occurrences_by_location
                or (
                    max(len(v) for v in regular_season_host_occurrences_by_location.values())
                    - min(len(v) for v in regular_season_host_occurrences_by_location.values())
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
    teams = db.query(Team).filter(Team.division_id == division_id, Team.is_active.is_(True)).all()
    division = db.query(Division).filter(Division.id == division_id).first()
    if not division:
        raise HTTPException(404, 'Selected division is invalid')
    if not teams:
        raise HTTPException(400, 'Division/week produced zero valid schedule candidates.')
    required_field_type = _required_field_type_for_division(division)
    open_slots_count = db.query(GameSlot).filter(
        GameSlot.slot_date == week.start_date,
        GameSlot.status == 'OPEN',
        GameSlot.assigned_game_id.is_(None),
        GameSlot.field_type == required_field_type,
    ).count()
    if open_slots_count <= 0:
        raise HTTPException(400, 'No valid slot combinations available.')
    host_locations_count = db.query(GameSlot.host_location_id).filter(
        GameSlot.slot_date == week.start_date,
        GameSlot.status == 'OPEN',
        GameSlot.assigned_game_id.is_(None),
        GameSlot.field_type == required_field_type,
        GameSlot.host_location_id.is_not(None),
    ).distinct().count()
    if host_locations_count <= 0:
        raise HTTPException(400, 'No compatible host locations found.')
    logger.info(
        'auto_fill_apply_start season_id=%s week_id=%s division_id=%s active_team_count=%s open_slot_count=%s host_location_count=%s valid_matchup_count=%s',
        season_id, week_id, division_id, len(teams), open_slots_count, host_locations_count, len(proposals),
    )
    team_ids = {t.id for t in teams}
    no_byes = bool(payload.get('no_byes', True))
    is_odd_division = len(teams) % 2 == 1
    required_games_for_division_week = (len(teams) + 1) // 2 if (is_odd_division and no_byes) else len(teams) // 2
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
        Game.game_date == db.query(Week.start_date).filter(Week.id == week_id).scalar_subquery(),
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
        (str(row.field_instance_id), row.game_date, row.kickoff_time): row.name
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
            open_field_key = (str(open_slot.field_instance_id), open_slot.slot_date, open_slot.start_time)
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
        ranked: list[tuple[int, int, GameSlot]] = []
        for candidate_slot in open_slots:
            if not candidate_slot.start_time or not candidate_slot.field_instance_id:
                continue
            if (str(home_team_id), candidate_slot.slot_date, candidate_slot.start_time) in team_time_occupied:
                continue
            if (str(away_team_id), candidate_slot.slot_date, candidate_slot.start_time) in team_time_occupied:
                continue
            candidate_field_time_key = (str(candidate_slot.field_instance_id), candidate_slot.slot_date, candidate_slot.start_time)
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
            ranked.append((back_to_back_priority, distance, candidate_slot))
        ranked.sort(key=lambda item: (item[0], item[1], _minutes_from_time(item[2].start_time)))
        return ranked[0][2] if ranked else None

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
        ranked: list[tuple[int, int, int, GameSlot]] = []
        for candidate_slot in open_slots:
            if not candidate_slot.start_time or not candidate_slot.field_instance_id:
                continue
            if (str(home_team_id), candidate_slot.slot_date, candidate_slot.start_time) in team_time_occupied:
                continue
            if (str(away_team_id), candidate_slot.slot_date, candidate_slot.start_time) in team_time_occupied:
                continue
            candidate_field_time_key = (str(candidate_slot.field_instance_id), candidate_slot.slot_date, candidate_slot.start_time)
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
            ranked.append((adjacency_priority, is_later, distance, candidate_slot))
        ranked.sort(key=lambda item: (item[0], item[1], item[2], _minutes_from_time(item[3].start_time)))
        if not ranked:
            return None, False
        selected = ranked[0][3]
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
        field_time_key = (str(slot.field_instance_id), slot.slot_date, slot.start_time)
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
        field_time_key = (str(slot.field_instance_id), slot.slot_date, slot.start_time)
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
                field_time_key = (str(slot.field_instance_id), slot.slot_date, slot.start_time)
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
        field_time_occupied[(str(slot.field_instance_id), slot.slot_date, slot.start_time)] = teams_by_id.get(str(home_team_id)).division.name if teams_by_id.get(str(home_team_id)) and teams_by_id.get(str(home_team_id)).division else 'another division'
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
            GameSlot.slot_date == db.query(Week.start_date).filter(Week.id == week_id).scalar_subquery(),
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
    logger.info(
        f'Selected host sites for scheduling: {selected_host_ids}'
    )

    recovery_diagnostics: list[dict[str, object]] = []
    if is_odd_division and no_byes and total_created_for_week < required_games_for_division_week:
        remaining_needed = required_games_for_division_week - total_created_for_week
        division_team_ids = [str(team.id) for team in teams]
        unscheduled_ids = [tid for tid in division_team_ids if week_team_game_counts.get(uuid.UUID(tid), 0) == 0]
        double_header_team_ids = [str(tid) for tid, count in week_team_game_counts.items() if count >= 2]
        if not double_header_team_ids:
            double_header_team_ids = [tid for tid in division_team_ids if week_team_game_counts.get(uuid.UUID(tid), 0) == 1]
        open_slots = db.query(GameSlot).join(GameSlot.field_instance).filter(
            GameSlot.slot_date == db.query(Week.start_date).filter(Week.id == week_id).scalar_subquery(),
            GameSlot.status == 'OPEN',
            GameSlot.assigned_game_id.is_(None),
            GameSlot.field_type == required_field_type,
        ).order_by(GameSlot.start_time.asc()).all()
        while remaining_needed > 0:
            placed = False
            candidate_teams = sorted(division_team_ids, key=lambda tid: week_team_game_counts.get(uuid.UUID(tid), 0))
            for home_tid in candidate_teams:
                for away_tid in candidate_teams:
                    if home_tid == away_tid:
                        continue
                    home_count = week_team_game_counts.get(uuid.UUID(home_tid), 0)
                    away_count = week_team_game_counts.get(uuid.UUID(away_tid), 0)
                    if home_count >= 2 or away_count >= 2:
                        continue
                    projected_double_headers = len([tid for tid, cnt in week_team_game_counts.items() if cnt >= 2])
                    if home_count == 1 or away_count == 1:
                        if projected_double_headers >= 1 and home_count == 1 and away_count == 1:
                            continue
                    for slot in open_slots:
                        ok, reason = _can_place_matchup(home_tid, away_tid, slot)
                        if not ok:
                            recovery_diagnostics.append({'slot': f"{slot.start_time} {slot.field_type}", 'home': _team_name(home_tid), 'away': _team_name(away_tid), 'reason': reason})
                            continue
                        game = Game(season_id=season_id, week_id=week_id, home_team_id=home_tid, away_team_id=away_tid, field_id=None, game_status_id=status.id, game_date=slot.slot_date, kickoff_time=slot.start_time)
                        db.add(game); db.flush()
                        slot.status = 'ASSIGNED'; slot.assigned_game_id = game.id
                        team_time_occupied.add((home_tid, slot.slot_date, slot.start_time)); team_time_occupied.add((away_tid, slot.slot_date, slot.start_time))
                        field_time_occupied[(str(slot.field_instance_id), slot.slot_date, slot.start_time)] = division.name if division else 'another division'
                        host_time_occupied[(str(slot.host_location_id), slot.slot_date, slot.start_time)] = division.name if division else 'another division'
                        week_team_game_counts[uuid.UUID(home_tid)] = home_count + 1
                        week_team_game_counts[uuid.UUID(away_tid)] = away_count + 1
                        created_games += 1; assigned_slots += 1; remaining_needed -= 1; placed = True
                        break
                    if placed:
                        break
                if placed:
                    break
            if not placed:
                break
        total_created_for_week = existing_games_count + created_games
        if total_created_for_week < required_games_for_division_week:
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
            'unscheduled_teams': unscheduled_teams,
            'double_header_team': teams_by_id[double_header_team_id].name if double_header_team_id and double_header_team_id in teams_by_id else None,
            'recovery_diagnostics': recovery_diagnostics[-25:],
        },
        'diagnostics': {
            'weekly_host_planning_report': {
                'selected_host_sites': selected_host_ids,
                'overflow_sites_used': [],
                'host_limit_exceptions': [],
                'league_team_demand': {},
                'host_capacities': [],
            },
            'teams_evaluated': len(teams),
            'slots_evaluated': open_slots_count,
            'valid_matchups_found': len(proposals),
            'valid_slot_combinations_found': len(proposals),
            'rules_relaxed': len([s for s in skipped if 'non-back-to-back' in str(s.get('reason', '')).lower()]),
            'conflicts_avoided': len(skipped),
            'final_games_created': created_games,
        },
    }


@router.post('/manual-schedule-builder/auto-schedule-season', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def auto_schedule_entire_season(payload: dict, db: Session = Depends(get_db)):
    season_id = payload.get('season_id')
    clear_existing = bool(payload.get('clear_existing', False))
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
            db.commit()

    division_order = [
        ('COED', 'K/1ST'), ('GIRLS', 'K/1ST'),
        ('COED', '2ND/3RD'), ('GIRLS', '2ND/3RD'),
        ('COED', '4TH/5TH'), ('GIRLS', '4TH/5TH'),
        ('COED', '6TH/7TH'), ('COED', '8TH'),
        ('GIRLS', '6TH/7TH/8TH'),
    ]
    all_divisions = db.query(Division).all()
    divisions_by_key = {canonical_division_id_from_division(d): d for d in all_divisions}
    divisions_by_normalized_name = {
        normalize_division_name(f'{d.division_group or ""} {d.name or ""}'): d
        for d in all_divisions
    }
    weeks = db.query(Week).filter(Week.season_id == season_id).order_by(Week.week_number.asc(), Week.start_date.asc()).all()

    total_games_created = 0
    warnings: list[str] = []
    validation_errors: list[str] = []
    divisions_completed: list[str] = []
    divisions_with_unresolved_games: list[str] = []
    required_games_missing: list[dict[str, object]] = []
    skipped_attempts_by_reason: dict[str, int] = {}
    post_run_validation: list[dict[str, object]] = []
    validation_warnings: list[dict[str, object]] = []

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
            key = _normalize_skip_reason(str((row or {}).get('reason') or 'unknown'))
            skipped_attempts_by_reason[key] = skipped_attempts_by_reason.get(key, 0) + 1

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
        for week in weeks:
            preview = auto_fill_preview({'season_id': season_id, 'week_id': week.id, 'division_id': division.id}, db)
            proposals = preview.get('proposals') or []
            _record_skipped(preview.get('skipped') or [])
            preview_validation = preview.get('final_validation') or {}
            required_games = int(preview_validation.get('required_game_count') or 0)
            created_games = int(preview_validation.get('created_game_count') or 0)
            unscheduled_teams = list(preview_validation.get('unscheduled_teams') or [])
            unresolved_conflicts = list(preview.get('skipped') or [])
            if not proposals:
                actual_created_games = _actual_created_game_count_for_week(division.id, week.id)
                host_count = _host_count_for_week(division.id, week.id)
            else:
                applied = auto_fill_apply({'season_id': season_id, 'week_id': week.id, 'division_id': division.id, 'proposals': proposals}, db)
                created_count = int(applied.get('created_count') or 0)
                skipped_count = int(applied.get('skipped_count') or 0)
                division_created += created_count
                total_games_created += created_count
                _record_skipped(applied.get('skipped') or [])
                host_count = _host_count_for_week(division.id, week.id)
                actual_created_games = _actual_created_game_count_for_week(division.id, week.id)
                if skipped_count > 0:
                    division_unresolved = True
                apply_validation = applied.get('final_validation') or {}
                if int(apply_validation.get('required_game_count') or 0) != required_games:
                    required_games = int(apply_validation.get('required_game_count') or 0)
            post_run_validation.append({
                'division': division_label,
                'week': week.week_number,
                'active_team_count': int(preview_validation.get('active_team_count') or 0),
                'required_games': required_games,
                'created_games': actual_created_games,
                'unscheduled_teams': unscheduled_teams,
                'unresolved_conflicts': unresolved_conflicts,
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
                })
                validation_errors.append(
                    f'{division_label} Week {week.week_number}: required={required_games}, created={actual_created_games}, missing={missing_games}'
                )
        if division_created > 0 and not division_unresolved:
            divisions_completed.append(division_label)
        else:
            divisions_with_unresolved_games.append(division_label)

    return {
        'total_games_created': total_games_created,
        'games_skipped': sum(skipped_attempts_by_reason.values()),
        'skipped_attempts_by_reason': skipped_attempts_by_reason,
        'required_games_still_missing': required_games_missing,
        'warnings': warnings,
        'validation_errors': validation_errors,
        'validation_warnings': validation_warnings,
        'post_run_validation': post_run_validation,
        'divisions_completed': divisions_completed,
        'divisions_with_unresolved_games': divisions_with_unresolved_games,
    }

@router.get('/public/games', response_model=PagedResponse[PublicGameRead])
def list_public_games(host_location_id: uuid.UUID | None = None, organization_id: uuid.UUID | None = None, division_id: uuid.UUID | None = None, week_id: uuid.UUID | None = None, team_id: uuid.UUID | None = None, status_code: str | None = None, page: int = 1, page_size: int = 50, db: Session = Depends(get_db)):
    home_team = aliased(Team); away_team = aliased(Team)
    q = db.query(Game).join(Game.status).join(Game.field).join(Field.host_location).join(HostLocation.organization).join(home_team, Game.home_team).join(away_team, Game.away_team)
    q = q.filter(GameStatus.code == 'published')
    if host_location_id: q = q.filter(Field.host_location_id == host_location_id)
    if organization_id: q = q.filter(HostLocation.organization_id == organization_id)
    if division_id: q = q.filter(home_team.division_id == division_id)
    if week_id: q = q.filter(Game.week_id == week_id)
    if team_id: q = q.filter((Game.home_team_id == team_id) | (Game.away_team_id == team_id))
    if status_code: q = q.filter(GameStatus.code == status_code)
    total = q.count(); items = q.order_by(Game.game_date, Game.kickoff_time).offset((page - 1) * page_size).limit(page_size).all()
    return PagedResponse(items=[PublicGameRead(id=g.id,game_date=g.game_date,kickoff_time=g.kickoff_time,host_location_id=g.field.host_location.id,host_location_name=g.field.host_location.name,field_id=g.field.id,field_name=g.field.name,organization_id=g.field.host_location.organization.id,organization_name=g.field.host_location.organization.name,division_id=g.home_team.division_id,division_name=g.home_team.division.name,week_id=g.week_id,week_number=(g.week.week_number if g.week else None),home_team_id=g.home_team_id,home_team_name=g.home_team.name,away_team_id=g.away_team_id,away_team_name=g.away_team.name,game_status_id=g.game_status_id,game_status_code=g.status.code,game_status_label=g.status.label) for g in items], total=total, page=page, page_size=page_size)

@router.get('/public/schedule-filters')
def list_public_schedule_filters(db: Session = Depends(get_db)):
    games = db.query(Game).join(Game.status).join(Game.field).join(Field.host_location).join(HostLocation.organization).join(Game.home_team).filter(GameStatus.code == 'published').all()
    host_locations = {(g.field.host_location.id, g.field.host_location.name) for g in games}; organizations = {(g.field.host_location.organization.id, g.field.host_location.organization.name) for g in games}; divisions = {(g.home_team.division.id, g.home_team.division.name) for g in games}; weeks = {(g.week.id, g.week.week_number) for g in games}; teams = {(g.home_team.id, g.home_team.name) for g in games} | {(g.away_team.id, g.away_team.name) for g in games}; statuses = {(g.status.code, g.status.label) for g in games}
    return {'host_locations': [{'id': item[0], 'name': item[1]} for item in sorted(host_locations, key=lambda x: x[1])], 'organizations': [{'id': item[0], 'name': item[1]} for item in sorted(organizations, key=lambda x: x[1])], 'divisions': [{'id': item[0], 'name': item[1]} for item in sorted(divisions, key=lambda x: x[1])], 'weeks': [{'id': item[0], 'week_number': item[1]} for item in sorted(weeks, key=lambda x: x[1])], 'teams': [{'id': item[0], 'name': item[1]} for item in sorted(teams, key=lambda x: x[1])], 'statuses': [{'code': item[0], 'label': item[1]} for item in sorted(statuses, key=lambda x: x[1])]}



def _required_field_type_for_division(division: Division | None) -> str:
    if not division:
        return 'SMALL'
    layout_type = (division.required_field_layout_type or '').strip().upper()
    large_layout_tokens = ('FIFTY_THREE', '53', 'LARGE', 'FULL')
    return 'LARGE' if any(token in layout_type for token in large_layout_tokens) else 'SMALL'


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


def _schedule_management_rows(db: Session, filters: dict | None = None):
    filters = filters or {}
    q = db.query(Game, GameSlot, FieldInstance, HostLocation, Team, Team, Division, Organization, GameStatus).join(Game.status).join(Team, Game.home_team_id == Team.id).join(Division, Team.division_id == Division.id).join(Organization, Team.organization_id == Organization.id).join(Team, Game.away_team_id == Team.id, isouter=True)
    home = aliased(Team)
    away = aliased(Team)
    q = db.query(Game, GameSlot, FieldInstance, HostLocation, home, away, Division, Organization, GameStatus).join(Game.status).join(home, Game.home_team_id == home.id).join(away, Game.away_team_id == away.id).join(Division, home.division_id == Division.id).join(Organization, home.organization_id == Organization.id).outerjoin(GameSlot, GameSlot.assigned_game_id == Game.id).outerjoin(FieldInstance, FieldInstance.id == GameSlot.field_instance_id).outerjoin(HostLocation, HostLocation.id == GameSlot.host_location_id)
    q = q.filter(GameStatus.code != 'UNSCHEDULED')
    if filters.get('date'): q = q.filter(Game.game_date == filters['date'])
    if filters.get('division_id'): q = q.filter(Division.id == filters['division_id'])
    if filters.get('organization_id'): q = q.filter(home.organization_id == filters['organization_id'])
    if filters.get('host_location_id'): q = q.filter(HostLocation.id == filters['host_location_id'])
    if filters.get('field_type'): q = q.filter(GameSlot.field_type == filters['field_type'])
    if filters.get('field_id'): q = q.filter(FieldInstance.field_id == filters['field_id'])
    if filters.get('team_id'): q = q.filter((home.id == filters['team_id']) | (away.id == filters['team_id']))
    return q.order_by(Game.game_date, Game.kickoff_time).all()




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


@router.get('/schedule-management/quality-report', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def schedule_quality_report(division_id: uuid.UUID | None = None, organization_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    try:
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

        host_rows = db.query(HostingAvailability, HostLocation, Organization).join(HostingAvailability.host_location).join(HostLocation.organization)
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
            'games_per_team': games_per_team,
            'repeat_matchups': repeat_matchups,
            'home_away_balance': home_away_balance,
            'time_of_day_balance': time_of_day_balance,
            'host_community_priority': host_priority,
            'double_headers': double_headers,
            'unscheduled_teams': unscheduled,
            'field_utilization': field_utilization,
        }
    except Exception:
        logger.exception('Schedule quality report generation failed (division_id=%s organization_id=%s)', division_id, organization_id)
        return _empty_quality_report()

@router.get('/schedule-management/games', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def schedule_management_games(date: date | None = None, division_id: uuid.UUID | None = None, organization_id: uuid.UUID | None = None, host_location_id: uuid.UUID | None = None, field_type: str | None = None, field_id: uuid.UUID | None = None, team_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    rows = _schedule_management_rows(db, {'date': date, 'division_id': division_id, 'organization_id': organization_id, 'host_location_id': host_location_id, 'field_type': field_type, 'field_id': field_id, 'team_id': team_id})
    return {'items': [{
        'id': str(g.id), 'date': g.game_date.isoformat(), 'time': g.kickoff_time.strftime('%H:%M:%S'), 'division_id': str(div.id), 'division_name': div.name,
        'home_team_id': str(home.id), 'home_team_name': home.name, 'away_team_id': str(away.id), 'away_team_name': away.name,
        'organization_id': str(org.id), 'organization_name': org.name, 'host_location_id': (str(host.id) if host else None), 'host_location_name': (host.name if host else None),
        'field': (fi.field_name if fi else None), 'field_type': (slot.field_type if slot else None), 'status': status.code, 'slot_id': (str(slot.id) if slot else None), 'is_slot_active': (fi.is_active if fi else False),
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

@router.get('/schedule-management/export.csv', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def export_schedule_management_csv(date: date | None = None, division_id: uuid.UUID | None = None, organization_id: uuid.UUID | None = None, host_location_id: uuid.UUID | None = None, field_type: str | None = None, field_id: uuid.UUID | None = None, team_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    rows = _schedule_management_rows(db, {'date': date, 'division_id': division_id, 'organization_id': organization_id, 'host_location_id': host_location_id, 'field_type': field_type, 'field_id': field_id, 'team_id': team_id})
    out = io.StringIO(); w=csv.writer(out); w.writerow(['Date','Time','Division Group','Division','Division ID','Display Division Name','Category/Gender','Normalized Division Key','Home Team','Away Team','Host Location','Field','Field Type','Status'])
    export_division_names: set[str] = set()
    for g, slot, fi, host, home, away, div, org, status in rows:
        export_division_names.add(f'{div.division_group} {div.name}'.strip())
        w.writerow([g.game_date.isoformat(), g.kickoff_time.strftime('%H:%M'), div.division_group, div.name, str(div.id), f'{div.division_group} {div.name}'.strip(), div.division_group or '', normalized_division_key(div.division_group, div.name), home.name, away.name, host.name if host else '', fi.field_name if fi else '', slot.field_type if slot else '', status.code])
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
