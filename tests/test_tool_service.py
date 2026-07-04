"""Unit tests for `app.services.tool_service.build_langchain_tool`.

Verifies the header merge order: secret_headers first, then tool.headers
(direct overrides secret). This is the contract the orchestrator depends
on.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.schemas.tool import ToolConfig
from app.services.tool_service import build_langchain_tool


def _tool(**overrides) -> ToolConfig:
    base = dict(
        workflowId="wf-1",
        nodeId="node-1",
        name="my_tool",
        url="https://api.example.com/v1",
    )
    base.update(overrides)
    return ToolConfig.model_validate(base)


def test_merges_secret_then_direct():
    """Direct headers win over secret headers on key collision."""
    tool = _tool(headers={"Authorization": "Bearer direct", "X-Tenant": "t1"})
    captured: dict = {}

    def _from_tool_config(t, resolved_headers=None):
        captured["headers"] = dict(resolved_headers or {})
        return "fake-tool"

    with patch(
        "app.tools.langchain_converter.LangChainToolFactory.from_tool_config",
        side_effect=_from_tool_config,
    ):
        result = build_langchain_tool(
            tool,
            resolved_secret_headers={"Authorization": "Bearer from-secret", "X-Other": "o"},
        )
    assert result == "fake-tool"
    # direct 'Authorization' overrode secret 'Authorization'
    assert captured["headers"]["Authorization"] == "Bearer direct"
    # X-Tenant came from direct; X-Other came from secret
    assert captured["headers"]["X-Tenant"] == "t1"
    assert captured["headers"]["X-Other"] == "o"


def test_no_secret_headers_uses_direct_only():
    tool = _tool(headers={"Accept": "application/json"})
    captured: dict = {}

    def _from_tool_config(t, resolved_headers=None):
        captured["headers"] = dict(resolved_headers or {})
        return "fake-tool"

    with patch(
        "app.tools.langchain_converter.LangChainToolFactory.from_tool_config",
        side_effect=_from_tool_config,
    ):
        build_langchain_tool(tool)
    assert captured["headers"] == {"Accept": "application/json"}


def test_no_direct_uses_secret_only():
    tool = _tool(headers={})
    captured: dict = {}

    def _from_tool_config(t, resolved_headers=None):
        captured["headers"] = dict(resolved_headers or {})
        return "fake-tool"

    with patch(
        "app.tools.langchain_converter.LangChainToolFactory.from_tool_config",
        side_effect=_from_tool_config,
    ):
        build_langchain_tool(tool, resolved_secret_headers={"X-Token": "abc"})
    assert captured["headers"] == {"X-Token": "abc"}


def test_none_secret_treated_as_empty():
    tool = _tool(headers={"X": "1"})
    captured: dict = {}

    def _from_tool_config(t, resolved_headers=None):
        captured["headers"] = dict(resolved_headers or {})
        return "fake-tool"

    with patch(
        "app.tools.langchain_converter.LangChainToolFactory.from_tool_config",
        side_effect=_from_tool_config,
    ):
        build_langchain_tool(tool, resolved_secret_headers=None)
    assert captured["headers"] == {"X": "1"}


def test_handles_tool_with_no_headers_at_all():
    tool = _tool(headers={})
    captured: dict = {}

    def _from_tool_config(t, resolved_headers=None):
        captured["headers"] = dict(resolved_headers or {})
        return "fake-tool"

    with patch(
        "app.tools.langchain_converter.LangChainToolFactory.from_tool_config",
        side_effect=_from_tool_config,
    ):
        build_langchain_tool(tool)
    assert captured["headers"] == {}
