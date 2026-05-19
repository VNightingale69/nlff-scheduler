import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User
from app.security import decode_token

security = HTTPBearer()

ROLE_LEAGUE_ADMIN = 'league_admin'
ROLE_COMMUNITY_SCHEDULER = 'community_scheduler'


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)) -> User:
    payload = decode_token(credentials.credentials, 'access')
    user_id = payload.get('sub')
    user = db.query(User).filter(User.id == uuid.UUID(user_id), User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='User not found or inactive')
    return user


def require_roles(*allowed_roles: str):
    def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role.name not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Insufficient role')
        return current_user

    return checker


def enforce_organization_scope(request_org_id: uuid.UUID | None, current_user: User) -> None:
    if current_user.role.name == ROLE_LEAGUE_ADMIN:
        return
    if current_user.role.name == ROLE_COMMUNITY_SCHEDULER:
        if not current_user.organization_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='User has no organization scope')
        if request_org_id and request_org_id != current_user.organization_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Organization scope violation')
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Unsupported role')


def role_by_name(db: Session, role_name: str) -> Role:
    role = db.query(Role).filter(Role.name == role_name, Role.is_active.is_(True)).first()
    if not role:
        raise HTTPException(status_code=400, detail=f'Role {role_name} does not exist')
    return role
