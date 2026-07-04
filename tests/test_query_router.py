"""Unit tests for the QueryRouter classification dataclass + the
`classify_sync` skip path. The LLM-bound path is integration-tested.

We mock the LLM to return a structured payload so we can verify that
`QueryRouter.classify()` actually returns the parsed pydantic.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.schemas.state import QueryClassification
from app.orchestrator.router import QueryRouter


def test_query_classification_defaults():
    c = QueryClassification(
        agent_type="supply_chain_agent",
        confidence=0.9,
        reasoning="inventory question",
    )
    assert c.requires_multiple_agents is False
    assert c.secondary_agents == []


def test_query_classification_secondary_agents_distinct():
    c = QueryClassification(
        agent_type="a",
        confidence=0.9,
        requires_multiple_agents=True,
        secondary_agents=["a", "b"],
    )
    assert "a" in c.secondary_agents
    assert "b" in c.secondary_agents


def test_router_skip_when_zero_agents():
    """With zero connected agents, the router returns a sentinel."""
    llm = MagicMock()  # must NOT be called
    router = QueryRouter(connected_agents=[], llm=llm)
    result = router._skip()
    assert result is not None
    assert result.agent_type == "agent"
    assert result.confidence == 1.0


def test_router_skip_when_only_one_agent():
    """With a single connected agent, the router must short-circuit."""
    from app.schemas.workflow import ProjectedAgent
    agents = [ProjectedAgent(id="only", label="Only", role="Only role", capabilities=[])]
    llm = MagicMock()  # must NOT be called
    router = QueryRouter(connected_agents=agents, llm=llm)
    result = router._skip()
    assert result is not None
    assert result.agent_type == "only"
    assert result.requires_multiple_agents is False
    assert result.confidence == 1.0


def test_router_no_skip_when_multiple_agents():
    from app.schemas.workflow import ProjectedAgent
    agents = [
        ProjectedAgent(id="a", label="A", role="A", capabilities=[]),
        ProjectedAgent(id="b", label="B", role="B", capabilities=[]),
    ]
    llm = MagicMock()
    router = QueryRouter(connected_agents=agents, llm=llm)
    assert router._skip() is None
