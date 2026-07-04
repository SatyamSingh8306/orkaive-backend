"""Unit tests for the in-process ChatHistoryService."""
from __future__ import annotations

import pytest

from app.services.chat_history_service import (
    ChatHistoryService,
    get_chat_history_service,
)


@pytest.fixture
def svc() -> ChatHistoryService:
    return ChatHistoryService(max_turns=3)


async def test_append_and_load(svc):
    await svc.append("public", "t1", "user", "hello")
    await svc.append("public", "t1", "assistant", "hi back")
    turns = await svc.load("public", "t1")
    assert turns == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi back"},
    ]


async def test_separate_threads(svc):
    await svc.append("public", "t1", "user", "a")
    await svc.append("public", "t2", "user", "b")
    assert (await svc.load("public", "t1")) == [{"role": "user", "content": "a"}]
    assert (await svc.load("public", "t2")) == [{"role": "user", "content": "b"}]


async def test_max_turns_eviction(svc):
    for i in range(5):
        await svc.append("public", "t1", "user", f"msg-{i}")
    # Only the last 3 survive (deque maxlen=3)
    turns = await svc.load("public", "t1")
    assert [t["content"] for t in turns] == ["msg-2", "msg-3", "msg-4"]


async def test_clear(svc):
    await svc.append("public", "t1", "user", "hello")
    await svc.clear("public", "t1")
    assert await svc.load("public", "t1") == []


async def test_clear_unknown_thread_is_noop(svc):
    await svc.clear("public", "never-existed")  # must not raise


async def test_load_empty_returns_empty(svc):
    assert await svc.load("public", "never-existed") == []


def test_singleton_returns_same_instance():
    a = get_chat_history_service()
    b = get_chat_history_service()
    assert a is b
