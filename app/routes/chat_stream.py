"""Chat streaming route (SSE).

`POST /api/chats/{cid}/stream` accepts a user message, persists it, and
streams the orchestrator's response back as Server-Sent Events. Each
SSE frame is a single JSON object on a `data:` line.

Why POST + SSE instead of GET + EventSource:
  - Browsers' `EventSource` only does GET. We need the body for the
    user message, and we want to keep `Authorization: Bearer` in
    headers (no token in query string). The client opens a fetch()
    with `responseType: 'stream'` and parses frames from the body.

Event shapes match `Orchestrator.stream()` in `app/orchestrator/orchestrator.py`:
  - `ready`   – emitted before the orchestrator starts
  - `step`    – chain start/end (router / agent / synthesizer)
  - `token`   – chat-model token delta
  - `tool`    – tool start/end
  - `message` – per-agent final text
  - `conflict`– conflict raised (echoed from the conflict tool)
  - `done`    – final synthesized reply
  - `error`   – something went wrong
  - `stopped` – user cancelled (client closed the connection)
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.core.rate_limit import chat_limit
from app.orchestrator import get_orchestrator
from app.routes.auth import get_current_user
from app.schemas.message import MessageRole, MessageStatus
from app.schemas.user import UserResponse
from app.services.chat_conversation_service import (
    get_chat_conversation_service,
)
from app.services.chat_message_service import get_chat_message_service
from app.services.trace_service import get_trace_service
from app.schemas.trace import StepStatus
from app.ws.chat_bridge import publish_to_user

logger = get_logger(__name__)
router = APIRouter(prefix="/chats", tags=["chats-stream"])


def _to_langchain_messages(
    msgs: list[Any],
    *,
    current_query: str,
) -> list[BaseMessage]:
    """Convert stored Message rows into LangChain messages.

    Drops the trailing duplicate user turn (the message we just
    persisted) — `Orchestrator.stream` appends `current_query` on
    its own. Skips empty rows (assistant placeholders waiting for
    tokens).
    """
    out: list[BaseMessage] = []
    for m in msgs:
        if not m.content:
            continue
        if m.role == MessageRole.USER:
            out.append(HumanMessage(content=m.content))
        elif m.role == MessageRole.ASSISTANT:
            out.append(AIMessage(content=m.content))
    # Drop the duplicate trailing user turn if it's the freshly-
    # persisted one. Repeat-question history further back is kept.
    if out and isinstance(out[-1], HumanMessage) and out[-1].content == current_query:
        out.pop()
    return out


class StreamRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    content: str = Field(..., min_length=1, max_length=200_000)
    workflow_id: Optional[str] = Field(
        None,
        alias="workflowId",
        description=(
            "Optional workflow to bind to the new conversation. If "
            "omitted, the conversation is created without a workflow "
            "and the assistant will respond with a guidance note."
        ),
    )


def _sse(data: dict) -> bytes:
    """Format a single SSE frame. UTF-8, one event per call."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"data: {payload}\n\n".encode("utf-8")


async def _close_run(run_id: Optional[str], *, status=None, error: Optional[str] = None) -> None:
    # ponytail: route-level safety net. Called from a CancelledError
    # handler, so asyncio would re-cancel any await we make. Shield
    # the trace close so it actually runs. Idempotent in end_run.
    if not run_id:
        return
    try:
        await asyncio.shield(
            get_trace_service().end_run(run_id=run_id, status=status, error=error)
        )
    except asyncio.CancelledError:
        # Outer cancellation hits us, but the shielded task continues.
        pass
    except Exception:
        pass


