"""In-process chat history for the /try-agent demo surface.

A per-thread deque of recent turns. No Redis, no Mongo — the demo is
transient by design and a deploy can wipe state without consequences.

Why not Redis? The legacy `chat_history_service.py` was a thin Redis
wrapper. With the new /chats surface in Mongo, the demo surface no
longer needs a shared store. Keeping a single-process dict keeps the
public demo dependency-light.

Why not a real checkpointer? LangGraph's MemorySaver would replay the
same turns every run, but our `add_messages` reducer folds them on
top of the history we already inject, producing the
"agent echoes back the same query" symptom. The deque-injection
approach keeps history stateless and explicit.
"""
from __future__ import annotations

import threading
from collections import defaultdict, deque
from typing import Any


_MAX_TURNS = 20  # per thread


class ChatHistoryService:
    """In-memory chat history keyed by (bucket, thread_id)."""

    def __init__(self, max_turns: int = _MAX_TURNS) -> None:
        self._max_turns = max_turns
        self._store: dict[tuple[str, str], deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=self._max_turns)
        )
        self._lock = threading.Lock()

    async def append(
        self,
        bucket: str,
        thread_id: str,
        role: str,
        content: str,
    ) -> None:
        with self._lock:
            self._store[(bucket, thread_id)].append({
                "role": role,
                "content": content,
            })

    async def load(self, bucket: str, thread_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._store.get((bucket, thread_id), []))

    async def clear(self, bucket: str, thread_id: str) -> None:
        with self._lock:
            self._store.pop((bucket, thread_id), None)


_history: ChatHistoryService | None = None


def get_chat_history_service() -> ChatHistoryService:
    """Lazy singleton accessor."""
    global _history
    if _history is None:
        _history = ChatHistoryService()
    return _history
