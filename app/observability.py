"""Observability setup.

Wires the LangChain/LangGraph call stack to either:

  * LangSmith (`langchain_tracing=true` + `langsmith_api_key=...`)
  * LangFuse (`langfuse_enabled=true` + `langfuse_public_key=...` +
    `langfuse_secret_key=...`)

The wiring is one-shot. Call `configure_observability()` from the
FastAPI lifespan (after Settings is loaded). Subsequent LangChain /
LangGraph calls are then traced automatically — no per-call glue code.

Both backends are off by default. LangSmith and LangFuse can also be
used together (LangSmith for the trace timeline, LangFuse for prompt
registry + eval). In practice, set ONE.

Notes:

  * LangSmith is configured purely through env vars; the LangChain SDK
    reads them itself.
  * LangFuse ships a LangChain integration
    (`langfuse.langchain.CallbackHandler`) that is added to the
    LangGraph `astream_events` invocation.
  * The trace_service (Redis pubsub) is unchanged — it's a parallel
    in-house channel for the dashboard WS. Observability backends
    (LangSmith / LangFuse) are *external* sinks.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from app.config.settings import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def configure_observability(settings: Optional[Settings] = None) -> None:
    """One-shot observability setup. Safe to call multiple times."""
    s = settings or get_settings()

    if s.langchain_tracing and s.langsmith_api_key:
        # The LangChain SDK reads these env vars on first use.
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = s.langsmith_api_key
        os.environ["LANGCHAIN_PROJECT"] = s.langsmith_project
        os.environ["LANGCHAIN_ENDPOINT"] = s.langsmith_endpoint
        logger.info(
            "LangSmith tracing enabled (project=%s)",
            s.langsmith_project,
        )

    if s.langfuse_enabled and s.langfuse_public_key and s.langfuse_secret_key:
        # LangFuse reads its own env vars.
        os.environ["LANGFUSE_PUBLIC_KEY"] = s.langfuse_public_key
        os.environ["LANGFUSE_SECRET_KEY"] = s.langfuse_secret_key
        os.environ["LANGFUSE_HOST"] = s.langfuse_host
        logger.info(
            "LangFuse tracing enabled (host=%s env=%s)",
            s.langfuse_host,
            s.langfuse_environment,
        )

    if not (s.langchain_tracing and s.langsmith_api_key) and not (
        s.langfuse_enabled and s.langfuse_public_key and s.langfuse_secret_key
    ):
        logger.debug("observability: no tracing backend configured")


def get_langfuse_callbacks() -> list[Any]:
    """Return a list of LangChain callbacks for LangFuse, or [] if disabled.

    Add to `astream_events(..., config={"callbacks": get_langfuse_callbacks()})`.
    The handler is constructed lazily so the SDK isn't imported at boot
    when LangFuse isn't configured.
    """
    s = get_settings()
    if not (
        s.langfuse_enabled and s.langfuse_public_key and s.langfuse_secret_key
    ):
        return []
    try:
        from langfuse.langchain import CallbackHandler  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "langfuse is enabled in settings but the `langfuse` package is not installed. "
            "Run `pip install langfuse` to enable LangFuse tracing."
        )
        return []
    return [CallbackHandler(
        public_key=s.langfuse_public_key,
        secret_key=s.langfuse_secret_key,
        host=s.langfuse_host,
        environment=s.langfuse_environment,
    )]
