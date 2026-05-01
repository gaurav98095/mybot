"""Tests for agent/classifier.py — PreTurnClassifier."""

from unittest.mock import AsyncMock, patch

import pytest

from mybot.agent.classifier import PreTurnClassifier, _SYSTEM
from mybot.config.schema import ClassifierConfig
from mybot.providers.base import LLMResponse
from tests.conftest import FakeProvider


@pytest.fixture
def cfg():
    return ClassifierConfig(
        enabled=True,
        classifier_model="anthropic/claude-haiku-4-5-20251001",
        simple_model="anthropic/claude-haiku-4-5-20251001",
        medium_model="anthropic/claude-sonnet-4-6",
        complex_model="anthropic/claude-opus-4-5",
    )


@pytest.fixture
def classifier(cfg):
    provider = FakeProvider()
    return PreTurnClassifier(provider, cfg)


# ---------------------------------------------------------------------------
# _parse
# ---------------------------------------------------------------------------

class TestParse:
    @pytest.mark.parametrize("raw,expected", [
        ("simple", "simple"),
        ("SIMPLE", "simple"),
        ("  simple  ", "simple"),
        ("complex", "complex"),
        ("medium", "medium"),
        ("This task is simple.", "simple"),
        ("I think this is complex.", "complex"),
        ("definitely medium effort", "medium"),
        ("", "complex"),          # empty → safe fallback
        (None, "complex"),         # None → safe fallback
        ("dunno", "complex"),      # unrecognised → safe fallback
    ])
    def test_parse(self, raw, expected):
        assert PreTurnClassifier._parse(raw) == expected


# ---------------------------------------------------------------------------
# select_model — tier → model name mapping
# ---------------------------------------------------------------------------

class TestSelectModel:
    async def test_simple_returns_haiku(self, cfg):
        provider = FakeProvider([LLMResponse(content="simple")])
        c = PreTurnClassifier(provider, cfg)
        model = await c.select_model("what is 2+2", [])
        assert model == cfg.simple_model

    async def test_medium_returns_sonnet(self, cfg):
        provider = FakeProvider([LLMResponse(content="medium")])
        c = PreTurnClassifier(provider, cfg)
        model = await c.select_model("explain how async works", [])
        assert model == cfg.medium_model

    async def test_complex_returns_opus(self, cfg):
        provider = FakeProvider([LLMResponse(content="complex")])
        c = PreTurnClassifier(provider, cfg)
        model = await c.select_model("implement a full auth system", [])
        assert model == cfg.complex_model

    async def test_fallback_on_llm_error_returns_complex(self, cfg):
        from mybot.providers.base import GenerationSettings
        from tests.conftest import FakeProvider
        provider = FakeProvider()
        provider.chat = AsyncMock(side_effect=RuntimeError("network error"))
        c = PreTurnClassifier(provider, cfg)
        model = await c.select_model("any message", [])
        assert model == cfg.complex_model

    async def test_unrecognised_response_returns_complex(self, cfg):
        provider = FakeProvider([LLMResponse(content="I cannot decide")])
        c = PreTurnClassifier(provider, cfg)
        model = await c.select_model("some task", [])
        assert model == cfg.complex_model


# ---------------------------------------------------------------------------
# _build_messages
# ---------------------------------------------------------------------------

class TestBuildMessages:
    def test_system_prompt_first(self, classifier):
        msgs = classifier._build_messages("hello", [])
        assert msgs[0]["role"] == "system"
        assert "simple" in msgs[0]["content"]
        assert "complex" in msgs[0]["content"]

    def test_user_message_last(self, classifier):
        msgs = classifier._build_messages("what is python?", [])
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "what is python?"

    def test_history_included(self, classifier):
        history = [
            {"role": "user", "content": "previous question"},
            {"role": "assistant", "content": "previous answer"},
        ]
        msgs = classifier._build_messages("follow-up", history)
        roles = [m["role"] for m in msgs]
        assert "user" in roles
        assert "assistant" in roles

    def test_history_truncated_to_last_4(self, classifier):
        history = [
            {"role": "user", "content": f"msg {i}"}
            for i in range(10)
        ]
        msgs = classifier._build_messages("new", history)
        # system + up to 4 history entries + current user = max 6
        assert len(msgs) <= 6

    def test_long_message_truncated(self, classifier):
        long_msg = "x" * 5000
        msgs = classifier._build_messages(long_msg, [])
        assert len(msgs[-1]["content"]) <= 1000

    def test_long_history_content_truncated(self, classifier):
        history = [{"role": "user", "content": "y" * 5000}]
        msgs = classifier._build_messages("q", history)
        history_msg = next(m for m in msgs if m["role"] == "user" and m["content"] != "q")
        assert len(history_msg["content"]) <= 400

    def test_non_string_history_content_skipped(self, classifier):
        history = [
            {"role": "user", "content": [{"type": "text", "text": "block content"}]},
            {"role": "assistant", "content": "text reply"},
        ]
        msgs = classifier._build_messages("follow", history)
        # List content should be skipped; only string content included
        for m in msgs[1:-1]:
            assert isinstance(m["content"], str)

    def test_tool_role_excluded(self, classifier):
        history = [
            {"role": "user", "content": "run this"},
            {"role": "tool", "content": "shell output"},
            {"role": "assistant", "content": "done"},
        ]
        msgs = classifier._build_messages("next", history)
        assert all(m["role"] != "tool" for m in msgs)


