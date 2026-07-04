"""Conversation service.

Single owner of the `conversations` collection. All reads/writes are
scoped by `userId` from the JWT — a user can never read or mutate
another user's conversations.

Message bodies live in the `messages` collection (see
`app.services.chat_message_service`); this service only stores
*summary* fields used by the sidebar.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.db.mongodb import get_database
from app.schemas.conversation import Conversation

logger = get_logger(__name__)

UTC = timezone.utc


def _doc_to_model(doc: dict[str, Any]) -> Conversation:
    doc = dict(doc)
    if "_id" in doc:
        doc["_id"] = str(doc.pop("_id"))
    return Conversation.model_validate(doc)


def _to_oid(conversation_id: str) -> ObjectId:
    try:
        return ObjectId(conversation_id)
    except Exception as e:
        raise NotFoundError(f"Invalid conversation id: {conversation_id!r}") from e


class ChatConversationService:
    """Mongo-backed conversation CRUD.

    The frontend sidebar is fed by `list_for_user`; chat screens fetch a
    single conversation via `get` and then paginate `messages` separately.
    """

    # ---- list / get -----------------------------------------------------

    async def list_for_user(
        self,
        *,
        user_id: str,
        limit: int = 50,
        include_deleted: bool = False,
    ) -> list[Conversation]:
        db = get_database()
        query: dict[str, Any] = {"userId": user_id}
        if not include_deleted:
            query["deletedAt"] = None
        cursor = (
            db.conversations.find(query)
            .sort([("pinned", -1), ("lastMessageAt", -1)])
            .limit(limit)
        )
        return [_doc_to_model(d) async for d in cursor]

    async def get(self, *, user_id: str, conversation_id: str) -> Conversation:
        db = get_database()
        oid = _to_oid(conversation_id)
        doc = await db.conversations.find_one({"_id": oid, "userId": user_id})
        if not doc:
            raise NotFoundError(f"conversation {conversation_id!r} not found")
        return _doc_to_model(doc)

    async def search(
        self, *, user_id: str, query: str, limit: int = 20
    ) -> list[Conversation]:
        """Case-insensitive search on title + lastMessagePreview."""
        if not query.strip():
            return await self.list_for_user(user_id=user_id, limit=limit)
        db = get_database()
        # Use a regex on the server; both fields are short so this is fine
        # for the expected corpus size.
        rx = {"$regex": query.strip(), "$options": "i"}
        cursor = (
            db.conversations.find({
                "userId": user_id,
                "deletedAt": None,
                "$or": [{"title": rx}, {"lastMessagePreview": rx}],
            })
            .sort([("pinned", -1), ("lastMessageAt", -1)])
            .limit(limit)
        )
        return [_doc_to_model(d) async for d in cursor]

    # ---- mutations ------------------------------------------------------

    async def create(
        self,
        *,
        user_id: str,
        workflow_id: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Conversation:
        db = get_database()
        now = datetime.now(UTC)
        doc: dict[str, Any] = {
            "userId": user_id,
            "workflowId": workflow_id,
            "title": (title or "New chat").strip()[:200] or "New chat",
            "pinned": False,
            "createdAt": now,
            "updatedAt": now,
            "lastMessageAt": now,
            "messageCount": 0,
            "lastMessagePreview": "",
            "deletedAt": None,
            "metadata": {},
        }
        result = await db.conversations.insert_one(doc)
        return await self.get(user_id=user_id, conversation_id=str(result.inserted_id))

    async def rename(
        self, *, user_id: str, conversation_id: str, title: str
    ) -> Conversation:
        title = (title or "").strip()[:200] or "Untitled"
        db = get_database()
        oid = _to_oid(conversation_id)
        now = datetime.now(UTC)
        doc = await db.conversations.find_one_and_update(
            {"_id": oid, "userId": user_id},
            {"$set": {"title": title, "updatedAt": now}},
            return_document=True,
        )
        if not doc:
            raise NotFoundError(f"conversation {conversation_id!r} not found")
        return _doc_to_model(doc)

    async def set_pinned(
        self, *, user_id: str, conversation_id: str, pinned: bool
    ) -> Conversation:
        db = get_database()
        oid = _to_oid(conversation_id)
        now = datetime.now(UTC)
        doc = await db.conversations.find_one_and_update(
            {"_id": oid, "userId": user_id},
            {"$set": {"pinned": bool(pinned), "updatedAt": now}},
            return_document=True,
        )
        if not doc:
            raise NotFoundError(f"conversation {conversation_id!r} not found")
        return _doc_to_model(doc)

    async def set_workflow(
        self, *, user_id: str, conversation_id: str, workflow_id: Optional[str]
    ) -> Conversation:
        """Bind the conversation to a different workflow (or clear the
        binding when `workflow_id is None`). Existing messages keep
        the workflow context they were generated with; only the *next*
        user turn uses the new binding.
        """
        db = get_database()
        oid = _to_oid(conversation_id)
        now = datetime.now(UTC)
        doc = await db.conversations.find_one_and_update(
            {"_id": oid, "userId": user_id},
            {"$set": {"workflowId": workflow_id, "updatedAt": now}},
            return_document=True,
        )
        if not doc:
            raise NotFoundError(f"conversation {conversation_id!r} not found")
        return _doc_to_model(doc)

    async def soft_delete(
        self, *, user_id: str, conversation_id: str
    ) -> Conversation:
        """Mark a conversation deleted. The doc stays in Mongo for 7 days
        so the frontend can show a "Recently deleted" section and a
        background sweeper can drop it.
        """
        db = get_database()
        oid = _to_oid(conversation_id)
        now = datetime.now(UTC)
        doc = await db.conversations.find_one_and_update(
            {"_id": oid, "userId": user_id},
            {"$set": {"deletedAt": now, "updatedAt": now}},
            return_document=True,
        )
        if not doc:
            raise NotFoundError(f"conversation {conversation_id!r} not found")
        return _doc_to_model(doc)

    async def soft_delete_all(self, *, user_id: str) -> int:
        """Mark every non-deleted conversation for the user as deleted.
        Returns the number of conversations moved to "Recently deleted".
        """
        db = get_database()
        now = datetime.now(UTC)
        result = await db.conversations.update_many(
            {"userId": user_id, "deletedAt": None},
            {"$set": {"deletedAt": now, "updatedAt": now}},
        )
        return int(result.modified_count)

    async def purge_all(self, *, user_id: str) -> int:
        """Hard-delete every conversation (and its messages) for the user.
        Returns the total number of conversations removed. Used by the
        "Clear all history" action when the user has confirmed and
        explicitly wants everything gone.
        """
        from app.db.mongodb import get_database as _db

        db = get_database()
        cursor = db.conversations.find({"userId": user_id}, {"_id": 1})
        ids = [d["_id"] async for d in cursor]
        if not ids:
            return 0
        # Drop messages first, then conversation docs. Two writes so a
        # partial failure leaves the source-of-truth intact.
        await db.messages.delete_many({"conversationId": {"$in": ids}})
        result = await db.conversations.delete_many({"_id": {"$in": ids}})
        return int(result.deleted_count)

    async def restore(
        self, *, user_id: str, conversation_id: str
    ) -> Conversation:
        db = get_database()
        oid = _to_oid(conversation_id)
        doc = await db.conversations.find_one_and_update(
            {"_id": oid, "userId": user_id},
            {"$set": {"deletedAt": None, "updatedAt": datetime.now(UTC)}},
            return_document=True,
        )
        if not doc:
            raise NotFoundError(f"conversation {conversation_id!r} not found")
        return _doc_to_model(doc)

    async def purge_older_than(self, *, days: int = 7) -> int:
        """Drop soft-deleted conversations older than `days`. Returns
        the count purged. Called by a scheduled task in production.
        """
        from datetime import timedelta

        db = get_database()
        cutoff = datetime.now(UTC) - timedelta(days=days)
        result = await db.conversations.delete_many({
            "deletedAt": {"$ne": None, "$lt": cutoff},
        })
        return result.deleted_count

    # ---- bookkeeping used by the message service -----------------------

    async def touch_after_message(
        self,
        *,
        conversation_id: str,
        preview: str,
        created_at: datetime,
    ) -> None:
        """Bump `lastMessageAt`, `messageCount`, and `lastMessagePreview`
        for the conversation that just received a message. The user
        scope is intentionally NOT enforced here — call sites always
        come from the message service which has already verified scope.
        """
        db = get_database()
        oid = _to_oid(conversation_id)
        await db.conversations.update_one(
            {"_id": oid},
            {
                "$set": {
                    "lastMessageAt": created_at,
                    "lastMessagePreview": preview[:120],
                    "updatedAt": datetime.now(UTC),
                },
                "$inc": {"messageCount": 1},
            },
        )


# Singleton — services are stateless wrappers around the Mongo client.
_conversation_service: Optional[ChatConversationService] = None


def get_chat_conversation_service() -> ChatConversationService:
    global _conversation_service
    if _conversation_service is None:
        _conversation_service = ChatConversationService()
    return _conversation_service
