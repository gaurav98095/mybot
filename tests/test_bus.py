"""Tests for bus/events.py and bus/queue.py."""

import asyncio

import pytest

from mybot.bus.events import InboundMessage, OutboundMessage
from mybot.bus.queue import MessageBus


# ---------------------------------------------------------------------------
# InboundMessage
# ---------------------------------------------------------------------------

class TestInboundMessage:
    def test_session_key_default(self):
        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="hi")
        assert msg.session_key == "telegram:c1"

    def test_session_key_override(self):
        msg = InboundMessage(
            channel="telegram", sender_id="u1", chat_id="c1",
            content="hi", session_key_override="custom:key",
        )
        assert msg.session_key == "custom:key"

    def test_defaults(self):
        msg = InboundMessage(channel="slack", sender_id="u1", chat_id="c1", content="x")
        assert msg.media == []
        assert msg.metadata == {}
        assert msg.session_key_override is None

    def test_timestamp_set(self):
        msg = InboundMessage(channel="slack", sender_id="u1", chat_id="c1", content="x")
        assert msg.timestamp is not None


# ---------------------------------------------------------------------------
# OutboundMessage
# ---------------------------------------------------------------------------

class TestOutboundMessage:
    def test_default_type(self):
        msg = OutboundMessage(channel="telegram", chat_id="c1", content="reply")
        assert msg.type == "final"

    def test_stream_type(self):
        msg = OutboundMessage(channel="telegram", chat_id="c1", content="chunk", type="stream")
        assert msg.type == "stream"

    def test_defaults(self):
        msg = OutboundMessage(channel="telegram", chat_id="c1", content="hi")
        assert msg.reply_to is None
        assert msg.media == []
        assert msg.metadata == {}
        assert msg.buttons == []


# ---------------------------------------------------------------------------
# MessageBus
# ---------------------------------------------------------------------------

class TestMessageBus:
    async def test_inbound_roundtrip(self):
        bus = MessageBus()
        msg = InboundMessage(channel="test", sender_id="u", chat_id="c", content="hello")
        await bus.publish_inbound(msg)
        received = await bus.consume_inbound()
        assert received is msg

    async def test_outbound_roundtrip(self):
        bus = MessageBus()
        msg = OutboundMessage(channel="test", chat_id="c", content="reply")
        await bus.publish_outbound(msg)
        received = await bus.consume_outbound()
        assert received is msg

    async def test_inbound_fifo_order(self):
        bus = MessageBus()
        msgs = [
            InboundMessage(channel="t", sender_id="u", chat_id="c", content=str(i))
            for i in range(3)
        ]
        for m in msgs:
            await bus.publish_inbound(m)
        for expected in msgs:
            assert await bus.consume_inbound() is expected

    async def test_size_properties(self):
        bus = MessageBus()
        assert bus.inbound_size == 0
        assert bus.outbound_size == 0
        await bus.publish_inbound(
            InboundMessage(channel="t", sender_id="u", chat_id="c", content="x")
        )
        assert bus.inbound_size == 1
        await bus.publish_outbound(OutboundMessage(channel="t", chat_id="c", content="y"))
        assert bus.outbound_size == 1

    async def test_consume_blocks_until_message(self):
        bus = MessageBus()

        async def producer():
            await asyncio.sleep(0.05)
            await bus.publish_inbound(
                InboundMessage(channel="t", sender_id="u", chat_id="c", content="late")
            )

        asyncio.create_task(producer())
        msg = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
        assert msg.content == "late"
