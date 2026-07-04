"""LLM package.

Two public entry points:

  - `build_llm(settings)` — the workflow-agent LLM. Selected by
    `LLM_PROVIDER`. Heavy / domain model; can be slow and expensive.

  - `build_router_llm(settings)` — the query-classification LLM. Selected
    by `LLM_PROVIDER_ROUTER` (default `groq`). Small, fast, JSON-mode-
    capable. Callers never need to know which provider is active.

The router LLM is intentionally separate from the agent LLM so routing
cost and reliability can be tuned independently. Routing is a tiny
structured-classification job; running a heavy local model for it is
overkill and a tiny local model is unreliable at returning JSON.
"""

from .providers import (
    build_llm,
    build_router_llm,
    groq_llm,
    ollama_llm,
    openrouter_llm,
)

__all__ = [
    "build_llm",
    "build_router_llm",
    "groq_llm",
    "ollama_llm",
    "openrouter_llm",
]
