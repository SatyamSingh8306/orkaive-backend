"""Rate limiting for the FastAPI app.

Single Limiter instance, mounted once on the app via `init_rate_limiter`.
Limits are configured in `Settings` and applied per-route with
`@limiter.limit(...)` or with the helpers `auth_limit` / `chat_limit`.

Storage is in-process. For a multi-worker deploy a Redis-backed
storage URI would be required; single-process keeps the demo surface
dependency-light. The `Limiter` raises `RateLimitExceeded` on hit —
we convert that to a 429 JSON in the app exception handler.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from fastapi import Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config.settings import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _default_key(request: Request) -> str:
    """Per-IP key for unauthenticated endpoints (signup/login/etc).

    Falls back to "unknown" if the client has no remote address.
    """
    return get_remote_address(request) or "unknown"


def _user_or_ip_key(request: Request) -> str:
    """Per-user key for authenticated endpoints, with per-IP fallback.

    Tries to read the JWT `sub` claim without verifying the signature —
    rate limiting is a coarse first line of defence, not an authz
    check. A forged claim can only rate-limit the attacker's own key.
    """
    try:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            from jose import jwt
            s = get_settings()
            token = auth.split(" ", 1)[1]
            payload = jwt.get_unverified_claims(token)
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
    except Exception:
        pass
    return f"ip:{_default_key(request)}"


# Single Limiter. The default key_func is the conservative per-IP one
# (used when a decorator doesn't override it).
limiter = Limiter(
    key_func=_default_key,
    headers_enabled=True,  # writes X-RateLimit-* headers
    strategy="fixed-window",
)


# Lazy-decorated functions so the limiter reads the current Settings
# at request time (lets tests override the env). Calling `limiter.limit`
# returns a decorator that wraps the route handler.
def auth_limit() -> Callable:
    """Rate limit for unauthenticated /api/auth/* endpoints (per-IP)."""
    return limiter.limit(get_settings().rate_limit_auth, key_func=_default_key)


def chat_limit() -> Callable:
    """Rate limit for authenticated /api/chats/* endpoints (per-user)."""
    return limiter.limit(get_settings().rate_limit_chat, key_func=_user_or_ip_key)


async def rate_limit_exception_handler(
    request: Request, exc: RateLimitExceeded
) -> "Awaitable[dict]":  # type: ignore[name-defined]
    """Convert slowapi's 429 to a JSON body matching the rest of the API."""
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"},
        headers={"Retry-After": str(exc.detail.split(" per ")[0] if " per " in exc.detail else 60)},
    )


def init_rate_limiter(app) -> None:
    """Wire the limiter + 429 handler into a FastAPI app.

    Call once from `app.main:create_app` (or import-time of the app
    object) BEFORE any router is included — slowapi's exception
    handler registration is order-sensitive.
    """
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)
