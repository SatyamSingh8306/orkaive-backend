"""Conflict resolution tool for agents.

Constructed once at module import. The actual node/workflow IDs are read
from the per-agent `_workflow_id` / `_node_id` attributes that the
orchestrator sets via `agent.set_context_data(...)`. There are NO
"unknown" fallback strings — if the orchestrator forgot to call
`set_context_data`, the tool raises and the agent surfaces a clear error.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Optional

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.core.exceptions import ConflictNotFoundError, UpstreamError
from app.core.logging import get_logger
from app.services.conflict_service import ConflictService, get_conflict_service

logger = get_logger(__name__)


class ConflictToolInput(BaseModel):
    """Args schema for the conflict tool."""

    workflow_id: str = Field(..., description="Workflow ID (overridable from agent context)")
    node_label: str = Field(..., description="Human-readable agent name")
    owner_email: str = Field(..., description="Admin email to notify")
    query: str = Field(..., description="Conflict question for the admin")
    context: Optional[dict[str, Any]] = Field(default=None, description="Context data")
    timeout_seconds: int = Field(300, ge=5, le=3600)


class ConflictResolutionTool(BaseTool):
    name: str = "conflict_resolution"
    description: str = """Raise a conflict to an admin and wait for their guidance.

Use when:
- Data is anomalous (negative inventory, impossible dates, contradictions)
- A business rule is about to be violated
- A high-stakes decision has unclear outcomes
- Critical information is missing
- Multiple valid but contradictory options exist

The tool will pause execution, broadcast the conflict to connected admins,
and return their guidance (or a timeout message)."""

    args_schema: type[BaseModel] = ConflictToolInput

    # ---- Internal: per-agent context (set by BaseAgent.set_context_data) ----
    _workflow_id: Optional[str] = None
    _node_id: Optional[str] = None
    _service: Optional[ConflictService] = None

    def __init__(self, service: Optional[ConflictService] = None, **kwargs):
        super().__init__(**kwargs)
        self._service = service

    # Bound helpers for the test/mock surface; production code goes through
    # `_arun` so all raises funnel through the service.
    def _service_(self) -> ConflictService:
        if self._service is None:
            self._service = get_conflict_service()
        return self._service

    def _run(
        self,
        workflow_id: str,
        node_label: str,
        owner_email: str,
        query: str,
        context: Optional[dict[str, Any]] = None,
        timeout_seconds: int = 300,
    ) -> str:
        # Bridge sync → async (LangChain still calls _run in some paths).
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self._arun(workflow_id, node_label, owner_email, query, context, timeout_seconds)
            )
        # If we're already inside a loop, dispatch to a thread.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(
                asyncio.run,
                self._arun(workflow_id, node_label, owner_email, query, context, timeout_seconds),
            )
            return fut.result()

    async def _arun(
        self,
        workflow_id: str,
        node_label: str,
        owner_email: str,
        query: str,
        context: Optional[dict[str, Any]] = None,
        timeout_seconds: int = 300,
    ) -> str:
        # Resolve workflow/node IDs: prefer the per-agent context, fall back
        # to the tool args. Refuse "unknown" placeholders.
        wf_id = self._workflow_id or workflow_id
        node_id = self._node_id
        if not wf_id or wf_id == "unknown":
            raise UpstreamError(
                "conflict_resolution: missing workflow_id (agent context not set)"
            )
        if not node_id or node_id == "unknown":
            raise UpstreamError(
                "conflict_resolution: missing node_id (agent context not set)"
            )

        run_id = str(uuid.uuid4())
        try:
            query_id = await self._service_().raise_conflict(
                workflow_id=wf_id,
                run_id=run_id,
                node_id=node_id,
                node_label=node_label,
                owner_email=owner_email,
                query=query,
                context=context or {},
                timeout_seconds=timeout_seconds,
            )
        except Exception as e:
            logger.exception("conflict: raise failed")
            return f"Could not raise conflict: {e!s}"

        logger.info("conflict raised: query_id=%s node=%s", query_id, node_id)

        try:
            response = await self._service_().wait_for_response(
                query_id=query_id, timeout_seconds=timeout_seconds
            )
        except ConflictNotFoundError:
            return "Admin did not respond and the conflict record was lost."

        if response is not None:
            return f"Admin guidance received: {response}"
        return (
            f"Admin did not respond within {timeout_seconds}s. "
            "Proceeding with your default approach."
        )


# Module-level singleton. Tools are append-only on the agent; the same
# instance can be shared because all per-agent state is read from the
# attached `set_context_data`.
_conflict_service_singleton: ConflictService | None = None


def get_conflict_tool() -> ConflictResolutionTool:
    """Public accessor used by the orchestrator when building agents."""
    return ConflictResolutionTool()


# Backwards-compatible alias used by old code paths.
conflict_tool = get_conflict_tool()
