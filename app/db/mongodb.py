"""Mongo connection management."""

from __future__ import annotations

import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

_client: Optional[AsyncIOMotorClient] = None
_database: Optional[AsyncIOMotorDatabase] = None


async def connect() -> AsyncIOMotorDatabase:
    """Connect to MongoDB if not already connected. Idempotent."""
    global _client, _database
    if _database is not None:
        return _database

    settings = get_settings()
    _client = AsyncIOMotorClient(settings.mongodb_url)
    _database = _client[settings.mongodb_db]
    # ping to verify
    await _client.admin.command("ping")
    logger.info("connected to MongoDB: %s/%s", settings.mongodb_url, settings.mongodb_db)
    return _database


async def close() -> None:
    global _client, _database
    if _client is not None:
        _client.close()
    _client = None
    _database = None


def get_database() -> AsyncIOMotorDatabase:
    """Return the current database. Raises if `connect()` was not called."""
    if _database is None:
        raise RuntimeError("MongoDB not connected; call `connect()` from the FastAPI lifespan")
    return _database


async def ensure_indexes() -> None:
    """Create indexes used by the services. Idempotent."""
    db = await connect()
    await db.workflows.create_index("name")
    await db.tools.create_index([("workflowId", 1), ("nodeId", 1)])
    await db.conflicts.create_index("queryId", unique=True)
    await db.conflicts.create_index([("workflowId", 1), ("status", 1)])
    await db.conflicts.create_index("raisedAt")
    await db.users.create_index("email", unique=True)
    # Chat (conversations + messages) — owned by ChatConversationService /
    # ChatMessageService. The two compound indexes cover the sidebar list
    # (userId+lastMessageAt) and the message-history paginator
    # (conversationId+_id). The `deletedAt` partial filter keeps the
    # "Recently deleted" list out of the default queries.
    await db.conversations.create_index(
        [("userId", 1), ("lastMessageAt", -1)],
        partialFilterExpression={"deletedAt": None},
    )
    await db.conversations.create_index(
        [("userId", 1), ("pinned", -1), ("lastMessageAt", -1)],
        partialFilterExpression={"deletedAt": None},
    )
    await db.conversations.create_index(
        [("deletedAt", 1)],
        # Soft-deleted docs only — used by the sweeper.
    )
    await db.messages.create_index([("conversationId", 1), ("_id", 1)])
    # Per-workflow team chat (the conflict room). Compound index covers
    # the only query path: history pagination for a single workflow.
    await db.workflow_chats.create_index([("workflowId", 1), ("createdAt", 1)])
    # Prompt registry: lookup by (name, version) and the active marker.
    await db.prompt_versions.create_index(
        [("name", 1), ("version", 1)], unique=True
    )
    await db.prompt_versions.create_index(
        [("name", 1), ("isActive", 1)], partialFilterExpression={"isActive": True}
    )
    await db.prompt_templates.create_index("name", unique=True)
    # Evaluation runs: list-by-workflow (newest first) + status filter.
    await db.eval_runs.create_index([("workflowId", 1), ("createdAt", -1)])
    await db.eval_runs.create_index("status")
