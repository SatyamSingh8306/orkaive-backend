"""Trace + workflow run schemas (Pydantic v2)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class StepType(str, Enum):
    WORKFLOW = "workflow"
    AGENT = "agent"
    TOOL = "tool"
    CHAIN = "chain"
    ROUTER = "router"
    SYNTHESIZER = "synthesizer"


class StepStatus(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    workflow_id: str
    step_id: str = Field(default_factory=lambda: str(uuid4()))
    parent_step_id: Optional[str] = None
    step_type: StepType
    name: str
    status: StepStatus
    input: Optional[Any] = None
    output: Optional[Any] = None
    error: Optional[str] = None
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    token_usage: Optional[dict[str, int]] = None


class WorkflowRun(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    workflow_id: str
    workflow_name: str
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None
    status: StepStatus = StepStatus.STARTED
    input: Optional[Any] = None
    output: Optional[Any] = None
    error: Optional[str] = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    total_steps: int = 0
    completed_steps: int = 0
    error_steps: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class DashboardRunSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str
    workflow_id: str
    workflow_name: str
    status: StepStatus
    started_at: datetime
    duration_ms: Optional[float] = None
    total_steps: int
    completed_steps: int
    error_steps: int
    has_error: bool = False


class DashboardStepDetail(BaseModel):
    model_config = ConfigDict(extra="ignore")

    step_id: str
    parent_step_id: Optional[str] = None
    step_type: StepType
    name: str
    status: StepStatus
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    input_preview: Optional[str] = None
    output_preview: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    error: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    children: list["DashboardStepDetail"] = Field(default_factory=list)


DashboardStepDetail.model_rebuild()


class TraceFilter(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workflow_id: Optional[str] = None
    user_id: Optional[str] = None
    status: Optional[StepStatus] = None
    step_type: Optional[StepType] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)
