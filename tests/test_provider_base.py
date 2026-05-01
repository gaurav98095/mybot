"""Tests for providers/base.py — retry logic, error classification, message utilities."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from mybot.providers.base import (
    LLMProvider,
    LLMResponse,
    ToolCallRequest,
    GenerationSettings,
)
from tests.conftest import FakeProvider


# ---------------------------------------------------------------------------
# ToolCallRequest
# ---------------------------------------------------------------------------

class TestToolCallRequest:
    def test_to_openai_tool_call(self):
        tc = ToolCallRequest(id="call_1", name="shell", arguments={"command": "ls"})
        result = tc.to_openai_tool_call()
        assert result["id"] == "call_1"
        assert result["type"] == "function"
        assert result["function"]["name"] == "shell"
        assert '"command": "ls"' in result["function"]["arguments"]

    def test_to_openai_tool_call_empty_args(self):
        tc = ToolCallRequest(id="x", name="ping", arguments={})
        result = tc.to_openai_tool_call()
        assert result["function"]["arguments"] == "{}"


# ---------------------------------------------------------------------------
# LLMResponse properties
# ---------------------------------------------------------------------------

class TestLLMResponse:
    def test_has_tool_calls_false(self):
        r = LLMResponse(content="hello")
        assert r.has_tool_calls is False

    def test_has_tool_calls_true(self):
        tc = ToolCallRequest(id="x", name="tool", arguments={})
        r = LLMResponse(content=None, tool_calls=[tc])
        assert r.has_tool_calls is True

    def test_should_execute_tools_stop(self):
        tc = ToolCallRequest(id="x", name="tool", arguments={})
        r = LLMResponse(content=None, tool_calls=[tc], finish_reason="stop")
        assert r.should_execute_tools is True

    def test_should_execute_tools_tool_calls_reason(self):
        tc = ToolCallRequest(id="x", name="tool", arguments={})
        r = LLMResponse(content=None, tool_calls=[tc], finish_reason="tool_calls")
        assert r.should_execute_tools is True

    def test_should_not_execute_on_error(self):
        tc = ToolCallRequest(id="x", name="tool", arguments={})
        r = LLMResponse(content="err", tool_calls=[tc], finish_reason="error")
        assert r.should_execute_tools is False

    def test_should_not_execute_on_refusal(self):
        tc = ToolCallRequest(id="x", name="tool", arguments={})
        r = LLMResponse(content="no", tool_calls=[tc], finish_reason="refusal")
        assert r.should_execute_tools is False

    def test_should_not_execute_without_tool_calls(self):
        r = LLMResponse(content="hi", finish_reason="stop")
        assert r.should_execute_tools is False


# ---------------------------------------------------------------------------
# Transient error detection
# ---------------------------------------------------------------------------

class TestTransientErrorDetection:
    @pytest.mark.parametrize("text,expected", [
        ("Error 429: rate limit exceeded", True),
        ("HTTP 500 server error", True),
        ("overloaded, please retry", True),
        ("connection reset by peer", True),
        ("request timed out", True),
        ("502 bad gateway", True),
        ("invalid_api_key", False),
        ("your message is too long", False),
        ("invalid request body", False),
    ])
    def test_is_transient_error(self, text, expected):
        assert FakeProvider._is_transient_error(text) is expected

    def test_error_should_retry_overrides(self):
        r = LLMResponse(content="invalid_api_key", finish_reason="error",
                        error_should_retry=True)
        assert FakeProvider._is_transient_response(r) is True

    def test_error_should_not_retry_overrides(self):
        r = LLMResponse(content="rate limit", finish_reason="error",
                        error_should_retry=False)
        assert FakeProvider._is_transient_response(r) is False

    def test_status_500_is_transient(self):
        r = LLMResponse(content="server error", finish_reason="error",
                        error_status_code=500)
        assert FakeProvider._is_transient_response(r) is True

    def test_status_401_not_transient(self):
        r = LLMResponse(content="unauthorized", finish_reason="error",
                        error_status_code=401)
        assert FakeProvider._is_transient_response(r) is False

    def test_timeout_kind_is_transient(self):
        r = LLMResponse(content="something", finish_reason="error",
                        error_kind="timeout")
        assert FakeProvider._is_transient_response(r) is True

    def test_connection_kind_is_transient(self):
        r = LLMResponse(content="something", finish_reason="error",
                        error_kind="connection")
        assert FakeProvider._is_transient_response(r) is True


# ---------------------------------------------------------------------------
# 429 retryability
# ---------------------------------------------------------------------------

class TestRetryable429:
    def test_insufficient_quota_not_retryable(self):
        r = LLMResponse(content="insufficient_quota", finish_reason="error",
                        error_status_code=429,
                        error_type="insufficient_quota")
        assert FakeProvider._is_retryable_429_response(r) is False

    def test_rate_limit_exceeded_retryable(self):
        r = LLMResponse(content="rate_limit_exceeded", finish_reason="error",
                        error_status_code=429,
                        error_code="rate_limit_exceeded")
        assert FakeProvider._is_retryable_429_response(r) is True

    def test_billing_hard_limit_not_retryable(self):
        r = LLMResponse(
            content="billing hard limit reached", finish_reason="error",
            error_status_code=429,
        )
        assert FakeProvider._is_retryable_429_response(r) is False

    def test_unknown_429_defaults_to_retry(self):
        r = LLMResponse(content="too many requests", finish_reason="error",
                        error_status_code=429)
        assert FakeProvider._is_retryable_429_response(r) is True


# ---------------------------------------------------------------------------
# Retry-After parsing
# ---------------------------------------------------------------------------

class TestRetryAfterParsing:
    @pytest.mark.parametrize("text,expected", [
        ("retry after 30 seconds", 30.0),
        ("retry after 500ms", 0.5),
        ("try again in 2 minutes", 120.0),
        ("retry after 1s", 1.0),
        ("retry-after: 45", 45.0),
        ("no retry info here", None),
    ])
    def test_extract_retry_after(self, text, expected):
        result = FakeProvider._extract_retry_after(text)
        if expected is None:
            assert result is None
        else:
            assert abs(result - expected) < 0.01

    def test_extract_from_retry_after_header(self):
        headers = {"retry-after": "60"}
        result = FakeProvider._extract_retry_after_from_headers(headers)
        assert result == 60.0

    def test_extract_from_retry_after_ms_header(self):
        headers = {"retry-after-ms": "2000"}
        result = FakeProvider._extract_retry_after_from_headers(headers)
        assert abs(result - 2.0) < 0.01

    def test_no_headers(self):
        assert FakeProvider._extract_retry_after_from_headers(None) is None
        assert FakeProvider._extract_retry_after_from_headers({}) is None


# ---------------------------------------------------------------------------
# Message sanitization
# ---------------------------------------------------------------------------

class TestSanitizeEmptyContent:
    def test_empty_string_becomes_empty_placeholder(self):
        msgs = [{"role": "user", "content": ""}]
        result = FakeProvider._sanitize_empty_content(msgs)
        assert result[0]["content"] == "(empty)"

    def test_nonempty_string_unchanged(self):
        msgs = [{"role": "user", "content": "hello"}]
        result = FakeProvider._sanitize_empty_content(msgs)
        assert result[0]["content"] == "hello"

    def test_empty_text_block_stripped(self):
        msgs = [{"role": "user", "content": [{"type": "text", "text": ""}]}]
        result = FakeProvider._sanitize_empty_content(msgs)
        # empty text block removed → content becomes "(empty)"
        assert result[0]["content"] == "(empty)"

    def test_meta_field_removed(self):
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": "hello", "_meta": {"path": "/x"}}
        ]}]
        result = FakeProvider._sanitize_empty_content(msgs)
        block = result[0]["content"][0]
        assert "_meta" not in block
        assert block["text"] == "hello"

    def test_dict_content_wrapped_in_list(self):
        msgs = [{"role": "user", "content": {"type": "text", "text": "hi"}}]
        result = FakeProvider._sanitize_empty_content(msgs)
        assert isinstance(result[0]["content"], list)


# ---------------------------------------------------------------------------
# Image stripping
# ---------------------------------------------------------------------------

class TestStripImageContent:
    def test_strips_image_url_block(self):
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": "see this"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ]}]
        result = FakeProvider._strip_image_content(msgs)
        assert result is not None
        content = result[0]["content"]
        assert all(b.get("type") != "image_url" for b in content)
        assert any(b.get("type") == "text" for b in content)

    def test_no_images_returns_none(self):
        msgs = [{"role": "user", "content": "plain text"}]
        assert FakeProvider._strip_image_content(msgs) is None

    def test_image_replaced_with_placeholder(self):
        msgs = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": ""}}
        ]}]
        result = FakeProvider._strip_image_content(msgs)
        assert result[0]["content"][0]["text"] == "[image omitted]"


# ---------------------------------------------------------------------------
# Tool cache marker indices
# ---------------------------------------------------------------------------

class TestToolCacheMarkerIndices:
    def _tool(self, name: str) -> dict:
        return {"type": "function", "function": {"name": name}}

    def test_empty_tools(self):
        assert FakeProvider._tool_cache_marker_indices([]) == []

    def test_single_builtin(self):
        tools = [self._tool("shell")]
        assert FakeProvider._tool_cache_marker_indices(tools) == [0]

    def test_multiple_builtins_marks_last(self):
        tools = [self._tool("shell"), self._tool("web_search")]
        indices = FakeProvider._tool_cache_marker_indices(tools)
        assert 1 in indices  # last builtin

    def test_mcp_tool_at_end_marks_both(self):
        tools = [self._tool("shell"), self._tool("mcp_srv__do_thing")]
        indices = FakeProvider._tool_cache_marker_indices(tools)
        # both the last builtin and the last overall should be marked
        assert 0 in indices
        assert 1 in indices


# ---------------------------------------------------------------------------
# chat_with_retry behaviour
# ---------------------------------------------------------------------------

class TestChatWithRetry:
    async def test_success_on_first_try(self):
        provider = FakeProvider([LLMResponse(content="done")])
        result = await provider.chat_with_retry(
            messages=[{"role": "user", "content": "hi"}]
        )
        assert result.content == "done"
        assert len(provider.calls) == 1

    async def test_retries_on_transient_error(self):
        responses = [
            LLMResponse(content="Error 429: rate limit", finish_reason="error",
                        error_status_code=429, error_code="rate_limit_exceeded"),
            LLMResponse(content="success"),
        ]
        provider = FakeProvider(responses)
        with patch.object(provider, "_sleep_with_heartbeat", new=AsyncMock()):
            result = await provider.chat_with_retry(
                messages=[{"role": "user", "content": "hi"}]
            )
        assert result.content == "success"
        assert len(provider.calls) == 2

    async def test_no_retry_on_non_transient_error(self):
        responses = [
            LLMResponse(content="invalid_api_key", finish_reason="error",
                        error_status_code=401),
        ]
        provider = FakeProvider(responses)
        result = await provider.chat_with_retry(
            messages=[{"role": "user", "content": "hi"}]
        )
        assert result.finish_reason == "error"
        assert len(provider.calls) == 1

    async def test_gives_up_after_max_retries(self):
        error = LLMResponse(
            content="Error 503: overloaded", finish_reason="error", error_status_code=503
        )
        provider = FakeProvider([error] * 10)
        with patch.object(provider, "_sleep_with_heartbeat", new=AsyncMock()):
            result = await provider.chat_with_retry(
                messages=[{"role": "user", "content": "hi"}]
            )
        assert result.finish_reason == "error"
        # standard mode: 3 delays → 4 attempts max
        assert len(provider.calls) <= 5
