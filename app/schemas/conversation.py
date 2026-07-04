"""Conversation schemas (Pydantic v2).

A `Conversation` is the user-facing chat thread. It owns no message bodies
(those live in the `messages` collection for cheap pagination); it only
holds summary fields so the sidebar can render without scanning the full
history.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

UTC = timezone.utc


class Conversation(BaseModel):
    """A single chat thread owned by one user.

    Stored as one document in the `conversations` collection. Message
    bodies live in the separate `messages` collection keyed by
    `conversationId`.
    """

    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: Optional[str] = Field(default=None, alias="_id")
    user_id: str = Field(..., alias="userId")
    workflow_id: Optional[str] = Field(default=None, alias="workflowId")
    title: str = "New chat"
    pinned: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="createdAt")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="updatedAt")
    last_message_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        alias="lastMessageAt",
    )
    message_count: int = Field(default=0, alias="messageCount")
    last_message_preview: str = Field(default="", alias="lastMessagePreview")
    # Soft-delete: set on the doc when the user "deletes" a chat.
    # 7-day retention enforced by a background sweeper (out of scope here).
    deleted_at: Optional[datetime] = Field(default=None, alias="deletedAt")
    metadata: dict[str, Any] = Field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dict with string IDs and ISO timestamps."""
        d = self.model_dump(by_alias=True, exclude_none=True)
        if "_id" in d and d["_id"] is not None:
            d["_id"] = str(d["_id"])
        for k in ("createdAt", "updatedAt", "lastMessageAt", "deletedAt"):
            if k in d and d[k] is not None and hasattr(d[k], "isoformat"):
                d[k] = d[k].isoformat()
        return d


class ConversationCreate(BaseModel):
    """Body of `POST /api/chats`."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    workflow_id: Optional[str] = Field(default=None, alias="workflowId")
    title: Optional[str] = Field(default=None, alias="title", max_length=200)


class ConversationPatch(BaseModel):
    """Body of `PATCH /api/chats/{cid}`."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    title: Optional[str] = Field(default=None, max_length=200)
    pinned: Optional[bool] = None
    workflow_id: Optional[str] = Field(
        default=None,
        alias="workflowId",
        description=(
            "Bind or rebind the conversation to a workflow. Pass `null` "
            "to clear the binding (chat will respond with a guidance note)."
        ),
    )
