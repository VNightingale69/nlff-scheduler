import re
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User
from app.security import auth_invalid_token_exception, decode_token

security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)

ROLE_LEAGUE_ADMIN = 'LEAGUE_ADMIN'
ROLE_COMMUNITY_ADMIN = 'COMMUNITY_ADMIN'
ROLE_SCHEDULING_ADMIN = 'SCHEDULING_ADMIN'
LEGACY_ROLE_LEAGUE_ADMIN = 'league_admin'
LEGACY_ROLE_COMMUNITY_SCHEDULER = 'community_scheduler'
ROLE_COMMUNITY_SCHEDULER = ROLE_COMMUNITY_ADMIN

SCHEDULE_MANAGEMENT_ROLES = {ROLE_LEAGUE_ADMIN, ROLE_SCHEDULING_ADMIN}
SCORE_MANAGEMENT_ROLES = {ROLE_LEAGUE_ADMIN, ROLE_SCHEDULING_ADMIN}
SCORE_APPROVAL_ROLES = SCORE_MANAGEMENT_ROLES

_ROLE_ALIASES = {
    'ADMIN': ROLE_LEAGUE_ADMIN,
    'Admin': ROLE_LEAGUE_ADMIN,
    'admin': ROLE_LEAGUE_ADMIN,
    LEGACY_ROLE_LEAGUE_ADMIN: ROLE_LEAGUE_ADMIN,
    ROLE_LEAGUE_ADMIN: ROLE_LEAGUE_ADMIN,
    LEGACY_ROLE_COMMUNITY_SCHEDULER: ROLE_COMMUNITY_ADMIN,
    ROLE_COMMUNITY_ADMIN: ROLE_COMMUNITY_ADMIN,
    ROLE_SCHEDULING_ADMIN: ROLE_SCHEDULING_ADMIN,
    'SCHEDULING_ADMINISTRATOR': ROLE_SCHEDULING_ADMIN,
    'Scheduling Administrator': ROLE_SCHEDULING_ADMIN,
    'scheduling_administrator': ROLE_SCHEDULING_ADMIN,
    'scheduling_admin': ROLE_SCHEDULING_ADMIN,
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
    try:
        user_uuid = uuid.UUID(user_id)
    except (TypeError, ValueError):
        raise auth_invalid_token_exception()
    user = db.query(User).filter(User.id == user_uuid, User.is_active.is_(True)).first()
    if not user:
        raise auth_invalid_token_exception()
    return user




def get_optional_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(optional_security), db: Session = Depends(get_db)) -> User | None:
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials, 'access')
        user_id = payload.get('sub')
        if not user_id:
            return None
        return db.query(User).filter(User.id == uuid.UUID(user_id), User.is_active.is_(True)).first()
    except Exception:
        return None

def require_roles(*allowed_roles: str):
    normalized_allowed_roles = {normalize_role_name(role) for role in allowed_roles}

    def checker(current_user: User = Depends(get_current_user)) -> User:
        if normalize_role_name(current_user.role.name) not in normalized_allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Insufficient role')
        return current_user

    return checker


def is_league_admin(current_user: User) -> bool:
    return normalize_role_name(current_user.role.name) == ROLE_LEAGUE_ADMIN


def is_scheduling_admin(current_user: User) -> bool:
    return normalize_role_name(current_user.role.name) == ROLE_SCHEDULING_ADMIN


def can_manage_schedule(current_user: User | None) -> bool:
    if not current_user or not getattr(current_user, 'role', None):
        return False
    return normalize_role_name(current_user.role.name) in SCHEDULE_MANAGEMENT_ROLES


def can_publish_schedule(current_user: User | None) -> bool:
    return can_manage_schedule(current_user)


def can_unpublish_schedule(current_user: User | None) -> bool:
    return can_publish_schedule(current_user)


def can_modify_schedule(current_user: User | None) -> bool:
    return can_manage_schedule(current_user)


def can_auto_schedule(current_user: User | None) -> bool:
    return can_manage_schedule(current_user)


def can_manage_scores(current_user: User | None) -> bool:
    if not current_user or not getattr(current_user, 'role', None):
        return False
    return normalize_role_name(current_user.role.name) in SCORE_MANAGEMENT_ROLES


def can_approve_publish_scores(current_user: User | None) -> bool:
    if not current_user or not getattr(current_user, 'role', None):
        return False
    return normalize_role_name(current_user.role.name) in SCORE_APPROVAL_ROLES


def can_submit_community_scores(current_user: User | None, game) -> bool:
    if not current_user or not getattr(current_user, 'role', None):
        return False
    if normalize_role_name(current_user.role.name) != ROLE_COMMUNITY_ADMIN or not current_user.organization_id:
        return False
    organization_id = current_user.organization_id
    home_team = getattr(game, 'home_team', None)
    away_team = getattr(game, 'away_team', None)
    return bool(
        (home_team and getattr(home_team, 'organization_id', None) == organization_id)
        or (away_team and getattr(away_team, 'organization_id', None) == organization_id)
    )


def require_schedule_admin(current_user: User = Depends(get_current_user)) -> User:
    if not can_manage_schedule(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Insufficient role')
    return current_user


def require_schedule_publisher(current_user: User = Depends(get_current_user)) -> User:
    if not can_publish_schedule(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Insufficient role')
    return current_user


def require_score_admin(current_user: User = Depends(get_current_user)) -> User:
    if not can_manage_scores(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Insufficient role')
    return current_user


def is_community_admin(current_user: User) -> bool:
    return normalize_role_name(current_user.role.name) == ROLE_COMMUNITY_ADMIN


def enforce_organization_scope(request_org_id: uuid.UUID | None, current_user: User) -> None:
    if normalize_role_name(current_user.role.name) in {ROLE_LEAGUE_ADMIN, ROLE_SCHEDULING_ADMIN}:
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
