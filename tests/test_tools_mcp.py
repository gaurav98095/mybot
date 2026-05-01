"""Tests for agent/tools/mcp.py."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mybot.agent.tools.mcp import (
    MCPClient,
    MCPManager,
    MCPProxyTool,
    _format_result,
    _safe_id,
)
from mybot.config.schema import MCPServerConfig


# ---------------------------------------------------------------------------
# _safe_id
# ---------------------------------------------------------------------------

class TestSafeId:
    @pytest.mark.parametrize("input_,expected", [
        ("my-server", "my_server"),
        ("my.server.v2", "my_server_v2"),
        ("server 1", "server_1"),
        ("plain", "plain"),
        ("a-b-c", "a_b_c"),
    ])
    def test_sanitizes(self, input_, expected):
        assert _safe_id(input_) == expected


# ---------------------------------------------------------------------------
# _format_result
# ---------------------------------------------------------------------------

class TestFormatResult:
    def _text_block(self, text: str):
        import mcp.types as t
        b = MagicMock(spec=t.TextContent)
        b.__class__ = t.TextContent
        b.text = text
        return b

    def _image_block(self, mime: str):
        import mcp.types as t
        b = MagicMock(spec=t.ImageContent)
        b.__class__ = t.ImageContent
        b.mimeType = mime
        return b

    def _embedded_text_resource(self, text: str):
        import mcp.types as t
        b = MagicMock(spec=t.EmbeddedResource)
        b.__class__ = t.EmbeddedResource
        res = MagicMock()
        res.text = text
        b.resource = res
        return b

    def _result(self, blocks, is_error=False):
        r = MagicMock()
        r.content = blocks
        r.isError = is_error
        return r

    def test_text_content(self):
        result = self._result([self._text_block("hello")])
        assert _format_result(result) == "hello"

    def test_multiple_text_blocks_joined(self):
        result = self._result([self._text_block("a"), self._text_block("b")])
        assert _format_result(result) == "a\nb"

    def test_image_content_placeholder(self):
        result = self._result([self._image_block("image/png")])
        assert "[image:" in _format_result(result)
        assert "image/png" in _format_result(result)

    def test_embedded_resource_text(self):
        result = self._result([self._embedded_text_resource("resource text")])
        assert "resource text" in _format_result(result)

    def test_is_error_flag_prefixes_output(self):
        result = self._result([self._text_block("boom")], is_error=True)
        output = _format_result(result)
        assert output.startswith("tool error:")
        assert "boom" in output

    def test_empty_content_returns_placeholder(self):
        result = self._result([])
        assert _format_result(result) == "(empty response)"


# ---------------------------------------------------------------------------
# MCPProxyTool
# ---------------------------------------------------------------------------

class TestMCPProxyTool:
    def _make_proxy(self, server_id="my-api", tool_name="get_user",
                     description="Get a user", input_schema=None):
        client = MagicMock()
        client.server_id = server_id
        mcp_tool = MagicMock()
        mcp_tool.name = tool_name
        mcp_tool.description = description
        mcp_tool.inputSchema = input_schema or {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        }
        return MCPProxyTool(client, mcp_tool)

    def test_name_prefixed(self):
        proxy = self._make_proxy(server_id="my-api", tool_name="get_user")
        assert proxy.name == "mcp_my_api__get_user"

    def test_name_safe_id_applied(self):
        proxy = self._make_proxy(server_id="my.server.v2", tool_name="list")
        assert proxy.name == "mcp_my_server_v2__list"

    def test_description_from_tool(self):
        proxy = self._make_proxy(description="Fetches a record")
        assert proxy.description == "Fetches a record"

    def test_description_fallback_when_none(self):
        proxy = self._make_proxy(description=None)
        # Should fall back to a non-empty string
        assert len(proxy.description) > 0

    def test_parameters_from_input_schema(self):
        schema = {"type": "object", "properties": {"x": {"type": "int"}}}
        proxy = self._make_proxy(input_schema=schema)
        assert proxy.parameters == schema

    async def test_execute_delegates_to_client(self):
        client = MagicMock()
        client.server_id = "srv"
        client.call_tool = AsyncMock(return_value="tool output")
        mcp_tool = MagicMock()
        mcp_tool.name = "do_thing"
        mcp_tool.description = "Does a thing"
        mcp_tool.inputSchema = {"type": "object", "properties": {}}
        proxy = MCPProxyTool(client, mcp_tool)

        result = await proxy.execute(param="value")
        client.call_tool.assert_called_once_with("do_thing", {"param": "value"})
        assert result == "tool output"

    def test_to_schema_format(self):
        proxy = self._make_proxy()
        schema = proxy.to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"].startswith("mcp_")


# ---------------------------------------------------------------------------
# MCPClient — transport validation
# ---------------------------------------------------------------------------

class TestMCPClientValidation:
    def _cfg(self, **kwargs) -> MCPServerConfig:
        return MCPServerConfig(**kwargs)

    async def test_unknown_transport_raises(self):
        client = MCPClient("srv", self._cfg(type="grpc"))
        with pytest.raises(ValueError, match="unknown transport"):
            async with client._transport() as _:
                pass

    async def test_stdio_missing_command_raises(self):
        client = MCPClient("srv", self._cfg(type="stdio"))
        with pytest.raises(ValueError, match="command"):
            async with client._transport() as _:
                pass

    async def test_sse_missing_url_raises(self):
        client = MCPClient("srv", self._cfg(type="sse"))
        with pytest.raises(ValueError, match="url"):
            async with client._transport() as _:
                pass

    async def test_http_missing_url_raises(self):
        client = MCPClient("srv", self._cfg(type="http"))
        with pytest.raises(ValueError, match="url"):
            async with client._transport() as _:
                pass


# ---------------------------------------------------------------------------
# MCPManager
# ---------------------------------------------------------------------------

class TestMCPManager:
    async def test_empty_servers_no_tools(self):
        mgr = MCPManager({})
        await mgr.start()
        assert mgr.get_all_tools() == []
        await mgr.stop()

    async def test_failed_server_skipped(self):
        cfg = MCPServerConfig(type="sse", url="http://localhost:19999/sse")
        mgr = MCPManager({"bad": cfg})
        # Should not raise; failure is logged and skipped
        await mgr.start()
        assert mgr.get_all_tools() == []
        await mgr.stop()

    async def test_get_all_tools_aggregates_from_all_clients(self):
        mgr = MCPManager({})

        # Inject pre-connected fake clients
        for sid in ("srv_a", "srv_b"):
            client = MagicMock()
            client.server_id = sid
            mcp_tool = MagicMock()
            mcp_tool.name = f"tool_{sid}"
            mcp_tool.description = "desc"
            mcp_tool.inputSchema = {"type": "object", "properties": {}}
            client.get_proxy_tools.return_value = [MCPProxyTool(client, mcp_tool)]
            mgr._clients[sid] = client

        tools = mgr.get_all_tools()
        assert len(tools) == 2

    async def test_stop_idempotent(self):
        mgr = MCPManager({})
        await mgr.stop()  # stopping before starting should not raise
        await mgr.stop()
