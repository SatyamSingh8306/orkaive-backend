"""Password hashing + JWT helpers.

Uses the new `Settings` (no more import-time env reads).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config.settings import get_settings

# Password hashing
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return _pwd_context.hash(password)


def create_access_token(
    *, data: dict[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    settings = get_settings()
    payload = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload["exp"] = expire
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_password_reset_token(email: str) -> str:
    settings = get_settings()
    return jwt.encode(
        {
            "email": email,
            "type": "password_reset",
            "exp": datetime.now(timezone.utc) + timedelta(hours=settings.password_reset_expire_hours),
        },
        settings.secret_key,
        algorithm=ALGORITHM,
    )


def verify_password_reset_token(token: str) -> str:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError as e:
        raise ValueError("invalid or expired reset token") from e
    if payload.get("type") != "password_reset":
        raise ValueError("invalid or expired reset token")
    email = payload.get("email")
    if not email:
        raise ValueError("invalid or expired reset token")
    return email


def decode_token(token: str) -> dict[str, Any]:
    """Decode a JWT and return its claims. Raises `jose.JWTError` on failure."""
    settings = get_settings()
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
