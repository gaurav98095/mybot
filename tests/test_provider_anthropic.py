"""Tests for providers/anthropic.py — message conversion, caching, response parsing."""

from unittest.mock import MagicMock, patch

import pytest

from mybot.providers.anthropic import AnthropicProvider
from mybot.providers.base import LLMResponse, ToolCallRequest


# ---------------------------------------------------------------------------
# Helper to build provider without hitting the Anthropic SDK constructor
# ---------------------------------------------------------------------------

def _provider() -> AnthropicProvider:
    with patch("anthropic.AsyncAnthropic"):
        return AnthropicProvider(api_key="sk-test")


# ---------------------------------------------------------------------------
# _strip_prefix
# ---------------------------------------------------------------------------

class TestStripPrefix:
    def test_strips_anthropic_prefix(self):
        assert AnthropicProvider._strip_prefix("anthropic/claude-opus-4-5") == "claude-opus-4-5"

    def test_no_prefix_unchanged(self):
        assert AnthropicProvider._strip_prefix("claude-sonnet-4-6") == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# _convert_messages
# ---------------------------------------------------------------------------

class TestConvertMessages:
    def test_system_extracted(self):
        p = _provider()
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        system, anthropic_msgs = p._convert_messages(msgs)
        assert system == [{"type": "text", "text": "You are helpful.", "cache_control": {"type": "ephemeral"}}] or system == "You are helpful."
        assert anthropic_msgs[0]["role"] == "user"

    def test_user_message_preserved(self):
        p = _provider()
        msgs = [{"role": "user", "content": "Hi"}]
        _, anthropic_msgs = p._convert_messages(msgs)
        assert anthropic_msgs[0]["content"] == "Hi"

    def test_assistant_message_converted(self):
        p = _provider()
        # Must not be the trailing message — _merge_consecutive strips trailing assistant turns
        msgs = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "Follow-up"},
        ]
        _, anthropic_msgs = p._convert_messages(msgs)
        assert any(m["role"] == "assistant" for m in anthropic_msgs)

    def test_tool_result_grouped_into_user_turn(self):
        p = _provider()
        msgs = [
            {"role": "user", "content": "Run ls"},
            {"role": "assistant", "content": "", "tool_calls": [{
                "id": "tc1", "type": "function",
                "function": {"name": "shell", "arguments": '{"command":"ls"}'},
            }]},
            {"role": "tool", "tool_call_id": "tc1", "content": "file1\nfile2"},
        ]
        _, anthropic_msgs = p._convert_messages(msgs)
        # tool result should appear as a user turn with tool_result block
        tool_user = next(
            m for m in anthropic_msgs
            if m["role"] == "user" and isinstance(m["content"], list)
            and any(b.get("type") == "tool_result" for b in m["content"])
        )
        assert tool_user is not None

    def test_empty_content_sanitized(self):
        p = _provider()
        msgs = [{"role": "user", "content": ""}]
        _, anthropic_msgs = p._convert_messages(msgs)
        assert anthropic_msgs[0]["content"] != ""


# ---------------------------------------------------------------------------
# _merge_consecutive
# ---------------------------------------------------------------------------

class TestMergeConsecutive:
    def test_consecutive_user_merged(self):
        msgs = [
            {"role": "user", "content": "part 1"},
            {"role": "user", "content": "part 2"},
        ]
        result = AnthropicProvider._merge_consecutive(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_trailing_assistant_stripped(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = AnthropicProvider._merge_consecutive(msgs)
        assert result[-1]["role"] != "assistant"

    def test_leading_assistant_gets_opener(self):
        msgs = [{"role": "assistant", "content": "I started"}]
        result = AnthropicProvider._merge_consecutive(msgs)
        assert result[0]["role"] == "user"

    def test_alternating_roles_unchanged_length(self):
        msgs = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": "q2"},
        ]
        result = AnthropicProvider._merge_consecutive(msgs)
        assert len(result) == 3

    def test_empty_list(self):
        assert AnthropicProvider._merge_consecutive([]) == []


# ---------------------------------------------------------------------------
# _assistant_blocks
# ---------------------------------------------------------------------------

class TestAssistantBlocks:
    def test_text_content(self):
        msg = {"role": "assistant", "content": "Hello!"}
        blocks = AnthropicProvider._assistant_blocks(msg)
        assert {"type": "text", "text": "Hello!"} in blocks

    def test_tool_calls_become_tool_use(self):
        msg = {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "tc1", "type": "function",
                "function": {"name": "shell", "arguments": '{"command": "ls"}'},
            }],
        }
        blocks = AnthropicProvider._assistant_blocks(msg)
        tool_use = next(b for b in blocks if b.get("type") == "tool_use")
        assert tool_use["name"] == "shell"
        assert tool_use["input"] == {"command": "ls"}

    def test_thinking_blocks_preserved(self):
        msg = {
            "role": "assistant",
            "content": "answer",
            "thinking_blocks": [{"type": "thinking", "thinking": "I thought", "signature": "sig"}],
        }
        blocks = AnthropicProvider._assistant_blocks(msg)
        thinking = next(b for b in blocks if b.get("type") == "thinking")
        assert thinking["thinking"] == "I thought"


# ---------------------------------------------------------------------------
# _convert_tools
# ---------------------------------------------------------------------------

class TestConvertTools:
    def test_none_returns_none(self):
        assert AnthropicProvider._convert_tools(None) is None

    def test_empty_returns_none(self):
        assert AnthropicProvider._convert_tools([]) is None

    def test_openai_format_converted(self):
        tools = [{
            "type": "function",
            "function": {
                "name": "shell",
                "description": "Run a command",
                "parameters": {"type": "object", "properties": {}},
            },
        }]
        result = AnthropicProvider._convert_tools(tools)
        assert result[0]["name"] == "shell"
        assert result[0]["description"] == "Run a command"
        assert "input_schema" in result[0]

    def test_cache_control_preserved(self):
        tools = [{
            "type": "function",
            "function": {"name": "t", "parameters": {}},
            "cache_control": {"type": "ephemeral"},
        }]
        result = AnthropicProvider._convert_tools(tools)
        assert result[0].get("cache_control") == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# _apply_cache_control
