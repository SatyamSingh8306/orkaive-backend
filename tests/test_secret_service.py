"""Unit tests for `app.services.secret_service`."""
from __future__ import annotations

import importlib
import os

import pytest

from app.services import secret_service as ss


def _wipe_env():
    for k in list(os.environ):
        if k.startswith("ORKAIVE_SECRET_"):
            os.environ.pop(k)


@pytest.fixture
def svc():
    """Fresh SecretService with no env vars set."""
    _wipe_env()
    ss._secret_service = None  # type: ignore[attr-defined]
    importlib.reload(ss)
    return ss.SecretService()


def test_loads_single_header_from_env():
    _wipe_env()
    ss._secret_service = None  # type: ignore[attr-defined]
    os.environ["ORKAIVE_SECRET_OPENAI"] = "Authorization: Bearer sk-xxx"
    importlib.reload(ss)
    svc = ss.SecretService()
    try:
        assert svc.resolve_headers("openai") == {"Authorization": "Bearer sk-xxx"}
    finally:
        os.environ.pop("ORKAIVE_SECRET_OPENAI", None)


def test_ignores_env_vars_without_colon():
    _wipe_env()
    ss._secret_service = None  # type: ignore[attr-defined]
    os.environ["ORKAIVE_SECRET_BROKEN"] = "no-colon-here"
    importlib.reload(ss)
    svc = ss.SecretService()
    try:
        with pytest.raises(KeyError):
            svc.resolve_headers("broken")
    finally:
        os.environ.pop("ORKAIVE_SECRET_BROKEN", None)


def test_ignores_unrelated_env():
    _wipe_env()
    ss._secret_service = None  # type: ignore[attr-defined]
    os.environ["SOMETHING_ELSE"] = "Authorization: Bearer x"
    importlib.reload(ss)
    svc = ss.SecretService()
    try:
        with pytest.raises(KeyError):
            svc.resolve_headers("something_else")
    finally:
        os.environ.pop("SOMETHING_ELSE", None)


def test_case_insensitive_ref():
    _wipe_env()
    ss._secret_service = None  # type: ignore[attr-defined]
    os.environ["ORKAIVE_SECRET_MY_KEY"] = "X-Token: abc"
    importlib.reload(ss)
    svc = ss.SecretService()
    try:
        # ref name is lowercased on load
        assert svc.resolve_headers("my_key") == {"X-Token": "abc"}
    finally:
        os.environ.pop("ORKAIVE_SECRET_MY_KEY", None)


def test_register_secret(svc):
    svc.register_secret("custom", {"X-Custom": "value"})
    assert svc.resolve_headers("custom") == {"X-Custom": "value"}


def test_resolve_unknown_raises(svc):
    with pytest.raises(KeyError, match="not found"):
        svc.resolve_headers("does_not_exist")


def test_resolve_returns_copy(svc):
    svc.register_secret("k", {"X": "v"})
    h1 = svc.resolve_headers("k")
    h1["X"] = "mutated"
    # internal store is unchanged
    assert svc.resolve_headers("k") == {"X": "v"}


def test_multiple_headers_via_register(svc):
    svc.register_secret("multi", {"Authorization": "Bearer x", "X-Tenant": "t1"})
    assert svc.resolve_headers("multi") == {
        "Authorization": "Bearer x",
        "X-Tenant": "t1",
    }


def test_singleton_returns_same_instance():
    a = ss.get_secret_service()
    b = ss.get_secret_service()
    assert a is b
