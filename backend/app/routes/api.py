import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, aliased
from app.auth import ROLE_COMMUNITY_SCHEDULER, ROLE_LEAGUE_ADMIN, enforce_organization_scope, get_current_user, require_roles
from app.database import get_db
from app.models import Division, Field, Game, GameStatus, HostLocation, HostingAvailability, Organization, Season, Team, User, Week
from app.schemas import (
    DivisionCreate, DivisionRead, FieldCreate, FieldRead, GameCreate, GameRead, GameSaveResponse,
    HostLocationCreate, HostLocationRead, HostingAvailabilityCreate, HostingAvailabilityRead,
    OrganizationCreate, OrganizationRead, PublicGameRead, TeamCreate, TeamRead, PagedResponse
)
from app.services.scheduling_validation import validate_game

router = APIRouter(prefix='/api')

def paginate(query, page:int, page_size:int):
    total=query.count(); items=query.offset((page-1)*page_size).limit(page_size).all();
    return PagedResponse(items=items,total=total,page=page,page_size=page_size)

@router.post('/organizations', response_model=OrganizationRead, dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def create_organization(payload: OrganizationCreate, db: Session = Depends(get_db)):
    obj=Organization(**payload.model_dump()); db.add(obj); db.commit(); db.refresh(obj); return obj

@router.get('/organizations', response_model=PagedResponse[OrganizationRead], dependencies=[Depends(get_current_user)])
def list_organizations(search:str|None=None, is_active:bool|None=None, page:int=1, page_size:int=20, current_user:User=Depends(get_current_user), db:Session=Depends(get_db)):
    q=db.query(Organization)
    if current_user.role.name==ROLE_COMMUNITY_SCHEDULER: q=q.filter(Organization.id==current_user.organization_id)
    if search: q=q.filter(func.lower(Organization.name).like(f"%{search.lower()}%"))
    if is_active is not None: q=q.filter(Organization.is_active==is_active)
    return paginate(q.order_by(Organization.name),page,page_size)

@router.put('/organizations/{org_id}', response_model=OrganizationRead, dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def update_organization(org_id:uuid.UUID,payload:OrganizationCreate,db:Session=Depends(get_db)):
    o=db.query(Organization).filter(Organization.id==org_id).first();
    if not o: raise HTTPException(404,'Organization not found')
    for k,v in payload.model_dump().items(): setattr(o,k,v)
    db.commit(); db.refresh(o); return o

@router.delete('/organizations/{org_id}', dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def delete_organization(org_id:uuid.UUID,db:Session=Depends(get_db)):
    o=db.query(Organization).filter(Organization.id==org_id).first();
    if not o: raise HTTPException(404,'Organization not found')
    db.delete(o); db.commit(); return {'ok':True}

# similar basic CRUD
@router.post('/divisions', response_model=DivisionRead, dependencies=[Depends(get_current_user)])
def create_division(payload:DivisionCreate, db:Session=Depends(get_db)):
    d=Division(**payload.model_dump()); db.add(d); db.commit(); db.refresh(d); return d

@router.get('/divisions', response_model=PagedResponse[DivisionRead], dependencies=[Depends(get_current_user)])
def list_divisions(search:str|None=None, page:int=1,page_size:int=20, db:Session=Depends(get_db)):
    q=db.query(Division)
    if search: q=q.filter(func.lower(Division.name).like(f"%{search.lower()}%"))
    return paginate(q.order_by(Division.name),page,page_size)

@router.put('/divisions/{item_id}', response_model=DivisionRead, dependencies=[Depends(get_current_user)])
def upd_div(item_id:uuid.UUID,payload:DivisionCreate,db:Session=Depends(get_db)):
    x=db.query(Division).filter(Division.id==item_id).first();
    if not x: raise HTTPException(404,'Division not found')
    for k,v in payload.model_dump().items(): setattr(x,k,v)
    db.commit(); db.refresh(x); return x

@router.delete('/divisions/{item_id}', dependencies=[Depends(get_current_user)])
def del_div(item_id:uuid.UUID,db:Session=Depends(get_db)):
    x=db.query(Division).filter(Division.id==item_id).first();
    if not x: raise HTTPException(404,'Division not found')
    db.delete(x); db.commit(); return {'ok':True}

@router.post('/teams', response_model=TeamRead, dependencies=[Depends(get_current_user)])
def create_team(payload:TeamCreate,current_user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    enforce_organization_scope(payload.organization_id,current_user)
    x=Team(**payload.model_dump()); db.add(x); db.commit(); db.refresh(x); return x
@router.get('/teams', response_model=PagedResponse[TeamRead], dependencies=[Depends(get_current_user)])
def list_teams(search:str|None=None, organization_id:uuid.UUID|None=None, division_id:uuid.UUID|None=None, page:int=1,page_size:int=20,current_user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    q=db.query(Team)
    if current_user.role.name==ROLE_COMMUNITY_SCHEDULER: q=q.filter(Team.organization_id==current_user.organization_id)
    elif organization_id: q=q.filter(Team.organization_id==organization_id)
    if division_id: q=q.filter(Team.division_id==division_id)
    if search: q=q.filter(func.lower(Team.name).like(f"%{search.lower()}%"))
    return paginate(q.order_by(Team.name),page,page_size)
@router.put('/teams/{item_id}', response_model=TeamRead, dependencies=[Depends(get_current_user)])
def upd_team(item_id:uuid.UUID,payload:TeamCreate,current_user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    x=db.query(Team).filter(Team.id==item_id).first();
    if not x: raise HTTPException(404,'Team not found')
    enforce_organization_scope(payload.organization_id,current_user)
    for k,v in payload.model_dump().items(): setattr(x,k,v)
    db.commit(); db.refresh(x); return x
@router.delete('/teams/{item_id}', dependencies=[Depends(get_current_user)])
def del_team(item_id:uuid.UUID,current_user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    x=db.query(Team).filter(Team.id==item_id).first();
    if not x: raise HTTPException(404,'Team not found')
    enforce_organization_scope(x.organization_id,current_user); db.delete(x); db.commit(); return {'ok':True}


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
    return GameRead(
        id=g.id,created_at=g.created_at,updated_at=g.updated_at,season_id=g.season_id,week_id=g.week_id,
        division_id=g.home_team.division_id,home_team_id=g.home_team_id,away_team_id=g.away_team_id,field_id=g.field_id,
        game_status_id=g.game_status_id,game_date=g.game_date,kickoff_time=g.kickoff_time,status_code=g.status.code
    )

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
def list_public_games(
    host_location_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    division_id: uuid.UUID | None = None,
    week_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    status_code: str | None = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
):
    home_team = aliased(Team)
    away_team = aliased(Team)
    q = (
        db.query(Game)
        .join(Game.status)
        .join(Game.field)
        .join(Field.host_location)
        .join(HostLocation.organization)
        .join(home_team, Game.home_team)
        .join(away_team, Game.away_team)
    )
    q = q.filter(GameStatus.code == 'published')
    if host_location_id:
        q = q.filter(Field.host_location_id == host_location_id)
    if organization_id:
        q = q.filter(HostLocation.organization_id == organization_id)
    if division_id:
        q = q.filter(home_team.division_id == division_id)
    if week_id:
        q = q.filter(Game.week_id == week_id)
    if team_id:
        q = q.filter((Game.home_team_id == team_id) | (Game.away_team_id == team_id))
    if status_code:
        q = q.filter(GameStatus.code == status_code)

    total = q.count()
    items = q.order_by(Game.game_date, Game.kickoff_time).offset((page - 1) * page_size).limit(page_size).all()
    return PagedResponse(
        items=[
            PublicGameRead(
                id=g.id,
                game_date=g.game_date,
                kickoff_time=g.kickoff_time,
                host_location_id=g.field.host_location.id,
                host_location_name=g.field.host_location.name,
                field_id=g.field.id,
                field_name=g.field.name,
                organization_id=g.field.host_location.organization.id,
                organization_name=g.field.host_location.organization.name,
                division_id=g.home_team.division_id,
                division_name=g.home_team.division.name,
                week_id=g.week_id,
                week_number=g.week.week_number,
                home_team_id=g.home_team_id,
                home_team_name=g.home_team.name,
                away_team_id=g.away_team_id,
                away_team_name=g.away_team.name,
                game_status_id=g.game_status_id,
                game_status_code=g.status.code,
                game_status_label=g.status.label,
            )
            for g in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get('/public/schedule-filters')
def list_public_schedule_filters(db: Session = Depends(get_db)):
    games = db.query(Game).join(Game.status).join(Game.field).join(Field.host_location).join(HostLocation.organization).join(Game.home_team).filter(GameStatus.code == 'published').all()
    host_locations = {(g.field.host_location.id, g.field.host_location.name) for g in games}
    organizations = {(g.field.host_location.organization.id, g.field.host_location.organization.name) for g in games}
    divisions = {(g.home_team.division.id, g.home_team.division.name) for g in games}
    weeks = {(g.week.id, g.week.week_number) for g in games}
    teams = {(g.home_team.id, g.home_team.name) for g in games} | {(g.away_team.id, g.away_team.name) for g in games}
    statuses = {(g.status.code, g.status.label) for g in games}
    return {
        'host_locations': [{'id': item[0], 'name': item[1]} for item in sorted(host_locations, key=lambda x: x[1])],
        'organizations': [{'id': item[0], 'name': item[1]} for item in sorted(organizations, key=lambda x: x[1])],
        'divisions': [{'id': item[0], 'name': item[1]} for item in sorted(divisions, key=lambda x: x[1])],
        'weeks': [{'id': item[0], 'week_number': item[1]} for item in sorted(weeks, key=lambda x: x[1])],
        'teams': [{'id': item[0], 'name': item[1]} for item in sorted(teams, key=lambda x: x[1])],
        'statuses': [{'code': item[0], 'label': item[1]} for item in sorted(statuses, key=lambda x: x[1])],
    }

@router.post('/games', response_model=GameSaveResponse, dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def create_game(payload:GameCreate, db:Session=Depends(get_db)):
    validation=validate_game(db,payload)
    status=db.query(GameStatus).filter(GameStatus.id==payload.game_status_id).first()
    if not status: raise HTTPException(400,'Invalid game status')
    if status.code=='published' and validation.hard_conflicts:
        raise HTTPException(status_code=400, detail={'error':'hard_conflicts','validation':validation.model_dump()})
    obj=Game(**payload.model_dump(exclude={'division_id'})); db.add(obj); db.commit(); db.refresh(obj)
    return GameSaveResponse(game=_to_game_read(obj), validation=validation)

@router.put('/games/{game_id}', response_model=GameSaveResponse, dependencies=[Depends(require_roles(ROLE_LEAGUE_ADMIN))])
def update_game(game_id:uuid.UUID,payload:GameCreate, db:Session=Depends(get_db)):
    obj=db.query(Game).filter(Game.id==game_id).first()
    if not obj: raise HTTPException(404,'Game not found')
    validation=validate_game(db,payload,game_id=game_id)
    status=db.query(GameStatus).filter(GameStatus.id==payload.game_status_id).first()
    if not status: raise HTTPException(400,'Invalid game status')
    if status.code=='published' and validation.hard_conflicts:
        raise HTTPException(status_code=400, detail={'error':'hard_conflicts','validation':validation.model_dump()})
    for k,v in payload.model_dump(exclude={'division_id'}).items(): setattr(obj,k,v)
    db.commit(); db.refresh(obj)
    return GameSaveResponse(game=_to_game_read(obj), validation=validation)
