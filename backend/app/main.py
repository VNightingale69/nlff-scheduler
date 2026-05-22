import logging

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth import ROLE_COMMUNITY_SCHEDULER, ROLE_LEAGUE_ADMIN
from app.config import ADMIN_SEED_EMAIL, ADMIN_SEED_FULL_NAME, ADMIN_SEED_PASSWORD, CORS_ORIGINS
from app.database import get_db
from app.models import Role, User
from app.routes.api import ensure_league_defined_divisions, router as api_router
from app.security import hash_password, validate_password_strength
from app.services.game_statuses import seed_required_game_statuses

app = FastAPI(title='Northern Lakes Flag Football Scheduler API')
logger = logging.getLogger(__name__)


REQUIRED_TABLES = {
    'organization_division_participations': 'organization_division_participations',
    'hosting_site_setups': 'physical_field_areas',
    'hosting_availability': 'hosting_availabilities',
    'teams': 'teams',
    'host_locations': 'host_locations',
}



@app.exception_handler(SQLAlchemyError)
def handle_sqlalchemy_error(_: Request, exc: SQLAlchemyError):
    logger.exception('Database request failed.', exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            'error': 'database_error',
            'message': 'A database error occurred while processing the request.',
        },
    )


@app.exception_handler(Exception)
def handle_unexpected_error(_: Request, exc: Exception):
    logger.exception('Unhandled server error.', exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            'error': 'internal_server_error',
            'message': 'An unexpected server error occurred.',
        },
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
    allow_headers=['*'],
)


def _auth_tables_ready(db: Session) -> bool:
    inspector = inspect(db.bind)
    return inspector.has_table('roles') and inspector.has_table('users')




@app.on_event('startup')
def validate_required_tables() -> None:
    db = next(get_db())
    try:
        inspector = inspect(db.bind)
        missing_tables = [
            expected_name
            for expected_name, actual_table in REQUIRED_TABLES.items()
            if not inspector.has_table(actual_table)
        ]
        if missing_tables:
            logger.warning(
                'Startup table validation warning. Missing required tables: %s. Run: alembic upgrade head',
                ', '.join(missing_tables),
            )
        else:
            logger.info('Database schema validation passed. Required tables are present.')
    except SQLAlchemyError:
        logger.exception('Database schema validation failed due to database error.')
    finally:
        db.close()

@app.on_event('startup')
def seed_auth_data() -> None:
    db = next(get_db())
    try:
        if not _auth_tables_ready(db):
            logger.info('Auth seed skipped: roles/users tables are not ready yet.')
            return

        created_roles: list[str] = []
        for role_name, description in [
            (ROLE_LEAGUE_ADMIN, 'Global administrative access across all organizations'),
            (ROLE_COMMUNITY_SCHEDULER, 'Organization-scoped scheduling access'),
        ]:
            role = db.query(Role).filter(Role.name == role_name).first()
            if not role:
                db.add(Role(name=role_name, description=description, is_active=True))
                created_roles.append(role_name)
        db.commit()

        admin_role = db.query(Role).filter(Role.name == ROLE_LEAGUE_ADMIN).first()
        if not admin_role:
            logger.warning('Auth seed failed: %s role missing after seed attempt.', ROLE_LEAGUE_ADMIN)
            return

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
            if created_roles:
                logger.info(
                    'Auth seed complete: created roles=%s and admin user=%s.',
                    ','.join(created_roles),
                    ADMIN_SEED_EMAIL,
                )
            else:
                logger.info('Auth seed complete: admin user=%s created; roles already existed.', ADMIN_SEED_EMAIL)
            return

        if created_roles:
            logger.info(
                'Auth seed complete: created missing roles=%s; admin user=%s already exists.',
                ','.join(created_roles),
                ADMIN_SEED_EMAIL,
            )
        else:
            logger.info(
                'Auth seed noop: roles/admin already exist (admin=%s).',
                ADMIN_SEED_EMAIL,
            )
    except SQLAlchemyError:
        db.rollback()
        logger.exception('Auth seed failed due to database error.')
    finally:
        db.close()


@app.get('/health')
def health_check(db: Session = Depends(get_db)):
    db.execute(text('SELECT 1'))
    return {'status': 'ok'}


app.include_router(api_router)

@app.on_event('startup')
def seed_league_divisions() -> None:
    db = next(get_db())
    try:
        ensure_league_defined_divisions(db)
    except SQLAlchemyError:
        logger.exception('League division seed failed due to database error.')
        db.rollback()
    finally:
        db.close()


@app.on_event('startup')
def seed_game_statuses() -> None:
    db = next(get_db())
    try:
        seed_required_game_statuses(db)
    finally:
        db.close()
