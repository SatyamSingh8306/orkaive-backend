"""Per-workflow team chat routes — backs the conflict room UI.

Mounted under `/api` so the paths resolve to `/api/workflow-chats`.
The frontend `WorkflowRoom` page uses these for the initial history
load and the HTTP fallback for sending (the WebSocket at `/ws/{id}` is
the primary live path).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.services.workflow_chat_service import get_workflow_chat_service

router = APIRouter(prefix="/workflow-chats", tags=["workflow-chats"])


class WorkflowChatMessage(BaseModel):
    """Shape returned by the route and consumed by the frontend's
    `ChatMessage` type in `types/socket.ts`. Field names use camelCase
    to match the WebSocket payload."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    workflowId: str = Field(..., alias="workflowId")
    senderEmail: EmailStr = Field(..., alias="senderEmail")
    senderName: str = Field("", alias="senderName")
    message: str
    messageType: str = Field("text", alias="messageType")
    createdAt: str = Field(..., alias="createdAt")


class SendWorkflowChatBody(BaseModel):
    """Body for `POST /api/workflow-chats`."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    workflowId: str = Field(..., min_length=1, alias="workflowId")
    senderEmail: EmailStr = Field(..., alias="senderEmail")
    senderName: str = Field("", alias="senderName")
    message: str = Field(..., min_length=1, max_length=8000)
    messageType: str = Field("text", alias="messageType")
    # Optional client-generated id so the same id appears in the
    # HTTP response and the subsequent WS broadcast.
    clientId: Optional[str] = Field(default=None, alias="clientId")


@router.get("", response_model=list[WorkflowChatMessage])
async def list_(
    workflowId: str = Query(..., min_length=1),
    limit: int = Query(200, ge=1, le=500),
    beforeId: Optional[str] = Query(default=None, alias="beforeId"),
) -> list[WorkflowChatMessage]:
    """List messages for a workflow's room, oldest → newest."""
    svc = get_workflow_chat_service()
    docs = await svc.list_for_workflow(
        workflow_id=workflowId,
        limit=limit,
        before_id=beforeId,
    )
    out: list[WorkflowChatMessage] = []
    for d in docs:
        out.append(WorkflowChatMessage(
            id=d["id"],
            workflowId=d["workflowId"],
            senderEmail=d["senderEmail"],
            senderName=d.get("senderName", ""),
            message=d["message"],
            messageType=d.get("messageType", "text"),
            createdAt=(
                d["createdAt"].isoformat()
                if hasattr(d.get("createdAt"), "isoformat")
                else str(d.get("createdAt"))
            ),
        ))
    return out


@router.post("", response_model=WorkflowChatMessage, status_code=201)
async def send(payload: SendWorkflowChatBody) -> WorkflowChatMessage:
    """Persist a new team chat message and return the stored doc.

    The same message is also broadcast over the workflow WebSocket by
    the route that originally emitted the send (the WS `chat:send`
    handler in `routes/websocket.py`); the HTTP path is the source of
    truth for persistence.
    """
    svc = get_workflow_chat_service()
    doc = await svc.append(
        workflow_id=payload.workflowId,
        sender_email=payload.senderEmail,
        sender_name=payload.senderName,
        message=payload.message,
        message_type=payload.messageType,
        client_id=payload.clientId,
    )
    return WorkflowChatMessage(
        id=doc["id"],
        workflowId=doc["workflowId"],
        senderEmail=doc["senderEmail"],
        senderName=doc.get("senderName", ""),
        message=doc["message"],
        messageType=doc.get("messageType", "text"),
        createdAt=(
            doc["createdAt"].isoformat()
            if hasattr(doc.get("createdAt"), "isoformat")
            else str(doc.get("createdAt"))
        ),
    )
