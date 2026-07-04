"""Workflow and node schemas (Pydantic v2)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

NodeType = Literal[
    "trigger", "router", "service", "merge", "result", "human",
    # Legacy / sentinel values stored by previous versions. Kept valid so
    # old Mongo documents can still be read. The orchestrator ignores any
    # type it doesn't recognize.
    "function", "agent", "tool", "other",
]
NodeKind = NodeType  # alias for clarity at call sites

UTC = timezone.utc


def _id_safe(v: str) -> str:
    if not re.match(r"^[A-Za-z0-9_./\-]+$", v):
        raise ValueError("must contain only letters, digits, '.', '_', '-', '/'")
    return v


class WorkflowNode(BaseModel):
    """A single node in a workflow graph."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(..., min_length=1, max_length=128)
    type: NodeType
    label: str = ""
    role: str = ""
    description: str = ""
    system_prompt: str = Field(default="", alias="systemPrompt")
    goals_and_actions: str = Field(default="", alias="goalsAndActions")
    capabilities: list[str] = Field(default_factory=list)
    owner_email: Optional[str] = Field(default=None, alias="ownerEmail")
    # Canvas position + visual metadata. These used to be dropped on
    # round-trip (the backend had no field for them, and `extra="ignore"`
    # silently stripped them on save). The agent-maker needs them back
    # so a workflow reload doesn't dump every node on top of (0,0).
    x: float = 0
    y: float = 0
    icon: Optional[str] = None
    accent_color: Optional[str] = Field(default=None, alias="accentColor")
    # `kind` is a frontend-only visual discriminator (router, human,
    # …) — the orchestrator already falls back to `type` so this is
    # safe to ignore server-side, but we persist it so the UI round-
    # trips cleanly.
    kind: Optional[str] = None
    position: dict[str, float] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id_must_be_safe(cls, v: str) -> str:
        return _id_safe(v)



class WorkflowEdge(BaseModel):
    """A directed edge between two nodes."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = ""
    source: str = Field(..., alias="from")
    target: str = Field(..., alias="to")
    label: str = ""
    condition: str = ""

    @field_validator("source", "target")
    @classmethod
    def _no_whitespace(cls, v: str) -> str:
        return _id_safe(v)


class Workflow(BaseModel):
    """Top-level workflow document stored in MongoDB."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    status: Literal["draft", "active", "paused", "archived"] = "active"
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)
    created_by: Optional[str] = Field(default=None, alias="createdBy")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(UTC)


class ProjectedAgent(BaseModel):
    """The minimal agent view used by the router.

    The router only needs id, label, role, and short capabilities — it does
    NOT need the full system_prompt or goals_and_actions, which can run to
    thousands of characters and bloat the routing prompt.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    label: str
    role: str
    capabilities: list[str] = Field(default_factory=list)

    @classmethod
    def from_node(cls, node: WorkflowNode) -> "ProjectedAgent":
        # Cap each capability string to 200 chars to bound the prompt
        caps = [c[:200] for c in node.capabilities if c]
        if not caps and node.description:
            caps = [node.description[:200]]
        return cls(
            id=node.id,
            label=node.label or node.id,
            role=node.role or node.type,
            capabilities=caps,
        )
