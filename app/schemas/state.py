"""LangGraph AgentState (Pydantic v2)."""

from __future__ import annotations

from typing import Annotated, Any, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field


def _keep_last_str(a: Optional[str], b: Optional[str]) -> Optional[str]:
    return b if b is not None else a


class AgentState(BaseModel):
    """Main state that flows through the LangGraph."""

    model_config = ConfigDict(
        extra="ignore",
        arbitrary_types_allowed=True,
        populate_by_name=True,
    )

    messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)
    current_agent: Annotated[Optional[str], _keep_last_str] = None
    next_agent: Optional[str] = None
    user_query: str = ""
    query_type: Optional[str] = None
    context: dict[str, Any] = Field(default_factory=dict)
    results: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    iteration_count: int = 0
    max_iterations: int = 10
    is_complete: bool = False
    workflow_id: Optional[str] = None
    workflow_data: Optional[dict[str, Any]] = None
    node_id: Optional[str] = None
    node_data: Optional[dict[str, Any]] = None


class QueryClassification(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent_type: str
    confidence: float = Field(..., ge=0, le=1)
    reasoning: str = ""
    requires_multiple_agents: bool = False
    secondary_agents: list[str] = Field(default_factory=list)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
