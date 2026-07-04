"""Conflict resolution service.

Owns the `conflicts` collection. The flow:

  1. `raise_conflict(...)` — write the doc, broadcast a `conflict:raised`
     event to WebSocket clients, return the `query_id`.
  2. An admin (via REST or WS) calls `respond_conflict(...)` which
     updates the doc and publishes to a per-query Redis channel.
  3. The agent that called `wait_for_response(...)` subscribes to that
     channel and returns as soon as the response arrives (or times out).

The HTTP-poll loop from the previous implementation is gone. The wait
mechanism is pubsub with a 1s safety net.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.config.settings import get_settings
from app.core.exceptions import ConflictNotFoundError
from app.core.logging import get_logger
from app.db.mongodb import get_database
from app.db.redis import get_async_redis_client
from app.schemas.conflict import (
    ConflictDoc,
    ConflictListItem,
    ConflictStatus,
)

logger = get_logger(__name__)


def _channel(query_id: str) -> str:
    return f"conflict:{query_id}:events"


class ConflictService:
    """Service for managing human-in-the-loop conflicts."""

    async def raise_conflict(
        self,
        *,
        workflow_id: str,
        run_id: str,
        node_id: str,
        node_label: str,
        owner_email: str,
        query: str,
        context: dict[str, Any],
        timeout_seconds: int,
    ) -> str:
        settings = get_settings()
        query_id = f"{workflow_id}_{uuid.uuid4().hex[:8]}_{int(datetime.now(timezone.utc).timestamp())}"
        now = datetime.now(timezone.utc)
        timeout_at = now + timedelta(seconds=timeout_seconds)

        doc = ConflictDoc(
            query_id=query_id,
            workflow_id=workflow_id,
            run_id=run_id,
            node_id=node_id,
            node_label=node_label,
            owner_email=owner_email,
            query=query,
            context=context or {},
            status=ConflictStatus.PENDING,
            raised_at=now,
            timeout_at=timeout_at,
            timeout_seconds=timeout_seconds,
        )

        db = get_database()
        await db.conflicts.insert_one(doc.model_dump(by_alias=True))

        # Broadcast over WebSocket so any connected admin sees the conflict.
        await _broadcast(workflow_id, {
            "type": "conflict:raised",
            "queryId": query_id,
            "workflowId": workflow_id,
            "runId": run_id,
            "nodeId": node_id,
            "nodeLabel": node_label,
            "ownerEmail": owner_email,
            "query": query,
            "context": {
                "input": (context or {}).get("input", ""),
                "agentOutput": (context or {}).get("agentOutput", ""),
                "conflictReason": (context or {}).get("conflictReason", query),
            },
            "timeoutAt": timeout_at.isoformat(),
        })

        logger.info("conflict raised: %s node=%s", query_id, node_id)
        return query_id

    async def get(self, query_id: str) -> Optional[ConflictDoc]:
        db = get_database()
        doc = await db.conflicts.find_one({"queryId": query_id})
        if not doc:
            return None
        return ConflictDoc.model_validate(doc)

    async def respond_conflict(
        self, *, query_id: str, response: str, admin_email: str
    ) -> ConflictDoc:
        db = get_database()
        now = datetime.now(timezone.utc)
        updated = await db.conflicts.find_one_and_update(
            {"queryId": query_id, "status": "pending"},
            {
                "$set": {
                    "status": ConflictStatus.ANSWERED.value,
                    "response": response,
                    "respondedAt": now,
                    "respondedBy": admin_email,
                }
            },
            return_document=True,
        )
        if not updated:
            # Either unknown or already resolved
            existing = await self.get(query_id)
            if existing is None:
                raise ConflictNotFoundError(query_id)
            return existing

        # Publish to the per-query channel so any agent waiting returns.
        redis = get_async_redis_client()
        try:
            await redis.publish(_channel(query_id), json.dumps({
                "type": "conflict:resolved",
                "queryId": query_id,
                "response": response,
                "adminEmail": admin_email,
                "respondedAt": now.isoformat(),
            }))
        except Exception as e:
            logger.warning("conflict: redis publish failed: %s", e)

        # Also broadcast to WebSocket clients.
        await _broadcast(updated["workflowId"], {
            "type": "conflict:resolved",
            "queryId": query_id,
            "workflowId": updated["workflowId"],
            "response": response,
            "adminEmail": admin_email,
            "respondedAt": now.isoformat(),
        })

        return ConflictDoc.model_validate(updated)

    async def wait_for_response(
        self, *, query_id: str, timeout_seconds: int
    ) -> Optional[str]:
        """Block until an admin responds, or the timeout elapses.

        Strategy: subscribe to a per-query Redis channel. The `respond_conflict`
        method publishes the answer there. If pubsub is unavailable, fall
        back to a 1s poll on the Mongo doc.
        """
        settings = get_settings()
        redis = get_async_redis_client()
        channel = _channel(query_id)

        try:
            pubsub = redis.pubsub()
            await pubsub.subscribe(channel)
        except Exception as e:
            logger.warning("conflict: pubsub unavailable, falling back to poll: %s", e)
            return await self._poll(query_id, timeout_seconds)

        try:
            start = datetime.now(timezone.utc)
            while True:
                elapsed = (datetime.now(timezone.utc) - start).total_seconds()
                if elapsed >= timeout_seconds:
                    await self._mark_timeout(query_id)
                    return None

                # Read with a short timeout so the loop is interruptible.
                try:
                    msg = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                        timeout=1.5,
                    )
                except asyncio.TimeoutError:
                    msg = None

                if msg and msg.get("type") == "message":
                    data = json.loads(msg["data"])
                    return data.get("response")

                # If the doc was updated out-of-band, return it.
                doc = await self.get(query_id)
                if doc and doc.status == ConflictStatus.ANSWERED:
                    return doc.response
                if doc and doc.status == ConflictStatus.TIMEOUT:
                    return None
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception:
                pass

    async def _poll(self, query_id: str, timeout_seconds: int) -> Optional[str]:
        settings = get_settings()
        start = datetime.now(timezone.utc)
        while True:
            elapsed = (datetime.now(timezone.utc) - start).total_seconds()
            if elapsed >= timeout_seconds:
                await self._mark_timeout(query_id)
                return None
            doc = await self.get(query_id)
            if doc is None:
                return None
            if doc.status == ConflictStatus.ANSWERED:
                return doc.response
            if doc.status == ConflictStatus.TIMEOUT:
                return None
            await asyncio.sleep(settings.conflict_poll_interval)

    async def _mark_timeout(self, query_id: str) -> None:
        try:
            db = get_database()
            await db.conflicts.update_one(
                {"queryId": query_id, "status": "pending"},
                {"$set": {"status": ConflictStatus.TIMEOUT.value}},
            )
        except Exception as e:
            logger.warning("conflict: failed to mark timeout for %s: %s", query_id, e)

    async def list_for_workflow(
        self, *, workflow_id: str, status: Optional[str] = None, limit: int = 100
    ) -> list[ConflictListItem]:
        db = get_database()
        query: dict[str, Any] = {"workflowId": workflow_id}
        if status:
            query["status"] = status
        cursor = db.conflicts.find(query).sort("raisedAt", -1).limit(limit)
        items: list[ConflictListItem] = []
        async for d in cursor:
            items.append(ConflictListItem(
                query_id=d["queryId"],
                workflow_id=d["workflowId"],
                node_id=d["nodeId"],
                node_label=d.get("nodeLabel", ""),
                owner_email=d["ownerEmail"],
                query=d["query"],
                status=d["status"],
                raised_at=d["raisedAt"],
                responded_at=d.get("respondedAt"),
            ))
        return items
    
    async def list_for_user(
            self,
            *,
            owner_email: str,
            status: str | None = None,
            limit: int = 100
        ):
            db = get_database()

            query = {
                "ownerEmail": owner_email
            }

            if status:
                query["status"] = status

            cursor = (
                db.conflicts
                .find(query)
                .sort("raisedAt", -1)
                .limit(limit)
            )

            items = []

            async for d in cursor:
                items.append({
                    "queryId": d["queryId"],
                    "workflowId": d["workflowId"],
                    "nodeId": d["nodeId"],
                    "nodeLabel": d.get(
                        "nodeLabel", ""
                    ),
                    "ownerEmail": d[
                        "ownerEmail"
                    ],
                    "query": d["query"],
                    "status": d["status"],
                    "raisedAt": d[
                        "raisedAt"
                    ],
                    "respondedAt": d.get(
                        "respondedAt"
                    ),
                })

            return items


# -----------------------------------------------------------------------

# WebSocket bridge — avoid a circular import by calling the existing
# broadcast function lazily.
async def _broadcast(workflow_id: str, payload: dict[str, Any]) -> None:
    try:
        from app.routes.websocket import broadcast_conflict
        await broadcast_conflict(workflow_id, payload)
    except Exception as e:
        # If the WS layer isn't initialized yet, log and continue.
        logger.debug("ws broadcast skipped: %s", e)


# Singleton accessor used by `BaseAgent`-style callers.
_conflict_service_singleton: ConflictService | None = None


def get_conflict_service() -> ConflictService:
    global _conflict_service_singleton
    if _conflict_service_singleton is None:
        _conflict_service_singleton = ConflictService()
    return _conflict_service_singleton
