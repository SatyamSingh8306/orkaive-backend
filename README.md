# Orkaive Backend

[orkaive fontend - https://github.com/SatyamSingh8306/orkaive-frontend]

Multi-agent orchestration runtime for the **Orkaive** (Orchestrate + Archive + Hive) platform.
FastAPI + LangGraph + MongoDB + Redis.

This repo is the **backend only**. The visual workflow builder, chat surface, and admin UI live in
`orchive_agent_frontend/` (separate repo). Everything in `/api/*` on the browser hits this service
directly — the frontend's `lib/axios.ts` points at `NEXT_PUBLIC_FASTAPI_BASE_URL` and there is no
Next.js rewrite in the middle.

---

## What this service does

- **Routes user queries through a graph of specialist agents.** The `Orchestrator` (dynamic, per-workflow)
  reads a `Workflow` from Mongo, builds per-workflow agent instances, and assembles them into a
  LangGraph `StateGraph`. The static 5-agent baseline (`StaticOrchestrator`) backs `/api/query`
  for the public `/try-agent` page.
- **Resolves human-in-the-loop conflicts.** When an agent calls `conflict_tool`, the conflict is
  written to Mongo and broadcast over WebSocket; the agent-side wait blocks on a per-query Redis
  pub/sub channel until an admin responds.
- **Streams chat replies over SSE.** `/api/chats/{cid}/stream` and `/api/chats/stream` consume
  `Orchestrator.stream(...)`, yielding `ready | step | token | tool | message | conflict | done | error`
  events.
- **Pushes live conversation updates** to logged-in clients over a per-user WebSocket at
  `/api/ws/chats` (the chat bridge in `app/ws/chat_bridge.py`).
- **Persists conversations, messages, workflows, tools, and conflicts** in MongoDB. Each collection
  is owned by a single service module — see `app/services/`.
- **Bridges trace events to the dashboard** via Redis pub/sub → WebSocket
  (`app/routes/dashboard_websocket.py`).

---

## Quick start

### Prerequisites

- Python 3.12+
- MongoDB (default `mongodb://localhost:27017`, db `sasefied_agent`)
- Redis (default `redis://localhost:6379`) — used for memory and the dashboard pub/sub bridge

### Install

```bash
pip install -r requirements.txt
```

NLTK data (`punkt`, `punkt_tab`) is auto-downloaded on first run via the FastAPI lifespan.

### Configure

```bash
cp .env.example .env
# fill in GROQ_API_KEY, SECRET_KEY, REDIS_*, MONGODB_URL, SMTP_*, TAVILY_API_KEY
```

`SECRET_KEY` must be ≥ 32 characters. The `LLM_PROVIDER` env var selects the active LLM factory
(`groq` / `ollama` / `openrouter`, default `ollama`) — see `app/llm/__init__.py:build_llm`.

### Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

### Docker

```bash
docker build -t orkaive-backend .
docker run -p 8000:8000 --env-file .env orkaive-backend
```

Multi-stage build; `punkt` is baked into the image so the first request doesn't pay a 30s download.

### Tests

```bash
pytest                # unit + integration under tests/
pytest -m "not integration"   # unit only (no Mongo/Redis/LLM required)
```

Marker `integration` requires live services.

---

## Module layout

```
app/
  main.py                       # FastAPI entrypoint; lifespan wires Mongo, indexes, Redis listener
  config/settings.py            # pydantic-settings Settings (env_file=".env", extra="ignore")
  core/                         # exceptions (OrkaiveError) + logging
  llm/                          # build_llm(settings) — single factory, provider-selected
  schemas/                      # Pydantic v2 models (ConfigDict extra="ignore", populate_by_name=True)
  services/                     # one owner per Mongo collection
  agents/                       # base_agent + one file per specialist
  orchestrator/
    orchestrator.py             # dynamic per-workflow graph + Orchestrator.stream() (SSE)
    graph_static.py             # static 5-agent graph used by /api/query
    router.py                   # QueryRouter → QueryClassification
  routes/                       # FastAPI routers, all mounted under /api
  ws/                           # per-user chat bridge WebSocket
  tools/                        # http_executor, langchain_converter, conflict_tool, agent_tool
  db/  mongodb.py  redis.py
```

`app/__init__.py` is intentionally near-empty (just `load_dotenv()`). Required-env validation
lives in `app/config/settings.py` and is invoked from the FastAPI lifespan — a missing key surfaces
as a clear `pydantic.ValidationError`, not a 500 from an import-time `HTTPException`.

---

## HTTP routes

All mounted under `/api` from `app/main.py`. See each module for the full schema.

| Mount | Module | Purpose |
|---|---|---|
| `/api/auth` | `routes/auth.py` | Signup / login / forgot-password / reset-password / `GET /me` (JWT) |
| `/api/chats` | `routes/chats.py` | REST CRUD for chat conversations + messages |
| `/api/chats/{cid}/stream`, `/api/chats/stream` | `routes/chat_stream.py` | SSE streaming chat replies |
| `/api/workflows` | `routes/workflows.py` | Workflow CRUD (returned as a bare JSON array on `GET`) |
| `/api/tools` | `routes/tools.py` | Tool CRUD; HTTP executor with SSRF protection |
| `/api/conflicts` | `routes/conflicts.py` | Conflict raise / list / respond |
| `/api/dashboard` | `routes/dashboard.py` | Dashboard read endpoints |
| `/api/prompts` | `routes/prompts.py` | Prompt template versioning |
| `/api/workflow-chats` | `routes/workflow_chat.py` | Per-workflow team chat (the conflict room) |
| `/api/ws/chats` | `ws/chat_bridge.py` | Per-user WebSocket for live sidebar updates |
| `/api/query` | `routes/chat.py` | Static 5-agent baseline (the public `/try-agent` path) |
| `/ws/{workflowId}` | `routes/websocket.py` | Per-workflow conflict WebSocket (legacy panel) |
| `/ws/dashboard`, `/ws/run/{id}` | `routes/dashboard_websocket.py` | Redis pubsub → WS bridge |

---

## Key concepts

### LangGraph orchestration

Two orchestrators, different routes, not parallel implementations of the same thing:

- `app/orchestrator/orchestrator.py` — `Orchestrator` (dynamic) is the per-workflow path. Reads
  a `Workflow` from Mongo, builds per-workflow agent instances, wraps them in a `StateGraph`,
  and caches the result in `_workflow_registry` keyed by `workflow_id`. The router prompt is
  built from a `ProjectedAgent` projection (id, label, role, capabilities capped at 200 chars) —
  full `system_prompt` / `goals_and_actions` stay on the agent. Exposes
  `Orchestrator.stream(workflow_id, query)` — an async generator over `astream_events(version="v2")`
  yielding `ready | step | token | tool | message | conflict | done | error | stopped`.
- `app/orchestrator/graph_static.py` — `StaticOrchestrator` is the hard-coded 5-agent baseline
  (supply_chain, process, client, optimization, compliance) used by `/api/query`. It does not
  read Mongo and does not stream.

Both follow `START → router → conditional agent nodes → synthesizer → END`. The router is
`QueryRouter` with structured `QueryClassification` output. When `requires_multiple_agents=True`,
the graph loops through `secondary_agents` before the synthesizer.

**Workflows are cached** in `Orchestrator._workflow_registry` for the process lifetime. Change a
workflow in Mongo and restart the backend (or clear the registry) to see updates.

**Workflow validation is lenient by design** — saving a workflow with just agent nodes is allowed.
The orchestrator wraps it with `router` / `synthesizer` at graph-build time.

### LLM construction

A single factory at `app/llm/__init__.py:build_llm(settings)` returns a LangChain `BaseChatModel`.
The active provider is selected by `LLM_PROVIDER` (`groq` / `ollama` / `openrouter`, default
`ollama`). The factory is called once per `BaseAgent` instance — there is no global `self.llm`
mutation. To swap the model globally, change the `LLM_*` env vars; do not edit the provider
string in `base_agent.py`.

### Agents

`app/agents/base_agent.py` builds a LangChain ReAct agent with `create_agent` +
`SummarizationMiddleware` (token-6k trigger, keep 20 messages). `conflict_tool` is no longer
auto-appended — the orchestrator opts each agent in explicitly via `attach_tools([...])` (the
single tool-merge point). If you add a new specialist agent, register it in
`app/agents/__init__.py` and reference it from `orchestrator.py:_build_agents`.

### Tools

- `tools/conflict_tool.py` — pauses execution, raises a conflict, waits on a per-query Redis
  pub/sub channel for the admin response.
- `tools/agent_tool.py` — wraps sibling agents as callable tools, so any agent can invoke any
  other agent in the same workflow.
- `tools/http_executor.py` / `tools/langchain_converter.py` — generic HTTP and LangChain tool
  adapters. `project_for_llm(tool)` returns a sanitized `ToolForLLM` (no `headers`, no full
  doc dump) used for the LLM-facing description.

**HTTP tool config (`ToolConfig` in `app/schemas/tool.py`):**

- `headers: dict[str, str]` — stored in Mongo. Use for non-sensitive headers
  (`Accept`, `Content-Type`, `X-Trace-Id`). `_validate_headers` rejects CR/LF.
- `authSecretRef: str | None` — resolves at build time via `app/services/secret_service.py` for
  sensitive credentials (`Authorization`, API keys). Sources: `ORKAIVE_SECRET_<REF>` env vars
  or `register_secret()`. Direct `headers` override secret headers.
- `allowInternalUrls: bool` — admin-only escape hatch for SSRF.
- **SSRF protection** blocks `localhost`, `127/8`, `10/8`, `172.16/12`, `192.168/16`, `169.254/16`,
  multicast, reserved, and AWS/GCP/Azure metadata hosts. DNS-rebinding blocked by checking the
  resolved IP at request time.
- **Retry** with exponential backoff (0.5s, 1s, 2s) on 429/502/503/504 and network errors; 4xx
  is not retried.
- `follow_redirects=False` — 30x → internal is not chased.
- 4xx/5xx return a structured `{status_code, error, response}` so the agent sees the failure.

### Conflict resolution (human-in-the-loop)

`app/services/conflict_service.py` is the centerpiece. The `conflicts` collection is owned by the
backend. When an agent calls `conflict_tool`:

1. `ConflictService.raise_conflict(...)` writes the doc to Mongo and broadcasts a `conflict:raised`
   event over WebSocket via `app/routes/websocket.py`.
2. The agent-side `wait_for_response(...)` blocks by subscribing to a per-query Redis channel
   (`conflict:{query_id}:events`), with a Mongo-doc poll as a safety net.
3. An admin's `respond_conflict(...)` publishes the answer on the same Redis channel AND
   broadcasts a `conflict:resolved` event. The waiting agent returns the response as its tool
   output.

The backend and frontend no longer share conflict state over HTTP — the FastAPI Mongo is the
single source of truth.

### Tracing

`app/services/trace_service.py` runs over Redis pub/sub; the dashboard subscribes via
`app/routes/dashboard_websocket.py` which bridges Redis to WS clients. `start_run` / `end_run` /
`start_step` / `end_step` are the only entry points; avoid adding new write paths.

### Auth

`app/routes/auth.py` — JWT (HS256) with bcrypt, SMTP password-reset flow via `app/utils/email.py`.
Tokens are signed with `SECRET_KEY`; password-reset tokens are single-use and time-limited (1h).
See `docs/README_AUTH.md` for the full auth contract.

### Rate limiting

`app/core/rate_limit.py` uses SlowAPI. Endpoints that hit the limiter must accept a `Response`
parameter (SlowAPI requirement) — see `app/routes/auth.py` for the working pattern.

---

## Mongo collections

Created on first run by `app/db/mongodb.py:ensure_indexes()` (idempotent).

| Collection | Owner | Key indexes |
|---|---|---|
| `users` | `services/user_service.py` | `email` unique |
| `workflows` | `services/workflow_service.py` | `name` |
| `tools` | `services/tool_service.py` | `(workflowId, nodeId)` |
| `conflicts` | `services/conflict_service.py` | `queryId` unique, `(workflowId, status)`, `raisedAt` |
| `conversations` | `services/chat_conversation_service.py` | `(userId, lastMessageAt -1)`, `(userId, pinned -1, lastMessageAt -1)`, `deletedAt` (partial) |
| `messages` | `services/chat_message_service.py` | `(conversationId, _id)` |
| `workflow_chats` | `services/workflow_chat_service.py` | `(workflowId, createdAt)` |
| `prompt_versions` | `services/prompt_registry.py` | `(name, version)` unique, `(name, isActive)` partial |
| `prompt_templates` | `services/prompt_registry.py` | `name` unique |

---

## Where to start reading

| If you want to… | Open |
|---|---|
| Wire a new LLM provider | `app/llm/__init__.py` |
| Add a specialist agent | `app/agents/base_agent.py` → register in `app/agents/__init__.py` → reference in `app/orchestrator/orchestrator.py:_build_agents` |
| Tweak the router prompt | `app/orchestrator/router.py` (`QueryRouter`, `QueryClassification`) |
| Add a new HTTP route | `app/routes/` (mount under `/api` from `app/main.py`) |
| Add a Mongo collection | new module under `app/services/` + index in `app/db/mongodb.py:ensure_indexes` |
| Change the conflict round-trip | `app/services/conflict_service.py` + `app/tools/conflict_tool.py` + `app/routes/websocket.py` |
| Trace pipeline | `app/services/trace_service.py` + `app/routes/dashboard_websocket.py` |
| Auth contract | `docs/README_AUTH.md` |
| Architectural decisions | `docs/adr/` |

---

## Environment reference

See `.env.example`. The full list lives in `app/config/settings.py`.

| Variable | Required | Default | Notes |
|---|---|---|---|
| `SECRET_KEY` | yes | — | JWT signing key, ≥ 32 chars |
| `MONGODB_URL` | yes | `mongodb://localhost:27017` | |
| `DATABASE_NAME` | no | `sasefied_agent` | |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` | yes (for dashboard WS) | `localhost` / `6379` / — | |
| `GROQ_API_KEY` | for `LLM_PROVIDER=groq` | — | |
| `OPENAI_API_KEY` | for `LLM_PROVIDER=openrouter` | — | |
| `TAVILY_API_KEY` | for web search tools | — | |
| `SMTP_*`, `FROM_EMAIL` | for password reset | — | |
| `LLM_PROVIDER` | no | `ollama` | `groq` / `ollama` / `openrouter` |
| `CONFLICT_TIMEOUT_SECONDS` | no | `300` | |
| `NEXTJS_BASE_URL` | no | `http://localhost:3000` | legacy fallback only |

---

## Development notes

- **Single source of truth for workflow / tool / conflict / chat state is the FastAPI Mongo.**
  The Next.js app no longer owns these collections; if you find yourself adding a Next.js Route
  Handler for them, add the route to `app/routes/` instead.
- **`BaseAgent` does not auto-append `conflict_tool` anymore.** The orchestrator opts each agent
  in explicitly via `attach_tools([...])`. When you build a custom `BaseAgent` subclass, decide
  in the orchestrator whether it should have human-in-the-loop and add the tool there.
- **Workflows cache for process lifetime.** Restart the backend to see Mongo-side workflow
  changes.
- **Suggested prompts in the chat empty state must NOT create conversations.** The conversation
  is created on Send via `POST /api/chats/stream`. (The original implementation did this; the
  fix lives in the frontend's `mode="new"` composer with `onCreated` callback.)
- **`workflow_chat.py` and `chat_history_service.py` are LEGACY.** They use a Redis TTL store
  and are mounted for backwards compatibility only. The new `/chats` route is Mongo-backed.
  The `workflow_chats` collection (per-workflow team chat) is the active path, not the legacy
  Redis store.

---

## License

Proprietary. © Orkaive.
