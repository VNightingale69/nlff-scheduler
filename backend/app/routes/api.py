import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import (
    ROLE_COMMUNITY_SCHEDULER,
    ROLE_LEAGUE_ADMIN,
    enforce_organization_scope,
    get_current_user,
    require_roles,
    role_by_name,
)
from app.database import get_db
from app.models import Division, Field, Game, GameStatus, HostLocation, HostingAvailability, Organization, Role, Season, Team, User, Week
from app.schemas import (DivisionCreate, DivisionRead, FieldCreate, FieldRead, GameCreate, GameRead, GameStatusCreate, GameStatusRead, HostLocationCreate, HostLocationRead, HostingAvailabilityCreate, HostingAvailabilityRead, LoginRequest, OrganizationCreate, OrganizationRead, RefreshRequest, RoleCreate, RoleRead, SeasonCreate, SeasonRead, TeamCreate, TeamRead, TokenResponse, UserCreate, UserRead, WeekCreate, WeekRead)
from app.security import create_access_token, create_refresh_token, decode_token, hash_password, validate_password_strength, verify_password

router = APIRouter(prefix='/api')


def _create(db: Session, model, payload):
    obj = model(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.post('/auth/login', response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email, User.is_active.is_(True)).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail='Invalid credentials')
    uid = str(user.id)
    return TokenResponse(access_token=create_access_token(uid), refresh_token=create_refresh_token(uid))


@router.post('/auth/refresh', response_model=TokenResponse)
def refresh(payload: RefreshRequest):
    decoded = decode_token(payload.refresh_token, 'refresh')
    sub = decoded['sub']
    return TokenResponse(access_token=create_access_token(sub), refresh_token=create_refresh_token(sub))


@router.post('/users', response_model=UserRead, dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def create_user(payload: UserCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    validate_password_strength(payload.password)
    if payload.role_name == ROLE_COMMUNITY_SCHEDULER and not payload.organization_id:
        raise HTTPException(status_code=422, detail='Community Scheduler requires organization_id')
    if payload.role_name == ROLE_LEAGUE_ADMIN and payload.organization_id is not None:
        raise HTTPException(status_code=422, detail='League Admin cannot be organization-scoped')
    role = role_by_name(db, payload.role_name)
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409, detail='Email already exists')
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role_id=role.id,
        organization_id=payload.organization_id,
        is_active=payload.is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserRead.model_validate({**user.__dict__, 'role_name': role.name})


@router.get('/users', response_model=list[UserRead], dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [UserRead.model_validate({**u.__dict__, 'role_name': u.role.name}) for u in users]


@router.post('/roles', response_model=RoleRead, dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def create_role(payload: RoleCreate, db: Session = Depends(get_db)):
    return _create(db, Role, payload)

@router.get('/roles', response_model=list[RoleRead], dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def list_roles(db: Session = Depends(get_db)):
    return db.query(Role).all()

@router.post('/organizations', response_model=OrganizationRead, dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def create_organization(payload: OrganizationCreate, db: Session = Depends(get_db)):
    return _create(db, Organization, payload)

@router.get('/organizations', response_model=list[OrganizationRead], dependencies=[Depends(get_current_user)])
def list_organizations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role.name == ROLE_LEAGUE_ADMIN:
        return db.query(Organization).all()
    return db.query(Organization).filter(Organization.id == current_user.organization_id).all()

@router.post('/divisions', response_model=DivisionRead, dependencies=[Depends(get_current_user)])
def create_division(payload: DivisionCreate, db: Session = Depends(get_db)):
    return _create(db, Division, payload)
@router.get('/divisions', response_model=list[DivisionRead], dependencies=[Depends(get_current_user)])
def list_divisions(db: Session = Depends(get_db)):
    return db.query(Division).all()

@router.post('/host-locations', response_model=HostLocationRead, dependencies=[Depends(get_current_user)])
def create_host_location(payload: HostLocationCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enforce_organization_scope(payload.organization_id, current_user)
    return _create(db, HostLocation, payload)
@router.get('/host-locations', response_model=list[HostLocationRead], dependencies=[Depends(get_current_user)])
def list_host_locations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(HostLocation)
    if current_user.role.name == ROLE_COMMUNITY_SCHEDULER:
        q = q.filter(HostLocation.organization_id == current_user.organization_id)
    return q.all()

@router.post('/fields', response_model=FieldRead, dependencies=[Depends(get_current_user)])
def create_field(payload: FieldCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    host = db.query(HostLocation).filter(HostLocation.id == payload.host_location_id).first()
    if not host:
        raise HTTPException(status_code=404, detail='Host location not found')
    enforce_organization_scope(host.organization_id, current_user)
    return _create(db, Field, payload)
@router.get('/fields', response_model=list[FieldRead], dependencies=[Depends(get_current_user)])
def list_fields(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Field)
    if current_user.role.name == ROLE_COMMUNITY_SCHEDULER:
        q = q.join(HostLocation, HostLocation.id == Field.host_location_id).filter(HostLocation.organization_id == current_user.organization_id)
    return q.all()

@router.post('/teams', response_model=TeamRead, dependencies=[Depends(get_current_user)])
def create_team(payload: TeamCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enforce_organization_scope(payload.organization_id, current_user)
    return _create(db, Team, payload)
@router.get('/teams', response_model=list[TeamRead], dependencies=[Depends(get_current_user)])
def list_teams(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Team)
    if current_user.role.name == ROLE_COMMUNITY_SCHEDULER:
        q = q.filter(Team.organization_id == current_user.organization_id)
    return q.all()

@router.post('/seasons', response_model=SeasonRead, dependencies=[Depends(get_current_user)])
def create_season(payload: SeasonCreate, db: Session = Depends(get_db)): return _create(db, Season, payload)
@router.get('/seasons', response_model=list[SeasonRead], dependencies=[Depends(get_current_user)])
def list_seasons(db: Session = Depends(get_db)): return db.query(Season).all()
@router.post('/weeks', response_model=WeekRead, dependencies=[Depends(get_current_user)])
def create_week(payload: WeekCreate, db: Session = Depends(get_db)): return _create(db, Week, payload)
@router.get('/weeks', response_model=list[WeekRead], dependencies=[Depends(get_current_user)])
def list_weeks(db: Session = Depends(get_db)): return db.query(Week).all()
@router.post('/hosting-availabilities', response_model=HostingAvailabilityRead, dependencies=[Depends(get_current_user)])
def create_hosting_availability(payload: HostingAvailabilityCreate, db: Session = Depends(get_db)): return _create(db, HostingAvailability, payload)
@router.get('/hosting-availabilities', response_model=list[HostingAvailabilityRead], dependencies=[Depends(get_current_user)])
def list_hosting_availabilities(db: Session = Depends(get_db)): return db.query(HostingAvailability).all()
@router.post('/game-statuses', response_model=GameStatusRead, dependencies=[Depends(get_current_user)])
def create_game_status(payload: GameStatusCreate, db: Session = Depends(get_db)): return _create(db, GameStatus, payload)
@router.get('/game-statuses', response_model=list[GameStatusRead], dependencies=[Depends(get_current_user)])
def list_game_statuses(db: Session = Depends(get_db)): return db.query(GameStatus).all()
@router.post('/games', response_model=GameRead, dependencies=[Depends(get_current_user)])
def create_game(payload: GameCreate, db: Session = Depends(get_db)): return _create(db, Game, payload)
@router.get('/games', response_model=list[GameRead], dependencies=[Depends(get_current_user)])
def list_games(db: Session = Depends(get_db)): return db.query(Game).all()
