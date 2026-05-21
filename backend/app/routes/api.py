import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
import logging
from datetime import date, time

from sqlalchemy import and_, func
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError
from sqlalchemy.orm import Session, aliased

from app.auth import ROLE_COMMUNITY_SCHEDULER, ROLE_LEAGUE_ADMIN, enforce_organization_scope, get_current_user, require_roles
from app.database import get_db
from app.models import Division, Field, FieldConfigurationOption, Game, GameStatus, HostLocation, HostingAvailability, Organization, OrganizationDivisionParticipation, PhysicalFieldArea, Role, Season, Team, User, Week
from app.schemas import (
    DivisionCreate, DivisionRead, FieldConfigurationOptionCreate, FieldConfigurationOptionRead, FieldCreate, FieldRead, GameCreate, GameRead, GameSaveResponse,
    OrganizationDivisionParticipationBulkUpsertRequest, OrganizationDivisionParticipationRead,
    HostLocationCreate, HostLocationRead, HostingAvailabilityCreate, HostingAvailabilityRead, HostingAvailabilityBulkUpsertRequest, HostingAvailabilityBulkUpsertResponse, PhysicalFieldAreaCreate, PhysicalFieldAreaRead, SavedAvailabilityResponse,
    LoginRequest, OrganizationCreate, OrganizationRead, PagedResponse, PublicGameRead, RefreshRequest,
    TeamCreate, TeamRead, TokenResponse, UserCreate, UserRead
)
from app.security import create_access_token, create_refresh_token, hash_password, validate_password_strength, verify_password, decode_token
from app.services.scheduling_validation import validate_game

router = APIRouter(prefix='/api')
logger = logging.getLogger(__name__)
ALLOWED_FIELD_SPACE_TYPES = {
    'STADIUM_SITE',
    'GRASS_PARK_SITE',
}



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
    if db.query(Division).count() > 0:
        return
    for item in LEAGUE_DIVISION_SEED:
        db.add(Division(**item))
    db.commit()

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
    x = HostingAvailability(**payload.model_dump()); db.add(x); db.commit(); db.refresh(x); return x

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
    field = db.query(Field).join(Field.host_location).filter(Field.id == payload.field_id).first()
    if not field: raise HTTPException(400, 'Invalid field')
    enforce_organization_scope(field.host_location.organization_id, current_user)
    for k, v in payload.model_dump().items(): setattr(x, k, v)
    db.commit(); db.refresh(x); return x

