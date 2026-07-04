"""Prompt registry service.

Owns two Mongo collections:

  * `prompt_versions`  — immutable (name, version, body) records.
  * `prompt_templates` — (name, active_version) pointers.

Public API:

  * `get_active(name) -> str`        — body of the active version, or None.
  * `get_version(name, version) -> str` — body of a specific version.
  * `create_version(name, body, ...) -> int` — append a new version, returns its number.
  * `activate(name, version)`        — flip the active pointer.
  * `list_versions(name) -> list[int]`
  * `list_templates() -> list[str]`

The service is read-through with an in-process LRU cache. Writes
invalidate the cache. The cache is a per-process map; restarts are
fine — Mongo is the source of truth.

If the registry is empty (fresh install), `get_active("query_router")`
falls back to a hard-coded prompt so the router still works before
someone explicitly seeds the registry. The fallback is the literal
string that was in `router.py:_SYSTEM_PREAMBLE` before versioning
landed.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

from pydantic import ValidationError

from app.core.logging import get_logger
from app.db.mongodb import get_database
from app.schemas.prompt import PromptTemplate, PromptVersion

logger = get_logger(__name__)


# ---- Hard-coded fallback (used when Mongo is empty) ------------------------

_FALLBACK_QUERY_ROUTER = """
You are a query router for an enterprise multi-agent system.

You MUST respond with ONLY a single JSON object that matches this schema:

{format_instructions}

ABSOLUTE RULES:
- Reply with ONLY the raw JSON object.
- Do NOT wrap output in markdown.
- Do NOT return XML, YAML, or text.
- Do NOT explain your answer.
- `agent_type` MUST be one of the listed agent ids.
- `confidence` MUST be between 0.0 and 1.0.
- Prefer the best matching agent.
- If multiple agents are required, set:
  `requires_multiple_agents=true`
  and populate `secondary_agents`.
"""


class PromptRegistry:
    """Read-through cache over the Mongo prompt collections."""

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}
        self._lock = threading.Lock()

    # ---- Reads ----------------------------------------------------------

    async def get_active(self, name: str) -> str:
        """Return the body of the active version of `name`.

        On any error, returns the hard-coded fallback so the caller
        never breaks because of a missing prompt.
        """
        if name in self._cache:
            return self._cache[name]
        try:
            body = await self._fetch_active(name)
        except Exception as e:  # never let prompt lookups break the request path
            logger.warning("prompt registry lookup failed for %r: %s", name, e)
            body = self._fallback(name)
        with self._lock:
            self._cache[name] = body
        return body

    async def get_version(self, name: str, version: int) -> Optional[str]:
        try:
            db = get_database()
            doc = await db.prompt_versions.find_one(
                {"name": name, "version": version}
            )
            if not doc:
                return None
            return PromptVersion.model_validate(doc).body
        except Exception as e:
            logger.warning("get_version(%r, %d) failed: %s", name, version, e)
            return None

    async def list_versions(self, name: str) -> list[int]:
        try:
            db = get_database()
            cursor = db.prompt_versions.find(
                {"name": name}, projection={"version": 1, "_id": 0}
            ).sort("version", 1)
            return [doc["version"] async for doc in cursor]
        except Exception as e:
            logger.warning("list_versions(%r) failed: %s", name, e)
            return []

    async def list_templates(self) -> list[str]:
        try:
            db = get_database()
            cursor = db.prompt_templates.find(
                {}, projection={"name": 1, "_id": 0}
            ).sort("name", 1)
            return [doc["name"] async for doc in cursor]
        except Exception as e:
            logger.warning("list_templates failed: %s", e)
            return []

    # ---- Writes ---------------------------------------------------------

    async def create_version(
        self,
        name: str,
        body: str,
        description: str = "",
        created_by: Optional[str] = None,
    ) -> int:
        """Append a new version of `name`. Returns the new version number."""
        db = get_database()
        latest = await db.prompt_versions.find_one(
            {"name": name}, projection={"version": 1}, sort=[("version", -1)]
        )
        next_version = (latest["version"] + 1) if latest else 1
        doc = PromptVersion(
            name=name,
            version=next_version,
            body=body,
            description=description,
            created_at=datetime.now(timezone.utc),
            created_by=created_by,
            is_active=False,
        )
        await db.prompt_versions.insert_one(doc.model_dump(by_alias=True))
        # First version of a name is auto-activated.
        if next_version == 1:
            await self.activate(name, next_version)
        self._invalidate(name)
        return next_version

    async def activate(self, name: str, version: int) -> None:
        """Flip the active pointer for `name` to `version`."""
        db = get_database()
        # Verify the version exists.
        v = await db.prompt_versions.find_one(
            {"name": name, "version": version}
        )
        if not v:
            raise ValueError(f"prompt version not found: {name}@{version}")
        await db.prompt_versions.update_many(
            {"name": name}, {"$set": {"isActive": False}}
        )
        await db.prompt_versions.update_one(
            {"name": name, "version": version}, {"$set": {"isActive": True}}
        )
        await db.prompt_templates.update_one(
            {"name": name},
            {
                "$set": {
                    "name": name,
                    "activeVersion": version,
                    "updatedAt": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
        self._invalidate(name)

    # ---- Internals ------------------------------------------------------

    async def _fetch_active(self, name: str) -> str:
        db = get_database()
        doc = await db.prompt_versions.find_one(
            {"name": name, "isActive": True}
        )
        if not doc:
            # Fall back to the template pointer.
            t = await db.prompt_templates.find_one({"name": name})
            if not t:
                return self._fallback(name)
            v = PromptTemplate.model_validate(t)
            doc = await db.prompt_versions.find_one(
                {"name": name, "version": v.active_version}
            )
            if not doc:
                return self._fallback(name)
        return PromptVersion.model_validate(doc).body

    def _fallback(self, name: str) -> str:
        if name == "query_router":
            return _FALLBACK_QUERY_ROUTER
        # A blank-but-valid prompt is better than crashing the caller.
        logger.warning("no fallback for prompt %r; using empty body", name)
        return ""

    def _invalidate(self, name: str) -> None:
        with self._lock:
            self._cache.pop(name, None)


_registry: Optional[PromptRegistry] = None


def get_prompt_registry() -> PromptRegistry:
    """Lazy singleton accessor."""
    global _registry
    if _registry is None:
        _registry = PromptRegistry()
    return _registry


def reset_prompt_registry_cache() -> None:
    """Used by tests."""
    global _registry
    _registry = None
