"""Message service.

Single owner of the `messages` collection. Each message belongs to one
`Conversation` and is scoped by `userId` via a join in the calling route
(the route verifies conversation ownership, then the message service
trusts it).

Pagination strategy: cursor by `_id` (which is monotonically increasing
on ObjectId) so we get insertion order without an extra index. The
frontend renders oldest-first within each page.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from bson.errors import InvalidId

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.db.mongodb import get_database
from app.schemas.message import Message, MessageRole, MessageStatus

logger = get_logger(__name__)

UTC = timezone.utc


def _to_oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError) as e:
        raise NotFoundError(f"Invalid id: {value!r}") from e


def _doc_to_model(doc: dict[str, Any]) -> Message:
    doc = dict(doc)
    if "_id" in doc:
        doc["_id"] = str(doc.pop("_id"))
    return Message.model_validate(doc)


def _preview(content: str) -> str:
    """First 120 chars of the message, normalized for the sidebar."""
    return (content or "").strip().replace("\n", " ")[:120]


class ChatMessageService:
    """Mongo-backed message CRUD."""

    async def append(
        self,
        *,
        conversation_id: str,
        role: MessageRole,
        content: str,
        status: MessageStatus = MessageStatus.COMPLETE,
        run_id: Optional[str] = None,
        agent_results: Optional[dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
        parent_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Message:
        db = get_database()
        now = datetime.now(UTC)
        doc: dict[str, Any] = {
            "conversationId": conversation_id,
            "role": role.value,
            "content": content,
            "createdAt": now,
            "status": status.value,
            "parentId": parent_id,
            "metadata": metadata or {},
            "runId": run_id,
            "agentResults": agent_results or {},
            "durationMs": duration_ms,
        }
        result = await db.messages.insert_one(doc)
        return await self.get(str(result.inserted_id))

    async def get(self, message_id: str) -> Message:
        db = get_database()
        oid = _to_oid(message_id)
        doc = await db.messages.find_one({"_id": oid})
        if not doc:
            raise NotFoundError(f"message {message_id!r} not found")
        return _doc_to_model(doc)

    async def update(
        self,
        message_id: str,
        *,
        content: Optional[str] = None,
        status: Optional[MessageStatus] = None,
        agent_results: Optional[dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
    ) -> Message:
        """Idempotent update — used to flip a `streaming` message to
        `complete` once the orchestrator finishes, and to backfill the
        full assistant content as the SSE loop runs.
        """
        db = get_database()
        oid = _to_oid(message_id)
        sets: dict[str, Any] = {}
        if content is not None:
            sets["content"] = content
        if status is not None:
            sets["status"] = status.value
        if agent_results is not None:
            sets["agentResults"] = agent_results
        if duration_ms is not None:
            sets["durationMs"] = duration_ms
        if not sets:
            return await self.get(message_id)
        doc = await db.messages.find_one_and_update(
            {"_id": oid}, {"$set": sets}, return_document=True,
        )
        if not doc:
            raise NotFoundError(f"message {message_id!r} not found")
        return _doc_to_model(doc)

    async def list_for_conversation(
        self,
        *,
        conversation_id: str,
        limit: int = 200,
        before_id: Optional[str] = None,
    ) -> list[Message]:
        """Return messages oldest → newest, optionally limited to those
        before `before_id` (exclusive). Default cap is 200 to bound the
        initial /chats/[id] payload; the frontend paginates beyond.
        """
        db = get_database()
        query: dict[str, Any] = {"conversationId": conversation_id}
        if before_id:
            query["_id"] = {"$lt": _to_oid(before_id)}
        cursor = db.messages.find(query).sort("_id", 1).limit(limit)
        return [_doc_to_model(d) async for d in cursor]

    async def append_and_touch(
        self,
        *,
        conversation_id: str,
        role: MessageRole,
        content: str,
        status: MessageStatus = MessageStatus.COMPLETE,
        run_id: Optional[str] = None,
        agent_results: Optional[dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
        parent_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Message:
        """Insert a message AND bump the parent conversation's
        `lastMessageAt` / `messageCount` / `lastMessagePreview` in one
        call. Use this for every message that the user will see in the
        sidebar.
        """
        msg = await self.append(
            conversation_id=conversation_id,
            role=role,
            content=content,
            status=status,
            run_id=run_id,
            agent_results=agent_results,
            duration_ms=duration_ms,
            parent_id=parent_id,
            metadata=metadata,
        )
        # Local import to avoid a circular dependency.
        from app.services.chat_conversation_service import (
            get_chat_conversation_service,
        )
        await get_chat_conversation_service().touch_after_message(
            conversation_id=conversation_id,
            preview=_preview(content if role == MessageRole.ASSISTANT else content),
            created_at=msg.created_at,
        )
        return msg


# Singleton
_message_service: Optional[ChatMessageService] = None


def get_chat_message_service() -> ChatMessageService:
    global _message_service
    if _message_service is None:
        _message_service = ChatMessageService()
    return _message_service
