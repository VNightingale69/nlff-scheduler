import re
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import HTTPException, status

from app.config import ACCESS_TOKEN_EXPIRE_MINUTES, JWT_ALGORITHM, JWT_SECRET_KEY, REFRESH_TOKEN_EXPIRE_MINUTES

PASSWORD_RULE = re.compile(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^\w\s]).{8,128}$')
AUTH_EXPIRED_MESSAGE = 'Your session expired. Please log in again.'


def auth_invalid_token_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={'error': 'auth_invalid_token', 'message': AUTH_EXPIRED_MESSAGE},
    )


def validate_password_strength(password: str) -> None:
    if not PASSWORD_RULE.match(password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail='Password must be 8-128 chars and include uppercase, lowercase, number, and special character.',
        )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))


def create_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {'sub': subject, 'type': token_type, 'iat': int(now.timestamp()), 'exp': int((now + expires_delta).timestamp())}
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def access_token_expires_at() -> datetime:
    return datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)


def create_access_token(subject: str) -> str:
    return create_token(subject, 'access', timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(subject: str) -> str:
    return create_token(subject, 'refresh', timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES))


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise auth_invalid_token_exception() from exc
    if payload.get('type') != expected_type:
        raise auth_invalid_token_exception()
    return payload
