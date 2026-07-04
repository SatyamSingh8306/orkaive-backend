"""FastAPI entrypoint.

Lifespan:
  1. Load + validate Settings (a `ValidationError` here is a clean 500,
     not a 500 at import time).
  2. Connect to MongoDB and create indexes.
  3. Configure logging.
  4. Start the dashboard WS Redis listener.
  5. On shutdown: close redis + mongo.
"""

from __future__ import annotations

import datetime
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.core.exceptions import OrkaiveError
from app.core.logging import configure_logging, get_logger
from app.core.rate_limit import init_rate_limiter
from app.db.mongodb import close as mongo_close, connect as mongo_connect, ensure_indexes
from app.db.redis import close as redis_close


# ---------------------------------------------------------------- lifespan

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Configure logging first so subsequent errors are visible.
    try:
        from app.config.settings import get_settings
        settings = get_settings()
    except Exception as e:
        # `get_settings` calls Settings() which can raise ValidationError
        # when the .env is missing required values. We log clearly and
        # continue; route handlers that need settings will fail cleanly.
        configure_logging("INFO")
        logger = get_logger(__name__)
        logger.error("Settings validation failed: %s", e)
        yield
        return

    configure_logging(settings.log_level)
    logger = get_logger(__name__)

    # Observability (LangSmith / LangFuse). Idempotent, safe to call
    # even when no tracing backend is configured.
    try:
        from app.observability import configure_observability
        configure_observability(settings)
    except Exception as e:
        logger.warning("observability setup failed: %s", e)

    # MongoDB
    try:
        await mongo_connect()
        await ensure_indexes()
    except Exception as e:
        logger.warning("MongoDB connection failed: %s", e)

    # Dashboard WS listener (Redis pubsub bridge)
    try:
        from app.routes.dashboard_websocket import start_listener
        await start_listener()
    except Exception as e:
        logger.warning("Dashboard WS listener failed to start: %s", e)

    logger.info("Orkaive backend ready (env=%s, llm=%s)",
                settings.environment, settings.llm_provider)
    try:
        yield
    finally:
        try:
            await redis_close()
        except Exception as e:
            logger.debug("redis close: %s", e)
        try:
            await mongo_close()
        except Exception as e:
            logger.debug("mongo close: %s", e)
        logger.info("Orkaive backend shutdown complete")


# ---------------------------------------------------------------- app

app = FastAPI(
    title="Orkaive Multi-Agent System",
    description="Enterprise multi-agent system with LangGraph orchestration",
    version="2.0.0",
    lifespan=lifespan,
)

# Wire rate limiting BEFORE the routers so the exception handler is
# registered before any handler can raise RateLimitExceeded.
init_rate_limiter(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- handlers

@app.exception_handler(OrkaiveError)
async def _orkaive_error_handler(request, exc: OrkaiveError):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=exc.http_status,
        content={"detail": str(exc), "code": exc.code},
    )


@app.get("/")
def home() -> dict:
    return {"version": "2.0.0", "description": "Orkaive AI multi-agent system"}


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="healthy",
        timestamp=datetime.datetime.now().isoformat(),
        version="2.0.0",
    )


# ---------------------------------------------------------------- routers

from app.routes import (  # noqa: E402  (import after app created)
    auth as auth_module,
    chat as chat_module,
    chat_stream as chat_stream_module,
    chats as chats_module,
    conflicts as conflicts_module,
    dashboard as dashboard_module,
    dashboard_websocket as dashboard_ws_module,
    prompts as prompts_module,
    tools as tools_module,
    websocket as websocket_module,
    workflow_chat as workflow_chat_module,
    workflows as workflows_module,
)
from app.ws import chat_bridge_router  # noqa: E402

app.include_router(auth_module.auth_router, prefix="/api/auth")
app.include_router(chat_module.router, prefix="/api")
app.include_router(workflows_module.router, prefix="/api")
app.include_router(tools_module.router, prefix="/api")
app.include_router(conflicts_module.router, prefix="/api")
app.include_router(dashboard_module.router, prefix="/api")
# Per-workflow team chat (the conflict room). Mounted at /api so the
# frontend's `api.get('/workflow-chats')` resolves to /api/workflow-chats.
app.include_router(workflow_chat_module.router, prefix="/api")
# Prompt template versioning.
app.include_router(prompts_module.router, prefix="/api")
# Dashboard WebSocket (Redis pubsub bridge). Mounted at root so the
# paths `/ws/dashboard` and `/ws/run/{id}` resolve to the handlers
# declared in `dashboard_websocket.py`.
app.include_router(dashboard_ws_module.router)
# New chat surface: REST at /api/chats, SSE at /api/chats/{cid}/stream.
app.include_router(chats_module.router, prefix="/api")
app.include_router(chat_stream_module.router, prefix="/api")
# Per-user WebSocket for live sidebar updates. Mounted under /api so the
# existing CORS config covers it; the client passes the JWT via
# Sec-WebSocket-Protocol.
app.include_router(chat_bridge_router, prefix="/api")
# Pre-existing conflict/chat WS (per-workflow) — kept for the existing
# `useSocket` hook on the conflict panel.
app.include_router(websocket_module.router)
