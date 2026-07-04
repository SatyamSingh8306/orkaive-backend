"""Conflict resolution schemas (Pydantic v2)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ConflictStatus(str, Enum):
    PENDING = "pending"
    ANSWERED = "answered"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ConflictContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    input: str = ""
    agent_output: str = Field(default="", alias="agentOutput")
    conflict_reason: str = Field(default="", alias="conflictReason")


class ConflictDoc(BaseModel):
    """Conflict document stored in MongoDB `conflicts` collection."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    query_id: str = Field(..., alias="queryId")
    workflow_id: str = Field(..., alias="workflowId")
    run_id: str = Field(..., alias="runId")
    node_id: str = Field(..., alias="nodeId")
    node_label: str = Field("", alias="nodeLabel")
    owner_email: EmailStr = Field(..., alias="ownerEmail")
    query: str
    context: ConflictContext = Field(default_factory=ConflictContext)
    status: ConflictStatus = ConflictStatus.PENDING
    response: Optional[str] = None
    responded_at: Optional[datetime] = Field(default=None, alias="respondedAt")
    raised_at: datetime = Field(default_factory=lambda: datetime.utcnow(), alias="raisedAt")
    timeout_at: datetime = Field(..., alias="timeoutAt")
    timeout_seconds: int = Field(300, alias="timeoutSeconds")


class RaiseConflictRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    workflow_id: str = Field(..., alias="workflowId")
    run_id: str = Field(..., alias="runId")
    node_id: str = Field(..., alias="nodeId")
    node_label: str = Field(..., alias="nodeLabel")
    owner_email: EmailStr = Field(..., alias="ownerEmail")
    query: str
    context: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(300, ge=5, le=3600, alias="timeoutSeconds")


class RaiseConflictResponse(BaseModel):
    query_id: str = Field(..., alias="queryId")
    status: ConflictStatus
    timeout_at: datetime = Field(..., alias="timeoutAt")


class ConflictStatusResponse(BaseModel):
    query_id: str = Field(..., alias="queryId")
    status: ConflictStatus
    query: str
    response: Optional[str] = None
    responded_at: Optional[datetime] = Field(default=None, alias="respondedAt")
    timeout_at: datetime = Field(..., alias="timeoutAt")


class RespondConflictRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    query_id: str = Field(..., alias="queryId")
    response: str


class ConflictListItem(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    query_id: str
    workflow_id: str
    node_id: str
    node_label: str
    owner_email: EmailStr
    query: str
    status: ConflictStatus
    raised_at: datetime
    responded_at: Optional[datetime] = None


# Legacy alias used by older code paths.
LLMResponse = type("LLMResponse", (), {})
