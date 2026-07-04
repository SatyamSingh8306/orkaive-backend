"""Async Redis client management."""

from __future__ import annotations

import logging
from typing import Optional

import redis.asyncio as redis_async

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

_client: Optional[redis_async.Redis] = None


def get_async_redis_client() -> redis_async.Redis:
    """Return the active Redis client, building it lazily."""
    global _client
    if _client is None:
        s = get_settings()
        _client = redis_async.Redis(
            host=s.redis_host,
            port=s.redis_port,
            username=s.redis_username,
            password=s.redis_password,
            db=s.redis_db,
            decode_responses=True,
        )
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None
