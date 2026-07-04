# ADR 0003: LangGraph over CrewAI / AutoGen for orchestration

- **Status:** Accepted
- **Date:** 2026-07-01
- **Deciders:** Engineering team

## Context

The core of the platform is a multi-agent system: a user query is
classified, routed to one or more specialist agents, and the results
synthesized into a final response. We need a framework that:

- Models an explicit, inspectable graph of agents
- Streams intermediate events (`step`, `token`, `tool`, `message`,
  `conflict`, `done`) so the UI can show what each agent is doing
- Supports human-in-the-loop pauses (a conflict tool that blocks
  until an admin responds)
- Lets us build the graph dynamically from a `Workflow` document in
  MongoDB (different tenants get different agent sets)

The realistic candidates in 2026 were:

- **LangGraph** (LangChain's stateful-graph library)
- **CrewAI** (role-based crews, high-level)
- **AutoGen** (Microsoft's conversational-agent framework)
- **Custom** (raw LangChain + asyncio)

## Decision

Use **LangGraph** for the dynamic orchestrator
(`app/orchestrator/orchestrator.py`) and the static 5-agent baseline
(`app/orchestrator/graph_static.py`).

## Consequences

**Easier:**

- `StateGraph` is an explicit graph. The wiring is readable; the
  router → agents → synthesizer pattern is one file, not 200 lines of
  control flow.
- `astream_events(version="v2")` gives us token-level events with no
  glue code. That feeds the SSE chat stream directly.
- `MemorySaver` checkpointer gives free thread-id state for the
  chat conversations. We don't have to build a per-thread state
  store.
- Conditional edges (`add_conditional_edges`) express "loop over
  secondary agents when `requires_multiple_agents=True`" in 5 lines.
- Composes with the rest of LangChain — `SummarizationMiddleware`,
  `create_agent`, tool binding, the LLM factory all stay consistent.

**Harder:**

- The `astream_events` event schema changes between minor versions.
  Pin `langchain` and `langgraph` in `requirements.txt`.
- LangGraph's prompts and middleware live in different versions
  across providers. We pin them.
- LangGraph opinions on tool-merge are subtle: `create_agent` is the
  recommended path now, but older docs reference `AgentExecutor`. We
  standardize on `create_agent` (see `app/agents/base_agent.py`).
- Streaming-event ordering for a graph with conditional edges is
  subtle — the synthesizer event can land before the final agent's
  `done` event. The route layer (`app/routes/chat_stream.py`) is the
  only place we order SSE frames.

**Why not CrewAI?** CrewAI's role-based model fits "a team of
collaborative agents" but its graph is implicit. We need to expose
the actual graph to the UI (the "Steps" panel), the conflict tool
needs to pause *one* agent and resume *one* graph execution, and
agents can vary per workflow. LangGraph's explicit graph fits all
three.

**Why not AutoGen?** AutoGen is great for chat-style multi-agent
collaboration but its group-chat model doesn't compose well with
our per-workflow dynamic agent sets. The router → agents →
synthesizer pattern is more naturally a state machine than a
group chat.

**Why not custom?** We could build the state machine on raw
LangChain + asyncio, but the per-thread state, conditional edges,
and streaming-events integration would all have to be hand-rolled.
LangGraph already does this and is what the rest of the LangChain
ecosystem assumes.
