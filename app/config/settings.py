"""Centralized application settings.

Single source of truth for environment-driven configuration. Imported lazily by
`app.config.get_settings()` so a missing env file produces a clear
`pydantic.ValidationError`, not a 500 at import time.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


LLMProvider = Literal["groq", "ollama", "openrouter"]


class Settings(BaseSettings):
    """All runtime configuration. Loaded from process env + .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Server ----
    host: str = "0.0.0.0"
    port: int = 8000
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"

    # ---- Security ----
    secret_key: str = Field(..., min_length=16)
    access_token_expire_minutes: int = 30
    password_reset_expire_hours: int = 1

    # ---- LLM ----
    llm_provider: LLMProvider = "ollama"
    llm_temperature: float = 0.2
    # Provider-specific (only the active one is read by build_llm).
    groq_api_key: str | None = None
    groq_model: str = "qwen/qwen3-32b"
    ollama_model: str = "minimax-m2.5:cloud"
    # Ollama's local server speaks plain HTTP on 11434. The previous default
    # of `https://127.0.0.1:11434` caused httpx to attempt a TLS handshake
    # against an HTTP-only endpoint and fail with `WRONG_VERSION_NUMBER`.
    # Override with `OLLAMA_BASE_URL` in `.env` when running Ollama behind
    # a TLS-terminating reverse proxy.
    ollama_base_url: str = "http://127.0.0.1:11434"
    openrouter_api_key: str | None = None
    openrouter_model: str = "deepseek/deepseek-r1-0528:free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # ---- Router LLM ----
    # Routing is a tiny structured-classification job; it should NOT share
    # the workflow's heavy agent LLM. Default to groq (fast, reliable JSON
    # mode). Set `LLM_PROVIDER_ROUTER` in `.env` to override.
    llm_provider_router: LLMProvider = "groq"
    router_model: str = "llama-3.1-8b-instant"  # small, fast, supports JSON mode

    # ---- Observability: LangSmith / LangFuse ----
    # If `langchain_tracing=True` and `langsmith_api_key` is set, every
    # LangChain/LangGraph run is uploaded to LangSmith.
    # If `langfuse_*` are set, runs are sent to LangFuse instead.
    # They are independent; set ONE (or none, to disable).
    langchain_tracing: bool = False
    langsmith_api_key: str | None = None
    langsmith_project: str = "orkaive-multi-agent"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    # LangFuse (open-source LLM observability, self-hostable).
    # https://langfuse.com — provides trace timeline, token cost,
    # prompt registry integration, and eval hooks.
    langfuse_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_environment: str = "development"

    # ---- MongoDB ----
    mongodb_url: str = "mongodb://127.0.0.1:27017"
    mongodb_db: str = "sasefied_agent"

    # ---- Redis ----
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_username: str = "default"
    redis_password: str | None = None
    redis_db: int = 0

    # ---- Frontend ----
    nextjs_base_url: str = "http://127.0.0.1:3000"

    # ---- Email (SMTP) ----
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    from_email: str | None = None

    # ---- Conflict resolution ----
    conflict_timeout_seconds: int = 300
    conflict_poll_interval: float = 1.0  # used only as a fallback path

    # ---- Rate limiting ----
    # Per-IP on auth (no user context yet). Generous enough for a real
    # user retrying, tight enough to make credential stuffing expensive.
    rate_limit_auth: str = "10/minute"
    # Per-user on chat endpoints (post-auth). The streaming route
    # also gets a *concurrent-stream* cap, not just a per-minute cap,
    # so a user can't pin the orchestrator with 50 long-lived streams.
    rate_limit_chat: str = "60/minute"
    rate_limit_chat_concurrent_streams: int = 3

    # ---- Optional integrations ----
    tavily_api_key: str | None = None
    openai_api_key: str | None = None  # legacy, used by old /execute endpoint

    @model_validator(mode="after")
    def _check_provider_keys(self) -> "Settings":
        if self.llm_provider == "groq" and not self.groq_api_key:
            raise ValueError("GROQ_API_KEY is required when LLM_PROVIDER=groq")
        if self.llm_provider == "openrouter" and not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter")
        if self.llm_provider == "ollama" and not self.ollama_model:
            raise ValueError("OLLAMA_MODEL is required when LLM_PROVIDER=ollama")
        # Router provider is independent of the agent provider.
        if self.llm_provider_router == "groq" and not self.groq_api_key:
            raise ValueError("GROQ_API_KEY is required when LLM_PROVIDER_ROUTER=groq")
        if self.llm_provider_router == "openrouter" and not self.openrouter_api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is required when LLM_PROVIDER_ROUTER=openrouter"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Called from inside FastAPI handlers, agent constructors, and the lifespan.
    A `ValidationError` here is a *runtime* error (clean 500 with detail), not
    an import-time crash.
    """
    return Settings()  # type: ignore[call-arg]


def reset_settings_cache() -> None:
    """Used by tests. Clears the lru_cache."""
    get_settings.cache_clear()
