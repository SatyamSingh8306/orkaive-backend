"""Query Router.

Classifies a user query into one of the workflow's connected agents. The
router prompt is built from a *projected* view of the agents — id, label,
role, short capabilities — NOT from the full `systemPrompt` /
`goalsAndActions`. The full prompt is reserved for the agent itself.

The system preamble itself is versioned: see
`app.services.prompt_registry` and the "query_router" name. At
construction time the orchestrator passes the active preamble into
`QueryRouter(..., preamble=...)`. The default (no override) is the
hard-coded fallback so the router still works without a seed prompt.

LLM choice:
  The router uses `build_router_llm(settings)` (default: Groq with
  `llama-3.1-8b-instant`), NOT the workflow's heavy agent LLM. Routing
  is a tiny structured-classification job and benefits from a small,
  fast, JSON-mode-capable model. Override via `LLM_PROVIDER_ROUTER` in
  `.env`.

Skip path:
  If the workflow has zero or one connected agents, the router returns
  a deterministic `QueryClassification` without calling the LLM. Zero
  agents means "no agent to route to" (defensive default); one agent
  means "skip the LLM round-trip — there's nowhere else to route".
  The LLM round-trip is only paid when there's a real choice to make.

Output parsing:
  The default path uses `with_structured_output(QueryClassification)`,
  which works reliably for providers with native JSON / tool-call mode
  (Groq, OpenRouter). A parser-based chain is also wired in as a
  fallback for providers that don't support structured output. The two
  paths are tried in order: structured first, parser second.
"""

from __future__ import annotations

import logging
from typing import Optional

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.config.settings import Settings, get_settings
from app.llm import build_router_llm
from app.schemas.state import QueryClassification
from app.schemas.workflow import ProjectedAgent

logger = logging.getLogger(__name__)


# Hard-coded fallback, also exposed as `app.services.prompt_registry._FALLBACK_QUERY_ROUTER`
# so the registry has somewhere to fall back to when the `prompt_versions`
# collection is empty.
_SYSTEM_PREAMBLE_FALLBACK = """
You are a query router for an enterprise multi-agent system.

You MUST respond with ONLY a single JSON object that matches this schema:

{format_instructions}

ABSOLUTE RULES:
- Reply with ONLY the raw JSON object.
- Do NOT wrap output in markdown.
- Do NOT return XML, YAML, or text.
- Do NOT explain your answer.
- `agent_type` MUST be one of the listed agent ids.
- `confidence` MUST be between 0.0 and 1.0.
- Prefer the best matching agent.
- If multiple agents are required, set:
  `requires_multiple_agents=true`
  and populate `secondary_agents`.
"""


# Public name callers use to look up the versioned router preamble.
ROUTER_PROMPT_NAME = "query_router"


