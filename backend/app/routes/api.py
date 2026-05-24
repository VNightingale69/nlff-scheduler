import csv
import io
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
import logging
from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, func, or_
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
    try:
        o = db.query(Organization).filter(Organization.id == org_id).first()
        if not o:
            raise HTTPException(404, 'Organization not found')
        if not force:
            db.delete(o)
            db.commit()
            return {'success': True, 'deleted': {'organization': 1}}

        blocked_game_count = db.query(Game).join(Game.status).filter(
            and_(
                Game.game_date >= date.today(),
                GameStatus.code.in_(['published', 'completed']),
                (Game.home_team_id.in_(db.query(Team.id).filter(Team.organization_id == org_id).subquery()) | Game.away_team_id.in_(db.query(Team.id).filter(Team.organization_id == org_id).subquery()))
            )
        ).count()
        if blocked_game_count > 0:
            raise HTTPException(400, 'Cannot force delete organization with future published or completed games. Delete historical game data confirmation is required.')

        host_location_ids = [host_id for (host_id,) in db.query(HostLocation.id).filter(HostLocation.organization_id == org_id).all()]
        field_ids = [field_id for (field_id,) in db.query(Field.id).filter(Field.host_location_id.in_(host_location_ids)).all()] if host_location_ids else []
        area_ids = [area_id for (area_id,) in db.query(PhysicalFieldArea.id).filter(PhysicalFieldArea.host_location_id.in_(host_location_ids)).all()] if host_location_ids else []
        team_ids = [team_id for (team_id,) in db.query(Team.id).filter(Team.organization_id == org_id).all()]

        warnings: list[str] = []
        deleted_availability, warning = _safe_delete_count('hosting_availability', lambda: db.query(HostingAvailability).filter((HostingAvailability.field_id.in_(field_ids)) | (HostingAvailability.physical_field_area_id.in_(area_ids))).delete(synchronize_session=False) if (field_ids or area_ids) else 0)
        if warning: warnings.append(warning)
        deleted_field_config, warning = _safe_delete_count('field_configuration_options', lambda: db.query(FieldConfigurationOption).filter(FieldConfigurationOption.physical_field_area_id.in_(area_ids)).delete(synchronize_session=False) if area_ids else 0)
        if warning: warnings.append(warning)
        deleted_areas, warning = _safe_delete_count('hosting_site_setups', lambda: db.query(PhysicalFieldArea).filter(PhysicalFieldArea.host_location_id.in_(host_location_ids)).delete(synchronize_session=False) if host_location_ids else 0)
        if warning: warnings.append(warning)
        deleted_fields, warning = _safe_delete_count('fields', lambda: db.query(Field).filter(Field.host_location_id.in_(host_location_ids)).delete(synchronize_session=False) if host_location_ids else 0)
        if warning: warnings.append(warning)
        deleted_teams, warning = _safe_delete_count('teams', lambda: db.query(Team).filter(Team.organization_id == org_id).delete(synchronize_session=False))
        if warning: warnings.append(warning)
        deleted_participation, warning = _safe_delete_count('division_participation', lambda: db.query(OrganizationDivisionParticipation).filter(OrganizationDivisionParticipation.organization_id == org_id).delete(synchronize_session=False))
        if warning: warnings.append(warning)
        deleted_hosts, warning = _safe_delete_count('host_locations', lambda: db.query(HostLocation).filter(HostLocation.organization_id == org_id).delete(synchronize_session=False))
        if warning: warnings.append(warning)
        db.delete(o)
        db.commit()
        return {'success': True, 'message': 'Organization and related data deleted successfully.', 'deleted': {'hosting_availability': deleted_availability, 'field_configuration_options': deleted_field_config, 'hosting_site_setups': deleted_areas, 'teams': deleted_teams, 'division_participation': deleted_participation, 'fields': deleted_fields, 'host_locations': deleted_hosts, 'organization': 1}, 'warnings': warnings}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception('Organization delete failed for org_id=%s force=%s', org_id, force)
        raise HTTPException(
            status_code=500,
            detail={
                'error': 'organization_delete_failed',
                'message': 'Unable to delete organization due to a server error.',
            },
        )


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
    assigned_slots = db.query(GameSlot).join(GameSlot.field_instance).filter(
        FieldInstance.hosting_availability_id == x.id,
        GameSlot.assigned_game_id.isnot(None),
    ).count()
    if assigned_slots > 0:
        raise HTTPException(400, 'Cannot delete availability with assigned generated slots.')
    db.query(GameSlot).filter(GameSlot.field_instance_id.in_(db.query(FieldInstance.id).filter(FieldInstance.hosting_availability_id == x.id))).delete(synchronize_session=False)
    db.query(FieldInstance).filter(FieldInstance.hosting_availability_id == x.id).delete(synchronize_session=False)
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
    grouped: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        if not row.physical_field_area:
            continue
        area = row.physical_field_area
        host = area.host_location
        option = row.field_configuration_option
        layout_name = option.name if option else 'Custom Layout'
        key = (str(row.available_date), str(area.id), layout_name)
        if key not in grouped:
            grouped[key] = {
                'available_date': row.available_date,
                'host_location_name': host.name,
                'site_type': area.field_space_type,
                'available_layout': layout_name,
                'small_field_capacity': option.thirty_yard_capacity if option else 0,
                'large_field_capacity': option.fifty_three_yard_capacity if option else 0,
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
            'available_date': data['available_date'],
            'host_location_name': data['host_location_name'],
            'site_type': data['site_type'],
            'available_layout': data['available_layout'],
            'small_field_capacity': data['small_field_capacity'],
            'large_field_capacity': data['large_field_capacity'],
            'time_ranges': ranges,
        })
    items.sort(key=lambda x: (x['available_date'], x['host_location_name']))
    return {'items': items}


