from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Division,
    Field,
    Game,
    GameStatus,
    HostLocation,
    HostingAvailability,
    Organization,
    Role,
    Season,
    Team,
    User,
    Week,
)
from app.schemas import (
    DivisionCreate,
    DivisionRead,
    FieldCreate,
    FieldRead,
    GameCreate,
    GameRead,
    GameStatusCreate,
    GameStatusRead,
    HostLocationCreate,
    HostLocationRead,
    HostingAvailabilityCreate,
    HostingAvailabilityRead,
    OrganizationCreate,
    OrganizationRead,
    RoleCreate,
    RoleRead,
    SeasonCreate,
    SeasonRead,
    TeamCreate,
    TeamRead,
    UserCreate,
    UserRead,
    WeekCreate,
    WeekRead,
)

router = APIRouter(prefix='/api')


def _create(db: Session, model, payload):
    obj = model(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def _list(db: Session, model):
    return db.query(model).all()


@router.post('/users', response_model=UserRead)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    return _create(db, User, payload)


@router.get('/users', response_model=list[UserRead])
def list_users(db: Session = Depends(get_db)):
    return _list(db, User)


@router.post('/roles', response_model=RoleRead)
def create_role(payload: RoleCreate, db: Session = Depends(get_db)):
    return _create(db, Role, payload)


@router.get('/roles', response_model=list[RoleRead])
def list_roles(db: Session = Depends(get_db)):
    return _list(db, Role)


@router.post('/organizations', response_model=OrganizationRead)
def create_organization(payload: OrganizationCreate, db: Session = Depends(get_db)):
    return _create(db, Organization, payload)


@router.get('/organizations', response_model=list[OrganizationRead])
def list_organizations(db: Session = Depends(get_db)):
    return _list(db, Organization)


@router.post('/divisions', response_model=DivisionRead)
def create_division(payload: DivisionCreate, db: Session = Depends(get_db)):
    return _create(db, Division, payload)


@router.get('/divisions', response_model=list[DivisionRead])
def list_divisions(db: Session = Depends(get_db)):
    return _list(db, Division)


@router.post('/host-locations', response_model=HostLocationRead)
def create_host_location(payload: HostLocationCreate, db: Session = Depends(get_db)):
    return _create(db, HostLocation, payload)


@router.get('/host-locations', response_model=list[HostLocationRead])
def list_host_locations(db: Session = Depends(get_db)):
    return _list(db, HostLocation)


@router.post('/fields', response_model=FieldRead)
def create_field(payload: FieldCreate, db: Session = Depends(get_db)):
    return _create(db, Field, payload)


@router.get('/fields', response_model=list[FieldRead])
def list_fields(db: Session = Depends(get_db)):
    return _list(db, Field)


@router.post('/teams', response_model=TeamRead)
def create_team(payload: TeamCreate, db: Session = Depends(get_db)):
    return _create(db, Team, payload)


@router.get('/teams', response_model=list[TeamRead])
def list_teams(db: Session = Depends(get_db)):
    return _list(db, Team)


@router.post('/seasons', response_model=SeasonRead)
def create_season(payload: SeasonCreate, db: Session = Depends(get_db)):
    return _create(db, Season, payload)


@router.get('/seasons', response_model=list[SeasonRead])
def list_seasons(db: Session = Depends(get_db)):
    return _list(db, Season)


@router.post('/weeks', response_model=WeekRead)
def create_week(payload: WeekCreate, db: Session = Depends(get_db)):
    return _create(db, Week, payload)


@router.get('/weeks', response_model=list[WeekRead])
def list_weeks(db: Session = Depends(get_db)):
    return _list(db, Week)


@router.post('/hosting-availabilities', response_model=HostingAvailabilityRead)
def create_hosting_availability(payload: HostingAvailabilityCreate, db: Session = Depends(get_db)):
    return _create(db, HostingAvailability, payload)


@router.get('/hosting-availabilities', response_model=list[HostingAvailabilityRead])
def list_hosting_availabilities(db: Session = Depends(get_db)):
    return _list(db, HostingAvailability)


@router.post('/game-statuses', response_model=GameStatusRead)
def create_game_status(payload: GameStatusCreate, db: Session = Depends(get_db)):
    return _create(db, GameStatus, payload)


@router.get('/game-statuses', response_model=list[GameStatusRead])
def list_game_statuses(db: Session = Depends(get_db)):
    return _list(db, GameStatus)


@router.post('/games', response_model=GameRead)
def create_game(payload: GameCreate, db: Session = Depends(get_db)):
    return _create(db, Game, payload)


@router.get('/games', response_model=list[GameRead])
def list_games(db: Session = Depends(get_db)):
    return _list(db, Game)
