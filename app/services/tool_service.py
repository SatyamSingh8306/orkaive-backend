"""Tool service — single owner of the `tools` collection.

Provides:
  - CRUD on `ToolConfig`
  - `whitelist_for_llm()` projection for safe tool descriptions
  - `attach_to_node()` / `list_for_node()` for the orchestrator
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from pymongo import ReturnDocument

from app.core.exceptions import ToolNotFoundError
from app.core.logging import get_logger
from app.db.mongodb import get_database
from app.schemas.tool import ToolConfig
from app.tools.http_executor import project_for_llm

logger = get_logger(__name__)


def _to_object_id(tool_id: str) -> ObjectId:
    try:
        return ObjectId(tool_id)
    except Exception as e:
        raise ToolNotFoundError(f"Invalid tool id: {tool_id!r}") from e


def _doc_to_model(doc: dict[str, Any]) -> ToolConfig:
    doc = dict(doc)
    if "_id" in doc:
        doc["id"] = str(doc.pop("_id"))
    return ToolConfig.model_validate(doc)


async def get(tool_id: str) -> ToolConfig:
    db = get_database()
    oid = _to_object_id(tool_id)
    doc = await db.tools.find_one({"_id": oid})
    if not doc:
        raise ToolNotFoundError(tool_id)
    return _doc_to_model(doc)


async def list_for_node(workflow_id: str, node_id: str) -> list[ToolConfig]:
    db = get_database()
    cursor = db.tools.find({"workflowId": workflow_id, "nodeId": node_id})
    return [_doc_to_model(d) async for d in cursor]


async def list_for_workflow(workflow_id: str) -> list[ToolConfig]:
    db = get_database()
    cursor = db.tools.find({"workflowId": workflow_id})
    return [_doc_to_model(d) async for d in cursor]


async def create(payload: ToolConfig) -> ToolConfig:
    db = get_database()
    now = datetime.now(timezone.utc)
    doc = payload.model_dump(by_alias=True, exclude={"id"})
    doc["createdAt"] = now
    doc["updatedAt"] = now
    result = await db.tools.insert_one(doc)
    return await get(str(result.inserted_id))


async def update(tool_id: str, payload: ToolConfig) -> ToolConfig:
    db = get_database()
    oid = _to_object_id(tool_id)
    doc = payload.model_dump(by_alias=True, exclude={"id", "createdAt", "workflowId", "nodeId"})
    doc["updatedAt"] = datetime.now(timezone.utc)
    updated = await db.tools.find_one_and_update(
        {"_id": oid},
        {"$set": doc},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise ToolNotFoundError(tool_id)
    return _doc_to_model(updated)


async def delete(tool_id: str) -> None:
    db = get_database()
    oid = _to_object_id(tool_id)
    result = await db.tools.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise ToolNotFoundError(tool_id)


async def delete_for_node(workflow_id: str, node_id: str) -> int:
    """Bulk-delete all tools attached to a node. Returns the count."""
    db = get_database()
    result = await db.tools.delete_many({"workflowId": workflow_id, "nodeId": node_id})
    return int(result.deleted_count)


# ---- LLM projection ---------------------------------------------------------

def whitelist_for_llm(tool: ToolConfig) -> dict[str, Any]:
    """Build a sanitized view of the tool for the LLM.

    Strips: url, body, query_params, headers (none on the model anyway),
    timeout, auth_secret_ref, ids, timestamps. Keeps: name, summary,
    method, schema.
    """
    projection = project_for_llm(tool)
    return projection.model_dump()


def build_langchain_tool(
    tool: ToolConfig,
    resolved_secret_headers: Optional[dict[str, str]] = None,
):
    """Build the LangChain `StructuredTool` for a stored tool.

    Header merge order (later wins):
      1. resolved_secret_headers — from SecretService (authSecretRef)
      2. tool.headers             — direct config stored in Mongo

    Direct headers override secret defaults so users can tweak per-tool.
    """
    from app.tools.langchain_converter import LangChainToolFactory

    merged_headers = {**(resolved_secret_headers or {}), **(tool.headers or {})}
    return LangChainToolFactory.from_tool_config(
        tool, resolved_headers=merged_headers
    )