@router.delete('/hosting-availabilities/{item_id}', dependencies=[Depends(get_current_user)])
def del_hosting_availability(item_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(HostingAvailability).filter(HostingAvailability.id == item_id).first()
    if not x: raise HTTPException(404, 'Hosting availability not found')
    enforce_organization_scope(x.field.host_location.organization_id, current_user)
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
        else:
            db.add(HostingAvailability(**slot.model_dump()))
            created += 1
    db.commit()
    return HostingAvailabilityBulkUpsertResponse(created=created, updated=updated)
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
    deleted = q.delete(synchronize_session=False)
    db.commit()
    return {'ok': True, 'deleted': deleted}


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

@router.delete('/teams/{item_id}', dependencies=[Depends(get_current_user)])
def del_team(item_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = db.query(Team).filter(Team.id == item_id).first()
    if not x: raise HTTPException(404, 'Team not found')
    enforce_organization_scope(x.organization_id, current_user); db.delete(x); db.commit(); return {'ok': True}

# keep existing game/public routes omitted for brevity

@router.get('/game-statuses', response_model=PagedResponse[dict], dependencies=[Depends(get_current_user)])
def list_game_statuses(page:int=1,page_size:int=50, db:Session=Depends(get_db)):
    q=db.query(GameStatus).order_by(GameStatus.label)
    return PagedResponse(items=[{"id":x.id,"code":x.code,"label":x.label} for x in q.offset((page-1)*page_size).limit(page_size).all()], total=q.count(), page=page, page_size=page_size)

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

def _to_game_read(g: Game) -> GameRead:
    return GameRead(id=g.id,created_at=g.created_at,updated_at=g.updated_at,season_id=g.season_id,week_id=g.week_id,division_id=g.home_team.division_id,home_team_id=g.home_team_id,away_team_id=g.away_team_id,field_id=g.field_id,game_status_id=g.game_status_id,game_date=g.game_date,kickoff_time=g.kickoff_time,status_code=g.status.code)

@router.get('/games', response_model=PagedResponse[GameRead], dependencies=[Depends(get_current_user)])
def list_games(division_id:uuid.UUID|None=None, week_id:uuid.UUID|None=None, team_id:uuid.UUID|None=None, host_location_id:uuid.UUID|None=None, status_code:str|None=None, page:int=1,page_size:int=50, db:Session=Depends(get_db)):
    q=db.query(Game).join(Game.status).join(Game.home_team).join(Game.field)
    if division_id: q=q.filter(Team.division_id==division_id)
    if week_id: q=q.filter(Game.week_id==week_id)
    if team_id: q=q.filter((Game.home_team_id==team_id)|(Game.away_team_id==team_id))
    if host_location_id: q=q.filter(Field.host_location_id==host_location_id)
    if status_code: q=q.filter(GameStatus.code==status_code)
    total=q.count(); items=q.order_by(Game.game_date, Game.kickoff_time).offset((page-1)*page_size).limit(page_size).all()
    return PagedResponse(items=[_to_game_read(x) for x in items], total=total, page=page, page_size=page_size)

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
    return PagedResponse(items=[PublicGameRead(id=g.id,game_date=g.game_date,kickoff_time=g.kickoff_time,host_location_id=g.field.host_location.id,host_location_name=g.field.host_location.name,field_id=g.field.id,field_name=g.field.name,organization_id=g.field.host_location.organization.id,organization_name=g.field.host_location.organization.name,division_id=g.home_team.division_id,division_name=g.home_team.division.name,week_id=g.week_id,week_number=g.week.week_number,home_team_id=g.home_team_id,home_team_name=g.home_team.name,away_team_id=g.away_team_id,away_team_name=g.away_team.name,game_status_id=g.game_status_id,game_status_code=g.status.code,game_status_label=g.status.label) for g in items], total=total, page=page, page_size=page_size)

@router.get('/public/schedule-filters')
def list_public_schedule_filters(db: Session = Depends(get_db)):
    games = db.query(Game).join(Game.status).join(Game.field).join(Field.host_location).join(HostLocation.organization).join(Game.home_team).filter(GameStatus.code == 'published').all()
    host_locations = {(g.field.host_location.id, g.field.host_location.name) for g in games}; organizations = {(g.field.host_location.organization.id, g.field.host_location.organization.name) for g in games}; divisions = {(g.home_team.division.id, g.home_team.division.name) for g in games}; weeks = {(g.week.id, g.week.week_number) for g in games}; teams = {(g.home_team.id, g.home_team.name) for g in games} | {(g.away_team.id, g.away_team.name) for g in games}; statuses = {(g.status.code, g.status.label) for g in games}
    return {'host_locations': [{'id': item[0], 'name': item[1]} for item in sorted(host_locations, key=lambda x: x[1])], 'organizations': [{'id': item[0], 'name': item[1]} for item in sorted(organizations, key=lambda x: x[1])], 'divisions': [{'id': item[0], 'name': item[1]} for item in sorted(divisions, key=lambda x: x[1])], 'weeks': [{'id': item[0], 'week_number': item[1]} for item in sorted(weeks, key=lambda x: x[1])], 'teams': [{'id': item[0], 'name': item[1]} for item in sorted(teams, key=lambda x: x[1])], 'statuses': [{'code': item[0], 'label': item[1]} for item in sorted(statuses, key=lambda x: x[1])]}

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
