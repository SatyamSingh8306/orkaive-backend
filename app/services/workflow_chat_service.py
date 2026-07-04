"""Service for the per-workflow team chat (the conflict room).

The conflict room is a human-to-human chat scoped to a single workflow.
It is intentionally separate from the AI agent chat (`messages` +
`conversations` collections):

- Different shape: `senderEmail` / `senderName` / `message` rather than
  `role` / `content`.
- Different scope: keyed by `workflowId`, not by `conversationId`.
- Different audience: the team in the room, not the user against agents.

Stored in the `workflow_chats` collection, indexed on `workflowId`.
The WebSocket layer broadcasts new messages to all connected admins in
the same workflow; this service is the source of truth for history and
the persistence path for HTTP sends.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from app.core.logging import get_logger
from app.db.mongodb import get_database

logger = get_logger(__name__)

UTC = timezone.utc


class WorkflowChatService:
    """Mongo CRUD for workflow-room messages."""

    async def list_for_workflow(
        self,
        *,
        workflow_id: str,
        limit: int = 200,
        before_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return messages oldest → newest, optionally limited to those
        before `before_id` (exclusive). Default cap is 200 to match the
        initial-page size used by the room UI; the frontend paginates
        beyond.
        """
        db = get_database()
        query: dict[str, Any] = {"workflowId": workflow_id}
        if before_id:
            query["_id"] = {"$lt": before_id}
        cursor = (
            db.workflow_chats.find(query, {"_id": 0})
            .sort("createdAt", 1)
            .limit(limit)
        )
        return [doc async for doc in cursor]

    async def append(
        self,
        *,
        workflow_id: str,
        sender_email: str,
        sender_name: str,
        message: str,
        message_type: str = "text",
        client_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Insert a new message and return the stored document.

        `client_id` is the message id the frontend generated for its
        optimistic update; we keep it so the same id appears in the
        WS broadcast and the HTTP response (de-dupes on the client).
        """
        db = get_database()
        now = datetime.now(UTC)
        doc: dict[str, Any] = {
            "id": client_id or str(uuid4()),
            "workflowId": workflow_id,
            "senderEmail": sender_email,
            "senderName": sender_name,
            "message": message,
            "messageType": message_type,
            "createdAt": now,
        }
        await db.workflow_chats.insert_one(doc)
        # Mongo adds an _id we don't need to surface; strip it for the
        # shape the frontend already consumes from the WS.
        doc.pop("_id", None)
        return doc


# Singleton
_service: Optional[WorkflowChatService] = None


def get_workflow_chat_service() -> WorkflowChatService:
    global _service
    if _service is None:
        _service = WorkflowChatService()
    return _service
