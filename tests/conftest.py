"""Shared fixtures for the mybot test suite."""

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
async def cancel_background_tasks():
    """Cancel any asyncio tasks left over from a test before the loop closes."""
    yield
    tasks = [t for t in asyncio.all_tasks() if not t.done() and t is not asyncio.current_task()]
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

from mybot.bus.events import InboundMessage, OutboundMessage
from mybot.bus.queue import MessageBus
from mybot.providers.base import GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest


# ---------------------------------------------------------------------------
# Concrete LLMProvider stub
# ---------------------------------------------------------------------------

class FakeProvider(LLMProvider):
    """Minimal LLMProvider that serves a pre-programmed sequence of responses."""

    def __init__(self, responses: list[LLMResponse] | None = None):
        super().__init__()
        self.generation = GenerationSettings()
        self._queue: list[LLMResponse] = list(responses or [LLMResponse(content="ok")])
        self.calls: list[dict] = []  # records every chat() call

    async def chat(self, messages, tools=None, model=None, **kwargs) -> LLMResponse:
        self.calls.append({"messages": list(messages), "tools": tools, "model": model})
        if self._queue:
            return self._queue.pop(0)
        return LLMResponse(content="(no more responses)")

    def get_default_model(self) -> str:
        return "fake/model"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_provider():
    return FakeProvider()


@pytest.fixture
def bus():
    return MessageBus()


@pytest.fixture
def inbound():
    return InboundMessage(
        channel="test",
        sender_id="user1",
        chat_id="chat1",
        content="Hello",
    )


@pytest.fixture
def tool_call():
    return ToolCallRequest(id="tc_001", name="shell", arguments={"command": "echo hi"})
