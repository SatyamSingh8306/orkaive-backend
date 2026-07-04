"""Conflict routes — FastAPI owns the conflict Mongo collection.

Replaces the previous `routes/conflict_resolution.py` and
`routes/conflict_broadcast.py`. The `wait_for_response` mechanism uses
Redis pubsub (not HTTP polling).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.exceptions import ConflictNotFoundError
from app.core.logging import get_logger
from app.schemas.conflict import (
    ConflictListItem,
    ConflictStatus,
    ConflictStatusResponse,
    RaiseConflictRequest,
    RaiseConflictResponse,
    RespondConflictRequest,
)
from app.services.conflict_service import get_conflict_service

logger = get_logger(__name__)
router = APIRouter(prefix="/conflicts", tags=["conflicts"])


# --- Models (response-shaped) ----------------------------------------------

class RespondBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    response: str = Field(..., min_length=1, max_length=8000)
    admin_email: EmailStr = Field(..., alias="adminEmail")


# --- Routes -----------------------------------------------------------------

@router.post("/raise", response_model=RaiseConflictResponse, status_code=201)
async def raise_conflict(payload: RaiseConflictRequest) -> RaiseConflictResponse:
    svc = get_conflict_service()
    query_id = await svc.raise_conflict(
        workflow_id=payload.workflow_id,
        run_id=payload.run_id,
        node_id=payload.node_id,
        node_label=payload.node_label,
        owner_email=payload.owner_email,
        query=payload.query,
        context=payload.context,
        timeout_seconds=payload.timeout_seconds,
    )
    doc = await svc.get(query_id)
    if doc is None:  # pragma: no cover - race
        raise HTTPException(status_code=500, detail="conflict created but not retrievable")
    return RaiseConflictResponse(
        query_id=doc.query_id,
        status=doc.status,
        timeout_at=doc.timeout_at,
    )


@router.get("/status", response_model=ConflictStatusResponse)
async def status(query_id: str = Query(...)) -> ConflictStatusResponse:
    svc = get_conflict_service()
    doc = await svc.get(query_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="conflict not found")
    return ConflictStatusResponse(
        query_id=doc.query_id,
        status=doc.status,
        query=doc.query,
        response=doc.response,
        responded_at=doc.responded_at,
        timeout_at=doc.timeout_at,
    )


@router.post("/respond")
async def respond(payload: RespondBody, query_id: str = Query(...)) -> dict:
    svc = get_conflict_service()
    try:
        doc = await svc.respond_conflict(
            query_id=query_id,
            response=payload.response,
            admin_email=payload.admin_email,
        )
    except ConflictNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {
        "queryId": doc.query_id,
        "status": doc.status.value,
        "response": doc.response,
        "respondedAt": doc.responded_at.isoformat() if doc.responded_at else None,
    }


@router.get("/list", response_model=list[ConflictListItem])
async def list_(
    workflow_id: str = Query(..., min_length=1),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
) -> list[ConflictListItem]:
    svc = get_conflict_service()
    return await svc.list_for_workflow(workflow_id=workflow_id, status=status_filter, limit=limit)

@router.get(
    "/user/{email}",
    response_model=list[ConflictListItem]
)
async def list_for_user(
    email: str,
    status_filter: Optional[str] = Query(
        None,
        alias="status"
    ),
    limit: int = Query(
        100,
        ge=1,
        le=500
    ),
) -> list[ConflictListItem]:
    svc = get_conflict_service()

    return await svc.list_for_user(
        owner_email=email,
        status=status_filter,
        limit=limit
    )

@router.post("/wait")
async def wait(query_id: str = Query(...), timeout_seconds: int = Query(300, ge=5, le=3600)) -> dict:
    """Block (server-side) until the conflict is resolved or the timeout elapses.

    This is the new replacement for the old `poll_for_response` HTTP loop.
    The frontend can choose to subscribe to the WebSocket instead, but
    this endpoint is kept for parity.
    """
    svc = get_conflict_service()
    response = await svc.wait_for_response(query_id=query_id, timeout_seconds=timeout_seconds)
    return {
        "queryId": query_id,
        "response": response,
        "responded": response is not None,
    }
