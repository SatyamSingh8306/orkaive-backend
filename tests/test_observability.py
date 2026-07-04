"""Unit tests for `app.observability`.

`configure_observability` writes env vars that LangChain/LangFuse read
on first use. We assert the env vars are set (or not) based on the
settings.
"""
from __future__ import annotations

import importlib
import os
from unittest.mock import patch

import pytest

from app.config.settings import Settings, reset_settings_cache
from app import observability


def _settings(**overrides) -> Settings:
    """Build a Settings instance directly (bypasses env-file reading)."""
    base = dict(
        secret_key="x" * 32,
        langchain_tracing=False,
        langsmith_api_key=None,
        langfuse_enabled=False,
        langfuse_public_key=None,
        langfuse_secret_key=None,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def clean_env():
    """Wipe observability-related env vars before/after each test."""
    keys = [
        "LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY", "LANGCHAIN_PROJECT",
        "LANGCHAIN_ENDPOINT",
        "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST",
    ]
    saved = {k: os.environ.pop(k, None) for k in keys}
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


def test_disabled_when_no_keys(clean_env):
    s = _settings()
    observability.configure_observability(s)
    # No env vars were set
    assert "LANGCHAIN_TRACING_V2" not in os.environ
    assert "LANGFUSE_PUBLIC_KEY" not in os.environ


def test_langsmith_wires_env(clean_env):
    s = _settings(
        langchain_tracing=True,
        langsmith_api_key="lsv2_test_key",
        langsmith_project="my-proj",
    )
    observability.configure_observability(s)
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
    assert os.environ["LANGCHAIN_API_KEY"] == "lsv2_test_key"
    assert os.environ["LANGCHAIN_PROJECT"] == "my-proj"
    assert os.environ["LANGCHAIN_ENDPOINT"].startswith("https://")


def test_langfuse_wires_env(clean_env):
    s = _settings(
        langfuse_enabled=True,
        langfuse_public_key="pk_test",
        langfuse_secret_key="sk_test",
        langfuse_host="https://my-langfuse.example.com",
    )
    observability.configure_observability(s)
    assert os.environ["LANGFUSE_PUBLIC_KEY"] == "pk_test"
    assert os.environ["LANGFUSE_SECRET_KEY"] == "sk_test"
    assert os.environ["LANGFUSE_HOST"] == "https://my-langfuse.example.com"


def test_both_can_be_enabled(clean_env):
    s = _settings(
        langchain_tracing=True,
        langsmith_api_key="lsv2_x",
        langfuse_enabled=True,
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
    )
    observability.configure_observability(s)
    assert os.environ.get("LANGCHAIN_TRACING_V2") == "true"
    assert os.environ.get("LANGFUSE_PUBLIC_KEY") == "pk"


def test_get_langfuse_callbacks_disabled_returns_empty(clean_env):
    s = _settings()
    # Force the cache to use this settings
    reset_settings_cache()
    with patch("app.observability.get_settings", return_value=s):
        assert observability.get_langfuse_callbacks() == []


def test_get_langfuse_callbacks_enabled(monkeypatch, clean_env):
    """When LangFuse is enabled but the SDK is missing, we return []."""
    s = _settings(
        langfuse_enabled=True,
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
    )
    reset_settings_cache()

    # Force the import inside get_langfuse_callbacks to fail
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "langfuse.langchain" or name == "langfuse":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with patch("app.observability.get_settings", return_value=s):
        # SDK is not installed → returns [] instead of raising
        assert observability.get_langfuse_callbacks() == []
