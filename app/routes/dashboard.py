"""Dashboard routes.

Reads through `app.services.trace_service` rather than poking Redis
directly. Pagination and filtering are honored.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.logging import get_logger
from app.schemas.trace import DashboardRunSummary, StepStatus, TraceFilter
from app.services.trace_service import get_trace_service

logger = get_logger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/runs", response_model=list[DashboardRunSummary])
async def list_runs(
    workflow_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    status: Optional[StepStatus] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[DashboardRunSummary]:
    trace = get_trace_service()
    return await trace.list_runs(TraceFilter(
        workflow_id=workflow_id,
        user_id=user_id,
        status=status,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    ))


@router.get("/runs/{run_id}")
async def run_details(run_id: str) -> dict:
    trace = get_trace_service()
    details = await trace.get_run_details(run_id)
    if details is None:
        raise HTTPException(status_code=404, detail="run not found")
    return details


@router.get("/stats")
async def stats() -> dict:
    trace = get_trace_service()
    runs = await trace.list_runs(TraceFilter(limit=1000))
    total = len(runs)
    completed = sum(1 for r in runs if r.status == StepStatus.COMPLETED)
    failed = sum(1 for r in runs if r.status == StepStatus.ERROR)
    active = sum(1 for r in runs if r.status == StepStatus.STARTED)
    durations = [r.duration_ms for r in runs if r.duration_ms is not None]
    avg = sum(durations) / len(durations) if durations else 0
    return {
        "total_runs": total,
        "successful_runs": completed,
        "failed_runs": failed,
        "active_runs": active,
        "success_rate": (completed / total * 100) if total else 0,
        "avg_duration_ms": avg,
        "unique_workflows": len({r.workflow_id for r in runs}),
    }


@router.get("/workflows")
async def workflows() -> list[dict]:
    """Return a deduplicated list of workflows that have at least one run."""
    trace = get_trace_service()
    runs = await trace.list_runs(TraceFilter(limit=1000))
    by_id: dict[str, dict] = {}
    for r in runs:
        if r.workflow_id not in by_id:
            by_id[r.workflow_id] = {
                "workflow_id": r.workflow_id,
                "workflow_name": r.workflow_name,
                "total_runs": 0,
                "successful_runs": 0,
                "failed_runs": 0,
                "last_run": None,
            }
        w = by_id[r.workflow_id]
        w["total_runs"] += 1
        if r.status == StepStatus.COMPLETED:
            w["successful_runs"] += 1
        elif r.status == StepStatus.ERROR:
            w["failed_runs"] += 1
        if w["last_run"] is None or r.started_at > w["last_run"]:
            w["last_run"] = r.started_at
    return list(by_id.values())
