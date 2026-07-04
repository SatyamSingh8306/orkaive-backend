"""LLM registry — separate from the agent LLM.

The summarizer and any other auxiliary LLMs are configured from a separate
slot in `Settings`. By default they re-use the active provider.
"""

from __future__ import annotations

from typing import Any, Optional

from app.config.settings import get_settings
from app.llm import build_llm

_summarizer_llm: Any | None = None


def get_summarizer_llm() -> Any | None:
    """Return the summarizer LLM (lazy). Returns None if not configured."""
    global _summarizer_llm
    if _summarizer_llm is not None:
        return _summarizer_llm
    try:
        _summarizer_llm = build_llm(get_settings())
    except Exception:
        return None
    return _summarizer_llm


def reset_for_tests() -> None:
    global _summarizer_llm
    _summarizer_llm = None
