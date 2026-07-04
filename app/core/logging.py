"""Structured logging configuration.

Avoid `logging.basicConfig` at import time — it's called once from
`app.main:lifespan` so config can be re-read on reloads.
"""

from __future__ import annotations

import logging
import sys
from typing import Any


_DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"


def configure_logging(level: str = "INFO") -> None:
    """Configure root + project loggers. Idempotent."""
    root = logging.getLogger()
    if root.handlers:
        for h in root.handlers:
            root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT))
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Quiet noisy third-party loggers
    for name in ("httpx", "httpcore", "urllib3", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)

    # LangChain tends to be very chatty at INFO; bump to WARNING
    for name in ("langchain", "langchain_groq", "langchain_ollama",
                 "langchain_openai", "langsmith"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Thin wrapper so call sites are uniform and importable from one place."""
    return logging.getLogger(name)


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Emit a structured key=value line at INFO."""
    if not fields:
        logger.info(event)
        return
    parts = " ".join(f"{k}={v!r}" for k, v in fields.items())
    logger.info("%s %s", event, parts)
