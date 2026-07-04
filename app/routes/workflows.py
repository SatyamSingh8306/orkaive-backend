"""Workflow CRUD routes.

Thin FastAPI handlers on top of `app.services.workflow_service`. Every
write is Pydantic-validated; every read returns a `Workflow` model.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.logging import get_logger
from app.schemas.workflow import Workflow
from app.services import (
    create_workflow,
    delete_workflow,
    get_workflow,
    list_workflows,
    update_workflow,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("", response_model=Workflow, status_code=201, response_model_by_alias=True)
async def create(payload: Workflow, created_by: Optional[str] = Query(None)) -> Workflow:
    return await create_workflow(payload, created_by=created_by)


@router.get("", response_model=list[Workflow], response_model_by_alias=True)
async def list_(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[Workflow]:
    return await list_workflows(skip=skip, limit=limit)


@router.get("/{workflow_id}", response_model=Workflow, response_model_by_alias=True)
async def read(workflow_id: str) -> Workflow:
    try:
        return await get_workflow(workflow_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/{workflow_id}", response_model=Workflow, response_model_by_alias=True)
async def update(workflow_id: str, payload: Workflow) -> Workflow:
    try:
        return await update_workflow(workflow_id, payload)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/{workflow_id}", status_code=204)
async def delete(workflow_id: str) -> None:
    try:
        await delete_workflow(workflow_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
