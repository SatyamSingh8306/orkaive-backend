"""Unit tests for the JWT auth helpers in `app.routes.auth`.

We don't talk to Mongo here — we just verify token shape, expiry, and
that an invalid token raises the right HTTP error.
"""
from __future__ import annotations

import datetime as dt

import pytest
from fastapi import HTTPException
from jose import jwt

from app.routes.auth import (
    ALGORITHM,
    _create_token,
    verify_token,
    create_access_token,
    create_password_reset_token,
    verify_password_reset_token,
)


def _decode(token: str, key: str = "x" * 32) -> dict:
    return jwt.decode(token, key, algorithms=[ALGORITHM])


def test_create_token_round_trip():
    token = _create_token(data={"sub": "u@example.com"})
    payload = _decode(token)
    assert payload["sub"] == "u@example.com"
    assert "exp" in payload


def test_token_expiry_respected():
    """An expired token must raise 401."""
    expired = jwt.encode(
        {
            "sub": "u@example.com",
            "exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1),
        },
        "x" * 32,
        algorithm=ALGORITHM,
    )
    with pytest.raises(HTTPException) as exc:
        verify_token(expired)
    assert exc.value.status_code == 401


def test_verify_token_returns_sub():
    token = create_access_token({"sub": "alice@example.com"})
    assert verify_token(token) == "alice@example.com"


def test_verify_token_missing_sub_raises():
    token = jwt.encode(
        {"sub": None, "exp": 9999999999}, "x" * 32, algorithm=ALGORITHM
    )
    with pytest.raises(HTTPException) as exc:
        verify_token(token)
    assert exc.value.status_code == 401


def test_verify_token_bad_signature_raises():
    token = jwt.encode({"sub": "x"}, "WRONG" * 8, algorithm=ALGORITHM)
    with pytest.raises(HTTPException):
        verify_token(token)


def test_password_reset_token_round_trip():
    token = create_password_reset_token("u@example.com")  # type: ignore[arg-type]
    assert verify_password_reset_token(token) == "u@example.com"


def test_password_reset_rejects_wrong_type():
    token = jwt.encode(
        {
            "email": "u@example.com",
            "type": "not_a_reset",
            "exp": 9999999999,
        },
        "x" * 32,
        algorithm=ALGORITHM,
    )
    with pytest.raises(HTTPException) as exc:
        verify_password_reset_token(token)
    assert exc.value.status_code == 400
