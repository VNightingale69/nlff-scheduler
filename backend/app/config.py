import os


def _is_production_environment() -> bool:
    environment = os.getenv('ENVIRONMENT') or os.getenv('APP_ENV') or os.getenv('RAILWAY_ENVIRONMENT') or ''
    return environment.strip().lower() in {'production', 'prod'}


def _jwt_secret_key() -> str:
    configured_secret = os.getenv('JWT_SECRET_KEY')
    if configured_secret:
        return configured_secret
    if _is_production_environment():
        raise RuntimeError('JWT_SECRET_KEY must be set to a stable value in production environments.')
    return 'development-jwt-secret-key-change-me'


JWT_SECRET_KEY = _jwt_secret_key()
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv('ACCESS_TOKEN_EXPIRE_MINUTES', '30'))
REFRESH_TOKEN_EXPIRE_MINUTES = int(os.getenv('REFRESH_TOKEN_EXPIRE_MINUTES', str(60 * 24 * 7)))
JWT_ALGORITHM = 'HS256'
ADMIN_SEED_EMAIL = os.getenv('ADMIN_SEED_EMAIL', 'admin@example.com')
ADMIN_SEED_PASSWORD = os.getenv('ADMIN_SEED_PASSWORD', 'ChangeMe123!')
ADMIN_SEED_FULL_NAME = os.getenv('ADMIN_SEED_FULL_NAME', 'League Admin')
CORS_ORIGINS = [origin.strip() for origin in os.getenv('CORS_ORIGINS', 'http://localhost:3000').split(',') if origin.strip()]

RULEBOOK_UPLOAD_DIR = os.getenv('RULEBOOK_UPLOAD_DIR', 'uploads/rulebooks')
RULEBOOK_MAX_SIZE_BYTES = int(os.getenv('RULEBOOK_MAX_SIZE_BYTES', str(25 * 1024 * 1024)))

ENABLE_TURF_OPTIMIZATION = os.getenv('ENABLE_TURF_OPTIMIZATION', 'false').strip().lower() in {'1', 'true', 'yes', 'on'}

ENABLE_SCHEDULE_QUALITY_REPORT = os.getenv('ENABLE_SCHEDULE_QUALITY_REPORT', 'false').strip().lower() in {'1', 'true', 'yes', 'on'}
