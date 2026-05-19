from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import ROLE_COMMUNITY_SCHEDULER, ROLE_LEAGUE_ADMIN
from app.config import ADMIN_SEED_EMAIL, ADMIN_SEED_FULL_NAME, ADMIN_SEED_PASSWORD
from app.database import get_db
from app.models import Role, User
from app.routes.api import router as api_router
from app.security import hash_password, validate_password_strength

app = FastAPI(title='Northern Lakes Flag Football Scheduler API')


@app.on_event('startup')
def seed_auth_data():
    db = next(get_db())
    for role_name, description in [
        (ROLE_LEAGUE_ADMIN, 'Global administrative access across all organizations'),
        (ROLE_COMMUNITY_SCHEDULER, 'Organization-scoped scheduling access'),
    ]:
        role = db.query(Role).filter(Role.name == role_name).first()
        if not role:
            db.add(Role(name=role_name, description=description, is_active=True))
    db.commit()

    admin_role = db.query(Role).filter(Role.name == ROLE_LEAGUE_ADMIN).first()
    existing_admin = db.query(User).filter(User.email == ADMIN_SEED_EMAIL).first()
    if not existing_admin:
        validate_password_strength(ADMIN_SEED_PASSWORD)
        db.add(
            User(
                email=ADMIN_SEED_EMAIL,
                full_name=ADMIN_SEED_FULL_NAME,
                password_hash=hash_password(ADMIN_SEED_PASSWORD),
                role_id=admin_role.id,
                organization_id=None,
                is_active=True,
            )
        )
        db.commit()
    db.close()


@app.get('/health')
def health_check(db: Session = Depends(get_db)):
    db.execute(text('SELECT 1'))
    return {'status': 'ok'}


app.include_router(api_router)
