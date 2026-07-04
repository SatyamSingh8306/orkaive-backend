"""Workflow service — single owner of the `workflows` collection.

All reads and writes go through this module. Pydantic validation on every
boundary, no `Dict[str, Any]` leaking out.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from pymongo import ReturnDocument

from app.core.exceptions import WorkflowNotFoundError, WorkflowValidationError
from app.core.logging import get_logger
from app.db.mongodb import get_database
from app.schemas.workflow import Workflow, WorkflowNode

logger = get_logger(__name__)


def _to_object_id(workflow_id: str) -> ObjectId:
    try:
        return ObjectId(workflow_id)
    except Exception as e:
        raise WorkflowNotFoundError(f"Invalid workflow id: {workflow_id!r}") from e


def _doc_to_model(doc: dict[str, Any]) -> Workflow:
    """Convert a Mongo document to a `Workflow` model.

    Missing fields fall back to defaults; the model is the contract.
    """
    doc = dict(doc)
    if "_id" in doc:
        doc["id"] = str(doc.pop("_id"))
    return Workflow.model_validate(doc)


async def get(workflow_id: str) -> Workflow:
    db = get_database()
    oid = _to_object_id(workflow_id)
    doc = await db.workflows.find_one({"_id": oid})
    if not doc:
        raise WorkflowNotFoundError(workflow_id)
    return _doc_to_model(doc)


async def list_all(*, skip: int = 0, limit: int = 100) -> list[Workflow]:
    db = get_database()
    cursor = db.workflows.find().sort("updatedAt", -1).skip(skip).limit(limit)
    return [_doc_to_model(d) async for d in cursor]


async def create(payload: Workflow, *, created_by: Optional[str] = None) -> Workflow:
    db = get_database()
    _validate(payload)
    now = datetime.now(timezone.utc)
    doc = payload.model_dump(by_alias=True, exclude={"id"})
    doc["createdBy"] = created_by
    doc["createdAt"] = now
    doc["updatedAt"] = now
    result = await db.workflows.insert_one(doc)
    return await get(str(result.inserted_id))


async def update(workflow_id: str, payload: Workflow) -> Workflow:
    db = get_database()
    _validate(payload)
    oid = _to_object_id(workflow_id)
    doc = payload.model_dump(by_alias=True, exclude={"id", "createdAt", "createdBy"})
    doc["updatedAt"] = datetime.now(timezone.utc)
    updated = await db.workflows.find_one_and_update(
        {"_id": oid},
        {"$set": doc},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise WorkflowNotFoundError(workflow_id)
    return _doc_to_model(updated)


async def delete(workflow_id: str) -> None:
    db = get_database()
    oid = _to_object_id(workflow_id)
    result = await db.workflows.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise WorkflowNotFoundError(workflow_id)


# ---- helpers ----------------------------------------------------------------

def _validate(workflow: Workflow) -> None:
    """Light graph-level validation.

    We intentionally do NOT require router/synthesizer here — those
    structural nodes are added by the orchestrator at graph build time
    if missing. The frontend's "Save" action can store a workflow with
    just agent nodes, and the orchestrator wraps it.

    We DO check that edge endpoints reference real node ids.
    """
    # if not workflow.nodes:
    #     raise WorkflowValidationError("workflow must include at least one node")
    ids = {n.id for n in workflow.nodes}
    for edge in workflow.edges:
        if edge.source not in ids:
            raise WorkflowValidationError(f"edge source {edge.source!r} is not a node id")
        if edge.target not in ids:
            raise WorkflowValidationError(f"edge target {edge.target!r} is not a node id")


def find_agent_nodes(workflow: Workflow) -> list[WorkflowNode]:
    """Return nodes that should be backed by a real agent.

    Excludes the structural nodes (router, synthesizer) and the synthetic
    start/end markers. The orchestrator uses this to know which nodes need
    a LangChain agent instance.
    """
    structural = {"router", "synthesizer", "__start__", "__end__"}
    return [n for n in workflow.nodes if n.id not in structural]
