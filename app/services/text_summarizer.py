"""Best-effort large-response summarizer.

Replaces the previous `services/text_splitting.py` for the HTTP-tool path.
Summarization is opt-in (only when `focus_query` is provided) and a
best-effort optimization, never a hard dependency.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from app.core.logging import get_logger
from app.services.llm_registry import get_summarizer_llm

logger = get_logger(__name__)


def summarize_large_response(data: Any, focus_query: str) -> str:
    """Trim a large response to a focus_query-scoped summary.

    No-op if the data is small enough or the summarizer is not configured.
    """
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    if len(text) <= 100_000:
        return text

    llm = get_summarizer_llm()
    if llm is None:
        # Without a configured summarizer, return a truncated preview.
        return text[:50_000] + "\n\n...[truncated]..."

    try:
        # Single-pass: cap at ~120k chars to stay well under token limits.
        truncated = text[:120_000]
        prompt = (
            "You are a data-reduction expert. Given the API response and a "
            "user question, return ONLY the parts of the response that answer "
            "the question. Preserve IDs, timestamps, statuses, and error "
            "messages. Do NOT invent information.\n\n"
            f"Question: {focus_query}\n\n"
            f"Response:\n{truncated}\n\n"
            "Relevant Output:"
        )
        # Synchronous invoke — this is already inside an async tool coroutine
        # but we don't want to await on a separate model call.
        return llm.invoke(prompt).content  # type: ignore[union-attr]
    except Exception as e:
        logger.warning("summarize_large_response failed: %s", e)
        return text[:50_000] + "\n\n...[truncated]..."
