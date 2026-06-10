import logging
from datetime import date, timedelta

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth import ROLE_COMMUNITY_ADMIN, ROLE_LEAGUE_ADMIN, ROLE_SCHEDULING_ADMIN
from app.branding import APP_API_TITLE
from app.config import ADMIN_SEED_EMAIL, ADMIN_SEED_FULL_NAME, ADMIN_SEED_PASSWORD, CORS_ORIGINS
from app.database import get_db
from app.models import Organization, Role, Season, User, Week
from app.routes.api import ensure_league_defined_divisions, router as api_router
from app.security import hash_password, validate_password_strength
from app.services.game_statuses import seed_required_game_statuses

app = FastAPI(title=APP_API_TITLE)
logger = logging.getLogger(__name__)


REQUIRED_TABLES = {
    'organization_division_participations': 'organization_division_participations',
    'hosting_site_setups': 'physical_field_areas',
    'hosting_availability': 'hosting_availabilities',
    'teams': 'teams',
    'host_locations': 'host_locations',
    'rulebooks': 'rulebooks',
}



@app.exception_handler(HTTPException)
def handle_http_exception(_: Request, exc: HTTPException):
    if isinstance(exc.detail, dict) and exc.detail.get('error') == 'auth_invalid_token':
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={'detail': exc.detail})


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
        for legacy_name, canonical_name in [('league_admin', ROLE_LEAGUE_ADMIN), ('community_scheduler', ROLE_COMMUNITY_ADMIN)]:
            legacy_role = db.query(Role).filter(Role.name == legacy_name).first()
            canonical_role = db.query(Role).filter(Role.name == canonical_name).first()
            if legacy_role and not canonical_role:
                legacy_role.name = canonical_name
                legacy_role.description = 'Global administrative access across all organizations' if canonical_name == ROLE_LEAGUE_ADMIN else 'Community-scoped administrative access'
                legacy_role.is_active = True
            elif legacy_role and canonical_role:
                db.query(User).filter(User.role_id == legacy_role.id).update({User.role_id: canonical_role.id}, synchronize_session=False)
                legacy_role.is_active = False
        for role_name, description in [
            (ROLE_LEAGUE_ADMIN, 'Global administrative access across all organizations'),
            (ROLE_COMMUNITY_ADMIN, 'Community-scoped administrative access'),
            (ROLE_SCHEDULING_ADMIN, 'Scheduling administrative access for global schedule editing'),
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


        community_role = db.query(Role).filter(Role.name == ROLE_COMMUNITY_ADMIN).first()
        if community_role:
            seeded_accounts = [
                ('Lake County Stallions', 'Amy Schneider', 'aeschneider622@gmail.com', 'LakeCounty1'),
                ('Lake County Stallions', 'Katie Gandolf', 'lcstallionsflagfootball@gmail.com', 'LakeCounty2'),
                ('Lake County Stallions', 'Mike Schneider', 'michaelwb01@yahoo.com', 'LakeCounty3'),
                ('Cary', 'Brent Harmeier', 'harms827@gmail.com', 'Cary1'),
                ('Johnsburg', 'Eric Lostroscio', 'elostroscio@gmail.com', 'Johnsburg1'),
                ('Johnsburg', 'Tiffany Kendzior', 'kendzior.t@gmail.com', 'Johnsburg2'),
                ('Woodstock', 'Juan Cabajal', 'ju2carb@gmail.com', 'Woodstock1'),
                ('Westosha', 'Lisa Nightingale', 'LAR_Nightingale@hotmail.com', 'Westosha1'),
                ('Antioch', 'Nick Stafford', 'nicholasjstafford@gmail.com', 'Antioch1'),
                ('Prairie Ridge', 'Stephanie Dycha', 'sdycha144@gmail.com', 'PrairieRidge1'),
            ]
            for organization_name, full_name, email, password in seeded_accounts:
                organization = db.query(Organization).filter(Organization.name == organization_name).first()
                if not organization:
                    organization = Organization(name=organization_name, is_active=True)
                    db.add(organization)
                    db.flush()
                normalized_email = email.strip().lower()
                user = db.query(User).filter(User.email.ilike(normalized_email)).first()
                if not user:
                    db.add(
                        User(
                            email=normalized_email,
                            full_name=full_name,
                            password_hash=hash_password(password),
                            role_id=community_role.id,
                            organization_id=organization.id,
                            is_active=True,
                        )
                    )
                else:
                    user.full_name = full_name
                    user.role_id = community_role.id
                    user.organization_id = organization.id
                    user.is_active = True
            db.commit()

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


@app.on_event('startup')
def seed_default_season_and_weeks() -> None:
    db = next(get_db())
    try:
        existing = db.query(Season).count()
        if existing:
            return
        season = Season(
            name='2026 Fall Flag',
            start_date=date(2026, 9, 6),
            end_date=date(2026, 10, 25),
            is_active=True,
        )
        db.add(season)
        db.flush()
        starts = [date(2026, 9, 6), date(2026, 9, 13), date(2026, 9, 20), date(2026, 9, 27), date(2026, 10, 4), date(2026, 10, 11), date(2026, 10, 18), date(2026, 10, 25)]
        for idx, start in enumerate(starts, start=1):
            db.add(Week(season_id=season.id, week_number=idx, start_date=start, end_date=start + timedelta(days=6)))
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception('Season/week seed failed due to database error.')
    finally:
        db.close()
