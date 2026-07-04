"""Chat REST routes.

Mounted at `/api/chats` (see `main.py`). Every endpoint is scoped to the
JWT user — a user can never read or mutate another user's conversations.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.rate_limit import chat_limit
from app.routes.auth import get_current_user
from app.schemas.conversation import Conversation, ConversationCreate, ConversationPatch
from app.schemas.message import Message, MessageRole, MessageStatus
from app.schemas.user import UserResponse
from app.services.chat_conversation_service import (
    get_chat_conversation_service,
)
from app.services.chat_message_service import get_chat_message_service
from app.ws.chat_bridge import publish_to_user

logger = get_logger(__name__)
router = APIRouter(prefix="/chats", tags=["chats"])


# ---- Response wrappers ---------------------------------------------------

class ConversationListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    conversations: list[dict]
    total: int


class ConversationDetailResponse(BaseModel):
    """A conversation plus its most recent messages (oldest → newest)."""

    model_config = ConfigDict(extra="ignore")

    conversation: dict
    messages: list[dict]


class MessageListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    messages: list[dict]
    hasMore: bool = False


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    content: str = Field(..., min_length=1, max_length=200_000)


# ---- Endpoints -----------------------------------------------------------

@router.get("", response_model=ConversationListResponse)
async def list_chats(
    limit: int = Query(50, ge=1, le=200),
    q: Optional[str] = Query(None, description="Optional title/preview search"),
    current: UserResponse = Depends(get_current_user),
) -> ConversationListResponse:
    svc = get_chat_conversation_service()
    if q:
        convs = await svc.search(user_id=current.email, query=q, limit=limit)
    else:
        convs = await svc.list_for_user(user_id=current.email, limit=limit)
    return ConversationListResponse(
        conversations=[c.public_dict() for c in convs],
        total=len(convs),
    )


@router.post("", status_code=201, response_model=dict)
async def create_chat(
    body: ConversationCreate,
    current: UserResponse = Depends(get_current_user),
) -> dict:
    """Create an empty conversation. Returns the full Conversation doc."""
    svc = get_chat_conversation_service()
    conv = await svc.create(
        user_id=current.email,
        workflow_id=body.workflow_id,
        title=body.title,
    )
    payload = conv.public_dict()
    # Notify the user's other connected clients that a new chat appeared.
    await publish_to_user(current.email, {
        "type": "conversation:new",
        "conversation": payload,
    })
    return payload


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_chat(
    conversation_id: str,
    message_limit: int = Query(200, ge=1, le=500),
    current: UserResponse = Depends(get_current_user),
) -> ConversationDetailResponse:
    conv_svc = get_chat_conversation_service()
    msg_svc = get_chat_message_service()
    try:
        conv = await conv_svc.get(user_id=current.email, conversation_id=conversation_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    msgs = await msg_svc.list_for_conversation(
        conversation_id=conversation_id, limit=message_limit,
    )
    return ConversationDetailResponse(
        conversation=conv.public_dict(),
        messages=[m.public_dict() for m in msgs],
    )


@router.patch("/{conversation_id}", response_model=dict)
async def patch_chat(
    conversation_id: str,
    body: ConversationPatch,
    current: UserResponse = Depends(get_current_user),
) -> dict:
    conv_svc = get_chat_conversation_service()
    try:
        if body.title is not None:
            conv = await conv_svc.rename(
                user_id=current.email,
                conversation_id=conversation_id,
                title=body.title,
            )
        if body.pinned is not None:
            conv = await conv_svc.set_pinned(
                user_id=current.email,
                conversation_id=conversation_id,
                pinned=body.pinned,
            )
        if "workflowId" in body.model_fields_set:
            # `model_fields_set` lets the caller distinguish "explicitly
            # passed null" from "omitted". We treat both as "set the
            # binding", but the explicit null path means "clear it".
            conv = await conv_svc.set_workflow(
                user_id=current.email,
                conversation_id=conversation_id,
                workflow_id=body.workflow_id,
            )
        elif body.title is None and body.pinned is None:
            # No-op patch — return the current state.
            conv = await conv_svc.get(
                user_id=current.email, conversation_id=conversation_id,
            )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    payload = conv.public_dict()
    await publish_to_user(current.email, {
        "type": "conversation:updated",
        "conversation": payload,
    })
    return payload


@router.delete("", response_model=dict)
async def delete_all_chats(
    purge: bool = Query(
        False,
        description=(
            "If true, hard-delete the user's conversations and their messages "
            "permanently. Default is soft-delete (7-day recovery)."
        ),
    ),
    current: UserResponse = Depends(get_current_user),
) -> dict:
    """Bulk-delete the user's chat history.

    Default behaviour is soft-delete: every non-deleted conversation is
    moved to "Recently deleted" and will be purged after 7 days. Pass
    `?purge=true` to hard-delete immediately. Either way, the response
    reports the count of conversations affected.
    """
    svc = get_chat_conversation_service()
    if purge:
        count = await svc.purge_all(user_id=current.email)
    else:
        count = await svc.soft_delete_all(user_id=current.email)
    # Notify all of the user's open tabs to clear their local state.
    await publish_to_user(current.email, {
        "type": "conversation:deleted",
        "conversationId": "*",  # wildcard = clear all
    })
    return {"ok": True, "deleted": count, "purge": purge}


@router.delete("/{conversation_id}", response_model=dict)
async def delete_chat(
    conversation_id: str,
    current: UserResponse = Depends(get_current_user),
) -> dict:
    conv_svc = get_chat_conversation_service()
    try:
        await conv_svc.soft_delete(
            user_id=current.email, conversation_id=conversation_id,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await publish_to_user(current.email, {
        "type": "conversation:deleted",
        "conversationId": conversation_id,
    })
    return {"ok": True}


@router.get(
    "/{conversation_id}/messages",
    response_model=MessageListResponse,
)
async def list_messages(
    conversation_id: str,
    limit: int = Query(100, ge=1, le=500),
    before_id: Optional[str] = Query(None, description="Cursor: return msgs older than this _id"),
    current: UserResponse = Depends(get_current_user),
) -> MessageListResponse:
    # Verify ownership first.
    conv_svc = get_chat_conversation_service()
    try:
        await conv_svc.get(user_id=current.email, conversation_id=conversation_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    msg_svc = get_chat_message_service()
    # Fetch one extra to know if there's a next page.
    msgs = await msg_svc.list_for_conversation(
        conversation_id=conversation_id,
        limit=limit + 1,
        before_id=before_id,
    )
    has_more = len(msgs) > limit
    if has_more:
        msgs = msgs[:limit]
    return MessageListResponse(
        messages=[m.public_dict() for m in msgs],
        hasMore=has_more,
    )


@router.post(
    "/{conversation_id}/messages",
    status_code=201,
    response_model=dict,
)
@chat_limit()
async def post_message(
    conversation_id: str,
    body: SendMessageRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    current: UserResponse = Depends(get_current_user),
) -> dict:
    """Non-streaming send. Persists the user message and (in the
    background) runs the orchestrator and writes a complete assistant
    message. Returns the user message; the assistant reply will appear
    via a `message:new` WS event.
    """
    conv_svc = get_chat_conversation_service()
    msg_svc = get_chat_message_service()
    try:
        conv = await conv_svc.get(
            user_id=current.email, conversation_id=conversation_id,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    user_msg = await msg_svc.append_and_touch(
        conversation_id=conversation_id,
        role=MessageRole.USER,
        content=body.content,
    )

    # Publish the user message to the user's other tabs.
    await publish_to_user(current.email, {
        "type": "message:new",
        "conversationId": conversation_id,
        "message": user_msg.public_dict(),
    })

    # Run the orchestrator in the background and append the assistant reply.
    background_tasks.add_task(
        _run_assistant_non_streaming,
        conversation_id=conversation_id,
        workflow_id=conv.workflow_id,
        content=body.content,
        user_email=current.email,
    )
    return user_msg.public_dict()


async def _run_assistant_non_streaming(
    *,
    conversation_id: str,
    workflow_id: Optional[str],
    content: str,
    user_email: str,
) -> None:
    """Background helper: run the orchestrator, persist the assistant
    reply, and notify the user. Used by the non-streaming REST endpoint.
    """
    from app.orchestrator import get_orchestrator

    msg_svc = get_chat_message_service()

    # Insert a placeholder assistant message so the UI sees it immediately.
    placeholder = await msg_svc.append_and_touch(
        conversation_id=conversation_id,
        role=MessageRole.ASSISTANT,
        content="",
        status=MessageStatus.STREAMING,
    )
    await publish_to_user(user_email, {
        "type": "message:new",
        "conversationId": conversation_id,
        "message": placeholder.public_dict(),
    })

    if not workflow_id:
        # No workflow selected — short-circuit with a friendly note.
        await msg_svc.update(
            placeholder.id or "",
            content=(
                "This conversation has no workflow bound. "
                "Create a new chat with a workflow to use the multi-agent system."
            ),
            status=MessageStatus.COMPLETE,
        )
        return

    orch = get_orchestrator()
    final = ""
    agent_results: dict[str, Any] = {}
    # Replay prior turns so the agent sees the conversation history
    # (same as the streaming route does). `list_for_conversation`
    # returns oldest → newest; the freshly-persisted user message is
    # the most recent USER row, and the empty assistant placeholder
    # is the very last row. Skip both — `Orchestrator.stream` appends
    # the current query on its own.
    prior = await msg_svc.list_for_conversation(
        conversation_id=conversation_id, limit=50,
    )
    prior_msgs: list[Any] = []
    from langchain_core.messages import AIMessage, HumanMessage
    for m in prior:
        # Skip the empty assistant placeholder we just inserted.
        if m.id == placeholder.id:
            continue
        if not m.content:
            continue
        # Skip the most recent user message — its content matches
        # the current turn's `content`, so the orchestrator would
        # otherwise see this turn twice.
        if m.role == MessageRole.USER and m.content == content:
            # but only if this turn is right at the end — there might
            # be older turns with the same content (repeat questions)
            # below. Since `prior` is oldest→newest, just check the
            # last USER row once below.
            pass
        if m.role == MessageRole.USER:
            prior_msgs.append(HumanMessage(content=m.content))
        elif m.role == MessageRole.ASSISTANT:
            prior_msgs.append(AIMessage(content=m.content))
    # If the final entry of `prior_msgs` is the duplicate user turn
    # we just sent, drop it. (Robust against any matching history.)
    if prior_msgs and isinstance(prior_msgs[-1], HumanMessage) and prior_msgs[-1].content == content:
        prior_msgs.pop()
    try:
        # Consume the streaming generator and accumulate.
        async for ev in orch.stream(
            workflow_id, content,
            context={
                "messages": prior_msgs,
                "conversation_id": conversation_id,
            },
        ):
            t = ev.get("type")
            if t == "token":
                final += ev.get("delta", "")
                await msg_svc.update(placeholder.id or "", content=final)
            elif t == "message":
                agent_results[ev.get("agent", "")] = {"response": ev.get("content", "")}
            elif t == "done":
                final = ev.get("content", final) or final
                agent_results = ev.get("agentResults", agent_results)
            elif t == "error":
                await msg_svc.update(
                    placeholder.id or "",
                    content=f"Error: {ev.get('message', 'unknown')}",
                    status=MessageStatus.ERROR,
                )
                return
            elif t == "stopped":
                await msg_svc.update(
                    placeholder.id or "",
                    content=final or "(stopped)",
                    status=MessageStatus.STOPPED,
                )
                return
    except Exception as e:
        logger.exception("non-streaming assistant failed")
        await msg_svc.update(
            placeholder.id or "",
            content=f"Error: {e!s}",
            status=MessageStatus.ERROR,
        )
        return

    await msg_svc.update(
        placeholder.id or "",
        content=final,
        status=MessageStatus.COMPLETE,
        agent_results=agent_results,
    )
    final_msg = await msg_svc.get(placeholder.id or "")
    await publish_to_user(user_email, {
        "type": "message:updated",
        "conversationId": conversation_id,
        "message": final_msg.public_dict(),
    })
