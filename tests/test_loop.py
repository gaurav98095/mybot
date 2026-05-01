"""Tests for agent/loop.py — AgentLoop end-to-end message processing."""

import asyncio

import pytest

from mybot.agent.loop import AgentLoop
from mybot.bus.events import InboundMessage, OutboundMessage
from mybot.bus.queue import MessageBus
from mybot.providers.base import LLMResponse
from tests.conftest import FakeProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inbound(content: str, channel: str = "test", chat_id: str = "c1") -> InboundMessage:
    return InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)


async def _run_one_turn(loop: AgentLoop, bus: MessageBus, content: str) -> OutboundMessage:
    """Publish one message, run the loop for one turn, return the outbound reply."""
    await bus.publish_inbound(_inbound(content))
    loop_task = asyncio.create_task(loop.run())
    reply = await asyncio.wait_for(bus.consume_outbound(), timeout=5.0)
    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass
    return reply


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAgentLoopBasic:
    async def test_message_produces_outbound_reply(self):
        provider = FakeProvider([LLMResponse(content="Hello there!")])
        bus = MessageBus()
        loop = AgentLoop(provider=provider, model="fake/model", bus=bus)

        reply = await _run_one_turn(loop, bus, "Hi")
        assert reply.content == "Hello there!"
        assert reply.type == "final"
        assert reply.channel == "test"
        assert reply.chat_id == "c1"

    async def test_history_accumulates_across_turns(self):
        provider = FakeProvider([
            LLMResponse(content="turn1 reply"),
            LLMResponse(content="turn2 reply"),
        ])
        bus = MessageBus()
        loop = AgentLoop(provider=provider, model="fake/model", bus=bus)

        # Turn 1
        await bus.publish_inbound(_inbound("first message"))
        loop_task = asyncio.create_task(loop.run())
        await asyncio.wait_for(bus.consume_outbound(), timeout=5.0)

        # Turn 2
        await bus.publish_inbound(_inbound("second message"))
        await asyncio.wait_for(bus.consume_outbound(), timeout=5.0)

        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        # History should contain both user messages and both assistant replies
        history = loop._history
        user_msgs = [m for m in history if m["role"] == "user"]
        assistant_msgs = [m for m in history if m["role"] == "assistant"]
        assert len(user_msgs) == 2
        assert len(assistant_msgs) == 2

    async def test_error_in_runner_returns_error_outbound(self):
        """When runner.run() raises an exception the loop emits type='error'."""
        from unittest.mock import AsyncMock as AM
        provider = FakeProvider([])
        bus = MessageBus()
        loop = AgentLoop(provider=provider, model="fake/model", bus=bus)
        # Patch the runner directly so the exception propagates to the loop
        loop.runner.run = AM(side_effect=RuntimeError("runner exploded"))

        await bus.publish_inbound(_inbound("trigger error"))
        loop_task = asyncio.create_task(loop.run())
        reply = await asyncio.wait_for(bus.consume_outbound(), timeout=5.0)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        assert reply.type == "error"
        assert "runner exploded" in reply.content

    async def test_extra_tools_registered(self):
        from mybot.agent.tools.base import Tool

        class SpyTool(Tool):
            was_called = False

            @property
            def name(self):
                return "spy"

            @property
            def description(self):
                return "spy"

            @property
            def parameters(self):
                return {"type": "object", "properties": {}}

            async def execute(self, **kwargs):
                SpyTool.was_called = True
                return "spied"

        from mybot.providers.base import ToolCallRequest

        provider = FakeProvider([
            LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="tc1", name="spy", arguments={})],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="used spy tool"),
        ])
        bus = MessageBus()
        loop = AgentLoop(
            provider=provider,
            model="fake/model",
            bus=bus,
            extra_tools=[SpyTool()],
        )

        reply = await _run_one_turn(loop, bus, "use spy")
        assert reply.content == "used spy tool"
        assert SpyTool.was_called is True

    async def test_default_tools_present(self):
        """Shell, web_search and subagent are registered by default."""
        provider = FakeProvider([LLMResponse(content="ok")])
        bus = MessageBus()
        loop = AgentLoop(provider=provider, model="fake/model", bus=bus)

        assert loop.runner.registry.has("shell")
        assert loop.runner.registry.has("web_search")
        assert loop.runner.registry.has("subagent")

    async def test_extra_tools_appended_to_defaults(self):
        from mybot.agent.tools.base import Tool

        class BonusTool(Tool):
            @property
            def name(self): return "bonus"
            @property
            def description(self): return "bonus"
            @property
            def parameters(self): return {"type": "object", "properties": {}}
            async def execute(self, **kwargs): return "bonus"

        provider = FakeProvider([LLMResponse(content="ok")])
        bus = MessageBus()
        loop = AgentLoop(
            provider=provider, model="fake/model", bus=bus, extra_tools=[BonusTool()]
        )

        assert loop.runner.registry.has("shell")        # default still present
        assert loop.runner.registry.has("bonus")        # extra tool added


class TestAgentLoopConcurrency:
    async def test_multiple_messages_processed_sequentially(self):
        """The loop processes messages one at a time; all get replies."""
        responses = [LLMResponse(content=f"reply {i}") for i in range(3)]
        provider = FakeProvider(responses)
        bus = MessageBus()
        loop = AgentLoop(provider=provider, model="fake/model", bus=bus)

        for i in range(3):
            await bus.publish_inbound(_inbound(f"message {i}"))

        loop_task = asyncio.create_task(loop.run())
        replies = []
        for _ in range(3):
            replies.append(await asyncio.wait_for(bus.consume_outbound(), timeout=5.0))

        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        assert len(replies) == 3
        contents = {r.content for r in replies}
        assert "reply 0" in contents