@router.post("/stream")
@chat_limit()
async def stream_new_chat(
    body: StreamRequest,
    request: Request,
    current: UserResponse = Depends(get_current_user),
) -> StreamingResponse:
    """Create a new conversation and start streaming the reply.

    Equivalent to: `POST /api/chats` to create the row, then immediately
    `POST /api/chats/{id}/stream` to send. The two are merged here so the
    client only opens one SSE connection on the first turn of a new
    chat. The first event includes the new `conversationId`; the
    client uses it to update the URL via `router.replace`.

    Declared BEFORE the `/{conversation_id}/stream` route so FastAPI
    matches the more specific path first.
    """
    conv_svc = get_chat_conversation_service()
    msg_svc = get_chat_message_service()

    conv = await conv_svc.create(
        user_id=current.email,
        workflow_id=body.workflow_id,
    )
    conversation_id = conv.id or str(conv.public_dict().get("_id", ""))
    await publish_to_user(current.email, {
        "type": "conversation:new",
        "conversation": conv.public_dict(),
    })

    user_msg = await msg_svc.append_and_touch(
        conversation_id=conversation_id,
        role=MessageRole.USER,
        content=body.content,
    )
    await publish_to_user(current.email, {
        "type": "message:new",
        "conversationId": conversation_id,
        "message": user_msg.public_dict(),
    })

    placeholder = await msg_svc.append_and_touch(
        conversation_id=conversation_id,
        role=MessageRole.ASSISTANT,
        content="",
        status=MessageStatus.STREAMING,
    )
    await publish_to_user(current.email, {
        "type": "message:new",
        "conversationId": conversation_id,
        "message": placeholder.public_dict(),
    })

    async def event_stream() -> AsyncIterator[bytes]:
        # Tell the client which conversation we just created BEFORE the
        # first token so the URL can be updated to /chats/{id}.
        yield _sse({
            "type": "ready",
            "conversationId": conversation_id,
            "runId": "",
        })

        if not conv.workflow_id:
            note = (
                "This conversation has no workflow bound. "
                "Create a new chat with a workflow to use the multi-agent system."
            )
            await msg_svc.update(
                placeholder.id or "", content=note, status=MessageStatus.COMPLETE,
            )
            yield _sse({"type": "token", "delta": note, "agent": "system"})
            yield _sse({
                "type": "done",
                "runId": "",
                "content": note,
                "durationMs": 0,
                "agentsUsed": [],
                "messageId": placeholder.id,
            })
            return

        orch = get_orchestrator()
        accumulated = ""
        agent_results: dict = {}
        run_id: Optional[str] = None
        final_text = ""
        duration_ms = 0
        agents_used: list[str] = []

        # Replay prior turns so the agent has the conversation
        # history. Excludes the message we just persisted; the
        # orchestrator appends the current query on its own.
        prior = await msg_svc.list_for_conversation(
            conversation_id=conversation_id, limit=50,
        )
        prior_msgs = _to_langchain_messages(prior, current_query=body.content)

        try:
            async for ev in orch.stream(
                conv.workflow_id,
                body.content,
                context={
                    "messages": prior_msgs,
                    "conversation_id": conversation_id,
                },
            ):
                t = ev.get("type")
                run_id = ev.get("runId", run_id)
                if t == "ready":
                    yield _sse({**ev, "conversationId": conversation_id})
                    continue
                if t == "token":
                    delta = ev.get("delta", "")
                    if delta:
                        accumulated += delta
                        try:
                            await msg_svc.update(
                                placeholder.id or "", content=accumulated,
                            )
                        except Exception:
                            pass
                    yield _sse(ev)
                    continue
                if t in ("step", "tool", "message", "conflict"):
                    yield _sse(ev)
                    continue
                if t == "done":
                    final_text = ev.get("content", accumulated)
                    duration_ms = ev.get("durationMs", 0)
                    agents_used = ev.get("agentsUsed", [])
                    agent_results = ev.get("agentResults", agent_results)
                    try:
                        await msg_svc.update(
                            placeholder.id or "",
                            content=final_text,
                            status=MessageStatus.COMPLETE,
                            agent_results=agent_results,
                            duration_ms=duration_ms,
                        )
                    except Exception as e:
                        logger.warning("failed to persist final assistant msg: %s", e)
                    final_msg = await msg_svc.get(placeholder.id or "")
                    await publish_to_user(current.email, {
                        "type": "message:updated",
                        "conversationId": conversation_id,
                        "message": final_msg.public_dict(),
                    })
                    # Auto-title from the first user turn.
                    if conv.title == "New chat" or not conv.title:
                        auto_title = body.content.strip().split("\n", 1)[0][:50]
                        if auto_title:
                            try:
                                updated = await conv_svc.rename(
                                    user_id=current.email,
                                    conversation_id=conversation_id,
                                    title=auto_title,
                                )
                                await publish_to_user(current.email, {
                                    "type": "conversation:updated",
                                    "conversation": updated.public_dict(),
                                })
                            except Exception:
                                pass
                    ev["messageId"] = placeholder.id
                    yield _sse(ev)
                    return
                if t == "error":
                    try:
                        await msg_svc.update(
                            placeholder.id or "",
                            content=f"Error: {ev.get('message', 'unknown')}",
                            status=MessageStatus.ERROR,
                        )
                    except Exception:
                        pass
                    yield _sse(ev)
                    return
                if t == "stopped":
                    try:
                        await msg_svc.update(
                            placeholder.id or "",
                            content=accumulated or "(stopped)",
                            status=MessageStatus.STOPPED,
                        )
                    except Exception:
                        pass
                    yield _sse(ev)
                    return
        except asyncio.CancelledError:
            try:
                await msg_svc.update(
                    placeholder.id or "",
                    content=accumulated or "(stopped)",
                    status=MessageStatus.STOPPED,
                )
            except Exception:
                pass
            try:
                yield _sse({"type": "stopped", "runId": run_id, "content": accumulated})
            except Exception:
                pass
            await _close_run(run_id, status=StepStatus.CANCELLED, error="client closed connection")
            return
        except Exception as e:
            logger.exception("stream_new_chat failed")
            try:
                await msg_svc.update(
                    placeholder.id or "",
                    content=f"Error: {e!s}",
                    status=MessageStatus.ERROR,
                )
            except Exception:
                pass
            try:
                yield _sse({"type": "error", "runId": run_id, "message": str(e)})
            except Exception:
                pass
            await _close_run(run_id, error=str(e))
            return
        finally:
            # Happy path ran (done/error/stopped). The orchestrator's
            # own end_run may have already fired; this is a no-op then.
            await _close_run(run_id)

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=headers,
    )


