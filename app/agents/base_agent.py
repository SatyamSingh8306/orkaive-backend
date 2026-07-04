"""Base Agent.

The single, canonical place where:
  * the LLM is constructed (via `app.llm.build_llm`)
  * the SummarizationMiddleware is attached
  * the agent's tools are merged and `create_agent` is called

Subclasses own their domain-specific tools and a tailored system prompt. The
conflict tool is opt-in (passed in by the orchestrator) rather than auto-
appended in three places (the previous bug).
"""

from __future__ import annotations

from abc import ABC
from typing import Any, Optional

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool

from app.config.settings import Settings, get_settings
from app.core.logging import get_logger
from app.llm import build_llm

logger = get_logger(__name__)


# Default system prompt applied to all agents that don't override
# `get_system_prompt()`. Kept concise; the orchestrator can extend it.
DEFAULT_SYSTEM_PROMPT = """You are an intelligent, autonomous AI agent in the Orkaive multi-agent system.

You have:
  * a typed set of tools
  * access to other specialized agents via the `agent_*` tools
  * the `conflict_resolution` tool for situations that require human input

Behaviors:
  - Understand the goal, context, and constraints before responding
  - Be honest about uncertainty; flag conflicts when appropriate
  - Use tools only when they materially help
  - Prefer concise, structured outputs
"""


class BaseAgent(ABC):
    """Abstract base. Subclasses must override `get_system_prompt`."""

    def __init__(
        self,
        name: str,
        description: str,
        system_prompt: str,
        tools: list[BaseTool],
        settings: Optional[Settings] = None,
        temperature: Optional[float] = None,
    ):
        self.name = name
        self.description = description
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

        # If a Settings was provided, honor its temperature; otherwise fall
        # back to the explicit arg, then to the global default.
        self.settings: Settings = settings or get_settings()
        if temperature is None:
            temperature = self.settings.llm_temperature
        self.temperature = temperature

        # ---- Single LLM construction ---------------------------------------
        # This used to assign Groq, then Ollama, then OpenRouter to
        # `self.llm`, leaving SummarizationMiddleware wrapping the WRONG
        # client. Now there is exactly one assignment, after Settings has
        # been validated by `app.config.settings.get_settings`.
        self.llm: BaseChatModel = build_llm(self.settings)

        # Middleware is attached to the same LLM that will be used.
        self.middleware = SummarizationMiddleware(
            model=self.llm,
            trigger=("tokens", 6000),
            keep=("messages", 20),
        )

        # ---- Tool merge (the single merge point) ---------------------------
        # No more triple-injection of conflict_tool. The orchestrator passes
        # the conflict tool explicitly when it wants it.
        self.tools: list[BaseTool] = list(tools)
        self._agent: Any = None
        self._rebuild()

    # ------------------------------------------------------------------ build

    def _rebuild(self) -> None:
        """Recreate the underlying LangChain agent. Called on every tool merge
        so a single source of truth is in charge of the (llm, tools, prompt)
        triple.
        """
        self._agent = create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=self.system_prompt,
            middleware=[self.middleware],
        )

    def attach_tools(self, tools: list[BaseTool]) -> None:
        """Merge additional tools (e.g. cross-agent tools from the orchestrator)
        and rebuild. Replaces the previous `add_tools` / `_reconfigure_agent`
        trio that did the same thing in three different ways.
        """
        seen = {t.name for t in self.tools}
        for t in tools:
            if t.name not in seen:
                self.tools.append(t)
                seen.add(t.name)
        self._rebuild()

    def set_system_prompt(self, system_prompt: str) -> None:
        self.system_prompt = system_prompt
        self._rebuild()

    # --------------------------------------------------------------- run API

    async def invoke(
        self, messages: list[BaseMessage], config: Optional[dict] = None
    ) -> dict[str, Any]:
        result = await self._agent.ainvoke(
            {"messages": messages},
            config=config or {},
        )
        return result

    def invoke_sync(
        self, messages: list[BaseMessage], config: Optional[dict] = None
    ) -> dict[str, Any]:
        return self._agent.invoke(
            {"messages": messages},
            config=config or {},
        )

    # ----------------------------------------------------- conflict plumbing

    def set_context_data(
        self,
        workflow_id: Optional[str] = None,
        node_id: Optional[str] = None,
        node_data: Optional[dict] = None,
    ) -> None:
        """Set attributes the conflict tool reads. Stores real IDs only —
        no more "unknown" fallbacks hard-coded inside the tool.
        """
        if workflow_id is not None:
            self._workflow_id = workflow_id
        if node_id is not None:
            self._node_id = node_id
        if node_data is not None:
            self._node_data = node_data

    def get_context_data(self) -> dict[str, Any]:
        return {
            "workflow_id": getattr(self, "_workflow_id", None),
            "node_id": getattr(self, "_node_id", None),
            "node_data": getattr(self, "_node_data", None),
        }

    # ------------------------------------------------- subclasses override

    def get_system_prompt(self) -> str:
        return self.system_prompt


def create_base_agent(
    name: str,
    description: str,
    system_prompt: str,
    tools: list[BaseTool],
    settings: Optional[Settings] = None,
) -> BaseAgent:
    """Factory for ad-hoc / dynamic agents. The orchestrator builds these
    when a workflow node doesn't map to one of the named specialists.
    """
    agent = _DynamicAgent(
        name=name,
        description=description,
        system_prompt=system_prompt,
        tools=tools,
        settings=settings,
    )
    return agent


class _DynamicAgent(BaseAgent):
    """Internal: a BaseAgent with no further overrides."""

    def __init__(self, *, name: str, description: str, system_prompt: str,
                 tools: list[BaseTool], settings: Optional[Settings] = None):
        super().__init__(
            name=name,
            description=description,
            system_prompt=system_prompt,
            tools=tools,
            settings=settings,
        )
