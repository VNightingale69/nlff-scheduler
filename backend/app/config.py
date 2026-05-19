import os

JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'change-me-in-production')
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv('ACCESS_TOKEN_EXPIRE_MINUTES', '30'))
REFRESH_TOKEN_EXPIRE_MINUTES = int(os.getenv('REFRESH_TOKEN_EXPIRE_MINUTES', str(60 * 24 * 7)))
JWT_ALGORITHM = 'HS256'
ADMIN_SEED_EMAIL = os.getenv('ADMIN_SEED_EMAIL', 'admin@nlff.local')
ADMIN_SEED_PASSWORD = os.getenv('ADMIN_SEED_PASSWORD', 'ChangeMe123!')
ADMIN_SEED_FULL_NAME = os.getenv('ADMIN_SEED_FULL_NAME', 'System Admin')
