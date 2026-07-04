"""Tool CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.core.logging import get_logger
from app.schemas.tool import ToolConfig
from app.services import (
    create_tool,
    delete_for_node,
    delete_tool,
    get_tool,
    list_for_node,
    list_for_workflow,
    update_tool,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/tools", tags=["tools"])


@router.post("", response_model=ToolConfig, status_code=201)
async def create(payload: ToolConfig) -> ToolConfig:
    return await create_tool(payload)


@router.get("", response_model=list[ToolConfig])
async def list_(
    workflow_id: str = Query(..., min_length=1),
    node_id: str | None = Query(None),
) -> list[ToolConfig]:
    if node_id:
        return await list_for_node(workflow_id, node_id)
    return await list_for_workflow(workflow_id)


@router.get("/{tool_id}", response_model=ToolConfig)
async def read(tool_id: str) -> ToolConfig:
    try:
        return await get_tool(tool_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/{tool_id}", response_model=ToolConfig)
async def update(tool_id: str, payload: ToolConfig) -> ToolConfig:
    try:
        return await update_tool(tool_id, payload)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/{tool_id}", status_code=204)
async def delete(tool_id: str) -> None:
    try:
        await delete_tool(tool_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/by-node", status_code=200)
async def delete_by_node(workflow_id: str = Query(...), node_id: str = Query(...)) -> dict[str, int]:
    """Bulk-delete all tools for a node. Returns the count."""
    count = await delete_for_node(workflow_id, node_id)
    return {"deleted": count}
