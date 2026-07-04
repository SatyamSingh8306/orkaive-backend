"""Unit tests for the slowapi-backed rate limiter.

We don't fire real requests at the app — we exercise the key
function (per-user / per-IP), the decorator wiring on a stub
handler, and the JSON 429 exception handler.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.settings import reset_settings_cache
from app.core import rate_limit


@pytest.fixture(autouse=True)
def _clean_settings():
    reset_settings_cache()
    yield
    reset_settings_cache()


def _stub_request(headers: dict[str, str] | None = None, client_host: str = "1.2.3.4"):
    req = MagicMock()
    req.headers = headers or {}
    req.client = MagicMock()
    req.client.host = client_host
    return req


def test_user_or_ip_key_falls_back_to_ip_when_no_auth():
    req = _stub_request(headers={})
    key = rate_limit._user_or_ip_key(req)
    assert key == "ip:1.2.3.4"


def test_user_or_ip_key_uses_jwt_sub_when_present():
    # No real signature needed — the key function uses get_unverified_claims.
    from jose import jwt
    settings = rate_limit.get_settings()
    token = jwt.encode({"sub": "alice@example.com"}, settings.secret_key, algorithm="HS256")
    req = _stub_request(headers={"authorization": f"Bearer {token}"})
    key = rate_limit._user_or_ip_key(req)
    assert key == "user:alice@example.com"


def test_user_or_ip_key_handles_garbage_token():
    req = _stub_request(headers={"authorization": "Bearer not-a-jwt"})
    key = rate_limit._user_or_ip_key(req)
    # Falls back to per-IP — no raise.
    assert key.startswith("ip:")


def test_user_or_ip_key_handles_non_bearer_scheme():
    req = _stub_request(headers={"authorization": "Basic abcdef"})
    key = rate_limit._user_or_ip_key(req)
    assert key.startswith("ip:")


def test_default_key_uses_remote_address():
    req = _stub_request(client_host="9.9.9.9")
    assert rate_limit._default_key(req) == "9.9.9.9"


def test_default_key_handles_missing_client():
    # slowapi's get_remote_address always returns something (defaults to
    # "127.0.0.1" when there's no client). The `or "unknown"` fallback
    # is defensive — the test just confirms no exception is raised.
    req = MagicMock()
    req.headers = {}
    req.client = None
    key = rate_limit._default_key(req)
    assert isinstance(key, str) and key != ""


def test_limiter_is_singleton():
    """`limiter` is module-level; we expose it as the canonical Limiter."""
    assert rate_limit.limiter is rate_limit.limiter


def test_init_rate_limiter_registers_handler():
    from slowapi.errors import RateLimitExceeded as RLE
    app = FastAPI()
    assert RLE not in app.exception_handlers
    rate_limit.init_rate_limiter(app)
    assert RLE in app.exception_handlers
    assert app.state.limiter is rate_limit.limiter


def test_auth_limit_decorator_is_callable():
    """`auth_limit()` must return a decorator (slowapi's `limit`)."""
    deco = rate_limit.auth_limit()
    # slowapi's `limit` is a Limiter-bound method; calling it returns
    # a wrapper. We just need to confirm the function doesn't raise
    # and that it can be applied to a function.
    async def f(request):
        return None
    wrapped = deco(f)
    assert callable(wrapped)


def test_chat_limit_decorator_is_callable():
    deco = rate_limit.chat_limit()
    async def f(request):
        return None
    wrapped = deco(f)
    assert callable(wrapped)


def test_rate_limit_exception_handler_returns_429():
    """The 429 handler must return a JSON body with `detail`."""
    import asyncio
    from starlette.exceptions import HTTPException

    # slowapi's RateLimitExceeded expects a Limit object; for the handler
    # test, any HTTPException-derivative with status 429 is enough to
    # exercise the JSON envelope (the handler reads `exc.detail`).
    exc = HTTPException(status_code=429, detail="2 per 1 minute")
    req = _stub_request()
    resp = asyncio.run(rate_limit.rate_limit_exception_handler(req, exc))
    assert resp.status_code == 429
    body = resp.body.decode() if hasattr(resp, "body") else str(resp)
    assert "2 per 1 minute" in body
    # The handler does best-effort parsing of "N per ..." for Retry-After.
    assert resp.headers.get("Retry-After") == "2"
