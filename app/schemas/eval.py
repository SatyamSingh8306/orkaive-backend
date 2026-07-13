"""Evaluation schemas (Pydantic v2).

An `EvalRun` scores a workflow's multi-agent system against a set of
manually-supplied test cases. Each case is executed through the
orchestrator, then judged by an LLM (1..5 per criterion) and combined
with deterministic run metrics (latency, agents used, success/error).

The run doc (with embedded cases + results) lives in the `eval_runs`
Mongo collection, owned by `app/services/eval_service.py`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

UTC = timezone.utc

# The four quality criteria the LLM judge scores (1..5 each).
CRITERIA = ("relevance", "correctness", "completeness", "coherence")


class EvalCase(BaseModel):
    """One test case: a query and an optional expected answer."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    query: str = Field(..., min_length=1, max_length=20_000)
    expected_answer: Optional[str] = Field(
        default=None, alias="expectedAnswer", max_length=20_000
    )


class EvalCriterionScore(BaseModel):
    """Per-case result: the workflow output plus its judged scores."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    query: str
    expected_answer: Optional[str] = Field(default=None, alias="expectedAnswer")
    response: str = ""
    agent_outputs: dict[str, Any] = Field(default_factory=dict, alias="agentOutputs")
    agents_used: list[str] = Field(default_factory=list, alias="agentsUsed")
    duration_ms: float = Field(default=0.0, alias="durationMs")
    success: bool = True
    error: Optional[str] = None
    # criterion -> score (1..5); empty when the judge failed / case errored.
    scores: dict[str, float] = Field(default_factory=dict)
    overall_score: float = Field(default=0.0, alias="overallScore")
    rationale: str = ""


class EvalMetrics(BaseModel):
    """Aggregate scorecard across all cases in a run."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    total_cases: int = Field(default=0, alias="totalCases")
    evaluated: int = 0
    errors: int = 0
    success_rate: float = Field(default=0.0, alias="successRate")  # 0..1
    avg_duration_ms: float = Field(default=0.0, alias="avgDurationMs")
    avg_overall_score: float = Field(default=0.0, alias="avgOverallScore")  # 1..5
    criteria_averages: dict[str, float] = Field(
        default_factory=dict, alias="criteriaAverages"
    )
    overall_score: float = Field(default=0.0, alias="overallScore")  # 1..5 composite


class EvalRun(BaseModel):
    """A single evaluation run over one workflow."""

    model_config = ConfigDict(
        extra="ignore", populate_by_name=True, arbitrary_types_allowed=True
    )

    id: Optional[str] = Field(default=None, alias="_id")
    workflow_id: str = Field(..., alias="workflowId")
    workflow_name: str = Field(default="", alias="workflowName")
    status: Literal["running", "completed", "failed"] = "running"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="createdAt")
    started_at: Optional[datetime] = Field(default=None, alias="startedAt")
    finished_at: Optional[datetime] = Field(default=None, alias="finishedAt")
    cases: list[EvalCase] = Field(default_factory=list)
    results: list[EvalCriterionScore] = Field(default_factory=list)
    metrics: Optional[EvalMetrics] = None
    error: Optional[str] = None

    def public_dict(self) -> dict[str, Any]:
        d = self.model_dump(by_alias=True, exclude_none=True)
        if "_id" in d and d["_id"] is not None:
            d["_id"] = str(d["_id"])
        for k in ("createdAt", "startedAt", "finishedAt"):
            if k in d and d[k] is not None and hasattr(d[k], "isoformat"):
                d[k] = d[k].isoformat()
        return d


class RunEvalRequest(BaseModel):
    """Body of `POST /api/evaluations/{workflow_id}/runs`."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    # Either supply cases, or set `auto_generate` to have the backend
    # synthesize realistic test cases from the workflow's agents.
    cases: list[EvalCase] = Field(default_factory=list, max_length=100)
    auto_generate: bool = Field(
        default=False,
        description=(
            "If true (or if `cases` is empty), the backend generates test "
            "cases from the workflow definition before running."
        ),
    )
    num_cases: int = Field(
        default=5, ge=1, le=20,
        description="How many cases to synthesize when auto_generate is on.",
    )
