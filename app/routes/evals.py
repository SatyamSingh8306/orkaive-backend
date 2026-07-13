"""Evaluation routes.

Mounted at `/api/evaluations`. An eval run scores a workflow's multi-agent
system against manually-supplied test cases (LLM-judge quality + run
metrics). The run executes in the background; the client polls the run
detail endpoint until `status != "running"`.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.routes.auth import get_current_user
from app.schemas.eval import RunEvalRequest
from app.services.eval_generator import generate_cases
from app.schemas.user import UserResponse
from app.services.eval_service import get_eval_service

logger = get_logger(__name__)
router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.post("/{workflow_id}/generate", response_model=dict)
async def generate_eval_cases(
    workflow_id: str,
    body: RunEvalRequest,
    current: UserResponse = Depends(get_current_user),
) -> dict:
    """Preview: synthesize test cases for a workflow without running them.
    Returns `{cases: [...]}` so the UI can show/edit before evaluating."""
    try:
        cases = await generate_cases(workflow_id, num_cases=body.num_cases or 5)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"cases": [c.model_dump(by_alias=True) for c in cases]}


@router.post("/{workflow_id}/runs", status_code=201, response_model=dict)
async def create_eval_run(
    workflow_id: str,
    body: RunEvalRequest,
    background_tasks: BackgroundTasks,
    current: UserResponse = Depends(get_current_user),
) -> dict:
    """Start an eval run.

    Cases come from `body.cases` if supplied; otherwise (or when
    `auto_generate` is set) the backend synthesizes them from the workflow
    definition first. Returns the run doc (status `running`); scoring runs
    in the background.
    """
    svc = get_eval_service()
    # Auto-generate when requested or when no cases were provided.
    if body.auto_generate or not body.cases:
        try:
            cases = await generate_cases(
                workflow_id, num_cases=body.num_cases or 5
            )
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
    else:
        cases = body.cases

    try:
        run = await svc.create_run(workflow_id=workflow_id, cases=cases)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    background_tasks.add_task(
        svc.run_eval,
        workflow_id=workflow_id,
        run_id=run.id or "",
        cases=cases,
    )
    return run.public_dict()


@router.get("/{workflow_id}/runs", response_model=dict)
async def list_eval_runs(
    workflow_id: str,
    limit: int = Query(50, ge=1, le=200),
    current: UserResponse = Depends(get_current_user),
) -> dict:
    svc = get_eval_service()
    runs = await svc.list_runs(workflow_id=workflow_id, limit=limit)
    return {"runs": [r.public_dict() for r in runs], "total": len(runs)}


@router.get("/{workflow_id}/latest", response_model=dict)
async def latest_eval_run(
    workflow_id: str,
    current: UserResponse = Depends(get_current_user),
) -> dict:
    """Latest completed run's metrics — convenience for landing cards.
    Returns `{run: null}` when the workflow has no completed run yet."""
    svc = get_eval_service()
    run = await svc.latest_run(workflow_id=workflow_id)
    return {"run": run.public_dict() if run else None}


@router.get("/{workflow_id}/runs/{run_id}", response_model=dict)
async def get_eval_run(
    workflow_id: str,
    run_id: str,
    current: UserResponse = Depends(get_current_user),
) -> dict:
    svc = get_eval_service()
    try:
        run = await svc.get_run(run_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return run.public_dict()


@router.delete("/{workflow_id}/runs/{run_id}", response_model=dict)
async def delete_eval_run(
    workflow_id: str,
    run_id: str,
    current: UserResponse = Depends(get_current_user),
) -> dict:
    svc = get_eval_service()
    try:
        await svc.delete_run(run_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"ok": True}
