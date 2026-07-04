"""Unit tests for `app.services.prompt_registry` (the versioned prompt store).

We mock `get_database` to return a stub Motor-like object. The service
hits Mongo only in 3-4 places, so the stub is small.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import prompt_registry as pr


class _StubCursor:
    """A tiny async-iterable for the few .find() calls the registry makes."""

    def __init__(self, docs: list[dict]) -> None:
        self._docs = list(docs)

    def sort(self, *args, **kwargs):
        return self

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()


def _make_db(docs_by_collection: dict[str, list[dict]] | None = None) -> MagicMock:
    """Build a MagicMock that quacks like Motor's DB for our access pattern."""
    docs = docs_by_collection or {}
    db = MagicMock()
    for coll_name, coll_docs in docs.items():
        coll = MagicMock()
        coll_docs_iter = iter(coll_docs)
        coll.find_one = AsyncMock(side_effect=lambda *a, **kw: _next_or_none(coll_docs_iter))
        coll.find = MagicMock(side_effect=lambda *a, **kw: _StubCursor(coll_docs))
        coll.insert_one = AsyncMock()
        coll.update_one = AsyncMock()
        coll.update_many = AsyncMock()
        setattr(db, coll_name, coll)
    return db


def _next_or_none(it):
    try:
        return next(it)
    except StopIteration:
        return None


@pytest.fixture
def empty_db(monkeypatch):
    db = _make_db({"prompt_versions": [], "prompt_templates": []})
    monkeypatch.setattr(pr, "get_database", lambda: db)
    return db


@pytest.fixture
def fresh_registry(monkeypatch):
    """Wipe the module-level singleton so each test starts fresh."""
    pr.reset_prompt_registry_cache()
    return pr.PromptRegistry()


# ---- Reads -----------------------------------------------------------------

async def test_get_active_falls_back_when_registry_empty(empty_db, fresh_registry):
    body = await fresh_registry.get_active("query_router")
    assert "query router" in body.lower()
    assert "{format_instructions}" in body


async def test_get_active_caches(empty_db, fresh_registry):
    body1 = await fresh_registry.get_active("query_router")
    body2 = await fresh_registry.get_active("query_router")
    assert body1 == body2
    # The cache stores the resolved value
    assert fresh_registry._cache["query_router"] == body1


async def test_get_active_fetches_isactive_version(empty_db, fresh_registry):
    """If the registry has an isActive=true version, that's returned."""
    empty_db.prompt_versions.find_one = AsyncMock(
        return_value={"name": "query_router", "version": 3, "body": "v3 body",
                      "description": "", "createdAt": "2026-01-01", "isActive": True}
    )
    body = await fresh_registry.get_active("query_router")
    assert body == "v3 body"


async def test_get_active_falls_back_via_template_pointer(empty_db, fresh_registry):
    """If no isActive=true doc, look up the template's active_version."""
    empty_db.prompt_versions.find_one = AsyncMock(
        return_value={"name": "query_router", "version": 2, "body": "v2 body",
                      "description": "", "createdAt": "2026-01-01", "isActive": False}
    )
    body = await fresh_registry.get_active("query_router")
    assert body == "v2 body"


async def test_get_unknown_name_returns_empty(empty_db, fresh_registry):
    body = await fresh_registry.get_active("nonsense")
    assert body == ""


# ---- Writes ----------------------------------------------------------------

async def test_create_version_appends_and_auto_activates_first(empty_db, fresh_registry):
    # First find_one: "highest version of x" → None. Second find_one:
    # "does x@1 exist" → the doc we just inserted.
    async def find_one(filt, **kw):
        if "version" in filt and filt.get("name") == "x":
            return {
                "name": "x", "version": 1, "body": "body1",
                "description": "first", "createdAt": "2026-01-01",
                "isActive": False,
            }
        return None

    coll = empty_db.prompt_versions
    coll.find_one = AsyncMock(side_effect=find_one)
    new_v = await fresh_registry.create_version("x", "body1", "first")
    assert new_v == 1
    assert coll.insert_one.await_count == 1
    # Auto-activate on first version: clear-all + set-one
    assert coll.update_many.await_count == 1
    assert coll.update_one.await_count == 1
    # Template pointer upserted
    assert empty_db.prompt_templates.update_one.await_count == 1


async def test_create_version_increments(empty_db, fresh_registry):
    empty_db.prompt_versions.find_one = AsyncMock(return_value={"version": 7})
    new_v = await fresh_registry.create_version("x", "body8")
    assert new_v == 8


async def test_activate_marks_inactive_then_activates(empty_db, fresh_registry):
    empty_db.prompt_versions.find_one = AsyncMock(
        return_value={"name": "x", "version": 3, "body": "v3",
                      "description": "", "createdAt": "2026-01-01", "isActive": False}
    )
    await fresh_registry.activate("x", 3)
    # First: clear isActive on all of "x", then set isActive on the target
    assert empty_db.prompt_versions.update_many.await_count == 1
    assert empty_db.prompt_versions.update_one.await_count == 1
    # And the template pointer was upserted
    assert empty_db.prompt_templates.update_one.await_count == 1


async def test_activate_unknown_version_raises(empty_db, fresh_registry):
    empty_db.prompt_versions.find_one = AsyncMock(return_value=None)
    with pytest.raises(ValueError, match="not found"):
        await fresh_registry.activate("x", 99)
