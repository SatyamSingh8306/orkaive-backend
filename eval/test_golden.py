"""Golden cases for the orchestrator's *structural* behavior.

These tests don't hit an LLM. They pin down the parts of the
routing + classification logic that matter for the user-facing
surface: skip paths, deterministic fallbacks, validation
(LLM says an agent that's not connected), multi-agent expansion,
and the versioned-preamble contract.

Each test maps to a "golden case" the orchestrator is expected to
handle — if any of these regress, the user-visible behavior of the
chat surface changes.

Run:
    pytest eval/test_golden.py -v
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock

import pytest

# Allow `pytest eval/` from repo root.
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from app.config.settings import Settings, reset_settings_cache
from app.orchestrator.router import (
    ROUTER_PROMPT_NAME,
    QueryRouter,
    _SYSTEM_PREAMBLE_FALLBACK,
    make_router,
)
from app.schemas.state import QueryClassification
from app.schemas.workflow import ProjectedAgent


# ---------------------------------------------------------------- setup -----

def _settings() -> Settings:
    return Settings(
        secret_key="x" * 32,
        # Bypass the router LLM builder for these tests — we only
        # exercise the deterministic skip / fallback paths, but
        # `build_router_llm` would still try to instantiate Groq.
        llm_provider="ollama",
        llm_provider_router="ollama",
    )


@pytest.fixture(autouse=True)
def _clean_settings():
    reset_settings_cache()
    yield
    reset_settings_cache()


def _agent(agent_id: str, label: str | None = None, role: str | None = None,
           capabilities: list[str] | None = None) -> ProjectedAgent:
    return ProjectedAgent(
        id=agent_id,
        label=label or agent_id,
        role=role or agent_id,
        capabilities=capabilities or [role or agent_id],
    )


def _router_with_stub_llm(agents: list[ProjectedAgent]) -> QueryRouter:
    """Build a router whose LLM is a MagicMock — these tests must
    not hit a real provider. `classify` will only reach the LLM on
    the multi-agent path; the skip / fallback paths don't touch it.
    """
    r = QueryRouter(connected_agents=agents, settings=_settings())
    r.llm = MagicMock()
    return r


# ---------------------------------------------------- golden case 1-3: skip

def test_golden_01_zero_agents_returns_sentinel():
    """Workflow with no connected agents → router returns a
    deterministic sentinel; LLM is never called."""
    r = _router_with_stub_llm([])
    out = asyncio.run(r.classify("anything"))
    assert isinstance(out, QueryClassification)
    assert out.confidence == 1.0
    assert out.agent_type == "agent"
    assert "no connected agents" in out.reasoning
    r.llm.with_structured_output.assert_not_called()


def test_golden_02_single_agent_skips_llm():
    """Workflow with one agent → no LLM call, deterministic choice."""
    r = _router_with_stub_llm([_agent("supply_chain")])
    out = asyncio.run(r.classify("track shipment 12345"))
    assert out.agent_type == "supply_chain"
    assert out.confidence == 1.0
    assert "single connected agent" in out.reasoning
    r.llm.with_structured_output.assert_not_called()


def test_golden_03_single_agent_does_not_require_secondary():
    """Even if the user prompt *implies* multi-agent work, the skip
    path must not invent `secondary_agents` (only the LLM may)."""
    r = _router_with_stub_llm([_agent("process")])
    out = asyncio.run(r.classify("coordinate between supply and sales"))
    assert out.requires_multiple_agents is False
    assert out.secondary_agents == []


# ------------------------------------------- golden case 4-5: validation

def test_golden_04_invalid_agent_id_is_corrected(monkeypatch):
    """When the LLM returns an `agent_type` that's not in the
    workflow's connected set, the router must coerce it to a valid
    one and mark the reasoning with `(fallback->...)`."""
    r = _router_with_stub_llm([
        _agent("compliance"),
        _agent("supply_chain"),
    ])
    # LLM hallucinates an agent id that doesn't exist.
    bad = QueryClassification(
        agent_type="nonexistent_agent",
        confidence=0.9,
        reasoning="model picked it",
    )
    # The structured chain would normally be invoked, but we shortcut.
    fixed = r._validate(bad)
    assert fixed.agent_type in {"compliance", "supply_chain"}
    assert "(fallback->" in (fixed.reasoning or "")


def test_golden_05_validation_preserves_valid_choice(monkeypatch):
    """When the LLM picks a valid agent, validation is a no-op."""
    r = _router_with_stub_llm([_agent("supply_chain"), _agent("process")])
    good = QueryClassification(
        agent_type="process",
        confidence=0.7,
        reasoning="picked process",
    )
    fixed = r._validate(good)
    assert fixed.agent_type == "process"
    assert fixed.reasoning == "picked process"


# ----------------------------------- golden case 6-7: hard fallback path

def test_golden_06_fallback_when_llm_raises():
    """Both structured and parser chains raise → the router
    returns a 0-confidence `router_fallback:...` result and points
    at the first connected agent (or the sentinel `agent` id)."""
    r = _router_with_stub_llm([_agent("supply_chain"), _agent("process")])
    # Make every chain raise.
    r.llm.with_structured_output.return_value.ainvoke = \
        _async_raise(RuntimeError("boom"))
    r.llm.ainvoke = _async_raise(RuntimeError("boom"))
    out = asyncio.run(r.classify("a query"))
    assert out.agent_type == "supply_chain"  # first connected agent
    assert out.confidence == 0.0
    assert out.reasoning.startswith("router_fallback:")


def test_golden_07_fallback_with_no_connected_agents():
    """Fallback with zero agents → `agent_type="agent"`, confidence 0."""
    r = _router_with_stub_llm([])
    out = r._fallback(reason="test")
    assert out.agent_type == "agent"
    assert out.confidence == 0.0
    assert "test" in out.reasoning


# -------------------------------------------- golden case 8: multi-agent

def test_golden_08_multi_agent_synthesis_keeps_secondary_list():
    """When `requires_multiple_agents=True` is returned by the LLM,
    the `secondary_agents` list survives through `_validate` (the
    validator only corrects `agent_type`, not the list)."""
    r = _router_with_stub_llm([
        _agent("supply_chain"),
        _agent("process"),
        _agent("compliance"),
    ])
    multi = QueryClassification(
        agent_type="supply_chain",
        confidence=0.8,
        reasoning="primary supply, secondary compliance",
        requires_multiple_agents=True,
        secondary_agents=["compliance"],
    )
    fixed = r._validate(multi)
    assert fixed.agent_type == "supply_chain"
    assert fixed.requires_multiple_agents is True
    assert fixed.secondary_agents == ["compliance"]


# ----------------------------- golden case 9-10: versioned preamble -----

def test_golden_09_router_prompt_name_is_stable():
    """The prompt registry key is part of the public contract —
    renaming it would orphan all previously-versioned prompts."""
    assert ROUTER_PROMPT_NAME == "query_router"


def test_golden_10_set_preamble_actually_swaps_prompt():
    """`set_preamble` must rebuild the prompt and chains; a no-op
    when the preamble is unchanged."""
    agents = [_agent("supply_chain"), _agent("process")]
    r = _router_with_stub_llm(agents)
    original_prompt_id = id(r._prompt)
    r.set_preamble("CUSTOM PREAMBLE")
    assert r.preamble == "CUSTOM PREAMBLE"
    assert id(r._prompt) != original_prompt_id
    # Idempotent: setting the same preamble does NOT rebuild.
    stable_prompt_id = id(r._prompt)
    r.set_preamble("CUSTOM PREAMBLE")
    assert id(r._prompt) == stable_prompt_id


# ------------------------- golden case 11: factory wiring -----------------

def test_golden_11_make_router_uses_passed_preamble():
    """`make_router` is the orchestrator's entry point — it must
    propagate the registry-fetched preamble into the router."""
    agents = [_agent("a"), _agent("b")]
    r = make_router(agents, settings=_settings(), preamble="PREG")
    assert r.preamble == "PREG"


# --------------- golden case 12: prompt building contract ----------------

def test_golden_12_prompt_lists_every_connected_agent():
    """The router prompt must surface every connected agent's
    id+label+role. An agent missing from the prompt is invisible
    to the LLM and can never be picked — regression-protection."""
    r = _router_with_stub_llm([
        _agent("compliance", label="Compliance", role="auditor"),
        _agent("supply_chain", label="Supply", role="logistics"),
    ])
    r.set_preamble(_SYSTEM_PREAMBLE_FALLBACK)
    prompt_text = r._prompt.format(query="placeholder")
    assert "id=compliance" in prompt_text
    assert "id=supply_chain" in prompt_text
    assert "label=Compliance" in prompt_text
    assert "role=logistics" in prompt_text


# ------------------------- golden case 13: edge cases --------------------

def test_golden_13_update_connected_agents_rebuilds():
    """`update_connected_agents` must rebuild the prompt and
    chains so a live-swap of the agent set is observed."""
    r = _router_with_stub_llm([_agent("a"), _agent("b")])
    old_prompt_id = id(r._prompt)
    r.update_connected_agents([_agent("c"), _agent("d")])
    assert id(r._prompt) != old_prompt_id
    assert {a.id for a in r.connected_agents} == {"c", "d"}


def test_golden_14_classification_schema_rejects_bad_confidence():
    """Sanity check: the `confidence` field is bounded 0..1 and
    rejects out-of-range values — this is the schema the LLM has
    to produce, so a regression here would silently break routing."""
    with pytest.raises(Exception):
        QueryClassification(agent_type="x", confidence=1.5)
    with pytest.raises(Exception):
        QueryClassification(agent_type="x", confidence=-0.1)


# --------------- helper -----------------------------------------------------

def _async_raise(exc):
    async def _raise(*a, **kw):
        raise exc
    return _raise