@router.post("/{conversation_id}/stream")
@chat_limit()
async def stream_chat(
    conversation_id: str,
    body: StreamRequest,
    request: Request,
    current: UserResponse = Depends(get_current_user),
) -> StreamingResponse:
    conv_svc = get_chat_conversation_service()
    msg_svc = get_chat_message_service()
    try:
        conv = await conv_svc.get(
            user_id=current.email, conversation_id=conversation_id,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    # 1. Persist the user message.
    user_msg = await msg_svc.append_and_touch(
        conversation_id=conversation_id,
        role=MessageRole.USER,
        content=body.content,
    )
    await publish_to_user(current.email, {
        "type": "message:new",
        "conversationId": conversation_id,
        "message": user_msg.public_dict(),
    })

    # 2. Insert the assistant placeholder up front so the UI has an id
    #    to update as tokens arrive.
    placeholder = await msg_svc.append_and_touch(
        conversation_id=conversation_id,
        role=MessageRole.ASSISTANT,
        content="",
        status=MessageStatus.STREAMING,
    )
    await publish_to_user(current.email, {
        "type": "message:new",
        "conversationId": conversation_id,
        "message": placeholder.public_dict(),
    })

    async def event_stream() -> AsyncIterator[bytes]:
        # If no workflow is bound to this conversation, short-circuit.
        if not conv.workflow_id:
            note = (
                "This conversation has no workflow bound. "
                "Create a new chat with a workflow to use the multi-agent system."
            )
            await msg_svc.update(
                placeholder.id or "", content=note, status=MessageStatus.COMPLETE,
            )
            yield _sse({"type": "token", "delta": note, "agent": "system"})
            yield _sse({
                "type": "done",
                "runId": "",
                "content": note,
                "durationMs": 0,
                "agentsUsed": [],
                "messageId": placeholder.id,
            })
            return

        orch = get_orchestrator()
        accumulated = ""
        agent_results: dict = {}
        run_id: Optional[str] = None
        final_text = ""
        duration_ms = 0
        agents_used: list[str] = []

        # Replay prior turns so the agent has the conversation
        # history. Excludes the message we just persisted; the
        # orchestrator appends the current query on its own.
        prior = await msg_svc.list_for_conversation(
            conversation_id=conversation_id, limit=50,
        )
        prior_msgs = _to_langchain_messages(prior, current_query=body.content)

        try:
            async for ev in orch.stream(
                conv.workflow_id,
                body.content,
                context={
                    "messages": prior_msgs,
                    "conversation_id": conversation_id,
                },
            ):
                t = ev.get("type")
                run_id = ev.get("runId", run_id)

                if t == "ready":
                    # First event — save runId on the placeholder for later updates.
                    yield _sse(ev)
                    continue

                if t == "token":
                    delta = ev.get("delta", "")
                    if delta:
                        accumulated += delta
                        # Persist every token so a refresh shows progress.
                        try:
                            await msg_svc.update(
                                placeholder.id or "", content=accumulated,
                            )
                        except Exception:
                            pass
                    yield _sse(ev)
                    continue

                if t in ("step", "tool", "message", "conflict"):
                    yield _sse(ev)
                    continue

                if t == "done":
                    final_text = ev.get("content", accumulated)
                    duration_ms = ev.get("durationMs", 0)
                    agents_used = ev.get("agentsUsed", [])
                    agent_results = ev.get("agentResults", agent_results)
                    # Persist the final state.
                    try:
                        await msg_svc.update(
                            placeholder.id or "",
                            content=final_text,
                            status=MessageStatus.COMPLETE,
                            agent_results=agent_results,
                            duration_ms=duration_ms,
                        )
                    except Exception as e:
                        logger.warning("failed to persist final assistant msg: %s", e)
                    # Notify other tabs.
                    final_msg = await msg_svc.get(placeholder.id or "")
                    await publish_to_user(current.email, {
                        "type": "message:updated",
                        "conversationId": conversation_id,
                        "message": final_msg.public_dict(),
                    })
                    # Auto-title the conversation on the first turn.
                    if conv.title == "New chat" or not conv.title:
                        auto_title = body.content.strip().split("\n", 1)[0][:50]
                        if auto_title:
                            try:
                                updated = await conv_svc.rename(
                                    user_id=current.email,
                                    conversation_id=conversation_id,
                                    title=auto_title,
                                )
                                await publish_to_user(current.email, {
                                    "type": "conversation:updated",
                                    "conversation": updated.public_dict(),
                                })
                            except Exception:
                                pass
                    # Add messageId to the client-visible event.
                    ev["messageId"] = placeholder.id
                    yield _sse(ev)
                    return

                if t == "error":
                    try:
                        await msg_svc.update(
                            placeholder.id or "",
                            content=f"Error: {ev.get('message', 'unknown')}",
                            status=MessageStatus.ERROR,
                        )
                    except Exception:
                        pass
                    yield _sse(ev)
                    return

                if t == "stopped":
                    try:
                        await msg_svc.update(
                            placeholder.id or "",
                            content=accumulated or "(stopped)",
                            status=MessageStatus.STOPPED,
                        )
                    except Exception:
                        pass
                    yield _sse(ev)
                    return

        except asyncio.CancelledError:
            # Client closed the connection mid-stream.
            try:
                await msg_svc.update(
                    placeholder.id or "",
                    content=accumulated or "(stopped)",
                    status=MessageStatus.STOPPED,
                )
            except Exception:
                pass
            try:
                yield _sse({"type": "stopped", "runId": run_id, "content": accumulated})
            except Exception:
                pass
            await _close_run(run_id, status=StepStatus.CANCELLED, error="client closed connection")
            return
        except Exception as e:
            logger.exception("stream_chat failed")
            try:
                await msg_svc.update(
                    placeholder.id or "",
                    content=f"Error: {e!s}",
                    status=MessageStatus.ERROR,
                )
            except Exception:
                pass
            try:
                yield _sse({"type": "error", "runId": run_id, "message": str(e)})
            except Exception:
                pass
            await _close_run(run_id, error=str(e))
            return
        finally:
            await _close_run(run_id)

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # disable proxy buffering
    }
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=headers,
    )
