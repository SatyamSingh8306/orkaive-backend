"""LLM provider factories.

Each function returns a LangChain `BaseChatModel` configured from the active
`Settings`. They are pure functions — no module-level state, no `self.llm`
mutations, no chained reassignments.

Two factories live here:

  - `build_llm(settings)`  — the workflow-agent LLM. Selected by
    `LLM_PROVIDER`. Heavy / domain model; can be slow and expensive.

  - `build_router_llm(settings)` — the query-classification LLM. Selected
    by `LLM_PROVIDER_ROUTER`. Default `groq` with `llama-3.1-8b-instant`
    because routing is a tiny structured-classification job; a heavy
    local model is overkill and a tiny local model is unreliable at
    returning JSON. Override via `LLM_PROVIDER_ROUTER` in `.env`.
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from app.config.settings import Settings


def groq_llm(settings: Settings) -> BaseChatModel:
    from langchain_groq import ChatGroq

    if not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY is not configured")
    return ChatGroq(
        model=settings.groq_model,
        temperature=settings.llm_temperature,
        api_key=settings.groq_api_key,
    )


def ollama_llm(settings: Settings) -> BaseChatModel:
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=settings.ollama_model,
        temperature=settings.llm_temperature,
        base_url=settings.ollama_base_url,
    )


def openrouter_llm(settings: Settings) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    if not settings.openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY is not configured")
    return ChatOpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_model,
        temperature=settings.llm_temperature,
    )


_FACTORIES = {
    "groq": groq_llm,
    "ollama": ollama_llm,
    "openrouter": openrouter_llm,
}


def build_llm(settings: Settings) -> BaseChatModel:
    """Build the active LLM. Single entry point; the rest of the codebase
    never imports `langchain_groq` etc. directly.
    """
    try:
        factory = _FACTORIES[settings.llm_provider]
    except KeyError as exc:  # pragma: no cover - validated by Settings
        raise ValueError(
            f"Unknown LLM_PROVIDER: {settings.llm_provider!r}. "
            f"Expected one of: {sorted(_FACTORIES)}"
        ) from exc
    return factory(settings)


def build_router_llm(settings: Settings) -> BaseChatModel:
    """Build the LLM used by the query router.

    Independent of `build_llm` so routing cost + reliability can be tuned
    separately from the workflow's domain agents. The router is a
    structured-classification call: small + fast + JSON-mode matters more
    than long-context reasoning.
    """
    # Same factory map, but driven by `llm_provider_router`. The model
    # itself is `settings.router_model` (a small, fast, JSON-mode-capable
    # default), not the workflow's heavy `groq_model` / `ollama_model`.
    try:
        factory = _FACTORIES[settings.llm_provider_router]
    except KeyError as exc:  # pragma: no cover - validated by Settings
        raise ValueError(
            f"Unknown LLM_PROVIDER_ROUTER: {settings.llm_provider_router!r}. "
            f"Expected one of: {sorted(_FACTORIES)}"
        ) from exc

    # The generic factories read `groq_model` / `ollama_model` /
    # `openrouter_model`. For the router we want a *different* model
    # string, so build the model directly with `settings.router_model`
    # using the same per-provider config.
    from langchain_groq import ChatGroq
    from langchain_ollama import ChatOllama
    from langchain_openai import ChatOpenAI

    if settings.llm_provider_router == "groq":
        if not settings.groq_api_key:
            raise ValueError("GROQ_API_KEY is not configured")
        return ChatGroq(
            model=settings.router_model,
            temperature=0.0,  # deterministic routing
            api_key=settings.groq_api_key,
        )
    if settings.llm_provider_router == "ollama":
        return ChatOllama(
            model=settings.router_model,
            temperature=0.0,
            base_url=settings.ollama_base_url,
        )
    if settings.llm_provider_router == "openrouter":
        if not settings.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is not configured")
        return ChatOpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            model=settings.router_model,
            temperature=0.0,
        )
    raise ValueError(  # pragma: no cover
        f"Unknown LLM_PROVIDER_ROUTER: {settings.llm_provider_router!r}"
    )
