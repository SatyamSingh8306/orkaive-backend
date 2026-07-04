"""Auth routes — JWT-based, settings-driven."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import EmailStr

from app.config.settings import get_settings
from app.core.logging import get_logger
from app.core.rate_limit import auth_limit
from app.schemas.user import (
    ForgotPasswordForm,
    LoginFormData,
    ResetPasswordForm,
    SignUpFormData,
    Token,
    UserResponse,
)
from app.services.user_service import user_service
from app.utils.email import email_service

logger = get_logger(__name__)
auth_router = APIRouter(tags=["auth"])
security = HTTPBearer(auto_error=False)

ALGORITHM = "HS256"


def _create_token(*, data: dict, expires_delta: Optional[timedelta] = None) -> str:
    settings = get_settings()
    payload = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload["exp"] = expire
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def _decode_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    return _create_token(data={"sub": data.get("sub", "")},
                         expires_delta=expires_delta)


def verify_token(token: str) -> str:
    try:
        payload = _decode_token(token)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    email = payload.get("sub")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    return email


def create_password_reset_token(email: EmailStr) -> str:
    return _create_token(
        data={"email": email, "type": "password_reset"},
        expires_delta=timedelta(hours=1),
    )


def verify_password_reset_token(token: str) -> str:
    try:
        payload = _decode_token(token)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        ) from e
    if payload.get("type") != "password_reset":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    email = payload.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    return email


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> UserResponse:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    email = verify_token(credentials.credentials)
    user = await user_service.get_user_by_email(email)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found",
        )
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        created_at=user.created_at,
        is_active=user.is_active,
    )


# ---- Endpoints -------------------------------------------------------------

@auth_router.post("/signup", response_model=UserResponse, status_code=201)
@auth_limit()
async def signup(user_data: SignUpFormData, request: Request, response: Response) -> UserResponse:
    try:
        user = await user_service.create_user(user_data)  # type: ignore[arg-type]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {e!s}",
        ) from e
    try:
        await email_service.send_welcome_email(user.email, user.name)
    except Exception as e:
        logger.warning("welcome email failed: %s", e)
    return user


@auth_router.post("/login", response_model=Token)
@auth_limit()
async def login(payload: LoginFormData, request: Request, response: Response) -> Token:
    user = await user_service.authenticate_user(payload.email, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    settings = get_settings()
    token = _create_token(
        data={"sub": user.email},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    return Token(access_token=token)


@auth_router.post("/forgot-password")
@auth_limit()
async def forgot_password(payload: ForgotPasswordForm, request: Request, response: Response) -> dict:
    user = await user_service.get_user_by_email(payload.email)
    if not user:
        return {"message": "If the email exists, a reset link has been sent"}
    token = create_password_reset_token(user.email)
    try:
        sent = await email_service.send_password_reset_email(user.email, token)
    except Exception as e:
        logger.warning("reset email failed: %s", e)
        sent = False
    if not sent:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send reset email",
        )
    return {"message": "Password reset link sent to your email"}


@auth_router.post("/reset-password")
@auth_limit()
async def reset_password(payload: ResetPasswordForm, request: Request, response: Response) -> dict:
    email = verify_password_reset_token(payload.token)
    ok = await user_service.update_password(email, payload.new_password)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to reset password",
        )
    return {"message": "Password reset successfully"}


@auth_router.get("/me", response_model=UserResponse)
async def me(current: UserResponse = Depends(get_current_user)) -> UserResponse:
    return current


@auth_router.get("/")
async def index() -> dict:
    return {"service": "Authentication Routes"}