class QueryRouter:
    """Routes a user query to workflow agents."""

    def __init__(
        self,
        connected_agents: list[ProjectedAgent],
        settings: Optional[Settings] = None,
        llm: Optional[BaseChatModel] = None,
        preamble: Optional[str] = None,
    ):
        self.settings = settings or get_settings()
        self.connected_agents = list(connected_agents)

        # Allow external injection, otherwise use the dedicated router LLM
        # (default: Groq with a small fast model). NEVER the heavy agent LLM.
        self.llm = llm or build_router_llm(self.settings)

        # Versioned preamble: callers (the orchestrator) pass the body
        # fetched from `app.services.prompt_registry`. None means "use
        # the hard-coded fallback" (no seed prompt yet, or registry down).
        self.preamble = preamble if preamble is not None else _SYSTEM_PREAMBLE_FALLBACK

        self._parser = PydanticOutputParser(
            pydantic_object=QueryClassification
        )

        self._prompt = self._build_prompt()
        # Two chains: structured (preferred for Groq/OpenRouter) and
        # parser (fallback for providers without native JSON mode).
        self._structured_chain = (
            self._prompt | self.llm.with_structured_output(QueryClassification)
        )
        self._parser_chain = self._prompt | self.llm | self._parser

    def set_preamble(self, preamble: str) -> None:
        """Swap the system preamble at runtime and rebuild the prompt.

        Used by the orchestrator after fetching the active version
        from the prompt registry. No-op if the preamble is unchanged.
        """
        if preamble == self.preamble:
            return
        self.preamble = preamble
        self._prompt = self._build_prompt()
        self._structured_chain = (
            self._prompt | self.llm.with_structured_output(QueryClassification)
        )
        self._parser_chain = self._prompt | self.llm | self._parser

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    def update_connected_agents(
        self,
        agents: list[ProjectedAgent]
    ) -> None:
        """Update router agent graph."""
        self.connected_agents = list(agents)
        self._prompt = self._build_prompt()
        self._structured_chain = (
            self._prompt | self.llm.with_structured_output(QueryClassification)
        )
        self._parser_chain = self._prompt | self.llm | self._parser

    def _skip(self) -> Optional[QueryClassification]:
        """Return a deterministic classification if the LLM call can be
        skipped entirely. None means "no skip, run the LLM"."""
        # Zero agents: nothing to route to. Return a sentinel
        # classification so the graph can still terminate cleanly.
        if not self.connected_agents:
            return QueryClassification(
                agent_type="agent",
                confidence=1.0,
                reasoning="router skip: no connected agents",
                requires_multiple_agents=False,
                secondary_agents=[],
            )
        # One agent: there's only one choice. No need to ask the LLM.
        if len(self.connected_agents) == 1:
            only = self.connected_agents[0]
            return QueryClassification(
                agent_type=only.id,
                confidence=1.0,
                reasoning="router skip: single connected agent",
                requires_multiple_agents=False,
                secondary_agents=[],
            )
        return None

    async def classify(
        self,
        query: str
    ) -> QueryClassification:
        """Async classification."""
        skipped = self._skip()
        if skipped is not None:
            return skipped

        # Preferred path: native structured output.
        try:
            result = await self._structured_chain.ainvoke({"query": query})
            return self._validate(result)
        except OutputParserException as exc:
            logger.debug("router structured-output parse failure: %s", exc)
        except Exception as exc:
            logger.debug("router structured-output invocation failure: %s", exc)

        # Fallback path: parser-based chain.
        try:
            result = await self._parser_chain.ainvoke({"query": query})
            return self._validate(result)
        except OutputParserException as exc:
            logger.warning("router parser parse failure, falling back: %s", exc)
        except Exception as exc:
            logger.warning("router parser invocation failure, falling back: %s", exc)
        return self._fallback(reason="both structured and parser chains failed")

    def classify_sync(
        self,
        query: str
    ) -> QueryClassification:
        """Sync classification."""
        skipped = self._skip()
        if skipped is not None:
            return skipped

        try:
            result = self._structured_chain.invoke({"query": query})
            return self._validate(result)
        except OutputParserException as exc:
            logger.debug("router structured-output parse failure: %s", exc)
        except Exception as exc:
            logger.debug("router structured-output invocation failure: %s", exc)

        try:
            result = self._parser_chain.invoke({"query": query})
            return self._validate(result)
        except OutputParserException as exc:
            logger.warning("router parser parse failure, falling back: %s", exc)
        except Exception as exc:
            logger.warning("router parser invocation failure, falling back: %s", exc)
        return self._fallback(reason="both structured and parser chains failed")

    # ---------------------------------------------------------------------
    # Prompt Building
    # ---------------------------------------------------------------------

    def _build_prompt(self) -> ChatPromptTemplate:
        """Build router prompt."""

        if not self.connected_agents:
            agents_text = (
                "(no connected agents — "
                "caller will fallback)"
            )

        else:
            agent_lines: list[str] = []

            for agent in self.connected_agents:
                caps = (
                    agent.capabilities
                    or ([agent.role] if agent.role else [])
                )

                cap_str = " | ".join(
                    str(c)
                    for c in caps[:5]
                    if c
                )

                agent_lines.append(
                    f"- id={agent.id} "
                    f"label={agent.label} "
                    f"role={agent.role} "
                    f"capabilities={cap_str}"
                )

            agents_text = "\n".join(agent_lines)

        system_prompt = (
            self.preamble
            + "\nAVAILABLE AGENTS:\n"
            + agents_text
            + "\n\nINSTRUCTIONS:\n"
            + "1. Read the user query.\n"
            + "2. Select the best matching agent.\n"
            + "3. If more than one agent is needed, "
              "set requires_multiple_agents=true.\n"
            + "4. agent_type MUST match one "
              "of the listed ids.\n"
        )

        return ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{query}")
        ]).partial(
            format_instructions=(
                self._parser.get_format_instructions()
            )
        )

    # ---------------------------------------------------------------------
    # Validation
    # ---------------------------------------------------------------------

    def _validate(
        self,
        result: QueryClassification
    ) -> QueryClassification:
        """Validate selected agent."""

        valid_ids = {
            a.id for a in self.connected_agents
        }

        if (
            valid_ids
            and result.agent_type not in valid_ids
        ):
            fallback_agent = next(iter(valid_ids))

            logger.warning(
                "Invalid router agent '%s'. "
                "Fallback -> %s",
                result.agent_type,
                fallback_agent,
            )

            result.agent_type = fallback_agent
            result.reasoning = (
                f"{result.reasoning or ''} "
                f"(fallback->{fallback_agent})"
            )

        return result

    def _fallback(
        self,
        *,
        reason: str
    ) -> QueryClassification:
        """Safe fallback selection."""

        if self.connected_agents:
            fallback_agent = self.connected_agents[0].id
        else:
            fallback_agent = "agent"

        return QueryClassification(
            agent_type=fallback_agent,
            confidence=0.0,
            reasoning=f"router_fallback:{reason}",
            requires_multiple_agents=False,
            secondary_agents=[],
        )


# -------------------------------------------------------------------------
# Factory
# -------------------------------------------------------------------------

def make_router(
    connected_agents: list[ProjectedAgent],
    settings: Optional[Settings] = None,
    preamble: Optional[str] = None,
) -> QueryRouter:
    """Build a router for the given connected agents.

    The router uses the dedicated router LLM (default: Groq with
    `llama-3.1-8b-instant`), selected by `LLM_PROVIDER_ROUTER`. It does
    NOT use the workflow's heavy agent LLM.

    `preamble` is the system-prompt body, usually fetched from the
    prompt registry. None = use the hard-coded fallback.
    """
    return QueryRouter(
        connected_agents=connected_agents,
        settings=settings,
        preamble=preamble,
    )
