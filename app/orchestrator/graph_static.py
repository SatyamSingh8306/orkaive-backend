"""Static 5-agent orchestrator (no Mongo, hard-coded roster).

Used by the original /api/query endpoint. The new dynamic orchestrator
(`app.orchestrator.Orchestrator`) replaces it for the /api/workflows/*
surface.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from app.agents import create_deep_search_agent
from app.orchestrator.router import make_router
from app.schemas.state import AgentState
from app.schemas.workflow import ProjectedAgent
from app.services.chat_history_service import get_chat_history_service
from app.core.logging import get_logger

logger = get_logger(__name__)

# Max prior turns to feed back to the agent as message context. The
# /try-agent page is a transient demo surface — keep this small to
# avoid blowing past the LLM context window on long threads.
_HISTORY_TURNS = 10


class StaticOrchestrator:
    def __init__(self):
        self.router = make_router([
            ProjectedAgent(id="deep_search", label="Orkaive Agent",
                           role="Generalist web research, summarization, and cited answers",
                           capabilities=["Crawl", "Reason", "Summarize", "Cite"]),
        ])
        self.agents = {
            "deep_search": create_deep_search_agent(),
        }
        graph = StateGraph(AgentState)
        graph.add_node("router", self._route)
        for aid, a in self.agents.items():
            graph.add_node(aid, self._runner(aid, a))
        graph.add_node("synthesizer", self._synthesize)
        graph.add_edge(START, "router")
        graph.add_conditional_edges("router", self._next, {
            **{aid: aid for aid in self.agents},
            "synthesize": "synthesizer",
        })
        for aid in self.agents:
            graph.add_conditional_edges(aid, self._more,
                                        {"continue": "router", "finish": "synthesizer"})
        graph.add_edge("synthesizer", END)
        # No checkpointer: history is owned by Redis (`chat_history_service`),
        # not by LangGraph. A checkpointer would re-load prior turns on every
        # run with the same `thread_id` and the `add_messages` reducer would
        # fold them on top of the history we already inject, doubling the
        # user's prior messages in the agent's view and producing the
        # "echoes back the same query" symptom.
        self.graph = graph.compile()

    async def _route(self, state: AgentState) -> AgentState:
        query = state.user_query or (state.messages[-1].content if state.messages else "")
        classification = await self.router.classify(query)
        ctx = {**(state.context or {}),
               "classification": classification.model_dump(),
               "requires_multiple_agents": classification.requires_multiple_agents,
               "secondary_agents": classification.secondary_agents}
        return state.model_copy(update={
            "query_type": classification.agent_type,
            "next_agent": classification.agent_type,
            "context": ctx,
        })

    def _runner(self, agent_id, agent):
        async def run(state: AgentState) -> AgentState:
            try:
                result = await agent.invoke(state.messages)
                msgs = result.get("messages", [])
                completed = list((state.context or {}).get("completed_agents", []))
                completed.append(agent_id)
                results = {**(state.results or {}), agent_id: {
                    "response": msgs[-1].content if msgs else "",
                    "status": "completed",
                }}
                ctx = {**(state.context or {}), "completed_agents": completed}
                return state.model_copy(update={
                    "messages": msgs,
                    "current_agent": agent_id,
                    "results": results,
                    "context": ctx,
                    "iteration_count": (state.iteration_count or 0) + 1,
                })
            except Exception as e:
                return state.model_copy(update={
                    "error": f"agent {agent_id} failed: {e!s}",
                    "current_agent": agent_id,
                })
        return run

    def _next(self, state: AgentState) -> str:
        if state.is_complete:
            return "synthesize"
        return state.next_agent or "synthesize"

    def _more(self, state: AgentState) -> str:
        ctx = state.context or {}
        if ctx.get("requires_multiple_agents"):
            sec = ctx.get("secondary_agents", []) or []
            done = ctx.get("completed_agents", []) or []
            if any(s for s in sec if s not in done):
                return "continue"
        return "finish"

    async def _synthesize(self, state: AgentState) -> AgentState:
        return state.model_copy(update={"is_complete": True})

    async def run(
        self,
        *,
        query: str,
        thread_id: str,
        context: dict,
    ) -> dict:
        # Replay prior turns from Redis (transient, TTL'd — no Mongo
        # writes). The current user query is appended last so the agent
        # sees a coherent back-and-forth.
        history = get_chat_history_service()
        prior = await history.load(self._bucket, thread_id)
        prior_msgs: list[HumanMessage | AIMessage] = []
        for turn in prior[-_HISTORY_TURNS:]:
            content = turn.get("content", "")
            if not content:
                continue
            if turn.get("role") == "user":
                prior_msgs.append(HumanMessage(content=content))
            elif turn.get("role") == "assistant":
                prior_msgs.append(AIMessage(content=content))
        prior_msgs.append(HumanMessage(content=query))

        state = AgentState(
            messages=prior_msgs,
            user_query=query,
            context=context or {},
        )
        result = await self.graph.ainvoke(state)
        msgs = result.get("messages", []) if isinstance(result, dict) else result.messages
        return {
            "response": msgs[-1].content if msgs else "",
            "thread_id": thread_id,
        }

    @property
    def _bucket(self) -> str:
        # Shared with `routes/chat.py` so the orchestrator reads the
        # same Redis keys the route writes to.
        return "public"


_static: StaticOrchestrator | None = None


def get_static_orchestrator() -> StaticOrchestrator:
    global _static
    if _static is None:
        _static = StaticOrchestrator()
    return _static