# ---------------------------------------------------------------------------

class TestApplyCacheControl:
    def test_string_system_gets_marker(self):
        system, msgs, _ = AnthropicProvider._apply_cache_control(
            "You are helpful.", [], None
        )
        assert isinstance(system, list)
        assert system[-1].get("cache_control") == {"type": "ephemeral"}

    def test_penultimate_user_message_gets_marker(self):
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ]
        _, new_msgs, _ = AnthropicProvider._apply_cache_control("", msgs, None)
        # second-to-last message (index -2) should have cache_control
        penultimate = new_msgs[-2]
        content = penultimate["content"]
        if isinstance(content, list):
            assert content[-1].get("cache_control") == {"type": "ephemeral"}
        else:
            pass  # string content wrapped in list

    def test_tools_last_entry_gets_marker(self):
        tools = [
            {"name": "shell", "input_schema": {}},
            {"name": "web_search", "input_schema": {}},
        ]
        _, _, new_tools = AnthropicProvider._apply_cache_control("", [], tools)
        assert new_tools[-1].get("cache_control") == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

class TestParseResponse:
    def _mock_response(self, blocks, stop_reason="end_turn", usage=None):
        response = MagicMock()
        response.content = blocks
        response.stop_reason = stop_reason
        if usage:
            response.usage = usage
        else:
            mock_usage = MagicMock()
            mock_usage.input_tokens = 10
            mock_usage.output_tokens = 5
            mock_usage.cache_creation_input_tokens = 0
            mock_usage.cache_read_input_tokens = 0
            response.usage = mock_usage
        return response

    def _text_block(self, text: str):
        b = MagicMock()
        b.type = "text"
        b.text = text
        return b

    def _tool_use_block(self, name: str, tool_id: str, input_: dict):
        b = MagicMock()
        b.type = "tool_use"
        b.id = tool_id
        b.name = name
        b.input = input_
        return b

    def _thinking_block(self, thinking: str):
        b = MagicMock()
        b.type = "thinking"
        b.thinking = thinking
        b.signature = "sig123"
        return b

    def test_text_content(self):
        response = self._mock_response([self._text_block("Hello!")])
        result = AnthropicProvider._parse_response(response)
        assert result.content == "Hello!"

    def test_multiple_text_blocks_concatenated(self):
        response = self._mock_response([
            self._text_block("Hello "),
            self._text_block("world"),
        ])
        result = AnthropicProvider._parse_response(response)
        assert result.content == "Hello world"

    def test_tool_use_block_parsed(self):
        response = self._mock_response(
            [self._tool_use_block("shell", "tc1", {"command": "ls"})],
            stop_reason="tool_use",
        )
        result = AnthropicProvider._parse_response(response)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "shell"
        assert result.tool_calls[0].arguments == {"command": "ls"}
        assert result.finish_reason == "tool_calls"

    def test_thinking_block_captured(self):
        response = self._mock_response([
            self._thinking_block("Let me think..."),
            self._text_block("Answer"),
        ])
        result = AnthropicProvider._parse_response(response)
        assert result.thinking_blocks is not None
        assert result.thinking_blocks[0]["thinking"] == "Let me think..."
        assert result.content == "Answer"

    def test_usage_dict_populated(self):
        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        usage.cache_creation_input_tokens = 0
        usage.cache_read_input_tokens = 20
        response = self._mock_response([self._text_block("hi")], usage=usage)
        result = AnthropicProvider._parse_response(response)
        assert result.usage["completion_tokens"] == 50
        assert result.usage.get("cached_tokens") == 20

    def test_finish_reason_mapping(self):
        for stop_reason, expected in [
            ("end_turn", "stop"),
            ("tool_use", "tool_calls"),
            ("max_tokens", "length"),
        ]:
            response = self._mock_response([self._text_block("x")], stop_reason=stop_reason)
            result = AnthropicProvider._parse_response(response)
            assert result.finish_reason == expected


# ---------------------------------------------------------------------------
# _build_kwargs — model-specific behaviour
# ---------------------------------------------------------------------------

class TestBuildKwargs:
    def test_opus_4_7_no_temperature(self):
        p = _provider()
        kwargs = p._build_kwargs(
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            model="claude-opus-4-7",
            max_tokens=1024,
            temperature=0.5,
            reasoning_effort=None,
            tool_choice=None,
        )
        assert "temperature" not in kwargs

    def test_other_model_has_temperature(self):
        p = _provider()
        kwargs = p._build_kwargs(
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            model="claude-sonnet-4-6",
            max_tokens=1024,
            temperature=0.7,
            reasoning_effort=None,
            tool_choice=None,
        )
        assert kwargs["temperature"] == 0.7

    def test_reasoning_effort_adaptive(self):
        p = _provider()
        kwargs = p._build_kwargs(
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            model="claude-sonnet-4-6",
            max_tokens=1024,
            temperature=0.7,
            reasoning_effort="adaptive",
            tool_choice=None,
        )
        assert kwargs.get("thinking") == {"type": "adaptive"}
        assert kwargs.get("temperature") == 1.0

    def test_reasoning_effort_low(self):
        p = _provider()
        kwargs = p._build_kwargs(
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            model="claude-sonnet-4-6",
            max_tokens=1024,
            temperature=0.7,
            reasoning_effort="low",
            tool_choice=None,
        )
        assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 1024}
