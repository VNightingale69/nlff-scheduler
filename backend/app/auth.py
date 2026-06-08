import re
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User
from app.security import decode_token

security = HTTPBearer()

ROLE_LEAGUE_ADMIN = 'LEAGUE_ADMIN'
ROLE_COMMUNITY_ADMIN = 'COMMUNITY_ADMIN'
ROLE_SCHEDULING_ADMIN = 'SCHEDULING_ADMIN'
LEGACY_ROLE_LEAGUE_ADMIN = 'league_admin'
LEGACY_ROLE_COMMUNITY_SCHEDULER = 'community_scheduler'
ROLE_COMMUNITY_SCHEDULER = ROLE_COMMUNITY_ADMIN

_ROLE_ALIASES = {
    LEGACY_ROLE_LEAGUE_ADMIN: ROLE_LEAGUE_ADMIN,
    ROLE_LEAGUE_ADMIN: ROLE_LEAGUE_ADMIN,
    LEGACY_ROLE_COMMUNITY_SCHEDULER: ROLE_COMMUNITY_ADMIN,
    ROLE_COMMUNITY_ADMIN: ROLE_COMMUNITY_ADMIN,
    ROLE_SCHEDULING_ADMIN: ROLE_SCHEDULING_ADMIN,
    'SCHEDULING_ADMINISTRATOR': ROLE_SCHEDULING_ADMIN,
    'Scheduling Administrator': ROLE_SCHEDULING_ADMIN,
    'scheduling_administrator': ROLE_SCHEDULING_ADMIN,
}


def normalize_role_name(role_name: str | None) -> str:
    raw_role_name = role_name or ''
    if raw_role_name in _ROLE_ALIASES:
        return _ROLE_ALIASES[raw_role_name]
    normalized_role_name = re.sub(r'[^A-Za-z0-9]+', '_', raw_role_name.strip()).strip('_').upper()
    return _ROLE_ALIASES.get(normalized_role_name, raw_role_name)


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)) -> User:
    payload = decode_token(credentials.credentials, 'access')
    user_id = payload.get('sub')
    user = db.query(User).filter(User.id == uuid.UUID(user_id), User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='User not found or inactive')
    return user


def require_roles(*allowed_roles: str):
    normalized_allowed_roles = {normalize_role_name(role) for role in allowed_roles}

    def checker(current_user: User = Depends(get_current_user)) -> User:
        if normalize_role_name(current_user.role.name) not in normalized_allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Insufficient role')
        return current_user

    return checker


def is_league_admin(current_user: User) -> bool:
    return normalize_role_name(current_user.role.name) == ROLE_LEAGUE_ADMIN


def is_community_admin(current_user: User) -> bool:
    return normalize_role_name(current_user.role.name) == ROLE_COMMUNITY_ADMIN


def enforce_organization_scope(request_org_id: uuid.UUID | None, current_user: User) -> None:
    if is_league_admin(current_user):
        return
    if is_community_admin(current_user):
        if not current_user.organization_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='User has no community scope')
        if request_org_id and request_org_id != current_user.organization_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Community scope violation')
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Unsupported role')


def role_by_name(db: Session, role_name: str) -> Role:
    normalized_role_name = normalize_role_name(role_name)
    role = db.query(Role).filter(Role.name == normalized_role_name, Role.is_active.is_(True)).first()
    if not role:
        legacy_name = next((name for name, normalized in _ROLE_ALIASES.items() if normalized == normalized_role_name), None)
        if legacy_name:
            role = db.query(Role).filter(Role.name == legacy_name, Role.is_active.is_(True)).first()
    if not role:
        raise HTTPException(status_code=400, detail=f'Role {role_name} does not exist')
    return role
