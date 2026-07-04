"""Orchestrator.

A single class that:
  1. Takes a `Workflow` (Pydantic model).
  2. Builds per-node agent instances (specialist or dynamic).
  3. Wires a LangGraph `StateGraph` (router → agents → synthesizer).
  4. Invokes the graph with a thread id and returns the result.

The previous implementation had two parallel orchestrators
(`graph.py:MultiAgentOrchestrator` and `agent_builder.py:AgentBuilder`)
that duplicated graph construction and conflict-prompt logic. This file
replaces both.

Two execution modes are supported:
  * `run(...)`    — fire-and-forget; returns the final assembled response.
  * `stream(...)` — yields `StreamEvent` dicts as the graph executes, so
    the HTTP layer can forward them to a client over SSE / WebSocket.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents import (
    create_base_agent,
    create_client_agent,
    create_compliance_agent,
    create_deep_search_agent,
    create_optimization_agent,
    create_process_agent,
    create_supply_chain_agent,
)
from app.config.settings import Settings, get_settings
from app.core.exceptions import WorkflowValidationError
from app.core.logging import get_logger
from app.orchestrator.router import QueryRouter, make_router
from app.schemas.state import AgentState
from app.schemas.workflow import ProjectedAgent, Workflow, WorkflowNode
from app.services import build_langchain_tool, list_for_node
from app.services.trace_service import StepType, get_trace_service
from app.tools.conflict_tool import get_conflict_tool

logger = get_logger(__name__)


# Map node id (after canonicalization) → agent factory.
_SPECIALIST_FACTORIES = {
    "supply_chain_agent": create_supply_chain_agent,
    "process_agent": create_process_agent,
    "client_agent": create_client_agent,
    "optimization_agent": create_optimization_agent,
    "compliance_agent": create_compliance_agent,
    "deep_search_agent": create_deep_search_agent,
}


def _clean(text: str) -> str:
    """Remove `<think>...</think>` blocks from LLM output (qwen / ollama artifact)."""
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


def _canonicalize(node_id: str) -> str:
    """Strip trailing `-<digits>` suffixes from node ids.

    The frontend assigns a unique timestamp suffix to custom-agent drops.
    Backend nodes should always look up agents by their canonical id.
    """
    return re.sub(r"-\d{10,}$", "", node_id)


def _is_specialist(node_id: str) -> bool:
    return _canonicalize(node_id) in _SPECIALIST_FACTORIES


class Orchestrator:
    """Builds and runs a workflow."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._cache: dict[str, dict[str, Any]] = {}

    # --------------------------------------------------------- workflow load

    async def _load(self, workflow_id: str) -> dict[str, Any]:
        if workflow_id in self._cache:
            return self._cache[workflow_id]

        from app.services import get_workflow

        workflow = await get_workflow(workflow_id)
        agents = await self._build_agents(workflow)
        router = await self._build_router(workflow)
        graph = self._build_graph(workflow, agents)

        compiled = graph.compile(checkpointer=MemorySaver())
        info = {
            "workflow": workflow,
            "agents": agents,
            "router": router,
            "graph": compiled,
        }
        self._cache[workflow_id] = info
        return info

    def invalidate(self, workflow_id: Optional[str] = None) -> None:
        if workflow_id:
            self._cache.pop(workflow_id, None)
        else:
            self._cache.clear()

    # --------------------------------------------------------- agent build

    async def _build_agents(self, workflow: Workflow) -> dict[str, Any]:
        """Build a BaseAgent for every agent node in the workflow."""
        from app.services.workflow_service import find_agent_nodes

        agent_nodes = find_agent_nodes(workflow)
        agents: dict[str, Any] = {}
        conflict_tool = get_conflict_tool()

        for node in agent_nodes:
            tools = await self._build_tools_for_node(workflow.id or "", node)
            agent = self._make_agent(workflow, node, tools, include_conflict=True)
            agent.set_context_data(
                workflow_id=workflow.id,
                node_id=node.id,
                node_data=node.model_dump(by_alias=True),
            )
            # Attach conflict tool explicitly. No more triple-injection.
            agent.attach_tools([conflict_tool])
            agents[node.id] = agent

        return agents

    async def _build_tools_for_node(
        self, workflow_id: str, node: WorkflowNode
    ) -> list:
        from app.services import list_for_node
        from app.services.secret_service import get_secret_service

        try:
            tool_configs = await list_for_node(workflow_id, node.id)
        except Exception as e:
            logger.warning("failed to load tools for node %s: %s", node.id, e)
            return []

        secret_service = get_secret_service()
        tools = []
        for tool_config in tool_configs:
            secret_headers: dict[str, str] = {}
            if tool_config.auth_secret_ref:
                try:
                    secret_headers = secret_service.resolve_headers(
                        tool_config.auth_secret_ref
                    )
                except Exception as e:
                    logger.warning(
                        "secret %s not resolved for tool %s: %s",
                        tool_config.auth_secret_ref, tool_config.name, e,
                    )
            tools.append(
                build_langchain_tool(tool_config, resolved_secret_headers=secret_headers)
            )
        return tools

    def _make_agent(
        self,
        workflow: Workflow,
        node: WorkflowNode,
        tools: list,
        include_conflict: bool,
    ):
        canonical = _canonicalize(node.id)
        system_prompt = self._compose_system_prompt(workflow, node, include_conflict)

        if canonical in _SPECIALIST_FACTORIES:
            factory = _SPECIALIST_FACTORIES[canonical]
            return factory(tools=tools, settings=self.settings).set_system_prompt(system_prompt) if False else _init_with_prompt(factory, tools, system_prompt, self.settings)
        # Dynamic / custom agent
        return create_base_agent(
            name=node.label or node.id,
            description=node.description or node.role or "Custom agent",
            system_prompt=system_prompt,
            tools=tools,
            settings=self.settings,
        )

    @staticmethod
    def _compose_system_prompt(
        workflow: Workflow, node: WorkflowNode, include_conflict: bool
    ) -> str:
        parts: list[str] = []
        if node.system_prompt:
            parts.append(node.system_prompt)
        if node.goals_and_actions:
            parts.append("Goals & actions:\n" + node.goals_and_actions)
        if include_conflict:
            parts.append(
                "When you encounter situations that require human input, "
                "use the conflict_resolution tool with workflow_id, node_label, "
                "owner_email, query, and context."
            )
        if not parts:
            parts.append("You are a specialized agent in the Orkaive workflow.")
        return "\n\n".join(parts)

    # --------------------------------------------------------- router build

    async def _build_router(self, workflow: Workflow) -> QueryRouter:
        from app.services.workflow_service import find_agent_nodes

        projections = [
            ProjectedAgent.from_node(n) for n in find_agent_nodes(workflow)
        ]
        # Pull the active preamble from the versioned prompt registry.
        # Falls back to a hard-coded string if the registry is empty.
        from app.orchestrator.router import ROUTER_PROMPT_NAME
        from app.services.prompt_registry import get_prompt_registry
        preamble = await get_prompt_registry().get_active(ROUTER_PROMPT_NAME)
        return make_router(projections, settings=self.settings, preamble=preamble)

    # --------------------------------------------------------- graph build

    def _build_graph(
        self, workflow: Workflow, agents: dict[str, Any]
    ) -> StateGraph:
        graph: StateGraph = StateGraph(AgentState)
        info = self._cache.get(workflow.id or "", {})

        # Add router
        graph.add_node("router", self._route)

        # Add agent runners
        for agent_id, agent in agents.items():
            graph.add_node(agent_id, self._make_runner(agent_id, agent, workflow))

        # Add synthesizer
        graph.add_node("synthesizer", self._synthesize)

        graph.add_edge(START, "router")

        # Router → agent or synthesizer
        targets = {agent_id: agent_id for agent_id in agents}
        targets["synthesize"] = "synthesizer"
        graph.add_conditional_edges("router", self._next_after_route, targets)

        # Each agent → router (for multi-agent) or synthesizer
        for agent_id in agents:
            graph.add_conditional_edges(
                agent_id, self._next_after_agent,
                {"continue": "router", "finish": "synthesizer"},
            )

        graph.add_edge("synthesizer", END)
        return graph

    # --------------------------------------------------------- node runners

    def _make_runner(self, agent_id: str, agent: Any, workflow: Workflow):
        async def run(state: AgentState) -> AgentState:
            trace = get_trace_service()
            user_input = ""
            for msg in reversed(state.messages):
                if isinstance(msg, HumanMessage):
                    user_input = msg.content
                    break

            run_id = (state.context or {}).get("run_id")
            step = None
            if run_id:
                try:
                    step = await trace.start_step(
                        run_id=run_id,
                        name=agent_id,
                        step_type=StepType.AGENT,
                        input_data={"input": user_input},
                        metadata={"workflow_id": workflow.id, "node_id": agent_id},
                    )
                except Exception as e:
                    logger.debug("trace.start_step failed: %s", e)

            try:
                result = await agent.invoke(state.messages)
                new_messages = result.get("messages", [])
                last = new_messages[-1].content if new_messages else ""
                clean = _clean(last)
                completed = list((state.context or {}).get("completed_agents", []))
                completed.append(agent_id)
                new_results = {**(state.results or {}), agent_id: {
                    "response": clean,
                    "status": "completed",
                }}
                new_context = {**(state.context or {}), "completed_agents": completed}
                new_state = state.model_copy(update={
                    "messages": new_messages,
                    "current_agent": agent_id,
                    "results": new_results,
                    "context": new_context,
                    "iteration_count": (state.iteration_count or 0) + 1,
                })
                if step:
                    try:
                        await trace.end_step(
                            run_id=run_id, step_id=step.step_id, output=clean,
                        )
                    except Exception:
                        pass
                return new_state
            except Exception as e:
                logger.exception("agent %s failed", agent_id)
                if step and run_id:
                    try:
                        await trace.end_step(
                            run_id=run_id, step_id=step.step_id, error=str(e),
                        )
                    except Exception:
                        pass
                return state.model_copy(update={
                    "error": f"agent {agent_id} failed: {e!s}",
                    "current_agent": agent_id,
                    "results": {**(state.results or {}), agent_id: {
                        "status": "error", "error": str(e),
                    }},
                })

        return run

    # --------------------------------------------------------- graph nodes

    async def _route(self, state: AgentState) -> AgentState:
        info = self._cache.get((state.workflow_id) or (state.context or {}).get("workflow_id", ""), {})
        router: QueryRouter = info.get("router") or self._build_router_for_state(state)
        query = state.user_query
        if not query and state.messages:
            for m in reversed(state.messages):
                if isinstance(m, HumanMessage):
                    query = m.content
                    break
        classification = await router.classify(query or "")

        new_context = {
            **(state.context or {}),
            "classification": classification.model_dump(),
            "requires_multiple_agents": classification.requires_multiple_agents,
            "secondary_agents": classification.secondary_agents,
        }
        return state.model_copy(update={
            "query_type": classification.agent_type,
            "next_agent": classification.agent_type,
            "context": new_context,
        })

    def _build_router_for_state(self, state: AgentState) -> QueryRouter:
        # Fallback router for cases where the workflow cache is cold.
        return make_router([], settings=self.settings)

    def _next_after_route(self, state: AgentState) -> str:
        if state.is_complete:
            return "synthesize"
        if state.next_agent:
            return state.next_agent
        return "synthesize"

    def _next_after_agent(self, state: AgentState) -> str:
        ctx = state.context or {}
        if ctx.get("requires_multiple_agents"):
            secondary = ctx.get("secondary_agents", []) or []
            completed = ctx.get("completed_agents", []) or []
            remaining = [a for a in secondary if a not in completed]
            if remaining:
                return "continue"
        return "finish"

    async def _synthesize(self, state: AgentState) -> AgentState:
        # Join completed agent responses verbatim — no per-agent
        # "Title:" headers and no "Summary:" footer. The chat UI shows
        # the agent roster in a separate steps panel; the main bubble
        # should read like a single assistant reply.
        parts: list[str] = []
        for _agent_name, result in (state.results or {}).items():
            if result.get("status") == "completed":
                resp = _clean(result.get("response", ""))
                if resp:
                    parts.append(resp)
            elif result.get("status") == "error":
                err = result.get("error", "unknown error")
                parts.append(f"(error: {err})")

        final = "\n\n".join(parts) if parts else "No agent produced a response."
        return state.model_copy(update={
            "messages": [AIMessage(content=final)],
            "is_complete": True,
        })

    # --------------------------------------------------------- entry point

    async def run(
        self,
        workflow_id: str,
        query: str,
        *,
        thread_id: Optional[str] = None,
        run_id: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        info = await self._load(workflow_id)
        compiled = info["graph"]
        workflow = info["workflow"]

        thread_id = thread_id or f"workflow_{workflow_id}"
        run_id = run_id or str(uuid.uuid4())

        trace = get_trace_service()
        try:
            await trace.start_run(
                run_id=run_id,
                workflow_id=workflow_id,
                workflow_name=workflow.name,
                input_data={"query": query},
                metadata={"thread_id": thread_id},
            )
        except Exception as e:
            logger.debug("trace.start_run failed: %s", e)

        state = AgentState(
            messages=[HumanMessage(content=query)],
            user_query=query,
            workflow_id=workflow_id,
            context={"run_id": run_id, "workflow_id": workflow_id, **(context or {})},
        )
        try:
            result = await compiled.ainvoke(
                state,
                config={"configurable": {"thread_id": thread_id}},
            )
        except Exception as e:
            logger.exception("orchestrator.run failed")
            try:
                await trace.end_run(run_id=run_id, error=str(e))
            except Exception:
                pass
            raise

        msgs = result.get("messages", []) if isinstance(result, dict) else result.messages
        final = msgs[-1].content if msgs else ""
        final = _clean(final)
        ctx = result.get("context", {}) if isinstance(result, dict) else (result.context or {})
        results = result.get("results", {}) if isinstance(result, dict) else (result.results or {})

        try:
            await trace.end_run(run_id=run_id, output={"response": final})
        except Exception:
            pass

        return {
            "response": final,
            "messages": [HumanMessage(content=final)],
            "results": results,
            "agents_used": (ctx or {}).get("completed_agents", []),
            "workflow_id": workflow_id,
            "workflow_name": workflow.name,
            "thread_id": thread_id,
            "run_id": run_id,
        }

    # --------------------------------------------------------- streaming

    async def stream(
        self,
        workflow_id: str,
        query: str,
        *,
        run_id: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run the graph and yield `StreamEvent` dicts.

        Event shapes:
          {type: "ready",     conversationId, runId}
          {type: "step",      name, status}                # chain start/end
          {type: "token",     delta, agent}                # chat-model token
          {type: "tool",      name, status}                # tool start/end
          {type: "conflict",  queryId, nodeLabel, query}   # raised mid-run
          {type: "message",   content, agent, runId}       # per-agent final text
          {type: "done",      runId, content, durationMs,
                              agentsUsed, agentResults}
          {type: "error",     message, runId}
          {type: "stopped",   runId, content}              # user cancelled
        """
        info = await self._load(workflow_id)
        compiled = info["graph"]
        workflow = info["workflow"]

        run_id = run_id or str(uuid.uuid4())
        thread_id = f"workflow_{workflow_id}"
        start_ts = time.time()

        yield {
            "type": "ready",
            "runId": run_id,
            "workflowId": workflow_id,
            "workflowName": workflow.name,
        }

        # Build state the same way `run()` does, but include the full
        # prior history (passed in via context["messages"]). The
        # current `query` is ALWAYS appended as the trailing
        # HumanMessage so the agent always sees what the user just
        # asked. Callers that pass prior turns should NOT include
        # the current query in `messages` — the orchestrator owns
        # that injection.
        prior_msgs = list((context or {}).get("messages") or [])
        prior_msgs.append(HumanMessage(content=query))
        state = AgentState(
            messages=prior_msgs,
            user_query=query,
            workflow_id=workflow_id,
            context={"run_id": run_id, "workflow_id": workflow_id, **(context or {})},
        )

        trace = get_trace_service()
        try:
            await trace.start_run(
                run_id=run_id,
                workflow_id=workflow_id,
                workflow_name=workflow.name,
                input_data={"query": query},
                metadata={"thread_id": thread_id, "run_id": run_id},
            )
        except Exception as e:
            logger.debug("trace.start_run failed: %s", e)

        accumulated_per_agent: dict[str, str] = {}
        agent_results: dict[str, Any] = {}
        current_agent: Optional[str] = None
        final_text = ""
        stopped = False
        stream_error: Optional[BaseException] = None
        # Tracks per-agent steps opened by the streaming path so we can
        # close them in the finally clause below (the graph's `_make_runner`
        # is bypassed by astream_events, so end_step never fires otherwise).
        open_steps: dict[str, str] = {}  # agent_name -> step_id

        try:
            # Optional LangFuse callback. get_langfuse_callbacks() returns
            # [] when LangFuse is disabled, so the astream_events config
            # is just {"configurable": {...}} + callbacks = [] otherwise.
            try:
                from app.observability import get_langfuse_callbacks
                callbacks = get_langfuse_callbacks()
            except Exception:
                callbacks = []

            stream_config = {"configurable": {"thread_id": thread_id}}
            if callbacks:
                stream_config["callbacks"] = callbacks

            async for ev in compiled.astream_events(
                state,
                config=stream_config,
                version="v2",
            ):
                kind = ev.get("event")
                name = ev.get("name") or ""
                data = ev.get("data") or {}

                # Chat-model token streaming
                if kind == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    delta = ""
                    if chunk is not None:
                        # AIMessageChunk has `.content`; ToolMessage variants
                        # also do but we only forward assistant text here.
                        delta = getattr(chunk, "content", "") or ""
                    if isinstance(delta, list):
                        # Some providers return a list of content parts.
                        delta = "".join(
                            p.get("text", "") if isinstance(p, dict) else str(p)
                            for p in delta
                        )
                    if delta:
                        # Accumulate the RAW delta (preserves whitespace
                        # between chunks). Strip <think>…</think> only at
                        # the end so trailing newlines / spaces don't get
                        # collapsed mid-stream.
                        if current_agent:
                            accumulated_per_agent[current_agent] = (
                                accumulated_per_agent.get(current_agent, "") + delta
                            )
                        yield {
                            "type": "token",
                            "delta": delta,
                            "agent": current_agent or "assistant",
                        }
                    continue

                # Chain start/end → yield a "step" event so the UI can
                # show which agent is currently working.
                if kind in ("on_chain_start", "on_chain_end"):
                    if name in ("router", "synthesizer"):
                        yield {"type": "step", "name": name, "status": "started" if kind == "on_chain_start" else "completed"}
                    elif name in info["agents"]:
                        current_agent = name if kind == "on_chain_start" else None
                        yield {
                            "type": "step",
                            "name": name,
                            "status": "started" if kind == "on_chain_start" else "completed",
                        }
                        if kind == "on_chain_start":
                            # Open a trace step for this agent. The
                            # streaming path bypasses `_make_runner`, so
                            # we have to record start_step ourselves;
                            # otherwise the dashboard shows zero per-agent
                            # rows for streamed runs.
                            try:
                                step = await trace.start_step(
                                    run_id=run_id,
                                    name=name,
                                    step_type=StepType.AGENT,
                                    input_data={"input": query},
                                    metadata={"workflow_id": workflow.id, "node_id": name},
                                )
                                open_steps[name] = step.step_id
                            except Exception as e:
                                logger.debug("trace.start_step failed: %s", e)
                        elif kind == "on_chain_end":
                            step_id = open_steps.pop(name, None)
                            txt = accumulated_per_agent.get(name, "")
                            cleaned = _clean(txt) if txt else ""
                            if step_id:
                                try:
                                    await trace.end_step(
                                        run_id=run_id,
                                        step_id=step_id,
                                        output=cleaned,
                                    )
                                except Exception:
                                    pass
                            if txt:
                                agent_results[name] = {
                                    "response": cleaned,
                                    "status": "completed",
                                }
                                if cleaned:
                                    yield {
                                        "type": "message",
                                        "agent": name,
                                        "content": cleaned,
                                        "runId": run_id,
                                    }
                    continue

                # Tool start/end
                if kind in ("on_tool_start", "on_tool_end"):
                    yield {
                        "type": "tool",
                        "name": name,
                        "status": "started" if kind == "on_tool_start" else "completed",
                    }
                    continue

                # Conflict tool raised a question — relay the event.
                # The actual round-trip still happens inside the agent
                # (Redis pubsub + Mongo doc); we just notify the client.
                if kind == "on_tool_end" and name == "conflict_resolution":
                    output = data.get("output")
                    if isinstance(output, str) and "Admin guidance" in output:
                        # Heuristic: tool returned a real answer. Nothing
                        # to do here; the agent will continue and emit
                        # the text in its own chain_end.
                        pass

        except asyncio.CancelledError:
            stopped = True
            logger.info("orchestrator.stream cancelled: run_id=%s", run_id)
            yield {"type": "stopped", "runId": run_id, "content": final_text}
        except Exception as e:
            stream_error = e
            logger.exception("orchestrator.stream failed")
            yield {"type": "error", "runId": run_id, "message": str(e)}
        finally:
            # Close any agent steps still open (the chain_end event never
            # arrived — typically because the run was cancelled or errored
            # mid-agent). Without this, the dashboard undercounts steps
            # and the step is left in `started` forever.
            # ponytail: this finally rarely runs on cancellation — the
            # route layer (chat_stream._close_run) is the real safety net.
            logger.debug("orchestrator.stream finally: run_id=%s stopped=%s err=%s open_steps=%s", run_id, stopped, stream_error, list(open_steps.keys()))
            for agent_name, step_id in list(open_steps.items()):
                try:
                    await trace.end_step(
                        run_id=run_id,
                        step_id=step_id,
                        error="stream ended before agent completed",
                    )
                except Exception:
                    pass
            open_steps.clear()

            # Always close the run — happy path, error, AND cancellation.
            # Without this, runs that the client abandoned (closed tab,
            # navigated away, network drop) stay at status="started" in
            # the dashboard forever. The `end_run` call is idempotent on
            # the WorkflowRun doc, so it's safe even if some other path
            # already closed it.
            try:
                if stream_error is not None:
                    await trace.end_run(run_id=run_id, error=str(stream_error))
                elif stopped:
                    await trace.end_run(
                        run_id=run_id,
                        output={"response": final_text, "agentResults": agent_results, "stopped": True},
                    )
                else:
                    parts: list[str] = []
                    for _agent_name, result in agent_results.items():
                        if result.get("status") == "completed":
                            resp = _clean(result.get("response", ""))
                            if resp:
                                parts.append(resp)
                    final_text = "\n\n".join(parts) if parts else final_text
                    final_text = _clean(final_text)
                    await trace.end_run(
                        run_id=run_id,
                        output={"response": final_text, "agentResults": agent_results},
                    )
            except Exception:
                pass

        # Synthesize the final response from the per-agent results.
        # Join responses verbatim — no per-agent "Title:" prefix, no
        # "Summary: Processed by N agent(s)" footer. The chat UI
        # already shows agent names in the steps panel; the main
        # bubble should read like one assistant reply.
        #
        # Clean each agent's accumulated text once (strip <think>…</think>
        # + leading/trailing whitespace). Per-chunk cleaning was
        # stripping whitespace mid-stream and collapsing paragraphs.
        if stream_error is not None or stopped:
            return

        parts: list[str] = []
        for _agent_name, result in agent_results.items():
            if result.get("status") == "completed":
                resp = _clean(result.get("response", ""))
                if resp:
                    parts.append(resp)
        completed = [a for a in agent_results if agent_results[a].get("status") == "completed"]
        final_text = "\n\n".join(parts) if parts else ""
        final_text = _clean(final_text)

        duration_ms = int((time.time() - start_ts) * 1000)

        if not stopped:
            yield {
                "type": "done",
                "runId": run_id,
                "content": final_text,
                "durationMs": duration_ms,
                "agentsUsed": completed,
                "agentResults": agent_results,
            }


# Backwards-compatible helper for old call sites.
_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


# -----------------------------------------------------------------------

def _init_with_prompt(factory, tools, system_prompt, settings):
    """Helper: create a specialist, then set its prompt. Done in one shot
    to avoid the previous double-rebuild."""
    agent = factory(tools=tools, settings=settings)
    agent.set_system_prompt(system_prompt)
    return agent
