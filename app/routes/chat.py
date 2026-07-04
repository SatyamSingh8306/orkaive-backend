"""Static multi-agent system routes (the original /api/query).

This is the hard-coded 5-agent orchestrator (supply_chain, process, client,
optimization, compliance). The new dynamic orchestrator lives in
`app.routes.workflow_chat` and reads workflows from Mongo.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.orchestrator.graph_static import StaticOrchestrator, get_static_orchestrator
from app.services.chat_history_service import get_chat_history_service

logger = get_logger(__name__)
router = APIRouter(tags=["agent-endpoints"])

_static: StaticOrchestrator | None = None


def _orchestrator() -> StaticOrchestrator:
    global _static
    if _static is None:
        _static = get_static_orchestrator()
    return _static


# /api/query is the public demo surface. We bucket its history under a
# fixed "public" workflow_id so the Redis keys (`chat:public:<thread_id>`)
# don't collide with the legacy workflow_chat keys
# (`chat:<workflow_id>:<conversation_id>`). Mirrored on
# `StaticOrchestrator._bucket` — keep them in sync.
_TRY_AGENT_BUCKET = "public"


# ---- Models ----------------------------------------------------------------

class QueryRequest(BaseModel):
    query: str = Field(..., description="The user query")
    thread_id: Optional[str] = None
    context: Optional[dict[str, Any]] = None


class QueryResponse(BaseModel):
    query: str
    response: str
    agents_used: list[str]
    thread_id: str
    timestamp: str
    execution_time_ms: float


class AgentInfo(BaseModel):
    name: str
    description: str
    tools: list[str]


# ---- Routes ----------------------------------------------------------------

@router.post("/query", response_model=QueryResponse)
async def process_query(payload: QueryRequest) -> QueryResponse:
    start = time.time()
    thread_id = payload.thread_id or str(uuid.uuid4())
    history = get_chat_history_service()

    await history.append(_TRY_AGENT_BUCKET, thread_id, "user", payload.query)

    try:
        result = await _orchestrator().run(
            query=payload.query,
            thread_id=thread_id,
            context=payload.context or {},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    final = result.get("response", "")
    await history.append(_TRY_AGENT_BUCKET, thread_id, "assistant", final)

    elapsed_ms = (time.time() - start) * 1000
    return QueryResponse(
        query=payload.query,
        response=final,
        agents_used=result.get("agents_used", []),
        thread_id=thread_id,
        timestamp=datetime.utcnow().isoformat(),
        execution_time_ms=elapsed_ms,
    )


@router.get("/query/history")
async def query_history(thread_id: str = Query(..., alias="threadId")) -> dict:
    """Return prior turns for the given /try-agent thread. Used by the
    frontend to seed state on mount."""
    history = get_chat_history_service()
    turns = await history.load(_TRY_AGENT_BUCKET, thread_id)
    return {"thread_id": thread_id, "messages": turns}


@router.get("/agents", response_model=list[AgentInfo])
async def list_agents() -> list[AgentInfo]:
    orch = _orchestrator()
    return [
        AgentInfo(
            name=getattr(a, "name", a_id),
            description=getattr(a, "description", ""),
            tools=[t.name for t in getattr(a, "tools", [])],
        )
        for a_id, a in orch.agents.items()
    ]


@router.get("/graph", response_model=None)
async def graph_topology() -> dict:
    # `/api/graph` is consumed by the public /try-agent page to render the
    # architecture SVG. Shape: { nodes, edges }. Edges cover
    # router→agent, router→synthesizer (early-finish path), and
    # agent→synthesizer (terminal step). Order is stable so the diagram
    # lays out deterministically.
    orch = _orchestrator()
    agent_ids = list(orch.agents.keys())
    nodes = ["router", *agent_ids, "synthesizer"]
    edges: list[list[str]] = (
        [["router", a] for a in agent_ids]
        + [["router", "synthesizer"]]
        + [[a, "synthesizer"] for a in agent_ids]
    )
    return {"nodes": nodes, "edges": edges}
