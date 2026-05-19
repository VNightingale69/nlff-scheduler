import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.auth import ROLE_COMMUNITY_SCHEDULER, ROLE_LEAGUE_ADMIN, enforce_organization_scope, get_current_user, require_roles
from app.database import get_db
from app.models import Division, Field, HostLocation, HostingAvailability, Organization, Team, User
from app.schemas import (
    DivisionCreate, DivisionRead, FieldCreate, FieldRead, HostLocationCreate, HostLocationRead,
    HostingAvailabilityCreate, HostingAvailabilityRead, OrganizationCreate, OrganizationRead,
    TeamCreate, TeamRead, PagedResponse
)

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
