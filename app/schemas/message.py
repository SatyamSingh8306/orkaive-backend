"""Message schemas (Pydantic v2).

A `Message` is one user or assistant turn inside a `Conversation`. Stored
as a document in the `messages` collection. Kept separate from the
conversation so the sidebar list doesn't pay for full message history.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

UTC = timezone.utc


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class MessageStatus(str, Enum):
    """Lifecycle of a single message.

    - `streaming` — assistant turn that is still receiving tokens.
    - `complete`  — finalized (either a finished assistant reply, or a user msg).
    - `error`     — assistant turn that failed (LLM error, timeout, etc.).
    - `stopped`   — assistant turn that the user cancelled mid-stream.
    """

    STREAMING = "streaming"
    COMPLETE = "complete"
    ERROR = "error"
    STOPPED = "stopped"


class Message(BaseModel):
    """One message in a conversation."""

    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: Optional[str] = Field(default=None, alias="_id")
    conversation_id: str = Field(..., alias="conversationId")
    role: MessageRole
    content: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="createdAt")
    status: MessageStatus = MessageStatus.COMPLETE

    # Optional per-message metadata.
    parent_id: Optional[str] = Field(default=None, alias="parentId")
    metadata: dict[str, Any] = Field(default_factory=dict)
    # The most recent `runId` and the agent-results map (for the steps panel).
    run_id: Optional[str] = Field(default=None, alias="runId")
    agent_results: dict[str, Any] = Field(default_factory=dict, alias="agentResults")
    duration_ms: Optional[int] = Field(default=None, alias="durationMs")

    def public_dict(self) -> dict[str, Any]:
        d = self.model_dump(by_alias=True, exclude_none=True)
        if "_id" in d and d["_id"] is not None:
            d["_id"] = str(d["_id"])
        if "createdAt" in d and hasattr(d["createdAt"], "isoformat"):
            d["createdAt"] = d["createdAt"].isoformat()
        # Enums come out as their str value via Pydantic v2 .model_dump.
        return d


class MessageCreate(BaseModel):
    """Body for `POST /api/chats/{cid}/messages` (non-streaming send)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    content: str = Field(..., min_length=1, max_length=200_000)
    role: MessageRole = MessageRole.USER


class MessageAppend(BaseModel):
    """Body for `POST /api/chats/{cid}/stream`."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    content: str = Field(..., min_length=1, max_length=200_000)
