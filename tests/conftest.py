"""Pytest fixtures shared across the suite.

These tests are designed to run without MongoDB / Redis / LLM access.
The whole point is to lock down behaviour with fast unit tests.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Make `app` importable when pytest is run from the backend root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Set the env BEFORE any app module imports Settings() so the
# lru_cache is populated with a known value. SECRET_KEY is required
# (no default). GROQ_API_KEY is required when LLM_PROVIDER_ROUTER=groq
# (the default) — we set a dummy so tests that don't care about LLMs
# still see a valid Settings instance.
os.environ.setdefault("SECRET_KEY", "x" * 32)
os.environ.setdefault("GROQ_API_KEY", "ci-dummy-groq-key")

_ORKAIVE_ENV_KEYS = {
    "GROQ_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY",
    "TAVILY_API_KEY", "MONGODB_URL", "REDIS_HOST",
    "SMTP_PASSWORD", "SMTP_USERNAME",
}


@pytest.fixture(autouse=True)
def _clean_settings_cache():
    """Clear pydantic-settings' lru_cache and re-assert SECRET_KEY.

    `app.config.settings.get_settings` is `lru_cache`d. If a test (or a
    previous run) instantiated Settings() with a different key, every
    later test would see the cached value.
    """
    from app.config.settings import reset_settings_cache, get_settings
    from app.utils.email import reset_email_service_cache
    reset_settings_cache()
    reset_email_service_cache()
    os.environ["SECRET_KEY"] = "x" * 32
    os.environ.setdefault("GROQ_API_KEY", "ci-dummy-groq-key")
    # Force re-construction now so `_create_token` etc. see the new key.
    get_settings()
    yield
    reset_settings_cache()
    reset_email_service_cache()


@pytest.fixture
def mock_db() -> MagicMock:
    """A bare MagicMock that quacks like Motor's AsyncIOMotorDatabase."""
    db = MagicMock()
    db.tools = MagicMock()
    db.workflows = MagicMock()
    db.conflicts = MagicMock()
    db.conversations = MagicMock()
    db.messages = MagicMock()
    db.users = MagicMock()
    return db