# ---------------------------------------------------------------------------
# classifier_model used for the LLM call
# ---------------------------------------------------------------------------

class TestClassifierModelUsed:
    async def test_uses_configured_classifier_model(self, cfg):
        provider = FakeProvider([LLMResponse(content="simple")])
        c = PreTurnClassifier(provider, cfg)
        await c.select_model("hi", [])
        assert provider.calls[0]["model"] == cfg.classifier_model

    async def test_uses_haiku_not_default_model(self, cfg):
        cfg.classifier_model = "anthropic/claude-haiku-4-5-20251001"
        provider = FakeProvider([LLMResponse(content="medium")])
        c = PreTurnClassifier(provider, cfg)
        await c.select_model("explain something", [])
        assert "haiku" in provider.calls[0]["model"]


# ---------------------------------------------------------------------------
# AgentLoop integration — classifier disabled by default
# ---------------------------------------------------------------------------

class TestAgentLoopClassifierIntegration:
    async def test_disabled_by_default_no_classifier(self):
        from mybot.agent.loop import AgentLoop
        from mybot.bus.queue import MessageBus
        from mybot.config.schema import ClassifierConfig

        provider = FakeProvider([LLMResponse(content="hi")])
        loop = AgentLoop(
            provider=provider,
            model="fake/model",
            bus=MessageBus(),
            classifier_config=ClassifierConfig(enabled=False),
        )
        assert loop._classifier is None

    async def test_enabled_creates_classifier(self):
        from mybot.agent.loop import AgentLoop
        from mybot.bus.queue import MessageBus
        from mybot.config.schema import ClassifierConfig

        provider = FakeProvider([LLMResponse(content="hi")])
        loop = AgentLoop(
            provider=provider,
            model="fake/model",
            bus=MessageBus(),
            classifier_config=ClassifierConfig(enabled=True),
        )
        assert loop._classifier is not None

    async def test_classifier_model_used_for_turn(self):
        """When enabled, the model returned by the classifier is used for the turn."""
        import asyncio
        from mybot.agent.loop import AgentLoop
        from mybot.bus.events import InboundMessage
        from mybot.bus.queue import MessageBus
        from mybot.config.schema import ClassifierConfig
        from mybot.providers.base import LLMResponse

        # classifier call → "simple"; main call → final answer
        provider = FakeProvider([
            LLMResponse(content="simple"),   # classifier response
            LLMResponse(content="2"),        # main response
        ])
        cfg = ClassifierConfig(
            enabled=True,
            classifier_model="anthropic/claude-haiku-4-5-20251001",
            simple_model="anthropic/claude-haiku-4-5-20251001",
            medium_model="anthropic/claude-sonnet-4-6",
            complex_model="anthropic/claude-opus-4-5",
        )
        bus = MessageBus()
        loop = AgentLoop(provider=provider, model="default/model", bus=bus,
                         classifier_config=cfg)

        await bus.publish_inbound(
            InboundMessage(channel="t", sender_id="u", chat_id="c", content="what is 1+1")
        )
        loop_task = asyncio.create_task(loop.run())
        reply = await asyncio.wait_for(bus.consume_outbound(), timeout=5.0)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        assert reply.content == "2"
        # Second call (main turn) should use the simple_model (haiku)
        main_call = provider.calls[1]
        assert main_call["model"] == cfg.simple_model
