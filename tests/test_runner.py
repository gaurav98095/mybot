"""Tests for agent/runner.py — AgentRunner tool-call loop."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mybot.agent.runner import MAX_TOOL_ROUNDS, AgentRunner
from mybot.agent.tools.base import Tool
from mybot.agent.tools.registry import ToolRegistry
from mybot.providers.base import LLMResponse, ToolCallRequest
from tests.conftest import FakeProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tool_call(name: str, arguments: dict | None = None, id: str = "tc_001"):
    return ToolCallRequest(id=id, name=name, arguments=arguments or {})


def _tool_response(content: str, tool_name: str = "echo") -> LLMResponse:
    """LLM response that requests a tool call."""
    return LLMResponse(
        content=None,
        tool_calls=[_tool_call(tool_name)],
        finish_reason="tool_calls",
    )


class ConstantTool(Tool):
    """Tool that always returns the same string."""

    def __init__(self, return_value: str = "tool_output"):
        self._return = return_value
        self.call_count = 0

    @property
    def name(self) -> str:
        return "constant"

    @property
    def description(self) -> str:
        return "Returns a constant."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        self.call_count += 1
        return self._return


class ErrorTool(Tool):
    @property
    def name(self) -> str:
        return "error_tool"

    @property
    def description(self) -> str:
        return "Always raises."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        raise RuntimeError("tool exploded")


def _registry(*tools: Tool) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAgentRunnerNoTools:
    async def test_single_llm_call_returned(self):
        provider = FakeProvider([LLMResponse(content="Hello!")])
        runner = AgentRunner(provider, "fake/model")
        result = await runner.run([{"role": "user", "content": "hi"}])
        assert result.content == "Hello!"
        assert len(provider.calls) == 1

    async def test_messages_passed_to_provider(self):
        provider = FakeProvider([LLMResponse(content="ok")])
        runner = AgentRunner(provider, "fake/model")
        msgs = [{"role": "user", "content": "what's up"}]
        await runner.run(msgs)
        assert provider.calls[0]["messages"][0]["content"] == "what's up"


class TestAgentRunnerToolCall:
    async def test_tool_called_and_result_appended(self):
        tool = ConstantTool("echo output")
        provider = FakeProvider([
            _tool_response("", tool_name="constant"),
            LLMResponse(content="Done after tool"),
        ])
        runner = AgentRunner(provider, "fake/model", _registry(tool))

        msgs = [{"role": "user", "content": "use tool"}]
        result = await runner.run(msgs)

        assert result.content == "Done after tool"
        assert tool.call_count == 1
        # Messages should contain the tool result
        assert any(m.get("role") == "tool" for m in msgs)

    async def test_unknown_tool_returns_error_result(self):
        provider = FakeProvider([
            _tool_response("", tool_name="nonexistent"),
            LLMResponse(content="Got the error"),
        ])
        runner = AgentRunner(provider, "fake/model", _registry())

        msgs = [{"role": "user", "content": "use unknown tool"}]
        await runner.run(msgs)

        tool_msg = next(m for m in msgs if m.get("role") == "tool")
        assert "unknown tool" in tool_msg["content"].lower()

    async def test_tool_exception_becomes_error_string(self):
        provider = FakeProvider([
            _tool_response("", tool_name="error_tool"),
            LLMResponse(content="handled"),
        ])
        runner = AgentRunner(provider, "fake/model", _registry(ErrorTool()))

        msgs = [{"role": "user", "content": "cause error"}]
        await runner.run(msgs)

        tool_msg = next(m for m in msgs if m.get("role") == "tool")
        assert "error" in tool_msg["content"].lower()
        assert "exploded" in tool_msg["content"].lower()

    async def test_multiple_tool_rounds(self):
        tool = ConstantTool("result")
        # Two tool calls before final response
        provider = FakeProvider([
            _tool_response("", tool_name="constant"),
            _tool_response("", tool_name="constant"),
            LLMResponse(content="final"),
        ])
        runner = AgentRunner(provider, "fake/model", _registry(tool))

        result = await runner.run([{"role": "user", "content": "go"}])
        assert result.content == "final"
        assert tool.call_count == 2

    async def test_max_tool_rounds_stops_loop(self):
        tool = ConstantTool()
        # Provider always requests another tool call — runner must stop at MAX_TOOL_ROUNDS
        always_tool = [_tool_response("", tool_name="constant")] * (MAX_TOOL_ROUNDS + 5)
        provider = FakeProvider(always_tool)
        runner = AgentRunner(provider, "fake/model", _registry(tool))

        result = await runner.run([{"role": "user", "content": "loop"}])
        # Loop runs MAX_TOOL_ROUNDS + 1 iterations before stopping
        assert tool.call_count <= MAX_TOOL_ROUNDS + 1

    async def test_tool_schemas_sent_to_provider(self):
        tool = ConstantTool()
        provider = FakeProvider([LLMResponse(content="ok")])
        runner = AgentRunner(provider, "fake/model", _registry(tool))

        await runner.run([{"role": "user", "content": "go"}])
        tools_sent = provider.calls[0]["tools"]
        assert tools_sent is not None
        assert any(t["function"]["name"] == "constant" for t in tools_sent)

    async def test_thinking_blocks_forwarded(self):
        thinking_response = LLMResponse(
            content=None,
            tool_calls=[_tool_call("constant")],
            finish_reason="tool_calls",
            thinking_blocks=[{"type": "thinking", "thinking": "hmm", "signature": "s"}],
        )
        provider = FakeProvider([thinking_response, LLMResponse(content="done")])
        runner = AgentRunner(provider, "fake/model", _registry(ConstantTool()))

        msgs = [{"role": "user", "content": "think"}]
        await runner.run(msgs)

        # The assistant message with thinking blocks should be in history
        assistant_msg = next(m for m in msgs if m.get("role") == "assistant")
        assert assistant_msg.get("thinking_blocks") is not None