@router.delete('/hosting-availabilities/saved', dependencies=[Depends(get_current_user)])
def delete_saved_hosting_availability(host_location_id: uuid.UUID, available_date: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    date_value = date.fromisoformat(available_date)
    q = db.query(HostingAvailability).join(HostingAvailability.physical_field_area).join(PhysicalFieldArea.host_location).filter(HostLocation.id == host_location_id, HostingAvailability.available_date == date_value)
    sample = q.first()
    if not sample:
        raise HTTPException(404, 'Saved availability not found')
    enforce_organization_scope(sample.physical_field_area.host_location.organization_id, current_user)
    availability_ids = [row.id for row in q.all()]
    assigned_slots = db.query(GameSlot).join(GameSlot.field_instance).filter(
        FieldInstance.hosting_availability_id.in_(availability_ids),
        GameSlot.assigned_game_id.isnot(None),
    ).count()
    if assigned_slots > 0:
        raise HTTPException(400, 'Cannot delete saved availability that has assigned generated slots.')
    db.query(GameSlot).filter(GameSlot.field_instance_id.in_(db.query(FieldInstance.id).filter(FieldInstance.hosting_availability_id.in_(availability_ids)))).delete(synchronize_session=False)
    db.query(FieldInstance).filter(FieldInstance.hosting_availability_id.in_(availability_ids)).delete(synchronize_session=False)
    deleted = q.delete(synchronize_session=False)
    db.commit()
    return {'ok': True, 'deleted': deleted}


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

    max_games_for_division_week = len(team_list) // 2 if division_id and week_id else None
    all_available_weekly_matchups_scheduled = (
        max_games_for_division_week is not None
        and len(already_scheduled_team_ids) >= (max_games_for_division_week * 2)
    )

    for i in range(len(team_list)):
        for j in range(i + 1, len(team_list)):
            a = team_list[i]
            b = team_list[j]
            key = tuple(sorted([a.id, b.id]))
            if a.id in already_scheduled_team_ids or b.id in already_scheduled_team_ids:
                continue
            if key in already_scheduled_pairs:
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
    return {
        'suggested_matchups': suggested_matchups[:25],
        'suggested_slots': slot_suggestions[:40],
        'all_available_weekly_matchups_scheduled': all_available_weekly_matchups_scheduled,
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
    expected_field_type = 'LARGE' if '53' in (division.required_field_layout_type or '') else 'SMALL'
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
    max_games_for_division_week = len(teams) // 2
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
    return {'game': _to_game_read(game), 'generated_slot_id': slot.id, 'status': 'SCHEDULED'}


@router.post('/manual-schedule-builder/auto-fill-preview', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def auto_fill_preview(payload: dict, db: Session = Depends(get_db)):
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
    season_id = payload.get('season_id')
    week_id = payload.get('week_id')
    division_id = payload.get('division_id')
    if not season_id or not week_id or not division_id:
        raise HTTPException(400, 'season_id, week_id, and division_id are required')
    division = db.query(Division).filter(Division.id == division_id).first()
    week = db.query(Week).filter(Week.id == week_id, Week.season_id == season_id).first()
    if not division or not week:
        raise HTTPException(404, 'Selected season/week/division is invalid')
    required_field_type = _required_field_type_for_division(division)
    teams = db.query(Team).filter(Team.division_id == division_id, Team.is_active.is_(True)).order_by(Team.name).all()
    teams_by_id = {t.id: t for t in teams}
    no_byes = bool(payload.get('no_byes', True))
    team_count = len(teams)
    is_odd_division = team_count % 2 == 1
    max_games_for_division_week = (team_count + 1) // 2 if (is_odd_division and no_byes) else team_count // 2
    existing_division_games = db.query(Game).join(Game.home_team).join(Game.status).filter(
        Game.season_id == season_id,
        Game.week_id == week_id,
        Team.division_id == division_id,
        Team.is_active.is_(True),
        GameStatus.code == 'SCHEDULED',
        GameStatus.is_active.is_(True),
    ).all()
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
    assigned_games = db.query(Game).join(GameSlot, GameSlot.assigned_game_id == Game.id).filter(
        Game.game_date == week.start_date
    ).all()
    season_division_games = db.query(Game).join(Game.home_team).join(Game.status).filter(
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
    plans = []
    skipped = []
    existing_games_count = len(existing_division_games)
    max_new_games = max(0, max_games_for_division_week - existing_games_count)
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
                'max_games_allowed': max_games_for_division_week,
                'counted_game_ids': counted_game_ids,
            }],
            'proposed_game_count': 0,
            'max_allowed_game_count': max_games_for_division_week,
            'existing_game_count': existing_games_count,
            'active_games_counted': existing_games_count,
            'counted_game_ids': counted_game_ids,
            'unused_team_ids': [str(tid) for tid in teams_by_id if tid not in used_team_ids],
            'unused_teams': [teams_by_id[tid].name for tid in teams_by_id if tid not in used_team_ids],
        }
    remaining_slots = list(open_slots)
    slots_by_host: dict[uuid.UUID, list[GameSlot]] = {}
    for slot in open_slots:
        if slot.host_location_id:
            slots_by_host.setdefault(slot.host_location_id, []).append(slot)
    games_required = max_new_games
    host_capacity = []
    for host_id, host_slots in slots_by_host.items():
        host_capacity.append({
            'host_id': host_id,
            'slot_count': len(host_slots),
            'field_count': len({s.field_instance_id for s in host_slots}),
            'continuity': len({(s.slot_date, s.start_time) for s in host_slots}),
        })
    host_capacity.sort(key=lambda x: (x['slot_count'] >= games_required, x['slot_count'], x['field_count'], x['continuity']), reverse=True)
    primary_host_id: uuid.UUID | None = host_capacity[0]['host_id'] if host_capacity else None
    single_site_possible = bool(host_capacity and host_capacity[0]['slot_count'] >= games_required)
    preferred_host_id: uuid.UUID | None = primary_host_id
    used_host_ids: set[uuid.UUID] = set()
    selected_double_header_team_id: uuid.UUID | None = None
    compatible_fields_by_host: dict[uuid.UUID, set[uuid.UUID]] = {}
    for slot in open_slots:
        if slot.host_location_id and slot.field_instance_id:
            compatible_fields_by_host.setdefault(slot.host_location_id, set()).add(slot.field_instance_id)
    layout_key = required_field_type.value if hasattr(required_field_type, 'value') else str(required_field_type)

    def _planned_field_usage_snapshot() -> tuple[dict[tuple[str, str, str], int], dict[tuple[str, str], int], dict[tuple[str, str, str, str], int], dict[tuple[str, str, str], int]]:
        usage_by_field_division_layout: dict[tuple[str, str, str], int] = {}
        usage_by_host_field: dict[tuple[str, str], int] = {}
        usage_by_host_slot_field: dict[tuple[str, str, str, str], int] = {}
        usage_by_host_field_layout: dict[tuple[str, str, str], int] = {}
        for p in plans:
            host_id = p.get('host_location_id')
            field_id = p.get('field_instance_id')
            slot_time = p.get('proposed_start_time')
            if not host_id or not field_id:
                continue
            usage_by_field_division_layout[(field_id, str(division_id), layout_key)] = usage_by_field_division_layout.get((field_id, str(division_id), layout_key), 0) + 1
            usage_by_host_field[(host_id, field_id)] = usage_by_host_field.get((host_id, field_id), 0) + 1
            usage_by_host_field_layout[(host_id, field_id, layout_key)] = usage_by_host_field_layout.get((host_id, field_id, layout_key), 0) + 1
            if slot_time:
                usage_by_host_slot_field[(host_id, str(slot_time), field_id, layout_key)] = usage_by_host_slot_field.get((host_id, str(slot_time), field_id, layout_key), 0) + 1
        return usage_by_field_division_layout, usage_by_host_field, usage_by_host_slot_field, usage_by_host_field_layout
    if is_odd_division and no_byes:
        min_dh = min(double_header_counts.values() or [0])
        candidates = [tid for tid, count in double_header_counts.items() if count == min_dh]
        candidates.sort(key=lambda tid: teams_by_id[tid].name)
        selected_double_header_team_id = candidates[0] if candidates else None
    while remaining_slots and len(plans) < max_new_games:
        if is_odd_division and no_byes and selected_double_header_team_id:
            available_team_ids = [tid for tid in teams_by_id if week_team_game_counts.get(tid, 0) < 1]
            if week_team_game_counts.get(selected_double_header_team_id, 0) < 2 and selected_double_header_team_id not in available_team_ids:
                available_team_ids.append(selected_double_header_team_id)
        else:
            available_team_ids = [tid for tid in teams_by_id if tid not in used_team_ids]
        if len(available_team_ids) < 2:
            break
        all_candidates = []
        for slot in remaining_slots:
            for i in range(len(available_team_ids)):
                for j in range(i + 1, len(available_team_ids)):
                    a = available_team_ids[i]
                    b = available_team_ids[j]
                    pair = tuple(sorted((a, b)))
                    if pair in used_pairs:
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
                    if matchup_counts.get(pair, 0) == 0:
                        score += 100
                        reason_bits.append('new opponent pairing (+100)')
                    else:
                        all_unique_exhausted = len(matchup_counts) >= max(1, (team_count * (team_count - 1)) // 2)
                        if all_unique_exhausted:
                            score -= 50
                            warning_bits.append('repeat matchup after unique options were limited (-50)')
                        else:
                            score -= 150
                            warning_bits.append('repeat matchup before unique options exhausted (-150)')
                    if hosted_by_own_community:
                        score += 60
                        reason_bits.append('same-community at home host field (+60)')
                    elif same_community:
                        score -= 80
                        warning_bits.append('same-community away from host field (-80)')
                    if host_pref:
                        score += 40
                        reason_bits.append('reduced travel via host alignment (+40)')
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
                        score += completion_weight
                        reason_bits.append(f'single-site completion path (+{completion_weight})')
                    if single_site_possible and primary_host_id and candidate_host_id != primary_host_id and serialization_required:
                        score -= completion_weight
                        warning_bits.append(f'avoidable multi-site fragmentation (-{completion_weight})')
                    if candidate_host_id and any(p.get('host_location_id') == str(candidate_host_id) for p in plans):
                        score += 25
                        reason_bits.append('adjacent time-slot grouping at same location (+25)')
                    if candidate_host_id and any(p.get('host_location_id') == str(candidate_host_id) and p.get('field') == (slot.field_instance.field_name if slot.field_instance else '') for p in plans):
                        score += 10
                        reason_bits.append('light adjacent-field grouping preference (+10)')
                    if candidate_host_id:
                        compatible_fields = compatible_fields_by_host.get(candidate_host_id, set())
                        if len(compatible_fields) > 1:
                            usage_by_field_division_layout, usage_by_host_field, usage_by_host_slot_field, usage_by_host_field_layout = _planned_field_usage_snapshot()
                            candidate_host_key = str(candidate_host_id)
                            slot_field_id = str(slot.field_instance_id) if slot.field_instance_id else None
                            host_layout_loads = [
                                usage_by_host_field_layout.get((candidate_host_key, str(fid), layout_key), 0)
                                for fid in compatible_fields
                            ]
                            min_host_layout_load = min(host_layout_loads) if host_layout_loads else 0
                            used_fields = {
                                p.get('field_instance_id') for p in plans
                                if p.get('host_location_id') == str(candidate_host_id) and p.get('field_instance_id')
                            }
                            if slot_field_id and slot_field_id not in used_fields:
                                score += balance_weight
                                reason_bits.append(f'field utilization balance via new compatible field (+{balance_weight})')
                            if slot_field_id:
                                division_layout_load = usage_by_field_division_layout.get((slot_field_id, str(division_id), layout_key), 0)
                                if division_layout_load == min_host_layout_load:
                                    score += balance_weight
                                    reason_bits.append(f'least-used compatible field for this division/layout (+{balance_weight})')
                                else:
                                    imbalance_penalty = max(1, balance_weight // 2) * (division_layout_load - min_host_layout_load)
                                    score -= imbalance_penalty
                                    warning_bits.append(f'compatible field has higher current load than alternatives (-{imbalance_penalty})')
                            projected_used = set(used_fields)
                            if slot_field_id:
                                projected_used.add(slot_field_id)

                            same_host_same_time_slots = [
                                s for s in remaining_slots
                                if s.host_location_id == candidate_host_id and s.start_time == slot.start_time
                            ]
                            concurrent_capacity = len({str(s.field_instance_id) for s in same_host_same_time_slots if s.field_instance_id})
                            projected_concurrent_load = len(projected_used)
                            if concurrent_capacity >= min_concurrent_games_for_balancing and projected_concurrent_load >= min_concurrent_games_for_balancing:
                                utilization_ratio = projected_concurrent_load / max(1, concurrent_capacity)
                                spread_gap = max(0.0, preferred_utilization_spread - utilization_ratio)
                                saturation_bonus = round(parallel_weight * utilization_ratio)
                                spread_penalty = round(parallel_weight * spread_gap)
                                score += saturation_bonus
                                if spread_penalty > 0:
                                    score -= spread_penalty
                                    warning_bits.append(f'concurrent field saturation below preferred spread (-{spread_penalty})')
                                reason_bits.append(f'concurrent field utilization {projected_concurrent_load}/{concurrent_capacity} (+{saturation_bonus})')

                            recent_host_fields = [
                                p.get('field_instance_id') for p in plans
                                if p.get('host_location_id') == str(candidate_host_id)
                            ]
                            consecutive_same_field = 0
                            if slot_field_id:
                                for planned_field in reversed(recent_host_fields):
                                    if planned_field == slot_field_id:
                                        consecutive_same_field += 1
                                    else:
                                        break
                            if consecutive_same_field >= max_consecutive_games_same_field:
                                overload_penalty = balance_weight * (consecutive_same_field - max_consecutive_games_same_field + 1)
                                score -= overload_penalty
                                warning_bits.append(f'field overused consecutively at host site (-{overload_penalty})')
                            if slot_field_id:
                                selected_field_total = usage_by_host_field.get((candidate_host_key, slot_field_id), 0)
                                less_used_exists = any(
                                    usage_by_host_field.get((candidate_host_key, str(other_field_id)), 0) < selected_field_total
                                    for other_field_id in compatible_fields
                                    if str(other_field_id) != slot_field_id
                                )
                                if consecutive_same_field > 0 and less_used_exists:
                                    reuse_penalty = max(1, balance_weight // 2) * consecutive_same_field
                                    score -= reuse_penalty
                                    warning_bits.append(f'excess consecutive reuse while other compatible fields are less used (-{reuse_penalty})')
                                slot_collision_count = usage_by_host_slot_field.get((candidate_host_key, str(slot.start_time), slot_field_id, layout_key), 0)
                                if slot_collision_count > 0:
                                    score -= 1000
                                    warning_bits.append('field already has assigned game at this host/time/layout (-1000)')
                    if is_odd_division and no_byes and selected_double_header_team_id:
                        includes_dh = selected_double_header_team_id in {a, b}
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

                    all_candidates.append({
                        'slot': slot,
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
        valid_candidates = cross_candidates if cross_candidates else filtered_candidates

        if not valid_candidates:
            break

        best = max(valid_candidates, key=lambda c: c['score'])
        slot = best['slot']
        if cross_candidates:
            same_community_rejected = any(c['same_community'] for c in filtered_candidates)
            if same_community_rejected:
                best['reason_bits'].append('Same-community matchup avoided because cross-community option exists')
        if best['prior_week_team_repeat']:
            best['reason_bits'].append('Selected because no better alternative remained')
        home_team = teams_by_id[best['home_team_id']]
        away_team = teams_by_id[best['away_team_id']]
        reason_bits = ['single game per team per selected week', *best['reason_bits'], *best['warning_bits']]
        plans.append({
            'slot_id': str(slot.id),
            'proposed_matchup': f'{home_team.name} vs {away_team.name}',
            'home_team_id': str(home_team.id),
            'away_team_id': str(away_team.id),
            'proposed_date': str(slot.slot_date),
            'proposed_start_time': str(slot.start_time),
            'host_location': slot.host_location.name if slot.host_location else '',
            'host_location_id': str(slot.host_location_id) if slot.host_location_id else None,
            'field': slot.field_instance.field_name if slot.field_instance else '',
            'field_instance_id': str(slot.field_instance_id) if slot.field_instance_id else None,
            'score': int(best['score']),
            'reason': '; '.join(reason_bits),
            'warnings': best['warning_bits'],
            'rules_relaxed': [],
            'week': week.week_number,
            'division': division.name,
        })
        used_pairs.add(tuple(sorted((best['home_team_id'], best['away_team_id']))))
        week_team_game_counts[best['home_team_id']] = week_team_game_counts.get(best['home_team_id'], 0) + 1
        week_team_game_counts[best['away_team_id']] = week_team_game_counts.get(best['away_team_id'], 0) + 1
        if not (is_odd_division and no_byes):
            used_team_ids.add(best['home_team_id'])
            used_team_ids.add(best['away_team_id'])
        if slot.host_location_id:
            used_host_ids.add(slot.host_location_id)
            if not preferred_host_id:
                preferred_host_id = slot.host_location_id
        remaining_slots = [s for s in remaining_slots if s.id != slot.id]
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
    return {
        'proposals': plans,
        'skipped': skipped,
        'proposed_game_count': len(plans),
        'max_allowed_game_count': max_games_for_division_week,
        'existing_game_count': existing_games_count,
        'unused_team_ids': unused_team_ids,
        'unused_teams': [teams_by_id[uuid.UUID(tid)].name for tid in unused_team_ids],
        'double_header_team_id': str(selected_double_header_team_id) if selected_double_header_team_id else None,
        'audit': {
            'total_games_per_team': per_team_games,
            'duplicate_matchups': duplicate_matchups,
            'double_header_teams_by_week': double_header_teams,
            'host_locations_used_count': len(used_host_ids),
            'host_locations_used': [str(hid) for hid in used_host_ids],
            'single_site_possible': single_site_possible,
            'centralization_requested': centralization_requested,
            'staffing_limited': staffing_limited,
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
            'unresolved_conflicts': [],
        },
    }


@router.post('/manual-schedule-builder/auto-fill-apply', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def auto_fill_apply(payload: dict, db: Session = Depends(get_db)):
    season_id = payload.get('season_id')
    week_id = payload.get('week_id')
    division_id = payload.get('division_id')
    proposals = payload.get('proposals') or []
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
    teams = db.query(Team).filter(Team.division_id == division_id, Team.is_active.is_(True)).all()
    team_ids = {t.id for t in teams}
    no_byes = bool(payload.get('no_byes', True))
    is_odd_division = len(teams) % 2 == 1
    max_games_for_division_week = (len(teams) + 1) // 2 if (is_odd_division and no_byes) else len(teams) // 2
    existing_division_games = db.query(Game).join(Game.home_team).join(Game.status).filter(
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
    existing_games_count = len(existing_division_games)
    teams_by_id = {str(team.id): team for team in teams}

    def _team_name(team_id: str | None) -> str:
        if not team_id:
            return 'Unknown Team'
        team = teams_by_id.get(str(team_id))
        return team.name if team else 'Unknown Team'

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

    for proposal in proposals:
        if existing_games_count + created_games >= max_games_for_division_week:
            skipped.append({'reason': 'weekly game limit reached for selected division/week'})
            break
        slot = db.query(GameSlot).join(GameSlot.field_instance).filter(GameSlot.id == proposal.get('slot_id')).first()
        if not slot or slot.status != 'OPEN' or slot.assigned_game_id is not None:
            skipped.append({'reason': 'not enough open matching slots (selected slot is no longer available)'})
            continue
        home_team_id = proposal.get('home_team_id')
        away_team_id = proposal.get('away_team_id')
        if not home_team_id or not away_team_id or home_team_id == away_team_id:
            skipped.append({'reason': 'no valid opponent available (invalid matchup payload)'})
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
            skipped.append({'reason': _fmt_duplicate_skip(str(home_team_id), str(away_team_id), slot)})
            continue
        home_uuid = uuid.UUID(str(home_team_id))
        away_uuid = uuid.UUID(str(away_team_id))
        home_limit = 2 if (is_odd_division and no_byes) else 1
        away_limit = 2 if (is_odd_division and no_byes) else 1
        if week_team_game_counts.get(home_uuid, 0) >= home_limit or week_team_game_counts.get(away_uuid, 0) >= away_limit:
            skipped.append({
                'reason': (
                    f"Skipped {_team_name(str(home_team_id))} vs {_team_name(str(away_team_id))} "
                    'because one team already has a game this week.'
                )
            })
            continue
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
        used_team_ids.add(home_uuid)
        used_team_ids.add(away_uuid)
        week_team_game_counts[home_uuid] = week_team_game_counts.get(home_uuid, 0) + 1
        week_team_game_counts[away_uuid] = week_team_game_counts.get(away_uuid, 0) + 1
        created_games += 1
        assigned_slots += 1
    db.commit()
    return {
        'proposed_count': len(proposals),
        'created_count': created_games,
        'skipped_count': len(skipped),
        'max_games': max_games_for_division_week,
        'created_games': created_games,
        'assigned_slots': assigned_slots,
        'skipped': skipped,
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
    return 'LARGE' if division and '53' in (division.required_field_layout_type or '') else 'SMALL'


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
    out = io.StringIO(); w=csv.writer(out); w.writerow(['Date','Time','Division','Home Team','Away Team','Host Location','Field','Status'])
    for g, slot, fi, host, home, away, div, org, status in rows:
        w.writerow([g.game_date.isoformat(), g.kickoff_time.strftime('%H:%M'), div.name, home.name, away.name, host.name if host else '', fi.field_name if fi else '', status.code])
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
