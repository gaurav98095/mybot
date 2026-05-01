"""MCP (Model Context Protocol) tool integration.

Connects to any MCP server (stdio, SSE, or streamable HTTP) and exposes
every tool it advertises as a first-class mybot Tool. Names are prefixed
with ``mcp_<server_id>__`` so they are namespaced and picked up by the
prompt-cache marker logic in providers/base.py.
"""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from typing import Any

from loguru import logger

from mybot.agent.tools.base import Tool


def _safe_id(server_id: str) -> str:
    """Sanitize a server ID so it's safe to use inside a tool name."""
    return re.sub(r"[^a-zA-Z0-9]", "_", server_id)


class MCPProxyTool(Tool):
    """Wraps a single MCP server tool as a mybot Tool."""

    def __init__(self, client: MCPClient, mcp_tool: Any) -> None:
        self._client = client
        self._mcp_tool = mcp_tool
        self._name = f"mcp_{_safe_id(client.server_id)}__{mcp_tool.name}"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return (
            self._mcp_tool.description
            or f"MCP tool '{self._mcp_tool.name}' from server '{self._client.server_id}'"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return dict(self._mcp_tool.inputSchema)

    async def execute(self, **kwargs: Any) -> str:
        return await self._client.call_tool(self._mcp_tool.name, kwargs)


class MCPClient:
    """Manages a persistent connection to one MCP server.

    Usage::

        client = MCPClient("my-server", config)
        await client.start()          # connects, discovers tools
        tools = client.get_proxy_tools()
        ...
        await client.stop()
    """

    def __init__(self, server_id: str, config: Any) -> None:
        self.server_id = server_id
        self._config = config
        self._session: Any = None
        self._task: asyncio.Task | None = None
        self._ready_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._error: Exception | None = None
        self._mcp_tools: list[Any] = []

    # ------------------------------------------------------------------
    # Transport wiring
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def _transport(self):
        cfg = self._config
        kind = (cfg.type or "").lower()

        if kind == "stdio":
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            if not cfg.command:
                raise ValueError(
                    f"MCP server '{self.server_id}': 'command' required for stdio"
                )
            params = StdioServerParameters(
                command=cfg.command,
                args=list(cfg.args or []),
                env=cfg.env or None,
                cwd=cfg.cwd or None,
            )
            async with stdio_client(params) as (r, w):
                yield r, w

        elif kind == "sse":
            from mcp.client.sse import sse_client

            if not cfg.url:
                raise ValueError(
                    f"MCP server '{self.server_id}': 'url' required for sse"
                )
            async with sse_client(url=cfg.url, headers=cfg.headers or {}) as (r, w):
                yield r, w

        elif kind in ("http", "streamable_http"):
            from mcp.client.streamable_http import streamablehttp_client

            if not cfg.url:
                raise ValueError(
                    f"MCP server '{self.server_id}': 'url' required for http"
                )
            async with streamablehttp_client(
                url=cfg.url, headers=cfg.headers or {}
            ) as (r, w, _):
                yield r, w

        else:
            raise ValueError(
                f"MCP server '{self.server_id}': unknown transport '{cfg.type}'. "
                "Use 'stdio', 'sse', or 'http'."
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        from mcp import ClientSession

        try:
            async with self._transport() as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    self._mcp_tools = result.tools
                    self._session = session
                    self._ready_event.set()
                    logger.info(
                        "MCP '{}' connected — {} tool(s): {}",
                        self.server_id,
                        len(self._mcp_tools),
                        [t.name for t in self._mcp_tools],
                    )
                    # Hold the connection open until stop() is called.
                    await self._stop_event.wait()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._error = exc
            logger.error("MCP '{}' connection error: {}", self.server_id, exc)
        finally:
            self._session = None
            self._ready_event.set()  # unblock start() waiters on error path

    async def start(self, timeout: float = 30.0) -> None:
        self._task = asyncio.create_task(self._run(), name=f"mcp-{self.server_id}")
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self._task.cancel()
            raise TimeoutError(
                f"MCP server '{self.server_id}' did not connect within {timeout}s"
            )
        if self._error:
            raise self._error

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------
    # Tool access
    # ------------------------------------------------------------------

    def get_proxy_tools(self) -> list[MCPProxyTool]:
        return [MCPProxyTool(self, t) for t in self._mcp_tools]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if self._session is None:
            return f"error: MCP server '{self.server_id}' is not connected"
        try:
            result = await self._session.call_tool(tool_name, arguments or None)
            return _format_result(result)
        except Exception as exc:
            return f"error calling MCP tool '{tool_name}': {exc}"


# ------------------------------------------------------------------
# Result serialisation
# ------------------------------------------------------------------

def _format_result(result: Any) -> str:
    """Convert a CallToolResult to a plain string for the LLM."""
    import mcp.types as t

    parts: list[str] = []
    for block in result.content or []:
        if isinstance(block, t.TextContent):
            parts.append(block.text)
        elif isinstance(block, t.ImageContent):
            parts.append(f"[image: {block.mimeType}]")
        elif isinstance(block, t.EmbeddedResource):
            res = block.resource
            if hasattr(res, "text") and res.text is not None:
                parts.append(res.text)
            else:
                mime = getattr(res, "mimeType", "binary")
                parts.append(f"[resource: {mime}]")
        else:
            parts.append(str(block))

    text = "\n".join(parts) if parts else "(empty response)"
    if getattr(result, "isError", False):
        return f"tool error: {text}"
    return text


# ------------------------------------------------------------------
# Manager — owns all clients for a run
# ------------------------------------------------------------------

class MCPManager:
    """Starts and stops all configured MCP server connections."""

    def __init__(self, servers: dict[str, Any]) -> None:
        self._clients: dict[str, MCPClient] = {
            sid: MCPClient(sid, cfg) for sid, cfg in servers.items()
        }

    async def start(self) -> None:
        for sid, client in self._clients.items():
            try:
                await client.start()
            except Exception as exc:
                logger.warning("Skipping MCP server '{}': {}", sid, exc)

    async def stop(self) -> None:
        for client in self._clients.values():
            await client.stop()

    def get_all_tools(self) -> list[MCPProxyTool]:
        tools: list[MCPProxyTool] = []
        for client in self._clients.values():
            tools.extend(client.get_proxy_tools())
        return tools
